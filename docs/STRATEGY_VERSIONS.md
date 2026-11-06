# Strategy specifications / 策略版本

## Shared signal structure / 共同信号结构

Use 13 completed 30-minute bars from 09:30 through 15:30 New York time, with a
16:00 boundary row. Fifteen complete prior sessions are required. For slot `i`:

```text
sigma(i) = mean(abs(close(previous_day, i) / open(previous_day) - 1), last 14 sessions)
upper(i) = max(today_open, previous_session_close) * (1 + sigma(i))
lower(i) = min(today_open, previous_session_close) * (1 - sigma(i))
long  if completed_close > upper
short if completed_close < lower
long_breach  = (completed_close - upper) / completed_close
short_breach = (lower - completed_close) / completed_close
```

Previous close means the close of the last 15:30–16:00 bar. VWAP uses the
completed-bar HLC3 weighted by volume (a zero-volume bar has weight 1, retained
from the original model; this is a bar-based approximation, not tick VWAP).
Daily volatility is the sample standard deviation of the last 14 close-to-close
returns. Invalid/zero volatility is ineligible. Zero sigma among candidates
raises an error in the new engine rather than hiding an undefined denominator.

Only the earliest eligible slot is used. Deterministic ties sort by symbol.
There is no replacement trade later in the day if the selected quantity is
below the instrument minimum. At most one position per session. No opening
signal is permitted at the final 15:30 bar's completion.

以上计算仅使用此前完整交易日和当天已收盘的 K 线。每日只使用最早有效时点；数量不足时不会事后改选其他标的或更晚的信号。

## v1.0.0 — original signal rule / 原始信号

Select the largest raw `breach`. The legacy program `src/simulate.py` retains
its next-half-hour opening-price execution and entry-notional round-trip fee.
The v1 configuration in the **new** replay program keeps this original signal
rule but uses the **new shared minute execution protocol** for a fair control.
The new v1 run does not reproduce the legacy chart's execution assumptions.

## v1.1.0 — sigma-floor signal rule / 分母下限更新

```text
floor = median(sigma of all valid candidates in the first signal slot)
score(candidate) = breach / max(candidate_sigma, floor)
selected = candidate with highest score
reference = candidate with highest raw breach  # same reference as v1
reference_exposure = min(4, 0.04 / reference_daily_volatility)
reference_risk_budget = reference_exposure * reference_daily_volatility
selected_target_exposure = min(reference_exposure,
                               reference_risk_budget / selected_daily_volatility)
```

The floor is recalculated at each actual decision using only the current
candidate pool. It is not fitted to future returns, nor to a full-period median.
With one candidate the selected symbol is identical to v1. No neural network,
outcome-based filter or extra delay policy is included in this release.

更新改变的是同一时点的候选排序。波动极低的标的不能仅凭分母很小取得任意大的分数。替换后的标的仍受原始赢家的双重预算限制；并非直接提高杠杆，也不是提高止损阈值。

## Shared exits / 原策略退出

For a long position: exit when a completed half-hour close is at or below
`max(upper, VWAP)`. For a short: exit when close is at or above
`min(lower, VWAP)`. Otherwise exit at the regular session boundary. The new
engine samples the opening price one minute after each exit decision; the
forced end-of-session proxy is **16:01 New York time**. No stop, take-profit,
intraminute trigger or liquidation protection is implied.

退出仍然每半小时检查一次，不是每分钟重新决策。分钟数据用于成交与风险采样。可能全天持有，也可能在下一次半小时检查时退出。

## Shared minute accounting / 统一分钟账本

- `fee_bps_per_side=5`: 5 bp on entry notional and 5 bp on exit notional.
- `execution_proxy_bps_round_trip=5`: an additional 2.5 bp per side, also on each side's notional. This is an assumed cash deduction, not a measured spread.
- Both decisions wait exactly 60 seconds. Entry may be 10:01 at the earliest; forced close is 16:01. Those minute opens must exist.
- Margin leverage is rounded upward to a configurable step, with minimum 1. Target exposure is not rounded upward. Entry collateral plus fee/proxy must fit equity; quantity is rounded downward to its own step.
- Carry cash flow at an event is `-side * rate * settlement_minute_open * quantity * unit_value` for `entry < event <= exit`. The minute open is a settlement-price proxy, not an observed mark.
- Net cash change is `side * units * (exit - entry) - fees - execution_proxy + carry`. Next trade uses the resulting equity. There are no external deposits/withdrawals in the replay.
- Closed drawdown uses equity after positions close. Minute close-out drawdown additionally deducts hypothetical exit costs at each minute open and keeps its own running high. Neither is an intraminute worst loss or a liquidation simulation.

The registered historical replay used synthetic initial capital of 300 units
and instrument-specific size steps. Different initial capital/specifications
change rounding and can slightly change returns. The bundled demo defaults to
10,000 fictional units and generic specifications; it is not the historical data.

## Evidence and limits / 证据边界

See [aggregate evidence](../evidence/historical-v1.1.0.json). The aligned full
sample contains 157 signal days, 2026-03-18 to 2026-10-29. Original-rule return
is approximately +47.70%; sigma-floor return +67.49%. Their closed drawdowns
are 13.57% and 15.55%; minute-sampled drawdowns are 16.16% and 17.17%.
Higher retrospective return did not come with uniformly lower risk.

The early/late partitions have already been examined. They are not fresh
holdouts. Several candidate policies were researched, and uncertainty includes
no advantage; no statistically established best strategy is claimed.
Historical raw inputs are deliberately omitted. The exact historical chart
cannot be independently reproduced from a clone alone. Functional simulations
and tests are fully runnable with fictional or caller-supplied inputs.
