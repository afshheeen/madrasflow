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
    report={'all_checks_passed':True,'file_count':len(checks),'raw_records':sum(v['audit']['raw_records'] for v in manifest['files'].values()),
        'accepted_passengers':accepted,'hourly_passengers':hourly_pax,'files':checks,
        'training_day_of_week_summary':day_types,
        'note':'Physical-line equality verified against actual parsed records; independent passenger sums available for three fully parsed days.'}
    write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ['all_checks_passed','file_count','raw_records','accepted_passengers']},indent=2))

if __name__=='__main__': main()
