> v1.2.0 Ridge: [中文](RIDGE.zh-CN.md) / [English](RIDGE.en.md). This page describes the preserved v1.1.0 minute replay.

# v2 running guide

## Setup and the complete example

Use Python 3.10+. The simulator and tests use the standard library; Windows
may need the timezone database in `requirements.txt`.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/run_replay.py --demo --compare
python -m unittest discover -s tests
```

Demo prices are fictional, and their minute paths interpolate fictional
half-hour bars. They are not historical observations or evidence of profit.
Existing outputs are protected: choose another `--output`, or explicitly use
`--overwrite` to replace the known output files.

## Versions, capital and costs

```bash
python scripts/run_replay.py --demo --config configs/v1.1.0.json --output output/v1.1
python scripts/run_replay.py --demo --config configs/v1.0.0.json --output output/v1-control
python scripts/run_replay.py --demo --compare --initial-equity 300 --extra-cost-bps 20 --output output/stress20
```

`--compare` runs two separately compounded portfolios with identical input,
cost and delay assumptions. Base commission is 5 bp per side; the additional
execution-cost proxy is 5 bp round trip. `--extra-cost-bps 20` adds another
20 bp round trip to the proxy, not to commission. The 4x reference exposure cap
and 4% volatility budget are fixed components of these strategy specifications.

The v1 config in the **new** engine is the original signal under updated
minute accounting. It is not the legacy execution protocol. The unchanged
`python src/simulate.py --demo` and old research tools are documented in the
[legacy guide](LEGACY.en.md). Those tools expect legacy schemas/fee definitions;
do not apply them to new outputs without adapting them.

## Export and reload the full input formats

```bash
python scripts/run_replay.py --demo --compare --export-example output/example --output output/example-run
python scripts/run_replay.py --bars output/example/bars30.csv --minutes output/example/minutes.csv --specs output/example/specs.csv --carry-zero --compare --output output/from-files
```

These two runs should agree. Tests cover the export/reload path. The repository
does not download market data; bring and verify your own inputs.

### Half-hour bars

`bars30.csv` columns: `symbol,timestamp_ms,open,high,low,close,volume`.
Timestamps are UTC Unix **milliseconds**, denoting bar starts. Each symbol/date
must have all 13 regular-session bars starting at 09:30, 10:00, ..., 15:30
New York time, plus a 16:00 boundary row. The boundary row maintains the legacy
format; new execution prices come from minute data. At least 15 complete warm-up
sessions and one evaluation session are needed. All dates use the same universe.

Duplicate timestamps, missing bars and invalid OHLCV fail. Early-close sessions
must be excluded by a predefined input policy, not padded with invented prices.
The loader does not independently verify holidays, wholly absent dates,
publication latency or cross-frequency price consistency. Use a common source
and adjustment basis; mismatched adjustments can fabricate signals.

### Minute bars

`minutes.csv` columns: `symbol,timestamp_ms,open,high,low,close`.
Use UTC milliseconds on minute boundaries. Every minute from entry through
exit, inclusive, must be present. A full-session hold needs the **16:01** minute.
Invalid OHLC, duplicates and missing path prices fail; no forward-fill or
half-hour fallback is used. Risk sampling uses minute opens, not intraminute
extremes or exchange mark prices.

### Instrument specifications

`specs.csv` columns: `symbol,quantity_step,minimum_quantity,unit_value`.
All values must be positive and symbols unique. Quantity means contracts/shares;
`unit_value` is underlying units per quantity. Notional is
`quantity * unit_value * price`. Demo specifications are fictional assumptions.

### Carry events

Either explicitly use `--carry-zero`, or supply `carry.csv` with columns
`symbol,timestamp_ms,rate` and declared start/end coverage. A positive rate is
paid by longs and received by shorts. Only `entry < event <= exit` is charged.
The rate multiplies the settlement minute's opening notional, as a mark-price
proxy. The code assumes no fixed settlement schedule.

```bash
python scripts/run_replay.py --bars your-bars.csv --minutes your-minutes.csv --specs your-specs.csv --carry-file your-carry.csv --carry-coverage-start 1700000000000 --carry-coverage-end 1900000000000 --compare --output output/your-data
```

The example coverage numbers illustrate the format; replace them with actual
verified UTC-millisecond boundaries. A coverage declaration does not prove
that every required event was obtained. Check each instrument's schedule and
missing events yourself. Explicit zero-carry runs are labeled as assumptions.

`--start YYYY-MM-DD --end YYYY-MM-DD` limits evaluation by New York session
date; retain the 15 earlier warm-up sessions in the inputs. SHA-256 input hashes
are included for provenance and comparison.

## Outputs and module map

- `comparison.json`: aligned two-version summaries when `--compare` is used.
- Per-version `summary.json`: compounded return, separate closed and minute
  drawdowns, wins, cash components, configuration and input hashes.
- `trades.csv`: direction, timing, selected/reference symbols, sigma floor,
  quantity, exposure, gross P&L, fees, proxy, carry and before/after equity.
- `equity.csv`: daily equity, including no-signal days, and closed drawdown.
- `minute_equity.csv`: hypothetical net close-out value during positions;
  no interpolation across idle periods.
- `decisions.csv`: first-slot choice/reference, or `no_signal` / `below_minimum`.

`output/` is ignored by Git. Keep your market data and output records private,
including when you choose another directory.

`src/versioned_replay.py` contains selection, causal exit planning, quantity
budgets and the cash ledger. `src/replay_cli.py` handles validation, hashes and
exports. `scripts/run_replay.py` is the recommended entry point; `configs/`
registers versions; `tests/` verifies behavior. Original strategy modules remain
unchanged. `research/` has separate legacy-format experiments; `evidence/`
contains aggregate historical results only; `figures/` contains finished images.

See [version mathematics and evidence limits](STRATEGY_VERSIONS.md). Raw
historical inputs are not published, so a clone cannot independently reproduce
the historical curve. No live orders, account reconciliation, liquidation,
disconnect recovery or matching engine are provided. Passing tests validates
the offline behavior under stated assumptions, not future profitability.
