> v1.2.0 Ridge: [中文](RIDGE.zh-CN.md) / [English](RIDGE.en.md). This page describes the preserved v1.1.0 minute replay.

# v2 运行手册

## 1. 安装和首次运行

Python 3.10+；运行程序和测试仅用标准库。Windows 如缺少纽约时区数据，安装 `requirements.txt`。

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/run_replay.py --demo --compare
python -m unittest discover -s tests
```

演示行情完全虚构，分钟路径是对虚构半小时行情的插值，不是实际订单簿或真实历史。演示盈亏不验证模型盈利。默认输出目录已存在时会拒绝覆盖；重复运行可改 `--output`，或明确加 `--overwrite`。

## 2. 按版本运行、成本压力和初始资金

```bash
python scripts/run_replay.py --demo --config configs/v1.1.0.json --output output/v1.1
python scripts/run_replay.py --demo --config configs/v1.0.0.json --output output/v1-control
python scripts/run_replay.py --demo --compare --initial-equity 300 --extra-cost-bps 20 --output output/stress20
```

`--compare` 同时运行两个信号版本并共用同一份输入、费用和延迟设置。两个账户分别独立复利，不交叉挪用资金。基础成本是每边 5 bp 手续费，另加双边合计 5 bp 执行成本代理；`--extra-cost-bps 20` 只是在代理成本上再增加双边合计 20 bp。配置中的仓位约束固定为策略定义的 4 倍上限与 4% 波动预算；不提供无限杠杆或真实下单。

注意 `configs/v1.0.0.json` 是新成交口径下的原信号对照。旧入口 `python src/simulate.py --demo` 保留原来半小时成交代理的行为，相关研究命令仍见 [旧版手册](LEGACY.zh-CN.md)。旧分析工具不应直接读取新账本而假定字段、手续费定义一致。

## 3. 导出完整格式示例，再从文件运行

```bash
python scripts/run_replay.py --demo --compare --export-example output/example --output output/example-run
python scripts/run_replay.py --bars output/example/bars30.csv --minutes output/example/minutes.csv --specs output/example/specs.csv --carry-zero --compare --output output/from-files
```

上述两个运行应得到相同模拟结果；这也是自动化测试的检查项。真实行情、规格和资金费需要自行取得并核实，本仓库不联网下载数据。

### bars30.csv

必须列：`symbol,timestamp_ms,open,high,low,close,volume`。时间戳为 UTC Unix **毫秒**，代表 K 线开始。每个纽约日期、每个标的需要 09:30、10:00……15:30 共 13 根完整半小时 K 线，以及 16:00 的边界行。边界行 `open` 提供旧格式完整性信息；新回放实际退出价格来自分钟文件。

至少 16 个完整会话：前 15 个只用于初始化，后续才模拟。每一天使用相同完整标的集合。重复时间戳、缺柱、错误 OHLCV 都会失败。当前格式针对正常全日会话：半日市应在输入前按既定规则排除，不能伪造补齐。程序不会独立核实节假日、漏掉整天或数据发布延迟。应使用统一来源、相同复权口径的两个周期数据；不同来源/复权可能制造虚假信号。

### minutes.csv

必须列：`symbol,timestamp_ms,open,high,low,close`。UTC 毫秒，严格整分钟。需要实际入场至退出期间的**每一分钟**，包括两个端点。持有至收盘时必须有 16:01 数据。程序验证价格、重复、OHLC 和路径缺口；不会用前值填充，也不会拿半小时价格替代缺失分钟。风险采样用每分钟开盘价，并不捕获分钟内所有高低点。

### specs.csv

必须列：`symbol,quantity_step,minimum_quantity,unit_value`。`quantity` 是合约/份额数量，`unit_value` 是每份代表的基础资产单位；名义金额 = 数量 × unit_value × 价格。所有规格必须为正，每个标的恰好一行。演示规格仅是假定，不可视为任何真实产品规格。

### carry.csv（可选，但不能默认为零）

必须列：`symbol,timestamp_ms,rate`。正费率表示多方支付、空方收到；事件落在 `入场 < 时点 <= 退出` 才计费。每次结算使用该时刻分钟开盘价作为标记价代理。费率不是金额；程序不假定固定结算周期。

```bash
python scripts/run_replay.py --bars your-bars.csv --minutes your-minutes.csv --specs your-specs.csv --carry-file your-carry.csv --carry-coverage-start 1700000000000 --carry-coverage-end 1900000000000 --compare --output output/your-data
```

示例覆盖时间仅展示格式，应替换为**实际已核实**的 UTC 毫秒起止。声明覆盖并不能证明事件完整；使用者需检查每个标的的真实结算日程及缺失记录。也可显式指定 `--carry-zero`，结果会标记为人为零费用假设。

`--start YYYY-MM-DD --end YYYY-MM-DD` 按纽约会话日期限定评估范围，但输入仍须包含评估前 15 个完整会话。输出记录输入文件 SHA-256，方便确认对照使用同一份文件。

## 4. 输出文件

- `comparison.json`：双版本同口径汇总，只在 `--compare` 时生成。
- 每个版本目录的 `summary.json`：复利收益、已平仓回撤、分钟采样平仓估值回撤、胜率、费用分解、配置及输入哈希。
- `trades.csv`：入退场时间、方向、参考标的、sigma 下限、目标敞口、取整数量、实际敞口、毛收益/费用/持仓费与前后权益。
- `equity.csv`：每个评估日的权益和已平仓回撤，无信号日也保留。
- `minute_equity.csv`：持仓期间分钟开盘价上的假设平仓净值及回撤；空仓期间不插值。
- `decisions.csv`：最早信号、选择、原始参考赢家，或 `no_signal`、`below_minimum`；这些都是离线模拟状态。

所有默认运行结果写入被 Git 忽略的 `output/`。不把自己的行情或输出加入公开提交。重新使用别的输出路径同样应注意隐私。

## 5. 代码分类与修改边界

- `src/intraday_momentum.py`、`backtest.py`、`simulate.py`：保留初始版规则与旧回放。
- `src/versioned_replay.py`：新版候选排序、因果退出规划、数量预算和分钟现金账本。
- `src/replay_cli.py`：文件校验、配置、来源哈希、双版本运行及导出。
- `scripts/run_replay.py`：推荐入口。
- `configs/`：两个版本配置；`tests/`：规则、预算、资金费、缺失数据和命令行回归。
- `research/`：独立研究工具；`docs/`：中英文运行/版本说明；`evidence/`：仅历史汇总；`figures/`：成图。

历史曲线不是演示程序生成的数据，原始输入不公开，因此不能宣称一键复现历史收益。程序也没有真实持仓核对、订单执行、保证金强平或断线恢复接口。运行通过只证明离线链路按这些假设工作。
