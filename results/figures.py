"""Slide-ready figures for the Nov 9 midpoint: G1, G2, G3.

  python results/figures.py            # writes results/fig_*.png from the run dirs below

Inputs (small summaries live in results/; raw runs in $SCRATCH/dbkv/runs):
  G1: results/g1v2_gap.csv (or --g1 <gap.csv>)
  G2: $SCRATCH/dbkv/runs/g2/<job>/results.csv for SF10 and SF100
  G3: $SCRATCH/dbkv/runs/g3/main/rep*/c*_n*_r0/summary.json (+ turns.csv for the full-hit rule)
Palette: reference categorical slots 1-3 (validated all-pairs) for the three contexts; text in ink,
never in series color; recessive grid. Static PNGs for slides, so no hover layer.
"""
import argparse, csv, glob, json, os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CTX_COLOR = {4096: "#2a78d6", 8192: "#eb6834", 20480: "#1baf7a"}   # slots 1-3
CTX_LABEL = {4096: "4k context", 8192: "8k context", 20480: "20k context"}
LIMIT = {4096: 32.4, 8192: 16.2, 20480: 6.5}                        # prediction 1a
POLICY_COLOR = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # slots 1-5 (adjacent bars)
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.environ.get("SCRATCH", "/pscratch/sd/a/ap2568")


def style(ax, title=None):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(color=GRID, lw=0.8); ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.xaxis.label.set_color(INK2); ax.yaxis.label.set_color(INK2)


def fig(n=1, w=6.4, h=3.8):
    f, axes = plt.subplots(1, n, figsize=(w * n, h), facecolor=SURFACE, squeeze=False)
    return f, axes[0]


def save(f, name, note=None):
    if note:
        f.text(0.01, 0.01, note, fontsize=7.5, color=INK2)
    f.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    p = os.path.join(HERE, name); f.savefig(p, dpi=200, facecolor=SURFACE); plt.close(f)
    print("wrote", p)


# ---------------- G1 ----------------
def g1(gap_csv):
    rows = list(csv.DictReader(open(gap_csv)))
    num = lambda r, k: float(r[k]) if r[k] not in ("", "nan") else float("nan")  # noqa: E731
    # (a) oracle gap vs pause/generation ratio, above the limit
    f, (ax,) = fig()
    for ctx, c in CTX_COLOR.items():
        pts = [(num(r, "ratio"), num(r, "oracle_gap_pct")) for r in rows
               if int(r["ctx"]) == ctx and float(r["x_limit"]) >= 1.2 and r["mix"] != "ms"]
        pts = [p for p in pts if p[0] == p[0] and p[1] == p[1]]
        if pts:
            x, y = zip(*pts)
            ax.scatter(x, y, s=34, color=c, edgecolor=SURFACE, linewidth=1.5, label=CTX_LABEL[ctx], zorder=3)
    ax.axhline(10, color=INK2, lw=1, ls="--")
    ax.text(0.99, 10.6, "G1 kill line: 10%", transform=ax.get_yaxis_transform(), ha="right", fontsize=8, color=INK2)
    ax.set_xscale("log"); ax.set_ylim(-1, max(20, ax.get_ylim()[1]))
    ax.set_xlabel("mean query pause ÷ mean generation time per turn")
    ax.set_ylabel("oracle advantage at p95 (%)")
    style(ax, "Knowing each query's duration barely helps (sim, ≥1.2× memory limit)")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    save(f, "fig_g1_gap_vs_ratio.png", "G1 v2 simulator, 5 seeds; best per-call oracle vs best per-tool policy (incl. offload). Pause scales 1–30× Redshift-like.")

    # (b) policy p95 at 1.5× limit, per pause scale, 8k
    pols = [("stock_p95", "stock vLLM"), ("cont2_p95", "released Continuum (2 s)"),
            ("keep_ac_p95", "always-keep + program FCFS"), ("best_tool_p95", "best per-tool (+offload)"),
            ("best_any_p95", "oracle (knows durations)")]
    scales = ["1.0", "3.0", "10.0"]
    f, (ax,) = fig(w=7.2)
    sel = {s: next((r for r in rows if r["mix"] == "redshift" and r["pause_scale"] == s
                    and int(r["ctx"]) == 8192 and int(r["sessions"]) == 24), None) for s in scales}
    w = 0.16
    for i, (k, lab) in enumerate(pols):
        xs = np.arange(len(scales)) + (i - 2) * (w + 0.01)
        ys = [num(sel[s], k) if sel[s] else np.nan for s in scales]
        ax.bar(xs, ys, width=w, color=POLICY_COLOR[i], label=lab, edgecolor=SURFACE, linewidth=1)
    ax.set_xticks(range(len(scales))); ax.set_xticklabels([f"{float(s):g}× pauses" for s in scales])
    ax.set_ylabel("p95 task completion time (s)")
    style(ax, "Scheduling and offload matter; durations don't (8k, 24 agents = 1.5× limit)")
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK, ncol=2)
    save(f, "fig_g1_policies.png", "G1 v2 simulator (guessed GPU costs until refit from G3). Stock vLLM = request FCFS + LRU.")


