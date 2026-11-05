"""Export a small real-model snapshot and supplied geography; no raw transactions."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from madrasflow.storage import connection,literal,load_json,write_json
from madrasflow.geography import attach_geography

def main():
    root=Path(__file__).resolve().parents[1];workspace=root.parent
    report=load_json(root/'artifacts/segments/segment_report.json')
    con=connection()
    profiles=con.execute(f"SELECT * FROM read_parquet({literal(root/'artifacts/segment_profiles.parquet')})").fetchdf().to_dict('records')
    catalogue=con.execute(f"SELECT * FROM read_parquet({literal(root/'artifacts/segments/section_catalog.parquet')})").fetchdf().to_dict('records')
    con.execute(f"CREATE TEMP VIEW od AS SELECT * FROM read_parquet({literal(root/'data/partitions'/'*.parquet')})")
    con.execute("CREATE TEMP VIEW pilot AS SELECT DISTINCT route_id FROM read_parquet("+literal(root/'artifacts/segments/section_catalog.parquet')+")")
    stage_rows=con.execute('''SELECT route_id,stage,arg_max(name,passengers) name FROM (
        SELECT route_id,from_stage stage,source_name name,sum(passengers) passengers FROM od JOIN pilot USING(route_id)
        WHERE date<=DATE '2026-03-14' AND from_stage IS NOT NULL GROUP BY ALL
        UNION ALL SELECT route_id,to_stage stage,destination_name name,sum(passengers) passengers FROM od JOIN pilot USING(route_id)
        WHERE date<=DATE '2026-03-14' AND to_stage IS NOT NULL GROUP BY ALL) GROUP BY route_id,stage''').fetchall()
    names={}
    for rid,stage,name in stage_rows:names.setdefault(rid,{})[str(stage)]=name
    quality=con.execute('''SELECT route_id,sum(passengers) passengers,
        sum(CASE WHEN to_stage IS NULL THEN passengers ELSE 0 END)/sum(passengers) missing_destination_share
        FROM od JOIN pilot USING(route_id) GROUP BY route_id''').fetchall()
    quality={r[0]:r[2] for r in quality}
    con.close()
    routes=[]
    for r in report['routes_selected']:
        rid=r['route_id'];direction=r['route_direction'].rsplit(' - ',1)
        sections=[{'id':s['series_id'],'stage_a':s['stage_a'],'stage_b':s['stage_b'],
                   'from_name':names.get(rid,{}).get(str(s['stage_a']),f"Stage {s['stage_a']}"),
                   'to_name':names.get(rid,{}).get(str(s['stage_b']),f"Stage {s['stage_b']}")} for s in catalogue if s['route_id']==rid]
        sections.sort(key=lambda s:r['orientation']*s['stage_a'])
        route={'id':rid,'route_code':direction[0],'direction':direction[-1],
            'origin':r['origin'],'terminus':r['terminus'],'orientation':r['orientation'],
            'depot':None,'missing_destination_share':quality[rid],'sections':sections,
            'profile':{day:{} for day in ['weekday','weekend']}}
        for p in profiles:
            if p['series_id'].startswith(rid+':'):
                route['profile'][p['day_type']].setdefault(str(p['hour']),{})[p['series_id']]=round(p['predicted_passengers'],3)
        routes.append(route)
    geo=attach_geography(routes,names,workspace/'Public Transport/MTC/routes_merged.shp',workspace/'Tambaram, Avadi, GCC Bus Stops List  1.xlsx')
    data={'schema_version':1,'title':'Marina Ops','data_through':'2026-03-31','forecast_method':'historical_weekday_weekend_mean',
        'label_kind':report['label_kind'],'mode':'model_snapshot','routes':routes,'geography':geo,
        'validation':load_json(root/'reports/validation.json'),
        'limitations':['Boarding-hour section estimates; crossing timing is not observed',
            'Trip counts are planning assumptions, not a verified timetable',
            'Stage map matches require operator review; unmatched sections stay grey'],
        'incident_storage':'browser_local_for_hosted_snapshot; SQLite_for_local_API'}
    write_json(root/'web/dist/data/snapshot.json',data)
    write_json(root/'reports/geography.json',geo)
    print('Dashboard snapshot:',geo,'routes:',len(routes))

if __name__=='__main__':main()
