# 研究工具 / Research tools

这些工具只运行离线模拟，不下单。原始历史行情、账户记录和前向实验数据均未包含在仓库。以下命令从仓库根目录运行；示例行情完全虚构，结果不代表真实表现。默认要求 Python 3.10+；时区数据缺失时参见主 README。

All tools run offline and do not place orders. Original historical bars and account records are not included. Run commands from the repository root. Demo data are fictional and results are not evidence of performance.

## 准备示例 / Prepare the demo

```bash
python src/simulate.py --demo --save-demo-bars output/research-bars.csv --output output/research-demo
```

如果输出已存在，请指定其他路径或明确使用 `--overwrite`。实验只输出 JSON 到终端，不会覆盖输入。

If output already exists, select other paths or explicitly add `--overwrite`. Research commands write JSON to stdout and do not overwrite inputs.

## 1. 仓位和止损情景 / Sizing and stop scenarios

```bash
python research/risk/scenarios.py --trades output/research-demo/trades.csv --summary output/research-demo/summary.json --factor 2 --cap 4
python research/risk/scenarios.py --trades output/research-demo/trades.csv --summary output/research-demo/summary.json --bars output/research-bars.csv --stop 0.05
```

缩放名义杠杆，或者在原行情路径上模拟逐笔亏损触发。`--stop 0.05` 是**手续费前**相对入场权益的价格损失阈值；程序在半小时 K 线触及阈值时采用触发价，若该 K 线开盘已越过阈值则使用更差的开盘价。区间内触发次序、滑点、延迟、部分成交、保证金和强平均未模拟，费用或跳价可能使亏损超过阈值。由于不知道提前退出时的持仓费用，止损情景要求原交易的 carry 为零，且必须提供与交易对应的完整 K 线。

Scale exposure or apply a hypothetical per-position stop to the same price path. `--stop 0.05` is a pre-fee price-loss threshold relative to entry equity. A touched stop fills at the threshold, or at a worse bar open after a gap. Intrabar ordering, slippage, latency, partial fills, margin and liquidation are not simulated. Costs and gaps may exceed the threshold. Stop scenarios require zero carry and matching complete bars.

## 2. 入场信号过滤 / Entry signal filter

```bash
python research/signals/filter_study.py --trades output/research-demo/trades.csv --summary output/research-demo/summary.json --bars output/research-bars.csv --feature breach --train-count 6
```

从入场前已完成的 K 线和至少 15 个先前交易日重建信号，校验标的、方向与原杠杆，再比较全部后续交易与“突破幅度不超过训练段中位数”的示例过滤。可选 `--feature daily_vol` 或 `leverage`；中位数只取训练段。它是固定的教学规则，不会生成新的候选交易，也不能证明过滤有效。

Reconstruct the selected signal from completed bars and at least 15 prior sessions, checking symbol, direction and original leverage. Compare all later trades against one predeclared median threshold learned from training trades. `--feature daily_vol` and `leverage` are alternatives. This illustrative filter does not generate new candidate trades and is not a validated strategy.

## 3. 数据质量 / Data quality

```bash
python research/data_quality/check_bars.py --bars output/research-bars.csv
python research/data_quality/check_bars.py --bars path/to/bars.csv --calendar path/to/sessions.csv
```

检查 OHLCV、重复时间戳、每个标的的完整半小时网格及一致的交易日期。可选日历 CSV 仅需 `date` 列，列出**与数据范围完全一致**的预期交易日；缺失或额外日期会返回非零状态。日历由用户提供，程序不能自行证明数据来源可信或识别所有提前收市日。

Checks OHLCV, duplicate timestamps and complete per-symbol grids. An optional `date`-column calendar must cover exactly the data period; mismatches return a nonzero exit status. The user must supply a correct calendar; source integrity and special sessions cannot be guaranteed.

## 4–5. 基准预测与滚动区间 / Prediction baselines and rolling intervals

```bash
python research/models/prediction.py --trades output/research-demo/trades.csv --summary output/research-demo/summary.json --train-count 6 --mode fixed
python research/models/prediction.py --trades output/research-demo/trades.csv --summary output/research-demo/summary.json --train-count 6 --mode rolling
```

固定切分比较零预测、训练均值和只使用**入场前杠杆**的简单线性回归，同时报告预测为正才交易与全部交易的结果。滚动模式按时间扩展训练集，排除决策前尚未结束的标签，只用先前已完成的滚动预测残差生成经验区间；最初没有足够残差时不输出区间。样本少、反复研究的切分、模型选择及非平稳市场都可能导致严重过拟合，经验覆盖率不构成未来覆盖保证。此处是轻量基准，不是深度学习，也不做自动模型筛选。

The fixed split compares zero, training mean and a simple linear model using **pre-entry leverage**. It reports trade-all and positive-prediction results. Rolling mode trains on completed prior labels only and uses earlier completed rolling prediction residuals for empirical intervals. No interval is emitted until residuals exist. Small samples, repeated inspection, model selection and market shifts can overfit; empirical coverage is not guaranteed. These are lightweight baselines, not deep learning or automatic model selection.
