"""Conditional service arithmetic; no claim of dispatch or physical feasibility."""
import math

def band(load):
    if load is None:
        return 'unknown'
    if not math.isfinite(load) or load < 0:
        raise ValueError('Load must be finite and nonnegative')
    if load <= 40:
        return 'free'
    if load < 50:
        return 'light'
    if load < 60:
        return 'medium'
    if load < 70:
        return 'crowded'
    return 'very_crowded'

def minimum_trips(passenger_crossings, target_load=40.0):
    if not math.isfinite(passenger_crossings) or passenger_crossings < 0:
        raise ValueError('Passenger crossings must be finite and nonnegative')
    if not math.isfinite(target_load) or target_load <= 0:
        raise ValueError('Target load must be positive and finite')
    return math.ceil(passenger_crossings / target_load)

def scenario(section_flows, trips, target_load=40.0, cycle_minutes=None, reserve_trips=1):
    """All supplied sections share one full-route service; short turns need separate plans."""
    if isinstance(trips, bool) or not isinstance(trips, int) or trips < 0:
        raise ValueError('Trips must be a nonnegative integer')
    if reserve_trips < 0 or int(reserve_trips) != reserve_trips:
        raise ValueError('Reserve trips must be a nonnegative integer')
    if not section_flows:
        raise ValueError('At least one section is required')
    needed = max(minimum_trips(float(x), target_load) for x in section_flows)
    keep = max(needed, int(reserve_trips))
    peak = max(section_flows)
    load = peak / trips if trips else None
    if cycle_minutes is not None and (not math.isfinite(cycle_minutes) or cycle_minutes <= 0):
        raise ValueError('Cycle minutes must be positive and finite')
    return {
        'peak_passenger_crossings': peak, 'planned_trip_passages_per_hour': trips,
        'target_passengers_per_bus': target_load, 'minimum_trip_passages_per_hour': needed,
        'additional_trip_passages_needed': max(0, needed - trips),
        'potential_spare_trip_passages': max(0, trips - keep),
        'peak_average_passengers_per_bus': load,
        'band': 'no_service' if not trips and peak > 0 else ('no_service' if not trips else band(load)),
        'fleet_lower_bound': math.ceil(needed * cycle_minutes / 60) if cycle_minutes else None,
        'assumptions': ['Fixed passenger demand; even loading; all trips cover all supplied sections',
                        'Fleet lower bound needs a full round-trip cycle including layover and compatible opposite-direction service',
                        'Vehicle location, deadhead time, road access and crew feasibility are not established'],
    }

def reallocate(donor_flows, donor_trips, receiver_flows, receiver_trips, transfer=1, target_load=40.0):
    if isinstance(transfer, bool) or not isinstance(transfer, int) or transfer <= 0:
        raise ValueError('Transfer must be a positive integer number of trip passages')
    donor_before = scenario(donor_flows, donor_trips, target_load)
    if transfer > donor_before['potential_spare_trip_passages']:
        raise ValueError('Transfer would violate donor target or minimum service reserve')
    return {'status': 'conditional_candidate_not_dispatch', 'transferred_trip_passages': transfer,
            'donor_before': donor_before,
            'donor_after': scenario(donor_flows, donor_trips-transfer, target_load),
            'receiver_before': scenario(receiver_flows, receiver_trips, target_load),
            'receiver_after': scenario(receiver_flows, receiver_trips+transfer, target_load),
            'feasibility': 'unknown: requires vehicle/crew availability, transfer travel time and route compatibility'}
