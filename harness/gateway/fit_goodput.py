"""Fit the goodput lookup table (option B, PLAN 2j) from harness run directories.

    python harness/gateway/fit_goodput.py --out TABLE.json [--seeds 0] [--exclude-seeds 1,2] [--m 20] \
        [--censored include|drop] [--prefill-weight 1.0] [--db-weight 0] [--eval-seeds 1,2] [--compare OTHER.json] \
        [--turn-limits] RUN_OR_CELL_DIR [...]

Inputs: any directories (searched recursively) holding tasks.jsonl + turns.jsonl as written by
harness/agent_duckdb/run_w.py (closed cells) or harness/w3/loadgen_w3.py (open cells). Task and turn rows are
joined by (cell, qid). Task qids look like w3mix-s<seed>-<pos>; --seeds / --exclude-seeds select the training
set by stream seed (the evaluation reuses seeds 0-2, so choose the training set on purpose).

One training sample per LLM request (turns.jsonl row): state = the history before that turn (goodput.StateAcc),
targets = task correct, remaining output tokens, remaining uncached prompt tokens (prompt - cached) and
remaining tool wall seconds, from this turn to the task's end. Tasks with status drain_cancelled / exception:* are censored: --censored include
(default) keeps them with correct = False (as the evaluation counts them) and their observed work as a lower
bound; --censored drop leaves them out. llm_error turns end a task and are skipped.

--eval-seeds: score the fitted table on held-out requests of those seeds (Brier, log loss, AUC of p; Spearman
of predicted vs actual remaining work), for the table cut at each level (level 0 = the global rate).
--compare OTHER.json: how much the table differs from OTHER on the held-out (or training) states.
--turn-limits: offline view of static turn limits N (tasks reaching N, correct tasks among them, work after N).
"""
import argparse, collections, glob, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import goodput as G  # noqa: E402

QID_SEED = re.compile(r"-s(\d+)-")


def seed_of(qid):
    m = QID_SEED.search(qid or "")
    return int(m.group(1)) if m else None


def cell_dirs(paths):
    out = []
    for p in paths:
        for t in sorted(glob.glob(os.path.join(p, "**", "tasks.jsonl"), recursive=True)):
            d = os.path.dirname(t)
            if os.path.exists(os.path.join(d, "turns.jsonl")):
                out.append(d)
    return sorted(set(out))


def load_tasks(dirs, seeds=None, exclude=None, censored="include"):
    """-> list of task dicts: dict(cell, qid, seed, tenant, correct, censored, turns=[rows sorted by turn])."""
    tasks = []
    for d in dirs:
        rows = collections.defaultdict(list)
        for l in open(os.path.join(d, "turns.jsonl")):
            if l.strip():
                r = json.loads(l)
                rows[r["qid"]].append(r)
        for l in open(os.path.join(d, "tasks.jsonl")):
            if not l.strip():
                continue
            t = json.loads(l)
            s = seed_of(t["qid"])
            if seeds is not None and s not in seeds:
                continue
            if exclude and s in exclude:
                continue
            cens = t["status"] == "drain_cancelled" or t["status"].startswith("exception")
            if cens and censored == "drop":
                continue
            tr = sorted((r for r in rows.get(t["qid"], []) if "error" not in r), key=lambda r: r["turn"])
            if not tr:
                continue
            tasks.append(dict(cell=d, qid=t["qid"], seed=s, tenant=t.get("tenant") or t.get("db") or "",
                              correct=bool(t["correct"]), censored=cens, status=t["status"], turns=tr))
    return tasks


