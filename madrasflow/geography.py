"""Read supplied WGS84 GIS and conservatively match named ETM stages.

No geocoding requests, API key or synthetic stop coordinates are used.
"""
import math
import re
import struct
from pathlib import Path

def normalize(value):return re.sub('[^A-Z0-9]','',str(value).upper())

def read_dbf(path):
    with Path(path).open('rb') as f:
        h=f.read(32);n,hl,rl=struct.unpack('<IHH',h[4:12]);fields=[]
        while f.tell()<hl-1:
            d=f.read(32)
            if len(d)<32 or d[0]==13:break
            fields.append((d[:11].split(b'\0')[0].decode(),d[16]))
        f.seek(hl);rows=[]
        for _ in range(n):
            r=f.read(rl);p=1;row={}
            for name,size in fields:
                row[name]=r[p:p+size].decode('utf-8',errors='replace').strip();p+=size
            rows.append(row if r[:1]!=b'*' else None)
    return rows

def read_lines(path):
    shapes=[]
    with Path(path).open('rb') as f:
        f.read(100)
        while head:=f.read(8):
            _,size=struct.unpack('>ii',head);body=f.read(size*2)
            kind=struct.unpack_from('<i',body)[0]
            if kind not in [3,5,13,15,23,25]:shapes.append([]);continue
            parts,points=struct.unpack_from('<ii',body,36)
            starts=list(struct.unpack_from('<'+'i'*parts,body,44))+[points]
            coords=[list(struct.unpack_from('<dd',body,44+parts*4+i*16)) for i in range(points)]
            shapes.append([coords[starts[i]:starts[i+1]] for i in range(parts)])
    return shapes

def projection(point,line):
    scale=math.cos(math.radians(13));best=None;chain=0
    for a,b in zip(line,line[1:]):
        ax,ay=a[0]*scale,a[1];bx,by=b[0]*scale,b[1];px,py=point[0]*scale,point[1]
        dx,dy=bx-ax,by-ay;length=math.hypot(dx,dy)
        t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(length*length))) if length else 0
        q=[a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]
        distance=math.hypot((point[0]-q[0])*scale,point[1]-q[1])*111320
        value={'coordinate':q,'chain':chain+t*length,'distance_m':distance}
        if best is None or distance<best['distance_m']:best=value
        chain+=length
    return best

def cut_line(line,start,end):
    if end['chain']<=start['chain']:return None
    result=[start['coordinate']];chain=0;scale=math.cos(math.radians(13))
    for a,b in zip(line,line[1:]):
        chain+=math.hypot((b[0]-a[0])*scale,b[1]-a[1])
        if start['chain']<chain<end['chain']:result.append(b)
    result.append(end['coordinate'])
    return result

def load_stops(path):
    import openpyxl
    workbook=openpyxl.load_workbook(path,read_only=True,data_only=True)
    stops={}
    for sheet in workbook:
        for _,name,lat,lon,*rest in list(sheet.values)[1:]:
            if not name or not isinstance(lat,(float,int)) or not isinstance(lon,(float,int)):continue
            if 11<float(lat)<14 and 79<float(lon)<81:
                stops.setdefault(normalize(name),[]).append({'name':str(name),'coordinate':[float(lon),float(lat)]})
    return stops

def attach_geography(routes,stages,shape_path,stop_path):
    attrs=read_dbf(Path(shape_path).with_suffix('.dbf'));shapes=read_lines(shape_path);stops=load_stops(stop_path)
    bycode={}
    for a,parts in zip(attrs,shapes):
        if a and parts:bycode.setdefault(normalize(a['route_num']),[]).append((a,parts))
    counts={'route_geometry_matches':0,'geographic_section_matches':0,'unmapped_sections':0}
    for route in routes:
        code=normalize(route['route_code']);entries=bycode.get(code,[])
        # Require matching endpoint identities. Never choose a different route with a similar number.
        exact=[e for e in entries if {normalize(e[0]['source']),normalize(e[0]['destinat'])}=={normalize(route['origin']),normalize(route['terminus'])}]
        if not exact:
            route['geometry']=None;route['geometry_status']='unmatched';continue
        line=max(exact[0][1],key=len)
        names=stages.get(route['id'],{})
        ordered=sorted(names,key=lambda n:route['orientation']*int(n))
        def match(name,path):
            options=stops.get(normalize(name),[])
            candidates=[{**s,**projection(s['coordinate'],path)} for s in options]
            candidates=[c for c in candidates if c['distance_m']<=400]
            return min(candidates,key=lambda c:c['distance_m']) if candidates else None
        forward=[match(names[n],line) for n in ordered]
        valid=[(i,p) for i,p in enumerate(forward) if p]
        if len(valid)>=2 and valid[-1][1]['chain']<valid[0][1]['chain']:line=list(reversed(line))
        route['geometry']={'type':'LineString','coordinates':line}
        route['geometry_status']='route_number_and_endpoints_match_supplied_GIS'
        counts['route_geometry_matches']+=1
        mapped={n:match(names[n],line) for n in ordered}
        for section in route['sections']:
            a,b=str(section['stage_a']),str(section['stage_b'])
            section['from_name']=names.get(a,f'Stage {a}');section['to_name']=names.get(b,f'Stage {b}')
            pa,pb=mapped.get(a),mapped.get(b)
            coords=cut_line(line,pa,pb) if pa and pb else None
            section['geometry']={'type':'LineString','coordinates':coords} if coords else None
            section['geography_status']='name_and_route_proximity_match_unreviewed' if coords else 'stage_mapping_unavailable'
            if coords:counts['geographic_section_matches']+=1
            else:counts['unmapped_sections']+=1
    return counts
