# 30 分钟日内动量策略研究

[中文](README.md) | [English](README.en.md)

本仓库提供一个独立的 30 分钟噪声带策略和**离线模拟程序**。克隆后可以直接运行虚构数据示例，也可以使用自己的历史行情。程序不连接账户、不发送订单；示例中的数字不是实际交易结果。

## 快速开始

需要 Python 3.10 或更高版本。正常情况下不需要安装第三方 Python 包；如果系统缺少纽约时区数据库（部分 Windows 环境会出现这种情况），先运行 `python -m pip install tzdata`。

```bash
git clone https://github.com/Gladst0ne-cle/intraday-momentum-research.git
cd intraday-momentum-research
python src/simulate.py --demo
```

`--demo` 在本地生成虚构行情，假定持仓费用为零，默认以 10,000 模拟资金开始、双边手续费共 10 个基点。运行后生成：

- `output/simulation/trades.csv`：逐笔方向、进出场时间和价格、杠杆、费用后收益及每笔前后权益。
- `output/simulation/summary.json`：交易次数、胜率、复利权益、交易结束后最大回撤及假设说明。

为防止覆盖已有结果，重复运行时请用 `--output output/另一个目录`，或明确加入 `--overwrite`。也可以使用 `--initial-equity 300`、`--fee-bps 15` 调整初始资金和**双边合计**手续费假设。

```bash
python src/simulate.py --demo --initial-equity 300 --fee-bps 15 --output output/demo-300
python -m unittest discover -s tests
```

如果想查看完整的行情 CSV 格式，可运行以下命令导出一份**虚构**数据：

```bash
python src/simulate.py --demo --save-demo-bars output/example-bars.csv --output output/demo-export
python src/simulate.py --bars output/example-bars.csv --carry-zero --output output/from-csv
```

## 使用自己的行情

准备 UTF-8 CSV，列名必须为：

```csv
symbol,timestamp_ms,open,high,low,close,volume
AAA,1767623400000,100,101,99,100.5,1200
```

`timestamp_ms` 是 **UTC Unix 毫秒时间戳**，代表该根 K 线的开始时间。每个标的、每个提供的交易日都必须有完整的纽约时间 09:30、10:00、……、15:30 共 13 根半小时 K 线，以及 **16:00 的一行**：程序只使用该行开盘价作为收盘退出代理。标的之间必须覆盖同一组日期；至少提供此前 15 个完整交易日，才能开始模拟下一天。程序会检查日期内时间格、重复记录及 OHLCV，但**不能识别所有未提供的休市日或提前收市日**；请自行使用准确的市场日历筛选。时间转换使用纽约时区，包含夏令时。

如果明确选择把持仓费用暂时假定为零：

```bash
python src/simulate.py --bars path/to/bars.csv --carry-zero --output output/my-run
```

也可提供费用事件 CSV，列为 `symbol,timestamp_ms,rate`。`rate` 为小数形式：正值表示多头支付、空头收取；只计入开仓之后至平仓时刻的事件。必须同时以 Unix 毫秒声明文件覆盖起止；程序会检查每笔持仓是否位于声明范围内，但**不会独立证明事件完整**。

```bash
python src/simulate.py --bars path/to/bars.csv --carry-file path/to/carry.csv \
  --carry-coverage-start 1767225600000 --carry-coverage-end 1798761600000 \
  --output output/my-run
```

可选 `--start 2026-03-01 --end 2026-06-30` 限定评估日期；CSV 仍须包含起始日前至少 15 个完整交易日作为历史。程序在每个日期计算信号前只使用此前日期的历史和当日已完成 K 线，不会用未来日期训练。但用户仍须自行验证行情在相应决策时刻确实可用。

## 策略与模拟假设

策略用前 14 个交易日同一时段相对开盘的平均绝对波动构造噪声带；当半小时收盘价突破上轨或下轨时产生候选。同一日最多选择一笔，优先最早时段，多个候选则按突破幅度排序。仓位依据前 14 个收盘到收盘收益的样本波动率计算，波动目标为 4%，名义敞口上限为权益的 4 倍。之后每个半小时检查噪声带和当日 VWAP 退出条件，剩余持仓在收盘退出。

模拟使用**下一根半小时开盘价**作为成交代理，按当时权益复利。实际点差、冲击、排队、延迟、部分成交、保证金、强平和盘中风险均未模拟；最大回撤只在交易完成后计算。模拟期间若账户收益达到或低于 −100%，程序会报错，而不是假装完成强平模拟。

## 历史研究汇总

一段截至 2026-10-29、已经被多次研究的历史测试包含 53 笔，模拟复利收益 **40.54%**、胜率 **49.06%**、交易完成后最大回撤 **15.20%**。这组数字使用与美股相关的衍生品数据、下一根半小时开盘代理、双边 10 基点手续费、没有额外滑点；历史持仓费用覆盖并不完整。它不是实盘收益，也不是独立样本外验证；少数大盈利对结果影响较大。

仓库不包含该测试的原始行情或逐笔数据，**因此克隆后不能直接重现 40.54%**。内置数据完全虚构，只用于检查流程。历史汇总保存在 [historical_summary.json](historical_summary.json)。

研究思路参考 [Beat the Market: An Effective Intraday Momentum Strategy for the S&P 500 ETF](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf)。本实现与论文在研究标的、成本和组合选择方面不同，论文不能证明本仓库的历史结果有效。