def samples(tasks):
    """-> list of (state, correct, rem_out, rem_pre, rem_db, task index); rem_db = remaining tool wall seconds."""
    out = []
    for ti, t in enumerate(tasks):
        tr = t["turns"]
        o = [r.get("output_tokens") or 0 for r in tr]
        p = [max(0, (r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0)) for r in tr]
        d = [sum(x.get("wall_s", x.get("runtime_s")) or 0.0 for x in r.get("tools") or []) for r in tr]
        ro, rp, rd = [0] * (len(tr) + 1), [0] * (len(tr) + 1), [0.0] * (len(tr) + 1)
        for i in range(len(tr) - 1, -1, -1):
            ro[i], rp[i], rd[i] = ro[i + 1] + o[i], rp[i + 1] + p[i], rd[i + 1] + d[i]
        acc = G.StateAcc(t["tenant"])
        for i, r in enumerate(tr):
            st = acc.state()
            if st["turn"] != r["turn"]:  # a gap in the rows (should not happen); keep the harness's turn index
                st["turn"] = r["turn"]
            out.append((st, t["correct"], ro[i], rp[i], rd[i], ti))
            acc.add_turn_row(r)
    return out


def fit(smp, m=20.0, prefill_weight=1.0, db_weight=0.0, p_floor=1e-3):
    """entries: key -> [n, p, out, pre, db], each smoothed toward the parent key (its prefix)."""
    sums = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
    for st, c, ro, rp, rd, _ in smp:
        for k in G.keys_of(st):
            s = sums[k]
            s[0] += 1; s[1] += c; s[2] += ro; s[3] += rp; s[4] += rd
    entries = {}
    for lvl in range(len(G.LEVELS)):  # parents first
        for k, v in sums.items():
            if not k.startswith(f"{lvl}|"):
                continue
            n = v[0]
            if lvl == 0:
                entries[k] = [n] + [x / n for x in v[1:]]
                continue
            parent = entries[f"{lvl - 1}|" + "|".join(k.split("|")[1:1 + len(G.LEVELS[lvl - 1])])]
            entries[k] = [n] + [(x + m * px) / (n + m) for x, px in zip(v[1:], parent[1:])]
    entries = {k: [v[0], round(v[1], 6), round(v[2], 2), round(v[3], 2), round(v[4], 3)] for k, v in entries.items()}
    return dict(bins_version=G.BINS_VERSION, levels=[list(l) for l in G.LEVELS], m=m,
                prefill_weight=prefill_weight, db_weight=db_weight, p_floor=p_floor, entries=entries)


# ---------- reports ----------
def auc(scores, labels):
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    allv = sorted((s, y) for s, y in zip(scores, labels))
    # rank-sum with average ranks for ties
    ranks, i = {}, 0
    rs = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            rs[k] = (i + j) / 2 + 1
        i = j + 1
    rpos = sum(r for r, (_, y) in zip(rs, allv) if y)
    return (rpos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def spearman(a, b):
    def rank(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra)); vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else None


def score(table, smp, label):
    T = G.Table(table)
    ps, ys, wp, wa = [], [], [], []
    for st, c, ro, rp, rd, _ in smp:
        r = T.lookup(st)
        ps.append(r["p"]); ys.append(c); wp.append(r["work"]); wa.append(ro + T.w * rp + T.wdb * rd)
    n = len(ps)
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    ll = -sum(math.log(min(max(p if y else 1 - p, 1e-6), 1)) for p, y in zip(ps, ys)) / n
    return dict(label=label, n=n, brier=round(brier, 4), logloss=round(ll, 4), auc=round(auc(ps, ys) or 0, 3),
                work_spearman=round(spearman(wp, wa) or 0, 3),
                work_mae=round(sum(abs(x - y) for x, y in zip(wp, wa)) / n, 1),
                mean_p=round(sum(ps) / n, 4), rate=round(sum(ys) / n, 4))


def truncated(table, depth):
    """The table cut to levels 0..depth (what each level adds, for the held-out scores)."""
    return dict(table, entries={k: v for k, v in table["entries"].items() if int(k.split("|", 1)[0]) <= depth})


