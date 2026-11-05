import unittest
from madrasflow.planning import band, minimum_trips, scenario, reallocate

class PlanningTests(unittest.TestCase):
    def test_thresholds_and_fractional_boundaries(self):
        for value, label in [(0,'free'),(40,'free'),(40.1,'light'),(49.9,'light'),(50,'medium'),(59.9,'medium'),(60,'crowded'),(69.9,'crowded'),(70,'very_crowded')]:
            self.assertEqual(band(value), label)
    def test_trip_recommendation_and_no_service(self):
        self.assertEqual(minimum_trips(420), 11)
        self.assertEqual(scenario([420,200], 6)['band'], 'very_crowded')
        self.assertEqual(scenario([420], 0)['band'], 'no_service')
        self.assertIsNone(scenario([420], 6)['fleet_lower_bound'])
        self.assertEqual(scenario([420], 6, cycle_minutes=90)['fleet_lower_bound'],17)
    def test_donor_protection(self):
        result=reallocate([80,60],4,[420],6)
        self.assertLessEqual(result['donor_after']['peak_average_passengers_per_bus'],40)
        with self.assertRaises(ValueError):
            reallocate([150],4,[420],6)
    def test_bad_inputs(self):
        for bad in [-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError): minimum_trips(bad)
        with self.assertRaises(ValueError): scenario([1],-1)
        with self.assertRaises(ValueError): minimum_trips(1,0)

if __name__=='__main__': unittest.main()
