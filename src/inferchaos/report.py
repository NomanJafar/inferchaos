"""Plots and table for a set of fault experiments."""

from __future__ import annotations

import json
from pathlib import Path

_STATE_Y = {"closed": 0, "half_open": 1, "open": 2}


def write_results(results: dict[str, dict], out_dir: str | Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, r in results.items():
        (out_dir / f"{name}.json").write_text(json.dumps(r, indent=1, default=str))
    table = render_markdown(results)
    (out_dir / "comparison.md").write_text(table)
    _plots(results, out_dir)
    return {"table": table}


def render_markdown(results: dict[str, dict]) -> str:
    head = ["fault", "requests", "errors", "429s", "budget consumed", "peak burn rate", "alerts fired", "breaker opened after", "slow before breaker", "fallbacks", "recovery"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, r in results.items():
        f = r["fault"]
        opened = f"{r['breaker_opened_at'] - f['start']:.1f} s" if r["breaker_opened_at"] is not None and f["start"] is not None else "–"
        alerts = ", ".join(f"{a['name']} @ {a['fired_at'] - (f['start'] or 0):.0f}s" for a in r["alerts"]) or "none"
        rec = f"{r['recovery_s']:.1f} s" if r["recovery_s"] is not None else "–"
        lines.append("| " + " | ".join([name, str(r["requests"]), str(r["errors"]), str(r["rate_limited"]), f"{r['budget_consumed']*100:.0f}% of the run's budget",
                                        f"{r['peak_burn_rate']:.0f}x", alerts, opened, str(r["slow_before_breaker"]), str(r["fallbacks"]), rec]) + " |")
    return "\n".join(lines) + "\n"


def _plots(results: dict[str, dict], out_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(results)
    fig, axes = plt.subplots(len(names), 1, figsize=(12, 3.4 * len(names)))
    axes = [axes] if len(names) == 1 else list(axes)
    for ax, name in zip(axes, names, strict=True):
        r = results[name]; f = r["fault"]
        recs = [x for x in r["records"] if x["ttft_s"] is not None]
        ax.scatter([x["t"] for x in recs], [x["ttft_s"] * 1000 for x in recs], s=5, color="tab:gray", alpha=0.5, label="user TTFT (ms)")
        bad = [x for x in r["records"] if not x["ok"] and x["status"] != 429]
        ax.scatter([x["t"] for x in bad], [0] * len(bad), s=14, color="tab:red", marker="x", label="error")
        ax.set_ylabel("TTFT ms"); ax.set_yscale("symlog", linthresh=100)
        ax2 = ax.twinx()
        ax2.plot([s["t"] for s in r["burn_series"]], [s["burn_rate"] or 0 for s in r["burn_series"]], color="tab:orange", label="burn rate (10 s window)")
        tgt = [s for s in r["breaker_timeline"] if s["provider"] == f["target"]]
        if tgt:
            ax2.step([s["t"] for s in tgt], [_STATE_Y[s["state"]] * 10 for s in tgt], where="post", color="tab:blue", lw=1.5, label="breaker (0 closed / 10 half / 20 open)")
        ax2.set_ylabel("burn rate / breaker")
        if f["start"] is not None:
            ax.axvspan(f["start"], f["end"], color="tab:red", alpha=0.08)
        for a in r["alerts"]:
            ax.axvline(a["fired_at"], color="tab:purple", ls="--", lw=1)
        ax.set_title(f"{name}: budget {r['budget_consumed']*100:.0f}%, peak burn {r['peak_burn_rate']:.0f}x, errors {r['errors']}, recovery {r['recovery_s'] if r['recovery_s'] is None else round(r['recovery_s'],1)} s")
        ax.grid(alpha=.3); ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("seconds")
    fig.tight_layout(); fig.savefig(out_dir / "faults.png", dpi=120); plt.close(fig)
