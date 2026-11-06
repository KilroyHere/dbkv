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
    save(f, "fig_g1_gap_vs_ratio.png", "G1 v2b sim (G3-measured costs), 5 seeds. Pauses: Redshift-like ×1–30 and TPC-H SF100.")

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
    save(f, "fig_g1_policies.png", "G1 v2b simulator (G3-measured costs; sim within ±14% of real vLLM above the limit). Stock vLLM = request FCFS + LRU.")


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


# ---------------- D2 ----------------
D2_ARMS = [("explore", "explore (no brief)"), ("full", "full schema"), ("compact", "(i) compact"),
           ("lexical", "(ii) lexical"), ("llm", "(iii) model pass"), ("oracle", "oracle brief")]
D2_RUNS = {"explore": "60873599", "full": "60873599", "compact": "60873600", "lexical": "60873600",
           "llm": "60873675", "oracle": "60873675"}


def _d2_load(arm):
    d = f"{SCR}/dbkv/runs/d2/{D2_RUNS[arm]}/{arm}"
    T = [json.loads(l) for l in open(os.path.join(d, "tasks.jsonl"))]
    U = [json.loads(l) for l in open(os.path.join(d, "turns.jsonl"))]
    return T, U


def d2_breakdown():
    """Where a real SQL agent's task time goes (frozen agent, all 1,534 BIRD dev questions, concurrency 8)."""
    parts = [("decode", "LLM decode", "#2a78d6"), ("prefill", "LLM prefill", "#eb6834"), ("queue", "LLM queue", "#1baf7a"),
             ("db", "database (SQL tools)", "#eda100"), ("other", "other", "#e87ba4")]
    rows = []
    for arm, lab in [("explore", "explore (no brief)"), ("full", "full schema"), ("lexical", "(ii) lexical brief"), ("oracle", "oracle brief")]:
        T, U = _d2_load(arm)
        tot = sum(t["task_s"] for t in T)
        q = sum((u.get("queue_ms") or 0) for u in U) / 1000; pf = sum((u.get("prefill_ms") or 0) for u in U) / 1000
        dc = sum((u.get("decode_ms") or 0) for u in U) / 1000; db = sum(t["db_s"] for t in T)
        rows.append((lab, dict(decode=dc / tot, prefill=pf / tot, queue=q / tot, db=db / tot, other=max(0.0, 1 - (dc + pf + q + db) / tot))))
    f, (ax,) = fig(w=7.4, h=3.0)
    y = np.arange(len(rows))[::-1]
    left = np.zeros(len(rows))
    for k, lab, c in parts:
        v = np.array([r[1][k] for r in rows]) * 100
        ax.barh(y, v, left=left, color=c, label=lab, edgecolor=SURFACE, linewidth=1.5, height=0.62)
        for i, (vi, li) in enumerate(zip(v, left)):
            if vi >= 6:
                ax.text(li + vi / 2, y[i], f"{vi:.0f}%", ha="center", va="center", fontsize=8, color="#ffffff")
        left += v
    ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows]); ax.set_xlim(0, 100); ax.set_xlabel("share of total task time (%)")
    style(ax, "A SQL agent's time is LLM decoding, not the database")
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.28))
    save(f, "fig_d2_time_breakdown.png", "Frozen ReAct agent (Qwen3-8B, A100-40GB), all 1,534 BIRD dev questions, 8 concurrent agents. Server-side per-request timings.")


def d2_arms():
    S = {}
    for arm, _ in D2_ARMS:
        T, _U = _d2_load(arm)
        ts = np.array([t["task_s"] for t in T])
        acc = np.mean([t["correct"] for t in T])
        S[arm] = dict(turns=np.mean([t["turns"] for t in T]), p50=np.percentile(ts, 50), p95=np.percentile(ts, 95),
                      acc=100 * acc, se=100 * np.sqrt(acc * (1 - acc) / len(T)), prompt=np.mean([t["prompt_tokens"] for t in T]) / 1000)
    f, axes = fig(4, w=3.3, h=3.6)
    labs = [l for _, l in D2_ARMS]; x = np.arange(len(D2_ARMS))
    cols = ["#8a8985", "#eb6834", "#2a78d6", "#2a78d6", "#2a78d6", "#1baf7a"]
    specs = [("turns", "turns per task", None), ("p95", "p95 task time (s)", "p50"), ("acc", "accuracy (%)", None),
             ("prompt", "prompt tokens per task (k)", None)]
    for ax, (k, title, k2) in zip(axes, specs):
        v = [S[a][k] for a, _ in D2_ARMS]
        ax.bar(x, v, color=cols, edgecolor=SURFACE, linewidth=1.5, width=0.7)
        if k == "acc":
            ax.errorbar(x, v, yerr=[S[a]["se"] for a, _ in D2_ARMS], fmt="none", ecolor=INK2, capsize=3, lw=1)
        if k2:
            ax.scatter(x, [S[a][k2] for a, _ in D2_ARMS], color=INK, s=14, zorder=3, label="p50")
            ax.legend(frameon=False, fontsize=7.5, labelcolor=INK)
        for i, vi in enumerate(v):
            ax.text(i, vi, f"{vi:.1f}" if k != "prompt" else f"{vi:.0f}", ha="center", va="bottom", fontsize=7.5, color=INK)
        ax.set_xticks(x); ax.set_xticklabels(labs, rotation=40, ha="right", fontsize=8)
        style(ax, title)
    save(f, "fig_d2_arms.png", "D2 step 5: frozen agent, all 1,534 BIRD dev questions, concurrency 8. Accuracy ± SE. Grey = no brief, orange = full schema, blue = generated briefs, green = oracle.")


