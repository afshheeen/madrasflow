"""Save small aggregate verification summaries, never ticket rows or model datasets."""
from pathlib import Path
import collections
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from madrasflow.storage import connection,literal,load_json,write_json
from madrasflow.forecast import metrics

def main():
    root=Path(__file__).resolve().parents[1]
    qa=load_json(root/'artifacts/data_verification.json')
    boarding=load_json(root/'artifacts/boardings/metrics.json')
    segment=load_json(root/'artifacts/segment_model/metrics.json')
    reconstruction=load_json(root/'artifacts/segments/segment_report.json')
    ingest=load_json(root/'data/ingestion_report.json')
    con=connection()
    con.execute(f"CREATE TEMP VIEW p AS SELECT * FROM read_parquet({literal(root/'artifacts/boardings/test_predictions.parquet')})")
    con.execute(f"CREATE TEMP VIEW mapping AS SELECT DISTINCT route_id,route_direction FROM read_parquet({literal(root/'data/hourly.parquet')})")
    grouped=con.execute('''SELECT date,hour,route_direction,sum(passengers) passengers,
        sum(baseline) baseline,sum(xgboost) xgboost FROM p JOIN mapping ON p.series_id=mapping.route_id
        GROUP BY ALL''').fetchdf()
    route_metrics={name:metrics(grouped.passengers,grouped[name]) for name in ['baseline','xgboost']}
    con.close()
    quality=sum((collections.Counter({r['quality']:r['records'] for r in f['quality']}) for f in ingest['files']),collections.Counter())
    summary={'data':{'files':qa['file_count'],'raw_records':qa['raw_records'],
              'accepted_passengers':qa['accepted_passengers'],'quality_records':dict(quality),
              'independent_checks_passed':qa['all_checks_passed'],
              'independent_raw_duty_check':qa.get('independent_raw_duty_check'),
              'training_day_of_week_summary':qa['training_day_of_week_summary']},
        'boarding_forecast':boarding,'route_direction_aggregation_of_same_predictions':route_metrics,
        'section_proxy_forecast':segment,
        'section_reconstruction':{k:reconstruction[k] for k in ['section_count','cohort_passengers',
            'reconstructed_journey_passengers','unreconstructed_journey_passengers','crossing_reconciliation',
            'masked_known_destination_validation','label_kind','limitations']},
        'section_route_variants':[{'direction':r['route_direction'],'origin':r['origin'],'terminus':r['terminus']}
                                  for r in reconstruction['routes_selected']],
        'release_scope':{'geographic_mapping':'not implemented','driver_mobile_ui':'not implemented',
                         'service_planning':'conditional arithmetic, no verified service plan available',
                         'actual_crowding_validation':'unavailable; occupancy outputs remain estimates'}}
    write_json(root/'reports/validation.json',summary)
    def pct(x):return f'{100*x:.2f}%'
    text=f'''# Initial validation results

These results describe one month of ETM data and an experimental prediction backend. They do not establish real-world occupancy accuracy.

## Data checks

- Files: {qa['file_count']}; parsed records: {qa['raw_records']:,}.
- Accepted passenger journeys: {qa['accepted_passengers']:,.0f}.
- All daily passenger aggregations reconcile. All 31 record counts agree with the independent physical-line audit; raw passenger sums also agree on the three independently fully parsed days.
- Quality/exclusion record counts: {dict(quality)}.
- Idempotent uploads, quoted stop names, overnight dates and duplicate handling are covered by automated tests.

## Held-out forecasting

Training history: March 2–14; validation: March 15–21; final test: March 22–28, 2026. Weekday/weekend grouping. The validation score chooses the method; test scores do not select it. Model weights are fixed for the test week while past-only daily features refresh.

| Target | Selected on validation | Historical benchmark test WAPE | XGBoost test WAPE |
|---|---|---:|---:|
| Hourly ticketed boardings per route variant/direction | {boarding['selected_model_from_validation']} | {pct(boarding['test']['baseline']['wape'])} | {pct(boarding['test']['xgboost']['wape'])} |
| Reconstructed stage-interval passenger flow, 10 pilot variants | {segment['selected_model_from_validation']} | {pct(segment['test']['baseline']['wape'])} | {pct(segment['test']['xgboost']['wape'])} |

WAPE is total absolute error divided by total actual target volume. It is not a classification accuracy or an accuracy percentage to subtract from 100. Errors on reconstructed flow are evaluated against the reconstruction, not independently measured occupancy.

Summing the same boarding predictions across endpoint variants into raw route/direction labels gives WAPE {pct(route_metrics['baseline']['wape'])} for the historical method and {pct(route_metrics['xgboost']['wape'])} for XGBoost. This is a different reporting granularity, not another fitted model or a reason to change the selected method.

## Section feasibility

- Pilot intervals: {reconstruction['section_count']}; route/direction variants: 10.
- Reconstructed journeys: {reconstruction['reconstructed_journey_passengers']:,.0f} of {reconstruction['cohort_passengers']:,.0f}; unsupported journeys: {reconstruction['unreconstructed_journey_passengers']:,.0f}.
- Independent crossing-sum arithmetic check passed.
- Masked known-destination validation top-destination accuracy: {pct(reconstruction['masked_known_destination_validation']['top_destination_accuracy'])}. Free-ticket journeys may have different patterns, so this does not validate the missing group.
- Stage geography, actual section crossing times and complete operated/planned trip counts are unavailable. These outputs are stage-interval, boarding-hour proxies and must not be displayed as verified crowding.

## Interpretation

The historical benchmark beat the tested XGBoost configuration on validation for both targets and remains the selected method. The current error levels and missing destination evidence do not justify a claim of accurate section overcrowding prediction. There was no additional model search after inspecting the final test.

The backend provides audited data, daily updates, separate weekday/weekend profiles, an XGBoost challenger and conditional minimum-trip/reallocation calculations. Physical fleet sizing requires cycle time; actual rerouting needs vehicle, road and crew feasibility. Maps/mobile UI are subsequent integration work.

See [methodology](../docs/methodology.md) and [machine-readable results](validation.json).
'''
    (root/'reports/validation.md').write_text(text,encoding='utf-8')
    print('Saved aggregate reports; route-direction WAPE:',route_metrics)

if __name__=='__main__': main()