def compare(a, b, smp):
    A, B = G.Table(a), G.Table(b)
    dp, dw, va, vb = [], [], [], []
    for st, *_ in smp:
        x, y = A.lookup(st), B.lookup(st)
        dp.append(abs(x["p"] - y["p"])); dw.append(abs(x["work"] - y["work"]) / max(y["work"], 1))
        va.append(x["value"]); vb.append(y["value"])
    dp.sort(); dw.sort()
    q = lambda xs, f: xs[min(len(xs) - 1, int(f * len(xs)))]  # noqa: E731
    lo_a = {i for i in sorted(range(len(va)), key=lambda i: va[i])[:max(1, len(va) // 10)]}
    lo_b = {i for i in sorted(range(len(vb)), key=lambda i: vb[i])[:max(1, len(vb) // 10)]}
    return dict(n=len(smp), p_absdiff_mean=round(sum(dp) / len(dp), 4), p_absdiff_p90=round(q(dp, 0.9), 4),
                work_reldiff_mean=round(sum(dw) / len(dw), 3), work_reldiff_p90=round(q(dw, 0.9), 3),
                value_spearman=round(spearman(va, vb) or 0, 3),
                bottom10_overlap=round(len(lo_a & lo_b) / len(lo_a), 3))


def natkey(k):
    """Bins in reading order: numbers by value ('3+' after '2', '<500' after '<250'), then names."""
    m = re.search(r"\d+", str(k))
    return (0, int(m.group()), str(k)) if m else (1, 0, str(k))


def headline(smp, table):
    """Raw rates (not smoothed) by turn / timeouts / errors / tenant, with the table's mean remaining work."""
    T = G.Table(table)
    def agg(keyf):
        g = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0, set()])
        for st, c, ro, rp, rd, ti in smp:
            k = keyf(st)
            x = g[k]; x[0] += 1; x[1] += c; x[2] += ro; x[3] += rp; x[4] += rd; x[5].add(ti)
        return {k: dict(requests=v[0], tasks=len(v[5]), p=round(v[1] / v[0], 3), rem_out=round(v[2] / v[0]),
                        rem_pre=round(v[3] / v[0]), rem_db_s=round(v[4] / v[0], 1)) for k, v in sorted(g.items(), key=lambda kv: natkey(kv[0]))}
    return dict(by_turn=agg(lambda s: G.b_turn(s["turn"])), by_timeouts=agg(lambda s: G.b_count(s["n_timeout"], (0, 1, 2, 3))),
                by_errors=agg(lambda s: G.b_count(s["n_err"], (0, 1, 3, 5))), by_tenant=agg(lambda s: s["tenant"]),
                by_last=agg(lambda s: s["last"]), by_out=agg(lambda s: G.b_out(s["out_tok"])),
                n_entries=len(T.entries))


def turn_limits(tasks, w=1.0):
    """For a static limit N (force final at turn N): tasks reaching turn N, correct ones among them (at risk),
    and the work of turns > N (an upper bound on what the limit saves)."""
    tot_work = sum((r.get("output_tokens") or 0) + w * max(0, (r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0))
                   for t in tasks for r in t["turns"])
    n_corr = sum(t["correct"] for t in tasks)
    out = []
    for N in range(3, 16):
        reach = [t for t in tasks if len(t["turns"]) > N
                 or (len(t["turns"]) == N and t["turns"][-1].get("turn_type") != "final")]
        saved = sum((r.get("output_tokens") or 0) + w * max(0, (r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0))
                    for t in tasks for r in t["turns"] if r["turn"] > N)
        out.append(dict(N=N, tasks_cut=len(reach), correct_at_risk=sum(t["correct"] for t in reach),
                        share_correct_at_risk=round(sum(t["correct"] for t in reach) / max(n_corr, 1), 3),
                        work_after_N_share=round(saved / max(tot_work, 1), 3)))
    return out


def fmt_table(name, d):
    lines = [f"{name}:", f"  {'bin':>10} {'req':>6} {'tasks':>6} {'P(ok)':>6} {'rem_out':>8} {'rem_pre':>8} {'rem_db_s':>8}"]
    for k, v in d.items():
        lines.append(f"  {str(k):>10} {v['requests']:>6} {v['tasks']:>6} {v['p']:>6.3f} {v['rem_out']:>8} {v['rem_pre']:>8} {v['rem_db_s']:>8}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", default="", help="train only on these stream seeds (comma list); default all")
    ap.add_argument("--exclude-seeds", default="")
    ap.add_argument("--exclude-cells", default="", help="comma list of substrings; cells whose path contains one are skipped (e.g. open_140,open_180)")
    ap.add_argument("--m", type=float, default=20.0, help="smoothing pseudo-count (requests) toward the parent bin")
    ap.add_argument("--censored", default="include", choices=["include", "drop"])
    ap.add_argument("--prefill-weight", type=float, default=1.0, help="work = out + w * uncached prompt tokens")
    ap.add_argument("--db-weight", type=float, default=0.0,
                    help="work += w * remaining tool wall seconds (token-equivalents per DB second; 0 = LLM work only)")
    ap.add_argument("--eval-seeds", default="", help="score on held-out requests of these seeds")
    ap.add_argument("--compare", default="", help="another table JSON to compare against")
    ap.add_argument("--turn-limits", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    ints = lambda s: {int(x) for x in s.split(",") if x != ""} or None  # noqa: E731
    dirs = cell_dirs(a.dirs)
    if a.exclude_cells:
        bad = [x for x in a.exclude_cells.split(",") if x]
        dirs = [d for d in dirs if not any(b in d for b in bad)]
    tasks = load_tasks(dirs, ints(a.seeds), ints(a.exclude_seeds), a.censored)
    if not tasks:
        sys.exit("no tasks selected")
    smp = samples(tasks)
    table = fit(smp, a.m, a.prefill_weight, a.db_weight)
    table["meta"] = dict(cells=dirs, seeds=sorted({t["seed"] for t in tasks}, key=str), n_tasks=len(tasks),
                         n_requests=len(smp), n_correct=sum(t["correct"] for t in tasks),
                         n_censored=sum(t["censored"] for t in tasks), censored=a.censored,
                         args={k: v for k, v in vars(a).items() if k != "dirs"})
    with open(a.out, "w") as f:
        json.dump(table, f, separators=(",", ":"))
    rep = dict(table=a.out, **{k: table["meta"][k] for k in ("seeds", "n_tasks", "n_requests", "n_correct", "n_censored")},
               n_cells=len(dirs), n_entries=len(table["entries"]))
    hl = headline(smp, table)
    ev_smp = None
    if a.eval_seeds:
        ev_tasks = load_tasks(dirs, ints(a.eval_seeds), None, a.censored)
        ev_smp = samples(ev_tasks)
        rep["eval"] = [score(truncated(table, d), ev_smp, f"levels 0-{d}: " + (",".join(G.LEVELS[d]) or "global rate"))
                       for d in range(len(G.LEVELS))]
    if a.compare:
        other = json.load(open(a.compare))
        rep["compare"] = dict(other=a.compare, **compare(table, other, ev_smp or smp))
    if a.turn_limits:
        rep["turn_limits"] = turn_limits(tasks, a.prefill_weight)
    rep["headline"] = hl
    if not a.quiet:
        print(json.dumps({k: v for k, v in rep.items() if k not in ("headline", "turn_limits", "eval", "compare")}))
        for k in ("by_turn", "by_timeouts", "by_errors", "by_last", "by_out", "by_tenant"):
            print(fmt_table(k, hl[k]))
        for s in rep.get("eval", []):
            print("eval", json.dumps(s))
        if "compare" in rep:
            print("compare", json.dumps(rep["compare"]))
        for r in rep.get("turn_limits", []):
            print("turn_limit", json.dumps(r))
    with open(os.path.splitext(a.out)[0] + ".report.json", "w") as f:
        json.dump(rep, f, indent=1)


if __name__ == "__main__":
    main()