def d2_sweep(on_dir, off_dir):
    import glob as _g
    if not (_g.glob(os.path.join(on_dir, "*_c*", "tasks.jsonl")) or _g.glob(os.path.join(off_dir, "*_c*", "tasks.jsonl"))):
        print("no sweep data yet"); return
    arms = [("explore", "#8a8985"), ("full", "#eb6834"), ("compact", "#6250d6"), ("lexical", "#2a78d6"), ("oracle", "#1baf7a")]
    f, axes = fig(2, w=5.0, h=3.6)
    for ax, (pc, d) in zip(axes, (("on", on_dir), ("off", off_dir))):
        for arm, c in arms:
            xs, ys = [], []
            for conc in (8, 32, 64):
                dd = f"{SCR}/dbkv/runs/d2sweep/60888614" if (arm == "compact" and pc == "on") else d
                t = os.path.join(dd, f"{arm}_c{conc}", "tasks.jsonl")
                if os.path.exists(t):
                    ts = [json.loads(l)["task_s"] for l in open(t)]
                    xs.append(conc); ys.append(np.percentile(ts, 95))
            if xs:
                ax.plot(xs, ys, "-o", color=c, lw=2, ms=6, mec=SURFACE, mew=1.5, label=arm)
        ax.set_xscale("log", base=2); ax.set_xticks([8, 32, 64]); ax.set_xticklabels(["8", "32", "64"])
        ax.set_xlabel("concurrent agents"); ax.set_ylabel("p95 task time (s)")
        style(ax, f"prefix caching {pc}")
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK)
    save(f, "fig_d2_sweep.png", "300 BIRD dev questions, frozen agent, A100-40GB. Step 6 (jobs 60876091/2); compact = Phase 1 (job 60888614, caching on only).")



def d2_acc_vs_tokens():
    f, (ax,) = fig(w=6.0, h=4.0)
    cols = {"explore": "#8a8985", "full": "#eb6834", "compact": "#2a78d6", "lexical": "#2a78d6", "llm": "#2a78d6", "oracle": "#1baf7a"}
    for arm, lab in D2_ARMS:
        T, _U = _d2_load(arm)
        acc = 100 * np.mean([t["correct"] for t in T]); se = 100 * np.sqrt(acc / 100 * (1 - acc / 100) / len(T))
        tok = np.mean([t["prompt_tokens"] for t in T]) / 1000
        ax.errorbar([tok], [acc], yerr=[se], fmt="o", color=cols[arm], ms=8, mec=SURFACE, mew=1.5, ecolor=INK2, capsize=3)
        ax.annotate(lab, (tok, acc), xytext=(6, 4), textcoords="offset points", fontsize=8, color=INK)
    ax.set_xlabel("prompt tokens per task (thousands)"); ax.set_ylabel("accuracy (%)")
    style(ax, "Schema briefs: accuracy vs prompt cost")
    save(f, "fig_d2_acc_vs_tokens.png", "D2 step 5: frozen agent, all 1,534 BIRD dev questions, concurrency 8. Accuracy ± SE.")


def priority_test():
    rows = [("8k × 24", 139.9, 134.7), ("8k × 32", 188.3, 182.7), ("20k × 10", 170.4, 132.7), ("20k × 12", 198.8, 152.9)]
    f, (ax,) = fig(w=6.0, h=3.6)
    x = np.arange(len(rows)); w = 0.36
    ax.bar(x - w / 2 - 0.01, [r[1] for r in rows], w, color="#8a8985", label="stock vLLM (FCFS)", edgecolor=SURFACE)
    ax.bar(x + w / 2 + 0.01, [r[2] for r in rows], w, color="#2a78d6", label="task-start priority", edgecolor=SURFACE)
    for i, r in enumerate(rows):
        ax.text(i + w / 2, r[2] + 3, f"{100 * (r[2] / r[1] - 1):+.0f}%", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x); ax.set_xticklabels([r[0] for r in rows]); ax.set_ylabel("p95 task time (s)")
    style(ax, "Ordering by task start cuts p95 above the memory limit")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    save(f, "fig_priority_test.png", "Synthetic replayer, real vLLM 0.33 on one A100-40GB, 1 rep (job 60827432). Context × agents, all above the KV limit.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--g1", default=os.path.join(HERE, "g1v2b_gap.csv"))
    ap.add_argument("--g2-sf10", default=f"{SCR}/dbkv/runs/g2/60825416/results.csv")
    ap.add_argument("--g2-sf100", default=f"{SCR}/dbkv/runs/g2/60826277/results.csv")
    ap.add_argument("--g3", default=f"{SCR}/dbkv/runs/g3/main")
    ap.add_argument("--sweep-on", default=f"{SCR}/dbkv/runs/d2sweep/60876091")
    ap.add_argument("--sweep-off", default=f"{SCR}/dbkv/runs/d2sweep/60876092")
    a = ap.parse_args()
    g1(a.g1)
    g2(a.g2_sf10, a.g2_sf100, os.path.join(HERE, "g2_sf10_summary.json"), os.path.join(HERE, "g2_sf100_summary.json"))
    g3(a.g3)
    d2_breakdown()
    d2_arms()
    d2_sweep(a.sweep_on, a.sweep_off)
    d2_acc_vs_tokens()
    priority_test()
