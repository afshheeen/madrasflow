# Initial validation results

These results describe one month of ETM data and an experimental prediction backend. They do not establish real-world occupancy accuracy.

## Data checks

- Files: 31; parsed records: 67,943,937.
- Accepted passenger journeys: 77,374,812.
- All daily passenger aggregations reconcile. All 31 record counts agree with the independent physical-line audit; raw passenger sums also agree on the three independently fully parsed days.
- Quality/exclusion record counts: {'excluded_ticket_type': 148674, 'accepted': 67795257, 'invalid_timestamp': 4, 'missing_route_identity': 2}.
- Idempotent uploads, quoted stop names, overnight dates and duplicate handling are covered by automated tests.

## Held-out forecasting

Training history: March 2–14; validation: March 15–21; final test: March 22–28, 2026. Weekday/weekend grouping. The validation score chooses the method; test scores do not select it. Model weights are fixed for the test week while past-only daily features refresh.

| Target | Selected on validation | Historical benchmark test WAPE | XGBoost test WAPE |
|---|---|---:|---:|
| Hourly ticketed boardings per route variant/direction | baseline | 32.62% | 34.18% |
| Reconstructed stage-interval passenger flow, 10 pilot variants | baseline | 22.17% | 22.24% |

WAPE is total absolute error divided by total actual target volume. It is not a classification accuracy or an accuracy percentage to subtract from 100. Errors on reconstructed flow are evaluated against the reconstruction, not independently measured occupancy.

Summing the same boarding predictions across endpoint variants into raw route/direction labels gives WAPE 29.60% for the historical method and 30.61% for XGBoost. This is a different reporting granularity, not another fitted model or a reason to change the selected method.

## Section feasibility

- Pilot intervals: 118; route/direction variants: 10.
- Reconstructed journeys: 4,140,604 of 4,143,997; unsupported journeys: 3,393.
- Independent crossing-sum arithmetic check passed.
- Masked known-destination validation top-destination accuracy: 37.92%. Free-ticket journeys may have different patterns, so this does not validate the missing group.
- Stage geography, actual section crossing times and complete operated/planned trip counts are unavailable. These outputs are stage-interval, boarding-hour proxies and must not be displayed as verified crowding.

## Interpretation

The historical benchmark beat the tested XGBoost configuration on validation for both targets and remains the selected method. The current error levels and missing destination evidence do not justify a claim of accurate section overcrowding prediction. There was no additional model search after inspecting the final test.

The backend provides audited data, daily updates, separate weekday/weekend profiles, an XGBoost challenger and conditional minimum-trip/reallocation calculations. Physical fleet sizing requires cycle time; actual rerouting needs vehicle, road and crew feasibility. Maps/mobile UI are subsequent integration work.

See [methodology](../docs/methodology.md) and [machine-readable results](validation.json).
