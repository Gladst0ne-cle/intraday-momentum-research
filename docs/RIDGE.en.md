# v1.2.0 Ridge running guide

## Modes

1. `python scripts/run_ridge.py --demo --output output/demo`:train and replay100 fictional sessions without a historical model.
2. `python scripts/run_ridge.py --bars B.csv --minutes M.csv --specs S.csv --carry-zero --output output/own`:chronological refits on your own inputs.
3. Add`--frozen-model models/ridge-v1.2.0.json`:inference only, with every signal at or after`prediction_not_before_ms`. This does not reproduce the historical warmup/refit mixture. Missing model outputs fall back to original exits.

Output directories must not exist. All operations are offline; there is no collection or order interface.

## Inputs

-30-minute CSV:`symbol,timestamp_ms,open,high,low,close,volume`,13 bars09:30–15:30 plus16:00 boundary, New York session converted to UTC milliseconds with DST.
-Minute CSV:same columns, complete09:30–15:59 paths for the prior14 sessions of each candidate and the current session through16:01. Minute volume must use the same units as parent bars. Do not fabricate missing volume.
-Specs CSV:`symbol,quantity_step,minimum_quantity,unit_value`. The unit affects quantity, PnL and carry.
-Carry:explicitly select`--carry-zero`, or supply`--carry-file carry.csv --carry-coverage-start START_MS --carry-coverage-end END_MS`. Columns:`symbol,timestamp_ms,rate`. Events must be unique minute boundaries inside caller-verified coverage; missing events are not implicitly zero funding.

Optional`--start YYYY-MM-DD --end YYYY-MM-DD`select signal dates. Prior bars are still required for features. Training warmup restarts at the selected signal range; labels from excluded earlier dates are not silently used. Changing the period can change fitted models.

```bash
python scripts/run_ridge.py --demo --export-example output/example --output output/example-run
python scripts/run_ridge.py --bars output/example/bars30.csv --minutes output/example/minutes.csv --specs output/example/specs.csv --carry-zero --cost-grid --output output/reload
```

## Features, training and exit

See`ridge_features.FEATURES`for the exact21-dimensional schema:holding time, time since net peak, net/peak/giveback, VWAP distance,5-minute directional return/range, entry-boundary distance, entry volatility/sigma/breach, next30-minute clock distance, original-line distance, second-close change, VWAP slope, violation streak, relative session/previous-bar volume, directional close location and warning age.

Features use completed prefixes only. Minute VWAP excludes zero-volume weights; aggregation uses traded minutes unless the whole bucket is empty. Frozen entry scale`s0`is the maximum of the prior14 same-slot5-minute true-range median and today's pre-signal mean true range.

Target:`[net per-unit outcome at original exit − net per-unit outcome at current decision+60s]/entry price`. Future outcomes are labels, not inputs. Fit only eligible two-confirmation events from completed past days. Weights balance day/candidate/event. Mean and population standard deviation are fitted on training features only; normalized inputs are clipped to±8, labels to±5%; Ridge alpha is100 with an unpenalized intercept.

Start forecasting after60 signal days; expanding refit every20 days, embargoing the immediately preceding signal day. Exit early only when two confirmations hold and predicted continuation is below−2bp. Original exits have priority and the regular forced proxy remains16:01. Reference budgets, entry-cost reserves, downward quantity rounding and compounding retain the shared minute cash engine.

## Diagnostics and limitations

`--cost-grid`adds0/2/5/10/20/40bp round-trip cost to the same frozen decisions without refitting. `python scripts/check_ridge.py --run output/demo --block 5 --replications 1000 --output output/diagnostics.json`resamples matched whole signal days against both controls. Intervals describe relative wealth advantage, not return-percentage-point differences or future loss probability. Removing top profits is retrospective sensitivity, not a tradable rule.

Original historical inputs remain necessary to reproduce the published curve. A latest frozen model cannot predict its training past.51 public tests and local833-path parity validate implementation, not real execution. There is no margin, liquidation, depth matching or guaranteed outage exit. No neural network is used.
