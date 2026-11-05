"""Partitioned, idempotent ETM ingestion with explicit reconciliation."""
import hashlib
from pathlib import Path
from .storage import connection, literal, load_json, write_json

PASSENGER_TYPES = ('Adult Ticket','Women Ticket','Senior Citizen Ticket',
                   'Disable Person Ticket','Disable Person Escort Ticket','Transgender Ticket')

def ingest(source, output, limit=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    files = sorted(source.glob('Ticket-Data-*.csv'))
    if not files:
        raise ValueError(f'No ticket CSVs found in {source}')
    if limit:
        files = files[:limit]
    (output/'partitions').mkdir(parents=True, exist_ok=True)
    manifest_path = output/'manifest.json'
    manifest = load_json(manifest_path) if manifest_path.exists() else {'schema_version':1,'files':{}}
    con=connection()
    audits=[]
    for path in files:
        stat=path.stat()
        old=manifest['files'].get(path.name,{})
        partition=output/'partitions'/f'{path.stem}.parquet'
        if old.get('bytes')==stat.st_size and old.get('mtime_ns')==stat.st_mtime_ns and partition.exists():
            audits.append(old['audit'])
            print(f'Unchanged: {path.name}',flush=True)
            continue
        digest=hashlib.sha256()
        with path.open('rb') as f:
            while block:=f.read(8*1024*1024): digest.update(block)
        con.execute(f"""CREATE OR REPLACE TEMP TABLE raw AS
            SELECT id, duty_date, date, time, ticket_type, passenger_count,
                   direction, Trip_Origin, Trip_Destination, from_stage, to_stage,
                   source, destination, fleet_no, waybill_no, trip_no
            FROM read_csv({literal(path)},header=true,all_varchar=true,strict_mode=true,
                          delim=',',quote='"',escape='"')""")
        raw_rows=con.execute('SELECT count(*) FROM raw').fetchone()[0]
        duplicate_keys=con.execute('''SELECT id,duty_date,count(*) AS n
            FROM raw GROUP BY id,duty_date HAVING count(*)>1''').fetchall()
        duplicates=[]
        if duplicate_keys:
            con.execute('''CREATE OR REPLACE TEMP TABLE duplicate_keys AS
                SELECT id,duty_date FROM raw GROUP BY id,duty_date HAVING count(*)>1''')
            duplicates=con.execute('''SELECT r.id,r.duty_date,count(*) AS n,
            count(DISTINCT (date,time,ticket_type,passenger_count,direction,Trip_Origin,
            Trip_Destination,from_stage,to_stage,source,destination,fleet_no,waybill_no,trip_no)) AS variants
            FROM raw r JOIN duplicate_keys k ON r.id IS NOT DISTINCT FROM k.id
                AND r.duty_date IS NOT DISTINCT FROM k.duty_date
            GROUP BY r.id,r.duty_date''').fetchall()
        conflicts=sum(r[3]>1 for r in duplicates)
        if conflicts:
            raise ValueError(f'{path.name}: {conflicts} conflicting transaction keys; ingestion stopped')
        con.execute('''CREATE OR REPLACE TEMP VIEW typed AS SELECT *,
            try_strptime(date || ' ' || time,'%d-%m-%Y %H:%M:%S') AS ticket_ts,
            try_cast(duty_date AS DATE) AS duty,
            try_cast(passenger_count AS DOUBLE) AS passengers,
            try_cast(from_stage AS DOUBLE) AS board_stage,
            try_cast(to_stage AS DOUBLE) AS alight_stage,
            upper(regexp_replace(trim(direction),'\\s+',' ','g')) AS route_direction,
            upper(regexp_replace(trim(Trip_Origin),'\\s+',' ','g')) AS origin,
            upper(regexp_replace(trim(Trip_Destination),'\\s+',' ','g')) AS terminus
            FROM raw''')
        allowed=','.join(literal(t) for t in PASSENGER_TYPES)
        con.execute(f'''CREATE OR REPLACE TEMP VIEW classified AS SELECT *, CASE
            WHEN ticket_type IS NULL OR ticket_type NOT IN ({allowed}) THEN 'excluded_ticket_type'
            WHEN id IS NULL OR duty IS NULL THEN 'invalid_transaction_key'
            WHEN ticket_ts IS NULL OR cast(ticket_ts AS DATE)<duty OR cast(ticket_ts AS DATE)>duty+1
                THEN 'invalid_timestamp'
            WHEN passengers IS NULL OR NOT isfinite(passengers) OR passengers<=0 OR passengers!=floor(passengers)
                THEN 'invalid_passenger_count'
            WHEN coalesce(route_direction,'')='' OR coalesce(origin,'')='' OR coalesce(terminus,'')=''
                THEN 'missing_route_identity'
            ELSE 'accepted' END AS quality
            FROM typed''')
        quality=con.execute('''SELECT quality,count(*) records,coalesce(sum(passengers) FILTER(WHERE isfinite(passengers)),0) passengers
            FROM classified GROUP BY quality''').fetchdf().to_dict('records')
        accepted_source="SELECT * FROM classified WHERE quality='accepted'"
        if duplicates:
            accepted_source='''SELECT * EXCLUDE(rn) FROM (
                SELECT *,row_number() OVER(PARTITION BY duty,id ORDER BY id) rn FROM classified WHERE quality='accepted'
            ) WHERE rn=1'''
        con.execute('''CREATE OR REPLACE TEMP TABLE accepted AS
            SELECT ticket_ts,passengers,route_direction,origin,terminus,board_stage,alight_stage,source,destination
            FROM ('''+accepted_source+')')
        accepted_count, accepted_pax=con.execute('SELECT count(*),coalesce(sum(passengers),0) FROM accepted').fetchone()
        con.execute('''CREATE OR REPLACE TEMP TABLE aggregate AS SELECT
            cast(ticket_ts AS DATE) AS date, cast(hour(ticket_ts) AS INTEGER) AS hour,
            sha256(to_json([route_direction,origin,terminus])) AS route_id,
            route_direction,origin,terminus,
            CASE WHEN board_stage>=0 AND board_stage=floor(board_stage) AND board_stage<1000 THEN cast(board_stage AS INTEGER) END AS from_stage,
            CASE WHEN alight_stage>=0 AND alight_stage=floor(alight_stage) AND alight_stage<1000 THEN cast(alight_stage AS INTEGER) END AS to_stage,
            sum(passengers) AS passengers,count(*) AS tickets,
            min(source) AS source_name,min(destination) AS destination_name
            FROM accepted GROUP BY ALL''')
        grouped_tickets,grouped_pax=con.execute('SELECT sum(tickets),sum(passengers) FROM aggregate').fetchone()
        if grouped_tickets!=accepted_count or grouped_pax!=accepted_pax:
            raise AssertionError('Aggregation reconciliation failed')
        # A changed source never overwrites a valid partition before validation succeeds.
        temp=partition.with_suffix('.tmp.parquet')
        con.execute(f"COPY aggregate TO {literal(temp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        if path.stat().st_size!=stat.st_size or path.stat().st_mtime_ns!=stat.st_mtime_ns:
            raise ValueError(f'Input changed while being read: {path.name}')
        temp.replace(partition)
        audit={'file':path.name,'raw_records':raw_rows,'accepted_records':accepted_count,
               'accepted_passengers':accepted_pax,'duplicate_records_removed':sum(r[2]-1 for r in duplicates),
               'quality':quality,'reconciled':True}
        manifest['files'][path.name]={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,
                                    'sha256':digest.hexdigest(),'audit':audit}
        write_json(manifest_path,manifest)
        audits.append(audit)
        print(f'{path.name}: {raw_rows:,} rows; {accepted_pax:,.0f} accepted passengers; reconciled',flush=True)
    con.close()
    write_json(output/'ingestion_report.json',{'files':audits,'source_file_count':len(files),
        'raw_records':sum(a['raw_records'] for a in audits),
        'accepted_passengers':sum(a['accepted_passengers'] for a in audits),
        'all_reconciled':all(a['reconciled'] for a in audits),
        'limitations':['Ticket issue timestamps assumed local Asia/Kolkata',
                       'Duplicates checked within duty files; cross-file key overlap must be reviewed',
                       'Luggage, adjustment and unknown categories excluded and counted in quality report']})
    return audits

def hourly_table(data, out):
    """Actual ticket calendar date, including next-day duty-file spillover."""
    con=connection()
    pattern=str(Path(data)/'partitions'/'*.parquet')
    con.execute(f"""CREATE TEMP VIEW od AS SELECT * FROM read_parquet({literal(pattern)})""")
    con.execute(f"""COPY (SELECT date,hour,route_id,route_direction,origin,terminus,
        sum(passengers) passengers,sum(tickets) tickets FROM od GROUP BY ALL)
        TO {literal(out)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    daily=con.execute('''SELECT date,CASE WHEN isodow(date)>=6 THEN 'weekend' ELSE 'weekday' END day_type,
        isodow(date) weekday,sum(passengers) passengers FROM od GROUP BY ALL ORDER BY date''').fetchdf()
    write_json(Path(data)/'daily_summary.json',daily.to_dict('records'))
    con.close()
