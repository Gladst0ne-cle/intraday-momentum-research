"""Regenerate the historical summary figure (requires matplotlib)."""
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "historical_summary.json").read_text(encoding="utf-8"))
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
fig, axes = plt.subplots(1, 3, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.2, 1, 1]})
fig.patch.set_facecolor("#f7f9fc")
for ax in axes:
    ax.set_facecolor("#f7f9fc")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)

ax = axes[0]
end = 100 * data["compounded_equity"]
bars = ax.bar(["Start", "End"], [100, end], color=["#aab8cd", "#2574c7"], width=.55)
ax.bar_label(bars, labels=["100.00", f"{end:.2f}"], padding=5, fontweight="bold")
ax.set_ylim(0, 165)
ax.set_ylabel("Equity index (start = 100)")
ax.set_title(f"Compounded return: +{data['return_percent']:.2f}%", fontweight="bold")

ax = axes[1]
win = data["win_rate_percent"]
bars = ax.bar(["Winning", "Non-winning"], [win, 100 - win], color=["#238b68", "#c87a59"], width=.55)
ax.bar_label(bars, labels=[f"{win:.2f}%", f"{100-win:.2f}%"], padding=5, fontweight="bold")
ax.set_ylim(0, 75)
ax.set_ylabel("Share of trades (%)")
ax.set_title(f"{data['trades']} simulated trades", fontweight="bold")

ax = axes[2]
dd = data["max_drawdown_after_completed_trades_percent"]
bars = ax.bar(["Closed-trade\nmaximum drawdown"], [dd], color="#ca715c", width=.42)
ax.bar_label(bars, labels=[f"{dd:.2f}%"], padding=5, fontweight="bold")
ax.set_ylim(0, 25)
ax.set_ylabel("Drawdown from prior peak (%)")
ax.set_title("Observed risk measure", fontweight="bold")

fig.suptitle("Historical research summary | simulated, not live", fontsize=17, fontweight="bold", y=.98)
fig.text(.5, .035, "2026-08-17 to 2026-10-29  |  10 bp round-trip fee; no extra slippage  |  funding incomplete", ha="center", fontsize=9)
fig.text(.5, .008, "Repeatedly studied sample; not independent validation. Intratrade drawdowns and actual fills are not included.", ha="center", fontsize=9)
fig.tight_layout(rect=(0, .08, 1, .9))
(ROOT / "figures").mkdir(exist_ok=True)
fig.savefig(ROOT / "figures" / "historical-summary.png", dpi=160, facecolor=fig.get_facecolor())
plt.close(fig)
