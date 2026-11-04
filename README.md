# Intraday momentum research

Research code for a 30-minute noise-band strategy on U.S.-equity-related instruments. The implementation is venue-neutral: it accepts caller-supplied bars, returns a decision, and does not fetch market data or place orders.

## Strategy

- For each instrument, estimate the expected absolute move from the session open using the same 30-minute slot in the previous 14 sessions.
- Build upper and lower bands around the session open and previous close. A close beyond a band creates a directional candidate; at most one candidate is selected per day, using the largest relative breach at the earliest signal time.
- Size the position from 14-session close-to-close volatility, with a 4% volatility target and a 4× exposure cap. This is a research sizing rule, not a loss limit.
- At subsequent 30-minute closes, exit a long when the close falls to the higher of the upper band and the session VWAP; the short rule is symmetric. Any remaining position is closed at the session boundary.

The caller is responsible for chronological data, actual availability timestamps, exchange calendars, execution, and position state. The function does not implement an execution engine, market impact, margin, liquidation, or a stop order.

## Historical research summary

One repeatedly examined historical test segment, ending on 2026-10-29, contained 53 trades. Under that experiment's assumptions, compounded equity changed from 1.0000 to **1.4054** (+40.54%), with **49.06%** winning trades and **15.20%** maximum drawdown measured after completed trades. The underlying instruments were derivatives associated with U.S. equities; these figures are not an equity-ETF backtest and are not real trading results.

The experiment used the next 30-minute opening price as a fill proxy and assumed a 10-basis-point round-trip fee on notional, with no additional slippage charge. Historical funding coverage was incomplete, so the result is not a fully reconciled cost estimate. The segment was examined repeatedly during research and is not an untouched independent validation set; a few large winners materially affected the result. No source prices, trade records, account information, credentials, or production execution code are included, so this repository alone cannot reproduce that historical figure. See [historical_summary.json](historical_summary.json) for the compact summary.

The general research context includes [Beat the Market: An Effective Intraday Momentum Strategy for the S&P 500 ETF](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf). This implementation and its historical experiment differ in instruments, execution assumptions, and portfolio selection; the paper does not validate these results.

## Use and tests

Python 3.10 or later is sufficient; the decision module uses the standard library only.

```bash
python -m unittest discover -s tests
```

Add `src` to the Python path and call `decide(histories, today, index, position, traded)`. A history consists of complete past sessions with `open`, `close`, and 13 bars. Each bar is `(timestamp, open, high, low, close, volume)`; `today` contains only the completed bars available at the decision time. See the tests for a synthetic input example.

`backtest.run_session` provides a single-session replay with next-bar opening-price proxies. It requires an explicit carry function; callers must supply their own data and cannot treat an absent funding history as a verified zero. `backtest.account` compounds completed trade returns and reports drawdown between those completed trades only.
