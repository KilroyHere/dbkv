"""Test S analysis (PLAN §2h, rules S1h-S4h) for one slurm/spec_suffix.sbatch job directory.

  python harness/agent_duckdb/analyze_s.py $DBKV_DATA/runs/spec_suffix/<job> [--out DIR]

Cells are the job's subdirectories: {off,on,smoke}_<stream>_n<N>_c<C> (W) and bird_{off,on}_n<N>_c<C>.
Per cell: p50/p95 task time, accuracy, no-SQL rate (status != "answered"), turns, decode tokens/s per
turn_type, spec-decode acceptance from counter deltas (metrics.jsonl). Per arm pair (same stream, N, c):
speedup = p50(off) / p50(on), gain = 1 - p50(on) / p50(off). Rules:
  S1h  c = 1, r80: p50(on) <= 0.75 x p50(off)                          (prediction 0.4-0.6x)
  S2h  smallest c (r80 pairs) with speedup < 1.05                        (prediction between 16 and 64)
  S3h  gain(r00) / gain(r80) at c = 4, the two pairs of the same N (axis B amendment: n30)   (prediction about 0.5)
  S4h  pooled over all off/on pairs: paired accuracy within +-1 point AND >= 95% of paired tasks with
       identical final pred_sql (exact string after whitespace normalization)   (prediction met)
Writes DIR/analysis_s.{md,json}, DIR/fig_speedup_vs_c.csv, DIR/fig_speedup_vs_repeat.csv (DIR = job dir).
"""
import argparse, json, math, os, re

import numpy as np

W_CELL = re.compile(r"^(smoke|off|on)_(.+)_n(\d+)_c(\d+)$")
B_CELL = re.compile(r"^bird_(off|on)_n(\d+)_c(\d+)$")
TURN_TYPES = ("explore", "execute_sql", "final")
SPEC = ("vllm:spec_decode_num_drafts", "vllm:spec_decode_num_draft_tokens", "vllm:spec_decode_num_accepted_tokens")
POS = "vllm:spec_decode_num_accepted_tokens_per_pos"


