"""Figures for Test S (suffix decoding, PLAN §2h) and the plan-cache tests (§2h Test P, §2i Test P2).

  python results/fig_spec.py JOB_DIR      # JOB_DIR = $DBKV_DATA/runs/spec_suffix/<job>, already analysed by
                                          # harness/agent_duckdb/analyze_s.py (reads its analysis_s.json)
Writes results/fig_spec_speedup_vs_c.png, fig_spec_speedup_vs_repeat.png, fig_plancache_hit_vs_repeat.png.
Style and palette from results/figures.py (reference categorical slots; text in ink).
"""
import json, os, sys

import textwrap

import matplotlib.pyplot as plt
from figures import INK, INK2, POLICY_COLOR, SURFACE, fig, style


def save(f, name, note):
    lines = textwrap.wrap(note, int(f.get_figwidth() * 16.5))
    f.text(0.01, 0.01, "\n".join(lines), fontsize=7.5, color=INK2, va="bottom")
    f.tight_layout(rect=(0, 0.035 * len(lines) + 0.01, 1, 1))
    p = os.path.join(HERE, name); f.savefig(p, dpi=200, facecolor=SURFACE); plt.close(f)
    print("wrote", p)

HERE = os.path.dirname(os.path.abspath(__file__))
C1, C2, C3 = POLICY_COLOR[:3]


def speedup_vs_c(a, job):
    pairs = sorted([p for p in a["pairs"] if p["stream"] == "r80"], key=lambda p: (p["c"], -p["n"]))
    by_c = {}
    for p in pairs:  # axis A: the largest-N pair per c
        by_c.setdefault(p["c"], p)
    cs = sorted(by_c)
    f, (ax,) = fig()
    ax.plot(cs, [by_c[c]["speedup"] for c in cs], color=C1, lw=2, marker="o", ms=8, mec="#fcfcfb", mew=2, zorder=3)
    for c in cs:
        ax.annotate(f"{by_c[c]['speedup']:.2f}×", (c, by_c[c]["speedup"]), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=8.5, color=INK)
    ax.axhline(1.05, color=INK2, lw=1, ls="--")
    ax.text(0.99, 1.07, "S2h line: 1.05×", transform=ax.get_yaxis_transform(), ha="right", fontsize=8, color=INK2)
    ax.set_xscale("log", base=2); ax.set_xticks(cs); ax.set_xticklabels([str(c) for c in cs])
    ax.set_ylim(0.8, max(by_c[c]["speedup"] for c in cs) * 1.18)
    ax.set_xlabel("concurrent agents"); ax.set_ylabel("speedup, p50 task time (off / on)")
    style(ax, "Suffix decoding speedup vs concurrency (80% repeats)")
    save(f, "fig_spec_speedup_vs_c.png", f"Test S, job {job}: W (TPC-DS, 4 tenants), DuckDB agent, Qwen3-8B, 1 A100-40GB, "
         "fresh server per cell, 1 run per cell. c=1,4: 150 q; c=16,64: 300 q.")


def speedup_vs_repeat(a, job):
    by = {}
    for p in a["pairs"]:
        if p["c"] == 4 and p["stream"] in ("r00", "r80"):
            by.setdefault(p["stream"], {})[p["n"]] = p
    n = min(by["r00"])  # the axis B pairs share N (amendment: 30)
    pts = [(0, by["r00"][n]), (80, by["r80"][n])]
    f, (ax,) = fig(w=5.6)
    xs = [0, 1]
    ax.bar(xs, [p["speedup"] for _, p in pts], width=0.5, color=C1, edgecolor="#fcfcfb", linewidth=2, zorder=3)
    for x, (_, p) in zip(xs, pts):
        ax.text(x, p["speedup"] + 0.04, f"{p['speedup']:.2f}×", ha="center", fontsize=9, color=INK)
    bird = [p for p in a["pairs"] if p["stream"] == "bird"]
    ax.set_xticks(xs); ax.set_xticklabels(["0% repeats\n(each template once)", "80% repeats\n(6 templates)"])
    ax.set_ylim(0, max(p["speedup"] for _, p in pts) * 1.2)
    ax.set_ylabel("speedup, p50 task time (off / on)")
    style(ax, "Speedup vs template repetition (4 agents)")
    note = f"Test S, job {job}: c=4, {n} questions per cell, 1 run per cell (PLAN §2h axis B amendment)."
    if bird:
        note += f" BIRD reference (c=1, 150 q): {bird[0]['speedup']:.2f}×."
    save(f, "fig_spec_speedup_vs_repeat.png", note)


def plancache():
    d = json.load(open(os.path.join(HERE, "plancache_p2.json")))
    ev = d["M2"]["eval"]
    rates = [20, 50, 80]
    series = [("top-1 template correct, no gate (repeats)", "repeat_top1_correct_no_gate", C1),
              ("hint given and correct, gated = P1i (repeats)", "P1i_repeat_recall", C2),
              ("wrong hint given = P2i (new questions)", "P2i_nonrepeat_hint_rate", C3)]
    f, (ax,) = fig()
    for lab, k, c in series:
        ys = [ev[f"r{r}"][k] for r in rates]
        ax.plot(rates, ys, color=c, lw=2, marker="o", ms=8, mec="#fcfcfb", mew=2, label=lab, zorder=3)
        ax.annotate(f"{ys[-1]:.2f}", (rates[-1], ys[-1]), textcoords="offset points", xytext=(8, 4), fontsize=8.5, color=INK)
    ax.axhline(0.80, color=INK2, lw=1, ls="--"); ax.axhline(0.10, color=INK2, lw=1, ls=":")
    ax.text(21, 0.82, "P1i bar 0.80", fontsize=7.5, color=INK2); ax.text(21, 0.12, "P2i bar 0.10", fontsize=7.5, color=INK2)
    ax.set_xticks(rates); ax.set_xticklabels([f"{r}%" for r in rates]); ax.set_xlim(15, 88); ax.set_ylim(0, 1.05)
    ax.set_xlabel("strict repeat rate of the stream"); ax.set_ylabel("share")
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK, loc="center right", bbox_to_anchor=(1.0, 0.33))
    style(ax, "Plan-cache retrieval vs repeat rate (Test P2: FAIL)")
    save(f, "fig_plancache_hit_vs_repeat.png", f"PLAN §2i: 121 templates (99 TPC-DS + 22 TPC-H), 150-q streams, 4 eval seeds; "
         f"matcher M2, calibrated τ={d['M2']['tau']:.1f}, m={d['M2']['m']}.")


if __name__ == "__main__":
    jd = sys.argv[1]
    a = json.load(open(os.path.join(jd, "analysis_s.json")))
    job = os.path.basename(os.path.normpath(jd))
    for fn in (lambda: speedup_vs_c(a, job), lambda: speedup_vs_repeat(a, job), plancache):
        try:
            fn()
        except Exception as e:  # each figure independently
            print("figure failed:", e)
