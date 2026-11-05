# What the errors mean, and what was tried

The original boarding forecast test WAPE is 32.62% per route variant/hour. WAPE is the sum of absolute passenger errors divided by actual passenger volume. It is not the percentage of rows predicted incorrectly and should not be converted to classification accuracy.

The 22.17% section-flow WAPE is against reconstructed labels on ten busy route variants. It is a different population and aggregation. It does not establish better accuracy for real crowding.

The 37.92% destination score is exact top-destination accuracy on known-destination passengers held out for validation. Missing passengers are not all assigned that single destination: their counts are distributed across the training-derived downstream destination probabilities. Aggregate section flow can be less sensitive than exact individual destinations, but missing/free-ticket passengers may differ from the known group. No independent real crowding accuracy is available.

## Timing diagnosis

On matched-history validation rows only, the same historical forecasts have 34.01% WAPE hourly, 26.19% when aggregated to two-hour totals, 21.01% at four hours and 14.41% for daily route-variant totals. These are diagnostic aggregations, not improvements in hourly accuracy. They suggest considerable uncertainty in the exact hourly allocation of ticketed demand.

Separate weekday/Saturday/Sunday profiles did not improve overall matched validation WAPE (34.01% to 34.52%). Replacing means with conditional medians produced only a small change (34.01% to 33.77%) and worsened Sunday. These diagnostics do not justify promising a fix.

## One focused XGBoost revision

The revised candidate uses the historical forecast as its starting count estimate, then learns regularized multiplicative corrections. Settings and boosting rounds are selected only on March 15–21 and require improved overall MAE without worsening busy-hour MAE. It did not beat the historical baseline on validation, so it is not promoted.

March 22–28 was already examined during initial work. The new candidate was audited once on March 29–31 instead, after settings were frozen. That audit spans only three days and does not establish long-term reliability. See refinement.json for the exact metrics; the small numerical difference on the audit does not override the validation-based selection decision.

PCA compresses feature columns; K-means groups similar observations. Neither supplies missing alighting destinations, actual segment crossing times or a verified service denominator. They remain possible future experiments, not an assured remedy for these errors.

The current release is suitable for a transparently labeled prototype and scenario discussion. It is not validated for automatic real-world overcrowding response.
