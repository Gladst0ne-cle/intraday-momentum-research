# Version numbering / 版本编号

- **v1.0.0**: initial public strategy and offline tools.
- **v1.1.0**: sigma-floor candidate ranking, reference budgets, minute cash ledger, CSV replay and bilingual manuals.
- **v1.2.0**: Ridge early-exit review, chronological training, replay and robustness research.

The additions retain the original entry point and controls. They are minor feature releases within the 1.x line, rather than a claim of a breaking second-generation interface. Patch versions will cover fixes that preserve the registered decision rules. More code or higher historical return alone does not justify a major version.

上次使用v2.0.0编号过大，现将其功能线归入v1.1.0。按维护者要求删除旧v2.0.0标签及旧Release，保留代码提交历史。`configs/v2.0.0.json`继续作为分母下限规则的兼容入口。新默认配置及`--compare`输出目录使用v1.1.0；调用旧配置单独运行仍保留其版本标识。

The obsolete v2.0.0 tag and Release are removed at the maintainer's request; source commits remain in history. Canonical v1.1.0 has updated labels and equivalent strategy behavior. Its changes are the previous feature update. A stable software release does not establish profitable trading performance.