# ---------------- G2 ----------------
def g2(sf10_csv, sf100_csv, sf10_sum, sf100_sum):
    f, (a1, a2) = fig(2, w=5.2)
    for path, lab, c in ((sf10_csv, "TPC-H/DS SF10", CTX_COLOR[4096]), (sf100_csv, "TPC-H SF100", CTX_COLOR[8192])):
        if not os.path.exists(path):
            continue
        r = [x for x in csv.DictReader(open(path)) if x["median_s"] not in ("", "nan") and x["sum_ec"] not in ("", "nan")]
        x = np.array([float(v["sum_ec"]) for v in r]); y = np.array([float(v["median_s"]) for v in r])
        a1.scatter(np.maximum(x, 1), y, s=6, alpha=0.45, color=c, label=lab, linewidths=0)
    for yv, t in ((0.25, "short | medium"), (2.0, "medium | long")):
        a1.axhline(yv, color=INK2, lw=0.8, ls="--")
        a1.text(0.01, yv * 1.15, t, transform=a1.get_yaxis_transform(), fontsize=7, color=INK2)
    a1.set_xscale("log"); a1.set_yscale("log")
    a1.set_xlabel("EXPLAIN: sum of estimated cardinalities"); a1.set_ylabel("measured query time (s)")
    style(a1, "The optimizer's estimate tracks runtime")
    a1.legend(frameon=False, fontsize=8, labelcolor=INK, markerscale=3)
    # accuracy on unseen templates
    labels, ex, hi = [], [], []
    for path, lab in ((sf10_sum, "SF10"), (sf100_sum, "SF100")):
        if not os.path.exists(path):
            continue
        s = json.load(open(path))
        d = s.get("pooled") or s
        acc = lambda pred: d["loto"][pred]["acc"] if "loto" in d else np.nan  # noqa: E731
        try:
            ex.append(100 * acc("explain")); hi.append(100 * acc("history")); labels.append(lab)
        except Exception:
            pass
    if labels:
        xs = np.arange(len(labels))
        a2.bar(xs - 0.17, ex, 0.32, color=CTX_COLOR[4096], label="EXPLAIN class", edgecolor=SURFACE)
        a2.bar(xs + 0.17, hi, 0.32, color=CTX_COLOR[8192], label="per-template history", edgecolor=SURFACE)
        for i in range(len(labels)):
            a2.text(i - 0.17, ex[i] + 1.5, f"{ex[i]:.0f}%", ha="center", fontsize=8, color=INK)
            a2.text(i + 0.17, hi[i] + 1.5, f"{hi[i]:.0f}%", ha="center", fontsize=8, color=INK)
        a2.set_xticks(xs); a2.set_xticklabels(labels); a2.set_ylim(0, 105)
        a2.set_ylabel("3-class accuracy, unseen templates (%)")
        a2.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right")
    style(a2, "Unseen query templates")
    save(f, "fig_g2_explain.png", "G2: DuckDB 2.0, 16 GB / 8 threads. SF10: 93.5% of queries < 0.25 s, so accuracy there barely discriminates.")


# ---------------- G3 ----------------
def g3(run_dir):
    pts = {}
    for p in glob.glob(os.path.join(run_dir, "rep*", "c*_n*_r0", "summary.json")):
        d = json.load(open(p))
        t = os.path.join(os.path.dirname(p), "turns.csv")
        hit = np.nan
        if os.path.exists(t):
            rc = [int(x["recomputed"]) for x in csv.DictReader(open(t))
                  if x["turn"] != "0" and float(x["t_req"]) >= d["warmup"] and x["recomputed"] not in ("", "None")]
            hit = float(np.mean([r <= 16 for r in rc])) if rc else np.nan
        pts.setdefault((d["ctx"], d["sessions"]), []).append((d["resume_ttft_p95"] or np.nan, hit))
    if not pts:
        print("no G3 data yet"); return
    f, (a1, a2) = fig(2, w=5.2)
    for ctx, c in CTX_COLOR.items():
        ks = sorted(n for (cx, n) in pts if cx == ctx)
        if not ks:
            continue
        x = [n / LIMIT[ctx] for n in ks]
        y1 = [np.nanmean([v[0] for v in pts[(ctx, n)]]) for n in ks]
        y2 = [100 * np.nanmean([v[1] for v in pts[(ctx, n)]]) for n in ks]
        a1.plot(x, y1, "-o", color=c, lw=2, ms=6, mec=SURFACE, mew=1.5, label=CTX_LABEL[ctx])
        a2.plot(x, y2, "-o", color=c, lw=2, ms=6, mec=SURFACE, mew=1.5, label=CTX_LABEL[ctx])
    for a in (a1, a2):
        a.axvline(1.0, color=INK2, lw=0.8, ls="--")
        a.text(1.02, 0.97, "predicted limit", transform=a.get_xaxis_transform(), fontsize=7.5, color=INK2, va="top")
        a.set_xlabel("agents ÷ predicted memory limit")
    a1.set_yscale("log"); a1.set_ylabel("p95 time from query return to next token (s)")
    a2.set_ylabel("resumes that found their KV cache (%)"); a2.set_ylim(-3, 103)
    style(a1, "Past the limit, resuming an agent gets slow"); style(a2, "…because its KV cache was evicted")
    a1.legend(frameon=False, fontsize=8, labelcolor=INK)
    save(f, "fig_g3_limit.png", "G3: stock vLLM on one A100-40GB, Qwen3-8B, Redshift-like pauses; mean over reps. Predicted limits: 32 / 16 / 6.5 agents.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--g1", default=os.path.join(HERE, "g1v2_gap.csv"))
    ap.add_argument("--g2-sf10", default=f"{SCR}/dbkv/runs/g2/60825416/results.csv")
    ap.add_argument("--g2-sf100", default=f"{SCR}/dbkv/runs/g2/60826277/results.csv")
    ap.add_argument("--g3", default=f"{SCR}/dbkv/runs/g3/main")
    a = ap.parse_args()
    g1(a.g1)
    g2(a.g2_sf10, a.g2_sf100, os.path.join(HERE, "g2_sf10_summary.json"), os.path.join(HERE, "g2_sf100_summary.json"))
    g3(a.g3)
