import csv
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
import pandas as pd
from madrasflow.ingest import ingest
from madrasflow.storage import connection, load_json
from madrasflow.forecast import features

TEST_TMP=Path(__file__).resolve().parents[1]/'artifacts'/'test_tmp'
TEST_TMP.mkdir(parents=True,exist_ok=True)

class PipelineTests(unittest.TestCase):
    def test_quote_spillover_reconciliation_and_idempotence(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            root=Path(temp)
            path=root/'Ticket-Data-2026-03-01.csv'
            fields=['id','duty_date','date','time','ticket_type','passenger_count','direction',
                    'Trip_Origin','Trip_Destination','from_stage','to_stage','source','destination',
                    'fleet_no','waybill_no','trip_no']
            rows=[['1','2026-03-01','01-03-2026','08:00:00','Women Ticket','2','57 - UP','A','C','1','','A, BUS STOP','Zero Value Ticket','V','W','1'],
                  ['2','2026-03-01','02-03-2026','00:30:00','Adult Ticket','3','57 - UP','A','C','1','3','A','C','V','W','2'],
                  ['3','2026-03-01','01-01-1970','00:00:00','Adult Ticket','9','57 - UP','A','C','1','3','A','C','V','W','1'],
                  ['4','2026-03-01','01-03-2026','08:00:00','Luggage Ticket','0','57 - UP','A','C','1','3','A','C','V','W','1']]
            with path.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(fields);w.writerows(rows+[rows[0]])
            first=ingest(root,root/'data')
            self.assertEqual(first[0]['raw_records'],5)
            self.assertEqual(first[0]['accepted_passengers'],5)
            self.assertEqual(first[0]['duplicate_records_removed'],1)
            con=connection()
            dates=con.execute('SELECT cast(date AS VARCHAR),sum(passengers) FROM read_parquet(?) GROUP BY date ORDER BY date',
                [str(root/'data'/'partitions'/'Ticket-Data-2026-03-01.parquet')]).fetchall()
            con.close()
            self.assertEqual(dates,[('2026-03-01',2.0),('2026-03-02',3.0)])
            second=ingest(root,root/'data')
            self.assertEqual(first,second)

    def test_no_target_leakage(self):
        history=pd.DataFrame({'date':pd.to_datetime(['2026-03-02','2026-03-03']),
            'series_id':['R','R'],'hour':[8,8],'is_weekend':[0,0],'passengers':[10.,30.]})
        target=pd.DataFrame({'date':pd.to_datetime(['2026-03-04']),
            'series_id':['R'],'hour':[8],'is_weekend':[0],'passengers':[999999.]})
        x=features(history,target,['R'])
        self.assertEqual(x.historical_mean.iloc[0],20)
        self.assertEqual(x.lag_1.iloc[0],30)
        target['passengers']=0
        pd.testing.assert_frame_equal(x,features(history,target,['R']))
        with self.assertRaises(ValueError): features(pd.concat([history,target]),target,['R'])

    def test_section_reconstruction_and_model_roundtrip(self):
        from madrasflow.segments import build_segments
        from madrasflow.forecast import train_and_evaluate,export_profiles
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temp:
            root=Path(temp)
            (root/'partitions').mkdir()
            rows=[]
            for day in pd.date_range('2026-03-01','2026-03-31'):
                for a,b,p in [(3,1,10.),(3,None,10.),(2,1,3.)]:
                    rows.append({'date':day,'hour':8,'route_id':'R','route_direction':'R - DOWN',
                                 'origin':'C','terminus':'A','from_stage':a,'to_stage':b,'passengers':p})
            con=connection()
            con.register('fixture',pd.DataFrame(rows))
            con.execute('COPY fixture TO ? (FORMAT PARQUET)',[str(root/'partitions'/'fixture.parquet')])
            con.close()
            report=build_segments(root,root/'segments',routes=1)
            self.assertEqual(report['section_count'],2)
            self.assertAlmostEqual(report['crossing_reconciliation']['actual'],31*43)
            self.assertEqual(report['routes_selected'][0]['orientation'],-1)
            result=train_and_evaluate(root/'segments'/'segments.parquet',root/'model','segments',rounds=5)
            self.assertEqual(result['test']['baseline']['rows'],7*24*2)
            self.assertEqual(export_profiles(root/'segments'/'segments.parquet',root/'model',root/'profiles.parquet'),2*24*2)

if __name__=='__main__': unittest.main()
