"""Phase 1 (PLAN 2j-P1) load curve for stock vLLM, Qwen3-32B TP=4, W3: throughput and p95 vs arrival rate.

    python results/fig_p1.py      # reads results/p1_sweep.json and results/p1_repeats.json -> results/fig_p1_load_curve.png

Sweep cells (one job per part, single run each) as open circles; the 3 repeat jobs (seeds 0/1/2) at R* = 40 and
R_o = 60 as mean with min-max bars. Two panels, one y-scale each.
"""
import json, os, statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2 = "#2a78d6", "#eb6834"  # reference palette slots 1 (blue) and 2 (orange)


def opens(path):
    out = {}
    for job in json.load(open(path)):
        for c in job["cells"].values():
            if c.get("kind") == "open":
                out.setdefault(c["rate"], []).append(c)
    return out


sweep, reps = opens(os.path.join(HERE, "p1_sweep.json")), opens(os.path.join(HERE, "p1_repeats.json"))
fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=200, facecolor=SURF)
for ax, key, title, unit in ((axes[0], "throughput_per_min", "Throughput", "tasks/min"),
                             (axes[1], "p95_s", "p95 task time", "s")):
    ax.set_facecolor(SURF)
    xs = sorted(sweep)
    ax.plot(xs, [sweep[x][0][key] for x in xs], color=S1, lw=2, marker="o", ms=8, mfc=SURF, mew=2, label="sweep (1 run)")
    rx = sorted(reps)
    m = [st.mean(c[key] for c in reps[x]) for x in rx]
    lo = [m[i] - min(c[key] for c in reps[x]) for i, x in enumerate(rx)]
    hi = [max(c[key] for c in reps[x]) - m[i] for i, x in enumerate(rx)]
    ax.errorbar(rx, m, yerr=[lo, hi], color=S2, lw=0, elinewidth=2, capsize=4, marker="s", ms=8, mec=SURF, mew=1.5,
                label="repeats (3 jobs, mean, min–max)")
    if key == "throughput_per_min":
        ax.plot([0, 190], [0, 190], color=INK2, lw=1, ls=(0, (3, 3)))
        ax.text(14, 74, "throughput = arrivals", color=INK2, fontsize=8)
        ax.set_ylim(0, 80)
    ax.set_xlim(0, 190)
    ax.set_title(f"{title} ({unit})", color=INK, fontsize=11, loc="left")
    ax.set_xlabel("arrival rate (tasks/min, Poisson)", color=INK2, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
axes[0].annotate("peak ≈ 55/min", (100, 54.8), (115, 68), color=INK, fontsize=8,
                 arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
axes[0].legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower right")
fig.suptitle("Stock vLLM, Qwen3-32B TP=4 on 4×A100-40GB, W3 agent tasks (Phase 1)", color=INK, fontsize=11, x=0.01,
             ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.93))
out = os.path.join(HERE, "fig_p1_load_curve.png")
fig.savefig(out, facecolor=SURF)
print("wrote", out)
