# Changelog / 版本记录

## v2.0.0 — 2026-11-06

- 保留 30 分钟噪声带突破、首个信号时点、每日最多一笔及原 band/VWAP 退出。
- 同时出现多个候选时，用 `breach / max(sigma, median(candidate_sigma))` 排序，降低极小波动分母对排序的影响。中位数只使用该时点有效候选。
- 候选仓位同时受原始突破赢家的名义敞口预算和波动风险预算限制；没有增加杠杆上限，仍为 4 倍。
- 新增独立的分钟成交代理回放：信号和退出决策后等一分钟，按进出场各自名义金额收取费用及执行成本代理；结算时分钟价计算持仓费用；预留入场费用并向下取整数量。
- 增加双版本对照、配置文件、逐笔现金账本、分钟权益及回撤、CSV 输入导出、测试和中英文运行手册。
- 新图沿用初始版版式，展示同口径 157 个信号日对照。初始版旧图保留；未上传原始行情、逐笔历史记录、账户或执行接口。
- 验证：28 项自动测试通过；从已完成半小时行情独立重建两个版本各 157 日的入场与退出，再对取整数量、现金账本和分钟回撤逐笔核对；与冻结研究结果一致。

The new selector floors its normalization denominator at the current candidate
pool's median sigma. The first entry slot, bands, half-hour exit checks and
four-times maximum reference exposure remain unchanged. A separate minute
proxy engine compares both signal rules with identical accounting. New runtime
reports distinguish closed-trade and minute-sampled close-out drawdowns.

This is retrospective research, not a claim of independent validation or live
profitability. The updated full-sample return is higher, but its full-sample
drawdown is also higher than the aligned original-rule control.

## v1.0.0 — initial public snapshot / 初始公开版

Preserves commit `cb7b2ce4132c1f1f82ff5a511149b9520a5aae83` before the v2 update.
Original raw-breakout ranking, 30-minute opening-price replay, offline research
modules and the original 53-trade historical summary remain available.
The legacy historical summary (+40.54%) uses a different sample/execution
protocol from the new 157-day comparison; do not subtract the two returns.
