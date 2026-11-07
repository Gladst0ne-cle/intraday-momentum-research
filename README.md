# 日内动量策略研究 · Ridge退出审核

[中文](README.md) | [English](README.en.md)

**当前版本：v1.2.0。版本线：v1.0.0 初始版 → v1.1.0 波动分母下限与分钟回放 → v1.2.0 Ridge退出审核。**

可以直接克隆运行的离线研究代码，包括策略、按时间训练、三方案回放、成本压力、成对区块重采样和单元测试。原30分钟突破和sigma-floor入场保留；Ridge只审核五分钟双确认提出的提前退出候选，不决定买什么或提高仓位。程序不连接账户、不下单。

## 完整157日策略展示 · v1.2.0

![Ridge完整历史权益、各版对照、已平仓回撤与具体策略步骤](figures/strategy-overview-v1.2.0.png)

**统一主口径：2026-03-18至2026-10-29，完整157个信号日，各自300单位资金开始、逐笔复利。** 同一入场、相同风险预算与费用：

- v1.1.0分母下限＋原30分钟退出：累计 **+67.49%**，最终 **502.48**；已平仓最大回撤 **15.55%**，分钟采样回撤 **17.17%**。
- 固定五分钟双确认对照：累计 **+71.61%**，最终 **514.84**；已平仓回撤 **13.90%**，分钟采样回撤 **16.47%**。
- v1.2.0 Ridge审核流程：累计 **+78.78%**，最终 **536.33**；已平仓回撤 **13.56%**，分钟采样回撤 **16.14%**，盈利 **62/157** 笔。

**这些是反复研究过的历史模拟，不是实盘收益或新的独立验证。** Ridge流程前60个信号日回退固定双确认，后97日才有模型预测，因此不能把全段盈利全部归功于Ridge。原研究的事后“过去均值审核”对照为+79.81%，高于Ridge；模型增量尚未确立。累计收益为最终权益÷起始权益−1，杠杆已经体现在下单数量，不能再乘一次。

原始行情和逐笔历史记录不公开。克隆即可运行演示和自有数据，但不能仅凭仓库复现这条历史曲线。[完整汇总](evidence/historical-v1.2.0.json)和[抗性汇总](evidence/robustness-v1.2.0.json)保留证据范围与本地代码一致性检查。

## 克隆后直接运行

Python3.10+；核心训练、推理与回放均使用标准库，`requirements.txt`只补齐时区支持。

```bash
git clone https://github.com/Gladst0ne-cle/intraday-momentum-research.git
cd intraday-momentum-research
python -m pip install -r requirements.txt
python scripts/run_ridge.py --demo --config configs/v1.2.0.json --cost-grid --output output/ridge-demo
python scripts/check_ridge.py --run output/ridge-demo --block 5 --replications 1000 --output output/ridge-check.json
python -m unittest discover -s tests
```

演示生成100个**虚构的工作日会话**和分钟路径，刻意包含可触发双确认的波动，用来演示训练和完整回放。它不是实际交易日历或真实行情，也不代表历史收益；演示可以亏损，不能拿它宣传策略盈利。输出目录已存在时会拒绝覆盖。

`output/ridge-demo/summary.json`包含三种策略、全区间指标、训练边界与成本网格；`training.json`记录各滚动窗口；`models/`保存演示训练出的模型；三个策略子目录各有`trades.csv`和`minute_equity.csv`。

## 用户自己的数据

```bash
# 导出可检查的虚构CSV格式
python scripts/run_ridge.py --demo --export-example output/ridge-inputs --output output/ridge-export-run
# 使用同样格式的自有数据，明确假设持仓费为零
python scripts/run_ridge.py --bars path/to/bars30.csv --minutes path/to/minutes.csv --specs path/to/specs.csv --carry-zero --cost-grid --output output/my-ridge
```

Ridge分钟CSV必须有`symbol,timestamp_ms,open,high,low,close,volume`，比旧回放多要求真实成交量。需要至少15个先前完整会话；每个入选候选所需的前14个会话分钟路径也必须齐全，供入场时波动尺度计算使用。空缺、重复或无效输入会终止，不能用“零”填充。真实费用、时区、会话日历和规格由数据提供者核实。

