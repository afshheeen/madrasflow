"""Local dashboard API and static frontend. Uses the exported real-model snapshot."""
import json
import math
import sqlite3
import uuid
from datetime import datetime,timezone
from functools import partial
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .planning import scenario,reallocate

ROOT=Path(__file__).resolve().parents[1]

def estimate(snapshot,route_id,day_type,hour,trips,target=40):
    if day_type not in ['weekday','weekend']:raise ValueError('Choose weekday or weekend')
    if not isinstance(hour,int) or not 0<=hour<=23:raise ValueError('Hour must be 0–23')
    route=next((r for r in snapshot['routes'] if r['id']==route_id),None)
    if route is None:raise ValueError('Unknown route')
    flows=route['profile'][day_type].get(str(hour),{})
    values=[float(flows.get(s['id'],0)) for s in route['sections']]
    answer=scenario(values,trips,target)
    answer.update({'route_id':route_id,'day_type':day_type,'hour':hour,
        'evidence_kind':'estimated_boarding_hour_section_flow_with_assumed_service',
        'missing_destination_share':route['missing_destination_share'],
        'sections':[{'id':s['id'],'passenger_crossings':v,'average_load_proxy':v/trips if trips else None}
                    for s,v in zip(route['sections'],values)]})
    return answer

def explain(snapshot,route_id,day_type,hour,trips,target=40,question=''):
    result=estimate(snapshot,route_id,day_type,hour,trips,target)
    route=next(r for r in snapshot['routes'] if r['id']==route_id)
    peak=result['peak_passenger_crossings'];load=result['peak_average_passengers_per_bus']
    section=max(zip(route['sections'],result['sections']),key=lambda s:s[1]['passenger_crossings'])[0]
    missing=100*route['missing_destination_share']
    lines=[f"The historical {day_type} profile estimates {peak:.0f} passenger crossings on the busiest stage interval, {section['from_name']} to {section['to_name']}, for {hour:02d}:00–{hour+1:02d}:00.",
           f"With your assumption of {trips} trip passages per hour, the average-load proxy is {load:.1f} passengers per bus ({result['band'].replace('_',' ')})." if trips else 'No trips are planned in this scenario, so a passengers-per-bus value cannot be calculated.',
           f"At a target of {target:g} passengers per bus, the arithmetic requires {result['minimum_trip_passages_per_hour']} full-route trip passages per hour.",
           f"{missing:.0f}% of this route variant's passenger records lack a destination. Those destinations are estimated from known journeys; section crossing times and a verified service plan are unavailable."]
    if any(word in question.lower() for word in ['add','extra','interven','bus']):
        extra=peak/(trips+1)
        lines.insert(3,f"One additional trip would change the same-flow average from {load:.1f} to {extra:.1f}, assuming even loading." if trips else f"One trip would have an average-load proxy of {extra:.1f}; operational feasibility is unknown.")
    return {'answer':'\n\n'.join(lines),'facts':result,'source':'recorded ETM-derived profile and explicit planning assumptions',
            'causal_claim':False,'data_through':snapshot['data_through']}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,directory=None,**kwargs):
        super().__init__(*args,directory=str(directory or ROOT/'web/dist'),**kwargs)
    def snapshot(self):return json.loads((ROOT/'web/dist/data/snapshot.json').read_text(encoding='utf-8'))
    @contextmanager
    def db(self):
        folder=ROOT/'data';folder.mkdir(exist_ok=True)
        con=sqlite3.connect(folder/'operations.sqlite')
        con.row_factory=sqlite3.Row
        con.execute('''CREATE TABLE IF NOT EXISTS incidents
            (id TEXT PRIMARY KEY,route_id TEXT,type TEXT,description TEXT,section_id TEXT,status TEXT,created_at TEXT)''')
        try:
            with con:
                yield con
        finally:
            con.close()
    def send_json(self,value,status=200):
        payload=json.dumps(value,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)))
        self.end_headers();self.wfile.write(payload)
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<=0 or size>16384:raise ValueError('Request body must be 1–16384 bytes')
        return json.loads(self.rfile.read(size))
    def do_GET(self):
        path=urlparse(self.path)
        if not path.path.startswith('/api/'):
            if path.path in ['/driver','/driver/']:self.path='/driver.html'
            return super().do_GET()
        try:
            if path.path=='/api/health':return self.send_json({'status':'ok','mode':'local_api','data_through':self.snapshot()['data_through']})
            if path.path=='/api/snapshot':return self.send_json(self.snapshot())
            if path.path=='/api/incidents':
                with self.db() as db:rows=[dict(r) for r in db.execute('SELECT * FROM incidents ORDER BY created_at DESC LIMIT 200')]
                return self.send_json({'incidents':rows,'storage':'shared_local_server'})
            return self.send_json({'error':'Not found'},404)
        except (ValueError,OSError,json.JSONDecodeError) as error:self.send_json({'error':str(error)},400)
    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                return self.send_json({'error':'Cross-origin writes are not accepted'},403)
            body=self.body();snapshot=self.snapshot();path=urlparse(self.path).path
            if path=='/api/scenario':
                return self.send_json(estimate(snapshot,body['route_id'],body['day_type'],body['hour'],body['trips'],float(body.get('target_load',40))))
            if path=='/api/explain':
                return self.send_json(explain(snapshot,body['route_id'],body['day_type'],body['hour'],body['trips'],float(body.get('target_load',40)),str(body.get('question',''))[:500]))
            if path=='/api/incidents':
                if body.get('route_id') not in {r['id'] for r in snapshot['routes']}:raise ValueError('Choose a known route')
                route=next(r for r in snapshot['routes'] if r['id']==body['route_id'])
                if body.get('section_id') and body['section_id'] not in {s['id'] for s in route['sections']}:
                    raise ValueError('Section does not belong to the selected route')
                if body.get('type') not in ['crowding','delay','breakdown','road_obstruction','other']:raise ValueError('Invalid incident type')
                description=str(body.get('description','')).strip()
                if not 5<=len(description)<=600:raise ValueError('Description must be 5–600 characters')
                row={'id':str(uuid.uuid4()),'route_id':body['route_id'],'type':body['type'],'description':description,
                    'section_id':str(body.get('section_id',''))[:160],'status':'reported','created_at':datetime.now(timezone.utc).isoformat()}
                with self.db() as db:db.execute('INSERT INTO incidents VALUES (:id,:route_id,:type,:description,:section_id,:status,:created_at)',row)
                return self.send_json(row,201)
            if path=='/api/incidents/status':
                if body.get('status') not in ['reported','acknowledged','resolved']:raise ValueError('Invalid status')
                with self.db() as db:
                    count=db.execute('UPDATE incidents SET status=? WHERE id=?',(body['status'],body['id'])).rowcount
                return self.send_json({'updated':bool(count)})
            return self.send_json({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError,OSError) as error:self.send_json({'error':str(error)},400)

def serve(host='127.0.0.1',port=8765):
    if not (ROOT/'web/dist/data/snapshot.json').exists():raise ValueError('Run scripts/build_dashboard_data.py first')
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'Marina Ops: http://{host}:{port} · Driver view: /driver.html',flush=True)
    try:server.serve_forever()
    finally:server.server_close()
