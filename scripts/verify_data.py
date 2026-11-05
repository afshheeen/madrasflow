"""Cross-check DuckDB ingestion against the independently generated stdlib CSV audit."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from madrasflow.storage import load_json,write_json,connection,literal

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',required=True)
    parser.add_argument('--data',default='data')
    parser.add_argument('--output',default='artifacts/data_verification.json')
    parser.add_argument('--source',help='Optional independent full scan of duty/file consistency and ticket categories')
    args=parser.parse_args()
    audit=load_json(args.audit)
    manifest=load_json(Path(args.data)/'manifest.json')
    checks=[]
    for file in audit['files']:
        actual=manifest['files'].get(file['name'])
        if actual is None: raise AssertionError('Missing ingested file '+file['name'])
        row={'file':file['name'],'physical_lines_equal_csv_records':file['physical_data_lines']==actual['audit']['raw_records'],
             'bytes_equal':file['bytes']==actual['bytes'],'accepted_totals_reconciled':actual['audit']['reconciled']}
        if 'full' in file:
            row['independent_full_csv_records_equal']=file['full']['counts']['rows']==actual['audit']['raw_records']
            raw_pax=sum(q['passengers'] for q in actual['audit']['quality'])
            row['independent_raw_passenger_sum_equal']=file['full']['counts']['passengers']==raw_pax
        if not all(v for k,v in row.items() if k!='file'): raise AssertionError(row)
        checks.append(row)
    con=connection()
    con.execute(f"CREATE TEMP VIEW hourly AS SELECT * FROM read_parquet({literal(Path(args.data)/'hourly.parquet')})")
    # Training dates only: this descriptive comparison does not tune on the test set.
    day_types=con.execute('''SELECT weekday,avg(passengers) average_daily_passengers,count(*) dates
        FROM (SELECT isodow(date) weekday,date,sum(passengers) passengers FROM hourly
        WHERE date BETWEEN DATE '2026-03-02' AND DATE '2026-03-14' GROUP BY date)
        GROUP BY weekday ORDER BY weekday''').fetchdf().to_dict('records')
    hourly_pax=con.execute('SELECT sum(passengers) FROM hourly').fetchone()[0]
    accepted=sum(v['audit']['accepted_passengers'] for v in manifest['files'].values())
    assert hourly_pax==accepted,(hourly_pax,accepted)
    raw_check=None
    if args.source:
        grouped=con.execute(f'''SELECT filename,duty_date,ticket_type,count(*) records FROM
            read_csv({literal(Path(args.source)/'Ticket-Data-*.csv')},header=true,all_varchar=true,
                     delim=',',quote='"',escape='"',filename=true,strict_mode=true)
            GROUP BY ALL''').fetchdf().to_dict('records')
        bad=[r for r in grouped if r['duty_date']!=Path(r['filename']).stem[-10:]]
        if bad: raise AssertionError('Duty/file mismatch detected in independent raw scan')
        types={}
        for r in grouped: types[r['ticket_type']]=types.get(r['ticket_type'],0)+r['records']
        raw_check={'duty_filename_consistency_passed':True,'records_checked':sum(r['records'] for r in grouped),
                   'ticket_types':types}
    report={'all_checks_passed':True,'file_count':len(checks),'raw_records':sum(v['audit']['raw_records'] for v in manifest['files'].values()),
        'accepted_passengers':accepted,'hourly_passengers':hourly_pax,'files':checks,
        'training_day_of_week_summary':day_types,'independent_raw_duty_check':raw_check,
        'note':'Physical-line equality verified against actual parsed records; independent passenger sums available for three fully parsed days.'}
    write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ['all_checks_passed','file_count','raw_records','accepted_passengers']},indent=2))

if __name__=='__main__': main()