也可提供持仓费事件及已核实覆盖范围；可加载冻结模型，但不能把它用于训练截止之前的日期。详见[中文运行手册](docs/RIDGE.zh-CN.md)和[English manual](docs/RIDGE.en.md)。

## 更新的具体机制

1. **保留入场。** 原30分钟噪声带、每日首个候选时点、sigma-floor排序，以及原始赢家的敞口/波动双预算，最高参考敞口仍为4倍。
2. **提出退出候选。** 每根完整五分钟柱检查上一根已完成30分钟柱的退出线；连续两次收盘越过不利侧才审核。首个完整持仓五分钟窗口结束后才能检查。
3. **Ridge审核。** 用21个当时可知特征，预测“继续持有至原策略退出”相对“现在退出”的成本后收益增量。预测小于 **−2bp**才提前退出；否则等待后续检查。决策后60秒用一分钟开盘价代理成交。
4. **按日期隔离训练。** 前60个信号日回退双确认；之后每20个信号日扩大训练集，隔离1个完整信号日。所有同日候选一起切分，按日/候选/事件分配权重。原退出触发时优先执行，不允许Ridge拖延原退出。

历史版本固定使用基准成本训练特征和标签；压力网格固定同一决策，不重新训练。仓位按当前权益复利；没有重新进场、神经网络或新的杠杆放大。详细公式见[Ridge设计](docs/RIDGE.zh-CN.md)与[版本差异](docs/STRATEGY_VERSIONS.md)。

## 抗性检验：收益仍可能转负

![完整157日的额外成本敏感度](figures/ridge-cost-sensitivity-v1.2.0.png)

- 在基础成本之外增加往返20bp，Ridge完整收益约 **+18.33%**；增加到40bp则 **−22.00%**，分钟采样回撤约 **37.13%**。
- 相对原退出与双确认的95%区块重采样增量区间均跨零，尚未证明稳定优势。
- 保留过去均值、按5日块扰乱标签残差的39次诊断，收益尾部比率为 **0.90**；这不是未来盈利概率，也不是完整多重试验校正。
- 本地历史数据核对：833条候选、24,200个状态的特征误差为0，Ridge预测最大差异约1.5e−17，三套各157日的现金账本一致。公开仓库有 **50项测试**。

部分历史代理退出量超过对应分钟总成交量，且存在零成交量分钟。分钟成交量不是盘口深度。缺少真实成交、标记价格、保证金阶梯及强平仿真，不能据此宣称可保证实盘盈利。发布代码也没有切换任何交易策略。

## 文件分类与版本

- `src/ridge_features.py`：21个因果特征、分钟聚合和原退出优先级。
- `src/ridge_model.py`：带未惩罚截距的Ridge、训练边界与模型校验。
- `src/ridge_replay.py`、`ridge_cli.py`：首时点候选、时间顺序训练、三方案现金回放及CSV入口。
- `src/ridge_diagnostics.py`：成对区块重采样和利润集中度诊断。
- `scripts/`：运行入口；`configs/`：冻结参数；`models/`：最新历史训练截止后的推理模型。
- `tests/`：自动验证；`docs/`：中英文说明；`evidence/`：汇总；`figures/`：成图。
- `research/`：原有数据质量、信号、仓位及预测基准工具；`output/`：本地输出，Git忽略。

v1.1.0的双版本对照仍可运行：`python scripts/run_replay.py --demo --compare`。v1.0.0旧入口`python src/simulate.py --demo`保留。旧53笔+40.54%采用不同期间与成本，不能直接与本次157日结果相减，见[初始说明](docs/LEGACY.zh-CN.md)。

版本按兼容功能增加编号，不按收益高低编号。旧v2.0.0标签和Release删除，提交历史保留；旧配置只作兼容入口。见[版本编号](docs/VERSIONING.md)与[更新记录](CHANGELOG.md)。

只公开通用离线代码、模型系数、汇总和成图；不含交易所接口、账户、密钥、服务器、原始行情或逐笔历史数据。制图脚本不上传。

## 研究背景

噪声带思路参考*Beat the Market: An Effective Intraday Momentum Strategy for the S&P500 ETF(SPY)*。本仓库是独立扩展，不是论文复现；Ridge不是论文结论。[回测过拟合研究](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)与[DSR研究](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)用于说明反复选择和非正态收益的证据限制。
