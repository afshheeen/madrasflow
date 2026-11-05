"""Training-only stage interval reconstruction; explicitly a boarding-hour proxy.

There is no GPS/timetable service count in the supplied inputs. These outputs are
not measured section-crossing-hour occupancy and do not fabricate that denominator.
"""
from pathlib import Path
import numpy as np
from .storage import connection, literal, write_json

def build_segments(data, output, train_end='2026-03-14', routes=10):
    data,output=Path(data),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    con=connection()
    con.execute(f"CREATE TEMP VIEW od AS SELECT * FROM read_parquet({literal(data/'partitions'/'*.parquet')})")
    end=literal(train_end)
    con.execute(f'''CREATE TEMP TABLE evidence AS SELECT route_id,route_direction,origin,terminus,
        sum(passengers) passengers,count(DISTINCT date) days,
        sum(passengers) FILTER(WHERE to_stage>from_stage) increasing,
        sum(passengers) FILTER(WHERE to_stage<from_stage) decreasing
        FROM od WHERE date<={end} GROUP BY ALL''')
    con.execute('''CREATE TEMP TABLE candidates AS SELECT *,
        CASE WHEN coalesce(increasing,0)>=coalesce(decreasing,0) THEN 1 ELSE -1 END orientation,
        greatest(coalesce(increasing,0),coalesce(decreasing,0)) /
        nullif(coalesce(increasing,0)+coalesce(decreasing,0),0) orientation_agreement
        FROM evidence WHERE days>=10''')
    con.execute(f'''CREATE TEMP TABLE stages AS SELECT DISTINCT route_id,stage FROM (
        SELECT route_id,from_stage stage FROM od WHERE date<={end}
        UNION SELECT route_id,to_stage stage FROM od WHERE date<={end})
        WHERE stage IS NOT NULL''')
    con.execute(f'''CREATE TEMP TABLE selected AS SELECT c.* FROM candidates c
        JOIN (SELECT route_id,count(*) n FROM stages GROUP BY route_id) s USING(route_id)
        WHERE orientation_agreement>=0.95 AND n BETWEEN 2 AND 60
        ORDER BY passengers DESC,route_id LIMIT {int(routes)}''')
    con.execute('''CREATE TEMP TABLE sections AS SELECT *,
        route_id || ':' || cast(stage_a AS VARCHAR) || ':' || cast(stage_b AS VARCHAR) series_id
        FROM (SELECT route_id,orientation,stage stage_a,
            lead(stage) OVER(PARTITION BY route_id ORDER BY orientation*stage) stage_b
            FROM stages JOIN selected USING(route_id)) WHERE stage_b IS NOT NULL''')
    n=con.execute('SELECT count(*) FROM sections').fetchone()[0]
    if not n: raise ValueError('No route variants meet training-only stage coverage requirements')
    con.execute(f'''CREATE TEMP TABLE destinations AS SELECT route_id,from_stage,to_stage,
        sum(passengers) passengers FROM od JOIN selected USING(route_id)
        WHERE date<={end} AND (to_stage-from_stage)*orientation>0
        GROUP BY route_id,from_stage,to_stage''')
    con.execute('''CREATE TEMP TABLE probabilities AS SELECT *,
        passengers/sum(passengers) OVER(PARTITION BY route_id,from_stage) probability
        FROM destinations''')
    con.execute('''CREATE TEMP TABLE cohort AS SELECT od.*,orientation FROM od JOIN selected USING(route_id)''')
    con.execute('''CREATE TEMP TABLE journeys AS
        SELECT date,hour,route_id,from_stage,to_stage,passengers,false estimated
        FROM cohort WHERE (to_stage-from_stage)*orientation>0
        UNION ALL
        SELECT c.date,c.hour,c.route_id,c.from_stage,p.to_stage,c.passengers*p.probability,true estimated
        FROM cohort c JOIN probabilities p USING(route_id,from_stage)
        WHERE c.to_stage IS NULL''')
    con.execute('''CREATE TEMP TABLE flow AS SELECT date,hour,s.route_id,s.series_id,s.stage_a,s.stage_b,
        sum(passengers) passengers,
        sum(CASE WHEN estimated THEN passengers ELSE 0 END) estimated_passengers
        FROM journeys j JOIN sections s ON j.route_id=s.route_id
          AND (s.stage_a-j.from_stage)*s.orientation>=0
          AND (j.to_stage-s.stage_b)*s.orientation>=0
        GROUP BY ALL''')
    # Every selected section gets 24 recorded-ticket hours on an observed route-day.
    con.execute('''CREATE TEMP TABLE dense AS SELECT d.date,h.hour,s.route_id,s.series_id,s.stage_a,s.stage_b,
        coalesce(f.passengers,0) passengers,coalesce(f.estimated_passengers,0) estimated_passengers
        FROM (SELECT DISTINCT date,route_id FROM cohort) d JOIN sections s USING(route_id)
        CROSS JOIN range(0,24) h(hour)
        LEFT JOIN flow f ON f.date=d.date AND f.hour=h.hour AND f.series_id=s.series_id''')
    con.execute(f"COPY dense TO {literal(output/'segments.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY sections TO {literal(output/'section_catalog.parquet')} (FORMAT PARQUET, COMPRESSION ZSTD)")
    # Reconstruct number of interval crossings two independent ways.
    expected=con.execute('''SELECT coalesce(sum(j.passengers * (
        SELECT count(*) FROM sections s WHERE j.route_id=s.route_id
        AND (s.stage_a-j.from_stage)*s.orientation>=0 AND (j.to_stage-s.stage_b)*s.orientation>=0)),0)
        FROM journeys j''').fetchone()[0]
    actual=con.execute('SELECT sum(passengers) FROM flow').fetchone()[0]
    if not np.isclose(expected,actual,rtol=1e-9): raise AssertionError('Section crossing reconciliation failed')
    selected=con.execute('SELECT * FROM selected ORDER BY passengers DESC').fetchdf().to_dict('records')
    coverage=con.execute('''SELECT date,sum(passengers) total_passengers,
        sum(passengers) FILTER(WHERE (to_stage-from_stage)*orientation>0) known_valid_destination_passengers,
        sum(passengers) FILTER(WHERE to_stage IS NULL) missing_destination_passengers
        FROM cohort GROUP BY date ORDER BY date''').fetchdf().replace({np.nan:None}).to_dict('records')
    total=con.execute('SELECT sum(passengers) FROM cohort').fetchone()[0]
    reconstructed=con.execute('SELECT sum(passengers) FROM journeys').fetchone()[0]
    report={'training_cutoff':train_end,'routes_selected':selected,'section_count':n,
        'cohort_passengers':total,'reconstructed_journey_passengers':reconstructed,
        'unreconstructed_journey_passengers':total-reconstructed,'daily_coverage':coverage,
        'crossing_reconciliation':{'expected':expected,'actual':actual,'passed':True},
        'destination_method':'Training-only empirical distribution by route variant and boarding stage; no unsupported fallback',
        'label_kind':'estimated_stage_interval_passenger_crossings_by_boarding_hour',
        'limitations':['Stage intervals are not yet matched to geographic stop-to-stop segments',
                       'Missing destination estimates may be biased for free-ticket passengers',
                       'Unmatched destinations/stages are excluded and reported, not assumed zero',
                       'No crossing-time or full-service denominator is available',
                       'Prediction validation against these labels is not independent crowding validation']}
    write_json(output/'segment_report.json',report)
    con.close()
    return report
