import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from madrasflow.dashboard import estimate,explain,Handler
from madrasflow.geography import projection,cut_line,normalize

FIXTURE={'data_through':'2026-03-31','routes':[{'id':'R','route_code':'57','origin':'A','terminus':'C',
    'missing_destination_share':.6,'sections':[{'id':'S1','from_name':'A','to_name':'B'},{'id':'S2','from_name':'B','to_name':'C'}],
    'profile':{'weekday':{'18':{'S1':420.,'S2':210.}},'weekend':{'18':{'S1':210.,'S2':100.}}}}]}

class DashboardTests(unittest.TestCase):
    def test_scenario_uses_selected_real_profile(self):
        result=estimate(FIXTURE,'R','weekday',18,6)
        self.assertEqual(result['peak_average_passengers_per_bus'],70)
        self.assertEqual(result['minimum_trip_passages_per_hour'],11)
        self.assertEqual(estimate(FIXTURE,'R','weekend',18,6)['peak_average_passengers_per_bus'],35)
        self.assertEqual(estimate(FIXTURE,'R','weekday',18,0)['band'],'no_service')
        for args in [('invalid','weekday',18,6),('R','weekday',24,6),('R','weekday',18,2.5)]:
            with self.assertRaises(ValueError):estimate(FIXTURE,*args)
    def test_explanation_is_grounded_and_marks_assumptions(self):
        result=explain(FIXTURE,'R','weekday',18,6,question='add a bus')
        self.assertIn('420 passenger crossings',result['answer'])
        self.assertIn('60%',result['answer'])
        self.assertIn('70.0 to 60.0',result['answer'])
        self.assertFalse(result['causal_claim'])
    def test_incident_database_shared_between_connections(self):
        folder=Path(__file__).resolve().parents[1]/'artifacts/test_tmp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp,patch('madrasflow.dashboard.ROOT',Path(temp)):
            h=object.__new__(Handler)
            with h.db() as db:db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?)',('fixture','R','delay','Test fixture only','','reported','2026-03-31'))
            with h.db() as db:self.assertEqual(db.execute('SELECT status FROM incidents WHERE id=?',('fixture',)).fetchone()[0],'reported')
    def test_geometry_projection_never_invents_reverse_sections(self):
        line=[[80.,13.],[80.01,13.],[80.02,13.]]
        a=projection([80.005,13.],line);b=projection([80.015,13.],line)
        self.assertLess(a['distance_m'],.01)
        cut=cut_line(line,a,b)
        self.assertAlmostEqual(cut[0][0],80.005)
        self.assertAlmostEqual(cut[-1][0],80.015)
        self.assertIsNone(cut_line(line,b,a))
        self.assertEqual(normalize('M.G.R. Koyambedu'),'MGRKOYAMBEDU')

if __name__=='__main__':unittest.main()
