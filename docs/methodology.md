# Definitions and evaluation

## Weekday/weekend grouping

The initial features distinguish Monday–Friday from Saturday–Sunday. This pools the limited history. Hour and route/direction remain separate. Saturday and Sunday descriptive totals are reported independently so the grouping can be reviewed without fitting more forecast models. Only one month is available; no annual/event generalization is established.

## Two output levels

1. Ticketed boardings: the validated count of passengers recorded in tickets, by calendar date, route variant/direction and issue hour. Free passenger tickets are included. Luggage and adjustment tickets are not additional passenger journeys.
2. Estimated stage-interval passenger crossings: pilot route reconstruction using valid destinations and a training-only empirical distribution for missing destinations. These are boarding-hour proxies. They are not geographic stop-to-stop, crossing-hour occupancy measurements. Outputs carry coverage and missing-data limitations.

The absence of GPS, timetable, validated geographic stage mapping and complete alighting information limits occupancy claims. Do not color a map as verified crowding using these estimates alone. A failed or absent mapping is unknown rather than free. Likewise, do not divide by ticket-bearing vehicle counts and call them all operated trips.

## Stage reconstruction

Route identity retains raw direction and trip endpoints. Training history determines stage orientation (at least 95% agreement) and stage intervals. Missing destinations use known-destination frequencies conditional on route variant and boarding stage. Unsupported origins are excluded and counted. This is an initial, possibly biased imputation; fare groups may have different journeys.

The known-destination distribution, stage catalogue and pilot route selection are fit only through March 14. Forecast testing against reconstructed labels measures agreement with those labels, not independent real-world occupancy accuracy. A manual passenger-count sample is still needed for occupancy validation.

## Evaluation protocol

- March 1 is excluded from model targets because February duty-file spillover is unavailable.
- Initial fit through March 14; first five available dates supply feature history.
- Validation March 15–21 selects boosting rounds and chooses between a historical benchmark and XGBoost by MAE.
- Refit XGBoost once through March 21 with frozen settings. Model weights stay fixed throughout March 22–28 testing; recent features update from preceding days only.
- Weekday/weekend/hour means, recent summaries and one-/seven-day lags use past observations. No target-day observations are used for any of its 24 hours.
- Prior-day availability is an explicit assumption. Actual daily ETM delivery latency is unconfirmed. Adjust the feature cutoff before deployment if delivery is delayed.
- Score on 24 recorded-ticket hours for route-days observed in the dataset. Entirely absent route-days remain unknown and are not silently assigned zero. Evaluation therefore does not establish performance for unobserved service coverage.
- Report MAE, WAPE, signed error, underprediction, daily results and busy-period results. Validation chooses the model; final test scores are not a selection tool.

## Service recommendations

Crowding bands in passengers per bus: free <=40; light >40–<50; medium 50–<60; crowded 60–<70; very crowded >=70. Actual capacity is separate.

For a route whose trips all cover all supplied sections, minimum trip passages per hour is the maximum over sections of ceil(passenger crossings / target passengers per bus). Default target is 40 and is configurable. This is not a fleet count. A conditional fleet lower bound is ceil(hourly trip rate * full round-trip cycle minutes / 60), assuming compatible service in both directions and including layover in cycle time.

Reallocation protects the donor's target load and at least one trip per hour by default. It returns conditional candidates, not feasible reroutes or dispatch. Location, road access, deadhead time, crew, opposite-direction needs, uncertainty and headway requirements remain to be checked. Fixed demand and even passenger distribution are scenario assumptions.

## Updating

Source files are fingerprinted; unchanged files are skipped. Changed files replace their validated aggregate partition, so repeating an upload does not append it twice. A source must not change while being read. Keep raw inputs outside Git; outputs are ignored. Repeat ingestion, reconstruction and evaluation before replacing a deployed model. Retraining is not guaranteed to improve accuracy.

## Maps and explanations

Stage interval IDs, route identity, day type and hour are stable data adapters for a later geographic mapping/UI layer. No coordinates or matching certainty are invented. Structured explanations should show the historical reference, current features, service assumptions and quality flags. Feature contributions explain prediction associations, not intervention causality; Poisson contributions are on the raw log scale.

Driver reports belong in a separate reported/acknowledged/resolved workflow and may link to routes/sections. They are not automatically exact occupancy labels.