def jl(path):
    if not os.path.isfile(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def pct(xs, q):
    return float(np.percentile(xs, q)) if xs else None


def norm_sql(s):
    return " ".join(s.split()) if s else None


def rnd(x, k=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, k)


def spec_counters(metrics):
    """Counter deltas over the cell (max - min of each monotone counter); None if never exported."""
    out = {}
    for k in SPEC:
        v = [m[k] for m in metrics if k in m]
        out[k.split("spec_decode_")[1]] = (max(v) - min(v)) if v else None
    pos = {}
    for m in metrics:
        for p, v in (m.get(POS) or {}).items():
            pos.setdefault(int(p), []).append(v)
    out["accepted_per_pos"] = {p: max(v) - min(v) for p, v in sorted(pos.items())}
    d, dt, acc = out["num_drafts"], out["num_draft_tokens"], out["num_accepted_tokens"]
    out["acceptance_rate"] = acc / dt if dt else None          # accepted / drafted tokens
    out["mean_accepted_per_draft"] = acc / d if d else None    # extra tokens per verification step
    out["pos_acceptance"] = {p: v / d for p, v in out["accepted_per_pos"].items()} if d else {}
    return out


def decode_rates(turns):
    """output_tokens / decode_ms per turn_type (pooled ratio, tokens/s), plus turn counts."""
    r = {}
    for tt in TURN_TYPES + ("all",):
        rows = [t for t in turns if t.get("decode_ms") and t.get("output_tokens") is not None
                and (tt == "all" or t.get("turn_type") == tt)]
        tok = sum(t["output_tokens"] for t in rows); ms = sum(t["decode_ms"] for t in rows)
        r[tt] = dict(turns=len(rows), output_tokens=tok, decode_ms=ms, tok_s=rnd(tok / (ms / 1000.0), 1) if ms else None)
    return r


def cell_summary(name, d):
    m = W_CELL.match(name) or B_CELL.match(name)
    if W_CELL.match(name):
        arm, stream, n, c = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    else:
        arm, stream, n, c = m.group(1), "bird", int(m.group(2)), int(m.group(3))
    tasks, turns = jl(os.path.join(d, "tasks.jsonl")), jl(os.path.join(d, "turns.jsonl"))
    ts = [t["task_s"] for t in tasks]
    s = dict(cell=name, arm=arm, stream=stream, n=n, c=c, tasks=len(tasks),
             p50=rnd(pct(ts, 50)), p95=rnd(pct(ts, 95)), mean=rnd(float(np.mean(ts)) if ts else None),
             accuracy=rnd(sum(t["correct"] for t in tasks) / len(tasks), 4) if tasks else None,
             no_sql=rnd(sum(t.get("status") != "answered" for t in tasks) / len(tasks), 4) if tasks else None,
             turns=rnd(float(np.mean([t["turns"] for t in tasks])), 2) if tasks else None,
             decode=decode_rates(turns), spec=spec_counters(jl(os.path.join(d, "metrics.jsonl"))))
    if tasks and "is_repeat" in tasks[0]:
        rep = [t["task_s"] for t in tasks if t["is_repeat"]]; new = [t["task_s"] for t in tasks if not t["is_repeat"]]
        s.update(repeat_rate=rnd(len(rep) / len(tasks), 3), p50_repeat=rnd(pct(rep, 50)), p50_new=rnd(pct(new, 50)))
    return s, tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or a.job_dir
    os.makedirs(out, exist_ok=True)
    cells, tasks_by = {}, {}
    for name in sorted(os.listdir(a.job_dir)):
        d = os.path.join(a.job_dir, name)
        if os.path.isdir(d) and (W_CELL.match(name) or B_CELL.match(name)) and os.path.isfile(os.path.join(d, "tasks.jsonl")):
            cells[name], tasks_by[name] = cell_summary(name, d)

    # Arm pairs: same stream, N, c; one off and one on cell.
    pairs = []
    keys = sorted({(s["stream"], s["n"], s["c"]) for s in cells.values() if s["arm"] in ("off", "on")})
    for k in keys:
        off = [n for n, s in cells.items() if (s["stream"], s["n"], s["c"]) == k and s["arm"] == "off"]
        on = [n for n, s in cells.items() if (s["stream"], s["n"], s["c"]) == k and s["arm"] == "on"]
        if not (off and on):
            continue
        so, sn = cells[off[0]], cells[on[0]]
        to = {t["qid"]: t for t in tasks_by[off[0]]}; tn = {t["qid"]: t for t in tasks_by[on[0]]}
        q = sorted(set(to) & set(tn), key=str)
        ident = sum(norm_sql(to[x].get("pred_sql")) == norm_sql(tn[x].get("pred_sql")) for x in q)
        pairs.append(dict(stream=k[0], n=k[1], c=k[2], off=off[0], on=on[0], p50_off=so["p50"], p50_on=sn["p50"],
                          p95_off=so["p95"], p95_on=sn["p95"],
                          speedup=rnd(so["p50"] / sn["p50"]) if so["p50"] and sn["p50"] else None,
                          p95_speedup=rnd(so["p95"] / sn["p95"]) if so["p95"] and sn["p95"] else None,
                          gain=rnd(1 - sn["p50"] / so["p50"]) if so["p50"] and sn["p50"] else None,
                          acc_off=so["accuracy"], acc_on=sn["accuracy"], paired=len(q), identical_sql=ident,
                          identical_frac=rnd(ident / len(q), 4) if q else None,
                          _diffs=[int(tn[x]["correct"]) - int(to[x]["correct"]) for x in q],
                          repeat_rate=so.get("repeat_rate")))

    def find(stream, c, n=None):
        m = [p for p in pairs if p["stream"] == stream and p["c"] == c and (n is None or p["n"] == n)]
        return max(m, key=lambda p: p["n"]) if m else None

    rules = {}
    p = find("r80", 1, 150) or find("r80", 1)
    ratio = rnd(p["p50_on"] / p["p50_off"]) if p and p["p50_off"] else None
    rules["S1h"] = dict(rule="c=1, r80: p50(on) <= 0.75 x p50(off)", prediction="0.4-0.6x", pair=p and p["on"],
                        ratio_on_off=ratio, verdict=None if ratio is None else ("PASS" if ratio <= 0.75 else
                                                                                "FAIL (kill: drop suffix decoding and plan-guided speculation)"))
    a80 = sorted([p for p in pairs if p["stream"] == "r80" and p["speedup"] is not None], key=lambda p: (p["c"], p["n"]))
    by_c = {}
    for p in a80:  # axis A = the largest-N r80 pair per c (the n30 c=4 pair is axis B, PLAN §2h amendment)
        if p["c"] not in by_c or p["n"] > by_c[p["c"]]["n"]:
            by_c[p["c"]] = p
    below = [c for c, p in sorted(by_c.items()) if p["speedup"] < 1.05]
    s2 = below[0] if below else None
    rules["S2h"] = dict(rule="smallest c (r80) with speedup < 1.05", prediction="between 16 and 64",
                        speedups={c: p["speedup"] for c, p in sorted(by_c.items())}, c_boundary=s2,
                        verdict=("none of the tested c (all >= 1.05)" if s2 is None and by_c else
                                 None if s2 is None else ("as predicted" if 16 <= s2 <= 64 else "not as predicted")))
    # PLAN §2h amendment (Aryan, Nov 7): S3h compares the r00 pair with the r80 pair of the SAME N (30), both c=4
    g0 = find("r00", 4)
    g80 = g0 and find("r80", 4, g0["n"])
    s3 = rnd(g0["gain"] / g80["gain"]) if g0 and g80 and g80["gain"] else None
    rules["S3h"] = dict(rule="gain(0%) / gain(80%) at c=4, same N (axis B amendment), gain = 1 - p50(on)/p50(off)", prediction="about 0.5",
                        gain_r00=g0 and g0["gain"], gain_r80=g80 and g80["gain"], ratio=s3)
    diffs = [x for p in pairs for x in p["_diffs"]]
    npair = sum(p["paired"] for p in pairs); nid = sum(p["identical_sql"] for p in pairs)
    dacc = 100.0 * float(np.mean(diffs)) if diffs else None
    se = 100.0 * float(np.std(diffs, ddof=1) / math.sqrt(len(diffs))) if len(diffs) > 1 else None
    fid = nid / npair if npair else None
    wd = [x for p in pairs if p["stream"] != "bird" for x in p["_diffs"]]
    wn = sum(p["paired"] for p in pairs if p["stream"] != "bird"); wi = sum(p["identical_sql"] for p in pairs if p["stream"] != "bird")
    rules["S4h"] = dict(rule="pooled paired accuracy on-off within +-1 point AND >= 95% identical final SQL",
                        prediction="met", paired_tasks=npair, acc_diff_points=rnd(dacc, 2), acc_diff_se=rnd(se, 2),
                        identical_frac=rnd(fid, 4),
                        w_only=dict(paired_tasks=wn, acc_diff_points=rnd(100.0 * float(np.mean(wd)), 2) if wd else None,
                                    identical_frac=rnd(wi / wn, 4) if wn else None),
                        verdict=None if dacc is None else ("MET" if abs(dacc) <= 1.0 and fid >= 0.95 else "NOT MET"))

    # Decode tokens/s per turn_type per arm, pooled over W cells (not smoke, not BIRD).
    arm_decode = {}
    for arm in ("off", "on"):
        cs = [s for s in cells.values() if s["arm"] == arm and s["stream"] != "bird"]
        arm_decode[arm] = {}
        for tt in TURN_TYPES + ("all",):
            tk = sum(s["decode"][tt]["output_tokens"] for s in cs); ms = sum(s["decode"][tt]["decode_ms"] for s in cs)
            arm_decode[arm][tt] = rnd(tk / (ms / 1000.0), 1) if ms else None
    spec_pooled = {}
    for arm in ("off", "on"):
        cs = [s["spec"] for s in cells.values() if s["arm"] == arm]
        dt = sum(x["num_draft_tokens"] or 0 for x in cs); ac = sum(x["num_accepted_tokens"] or 0 for x in cs)
        spec_pooled[arm] = dict(draft_tokens=dt, accepted_tokens=ac, acceptance_rate=rnd(ac / dt, 4) if dt else None)

    fig_c = [dict(c=c, n=p["n"], speedup=p["speedup"], p95_speedup=p["p95_speedup"], p50_off=p["p50_off"], p50_on=p["p50_on"])
             for c, p in sorted(by_c.items())]
    fig_r = []
    for p in sorted([p for p in pairs if p["c"] == 4 and p["stream"] != "bird"], key=lambda p: p["stream"]):
        m = re.match(r"r(\d+)$", p["stream"])
        fig_r.append(dict(stream=p["stream"], nominal_repeat=int(m.group(1)) / 100 if m else None,
                          measured_repeat=p["repeat_rate"], n=p["n"], speedup=p["speedup"], gain=p["gain"]))
    for path, rows in (("fig_speedup_vs_c.csv", fig_c), ("fig_speedup_vs_repeat.csv", fig_r)):
        with open(os.path.join(out, path), "w") as f:
            if rows:
                f.write(",".join(rows[0]) + "\n")
                f.writelines(",".join("" if v is None else str(v) for v in r.values()) + "\n" for r in rows)

    for p in pairs:
        p.pop("_diffs")
    res = dict(job_dir=os.path.abspath(a.job_dir), cells=list(cells.values()), pairs=pairs, rules=rules,
               decode_tok_s_by_arm=arm_decode, spec_pooled=spec_pooled, fig_speedup_vs_c=fig_c, fig_speedup_vs_repeat=fig_r)
    json.dump(res, open(os.path.join(out, "analysis_s.json"), "w"), indent=1)

    L = [f"# Test S (PLAN §2h): {os.path.basename(os.path.abspath(a.job_dir))}", "", "## Cells", "",
         "| cell | tasks | p50 s | p95 s | accuracy | no-SQL | turns | decode tok/s (explore / exec / final) | acceptance | accepted/draft |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for s in cells.values():
        dd = s["decode"]; sp = s["spec"]
        L.append(f"| {s['cell']} | {s['tasks']} | {s['p50']} | {s['p95']} | {s['accuracy']} | {s['no_sql']} | {s['turns']} | "
                 f"{dd['explore']['tok_s']} / {dd['execute_sql']['tok_s']} / {dd['final']['tok_s']} | "
                 f"{rnd(sp['acceptance_rate'], 3)} | {rnd(sp['mean_accepted_per_draft'], 2)} |")
    L += ["", "## Pairs (speedup = p50 off / p50 on)", "",
          "| stream | n | c | p50 off | p50 on | speedup | p95 speedup | gain | acc off | acc on | identical SQL |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in pairs:
        L.append(f"| {p['stream']} | {p['n']} | {p['c']} | {p['p50_off']} | {p['p50_on']} | {p['speedup']} | {p['p95_speedup']} | "
                 f"{p['gain']} | {p['acc_off']} | {p['acc_on']} | {p['identical_sql']}/{p['paired']} |")
    r = rules
    L += ["", "## Rules", "",
          f"- **S1h** ({r['S1h']['rule']}; prediction {r['S1h']['prediction']}): ratio {r['S1h']['ratio_on_off']} -> **{r['S1h']['verdict']}**",
          f"- **S2h** ({r['S2h']['rule']}; prediction {r['S2h']['prediction']}): speedups {r['S2h']['speedups']}; "
          f"boundary c = {r['S2h']['c_boundary']} -> **{r['S2h']['verdict']}**",
          f"- **S3h** ({r['S3h']['rule']}; prediction {r['S3h']['prediction']}): gain r00 {r['S3h']['gain_r00']}, "
          f"gain r80 {r['S3h']['gain_r80']}, ratio **{r['S3h']['ratio']}**",
          f"- **S4h** ({r['S4h']['rule']}; prediction {r['S4h']['prediction']}): {r['S4h']['paired_tasks']} paired tasks, "
          f"accuracy on-off {r['S4h']['acc_diff_points']} ± {r['S4h']['acc_diff_se']} points, identical SQL "
          f"{r['S4h']['identical_frac']} (W only: {r['S4h']['w_only']}) -> **{r['S4h']['verdict']}**",
          "", "## Decode tokens/s per turn type (pooled W cells)", "", "| arm | explore | execute_sql | final | all |", "|---|---|---|---|---|"]
    for arm, d in arm_decode.items():
        L.append(f"| {arm} | {d['explore']} | {d['execute_sql']} | {d['final']} | {d['all']} |")
    L += ["", f"Spec-decode acceptance (pooled counter deltas): {spec_pooled}", "",
          "Figure data: fig_speedup_vs_c.csv, fig_speedup_vs_repeat.csv"]
    open(os.path.join(out, "analysis_s.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
