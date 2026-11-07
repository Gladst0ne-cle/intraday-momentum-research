# v1.2.0 Ridge运行手册

## 三种运行方式

1. `python scripts/run_ridge.py --demo --output output/demo`：100个虚构会话，默认完整流程训练，不读取外部模型。
2. `python scripts/run_ridge.py --bars B.csv --minutes M.csv --specs S.csv --carry-zero --output output/own`：用自有行情做同一滚动训练。
3. 加`--frozen-model models/ridge-v1.2.0.json`：只用已冻结模型推理，不重训；数据中所有信号必须在模型`prediction_not_before_ms`之后。此方式不复现历史157日的预热/滚动训练组合，缺失模型输出回退原退出。

输出路径必须不存在。路径可以是绝对路径或相对仓库根目录。所有运行离线，不含采集或订单能力。

## 输入

- `bars30.csv`：`symbol,timestamp_ms,open,high,low,close,volume`，每会话09:30–15:30的13根30分钟柱，加16:00边界行。时区为纽约，CSV时间戳是UTC毫秒，夏令时由时区转换。
- `minutes.csv`：同样列名，每个候选所需的前14个会话有完整09:30–15:59分钟路径，当天含至16:01的分钟开盘价。分钟成交量单位必须与30分钟一致。不能用虚构成交量替代自有数据。
- `specs.csv`：`symbol,quantity_step,minimum_quantity,unit_value`。数量取整与资金费均按实际单位计算。
- 持仓费：明确`--carry-zero`，或提供`--carry-file carry.csv --carry-coverage-start START_MS --carry-coverage-end END_MS`。CSV列`symbol,timestamp_ms,rate`；每条代表当时实际结算率，覆盖范围由提供者核实。时间必须为分钟边界、唯一且在声明范围内；不能默认为缺失资金费等于零。

开始和结束可用`--start YYYY-MM-DD --end YYYY-MM-DD`；日期以前的数据仍需提供供特征预热。过滤后训练的60日预热从所选信号日起算，不会悄悄使用过滤前的标签训练；因此变更范围可能改变模型。完整157日公开指标不是任意起止范围的承诺。

导出并重新读入虚构示例：

```bash
python scripts/run_ridge.py --demo --export-example output/example --output output/example-run
python scripts/run_ridge.py --bars output/example/bars30.csv --minutes output/example/minutes.csv --specs output/example/specs.csv --carry-zero --cost-grid --output output/reload
```

## 特征、训练与退出

21个特征的精确顺序见`ridge_features.FEATURES`：持仓时间、距净收益高点时间、当前净收益/高点/回吐、VWAP距离、五分钟方向收益、短期真实波幅、距入场边界距离、入场时日波动/sigma/突破、距下次30分钟检查的时钟距离、距原退出线距离、第二次收盘变化、VWAP斜率、连续违例次数、相对会话成交量、方向收盘位置、相对上一根成交量与预警持续时间。

数据只用当时完成的分钟和30分钟前缀。零成交量分钟不进入VWAP权重；五分钟聚合优先使用有成交量的分钟，若全为空才保留该区间的价格。入场尺度`s0`是过去14会话相同五分钟槽真实波幅中位数与当天信号前平均真实波幅的较大值，并在入场时冻结。

监督目标为：`[原退出的成本后每单位收益 − 当前决策后60秒退出的成本后每单位收益]/入场价`。标签可以读未来以衡量结果，特征不可以。训练只保留已完成日的连续两次确认事件；每个市场日按其候选路径数分配权重，再按该路径的有效事件数分配。特征均值/总体标准差仅在训练段计算，标准化后裁剪至±8；标签裁剪至±5%；Ridge惩罚100，截距不惩罚。

从第61个信号日开始，每20日扩大训练集，排除紧邻预测窗口的一个完整信号日。模型输出小于−2bp且连续两次确认才提前退出，否则继续原策略；原退出有优先权，最大常规期限仍为16:01成交代理。原始资金预算、费用预留、数量向下取整和复利沿用分钟账本。

## 诊断与边界

`--cost-grid`固定同一批预测，增加往返0/2/5/10/20/40bp；不会用更高成本重新挑模型。`python scripts/check_ridge.py --run output/demo --block 5 --replications 1000 --output output/diagnostics.json`比较两种控制的配对收益，按整个信号日的区块重采样。区间针对相对财富优势，不是累计收益百分点差，也不是未来亏损概率。删除最大盈利日只是事后敏感度，不是可交易过滤。

完整历史图需原始输入才能独立复现；发布的最新单个模型也不能倒推过去预测。公开50项测试和本地833路径核对验证程序行为，不证明可在真实市场按代理价格成交。没有保证金、强平、深度撮合或故障期间真实退出。默认不使用任何神经网络。
