"""Phase 1 analysis (PLAN 2j-P1): per-cell metrics from slurm/node_p1.sbatch job directories.

  python harness/w3/analyze_p1.py $DBKV_DATA/runs/p1/<job> [<job2> ...] --out results/p1_<name>.json

Per cell (cells.tsv gives each cell's server and time span; the server's step log is cut to that span):
  closed C:N  : p50/p95 task time, accuracy, turns, LLM / DB query / DB queue shares
  open RATE   : as summarize.py (measured-window p50/p95 incl. unfinished, throughput = tasks done in the window per
                min, unfinished at drain cap) + the same shares
  burst       : out tok/s mean over reps
Every agent cell also gets:
  miss causes (2j-P1): per task, turn n >= 2: new = P_n - (P_{n-1} + O_{n-1}); evicted = max(0, (P_n - new) - C_n - 16);
                turn 1: cold = P_1 - C_1. Token shares of all uncached prompt tokens; plus prefix hit rate = sum C / sum P.
  step log    : steps, prefill (ctx) tokens and decode (gen) tokens, prefill share of summed step time estimated as
                sum(step_ms over steps with ctx_tokens > 0) / sum(step_ms) and the token-weighted split, preemptions
                (iteration stats), eviction events, peak KV usage, mean running / waiting
  KV per task : pool x peak kv_usage / max tasks in flight during the cell (open: from tasks' arrival/done; closed: C);
                K = floor(pool / that)
Ceiling rule: R* = highest open rate with throughput >= 0.95 x rate and 0 unfinished at the drain cap.
"""
import argparse, json, os, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gateway"))


def pct(v, q):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q / 100
    f = int(k)
    return v[f] + (v[min(f + 1, len(v) - 1)] - v[f]) * (k - f)


def rnd(x, n=3):
    return None if x is None else round(x, n)


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def miss_causes(turns):
    by = {}
    for t in turns:
        if t.get("error"):
            continue
        by.setdefault(t.get("task_id") or t["qid"], []).append(t)
    cold = new = ev = rer = evp = P = C = 0
    for ts in by.values():
        ts.sort(key=lambda r: r["turn"])
        prev = None
        for t in ts:
            p, c, o = t.get("prompt_tokens") or 0, t.get("cached_tokens") or 0, t.get("output_tokens") or 0
            P += p; C += c
            if prev is None:
                cold += max(0, p - c)
            else:
                nw = max(0, p - (prev[0] + prev[1]))
                new += nw
                ev += max(0, (p - nw) - c - 16)
                # addendum (2j-P1): split into re-render of the previous reply vs eviction of the earlier conversation
                if c >= prev[2] - 32:
                    rer += max(0, (p - nw) - prev[2])
                evp += max(0, prev[2] - c - 32)
            prev = (p, o, p)
    unc = max(1, P - C)
    return dict(prefix_hit=rnd(C / max(1, P), 4), uncached_tokens=P - C, cold_share=rnd(cold / unc, 4),
                new_share=rnd(new / unc, 4), evicted_share=rnd(ev / unc, 4),
                rerender_share=rnd(rer / unc, 4), evicted_proper_share=rnd(evp / unc, 4),
                largest=max((("cold", cold), ("new", new), ("evicted", ev)), key=lambda x: x[1])[0])


def steps_in(steps, t0, t1):
    s = [r for r in steps if t0 <= r.get("t", 0) < t1]
    det = [r for r in s if "step_ms" in r and not r.get("dummy")]
    tot = sum(r["step_ms"] for r in det) or 1e-9
    pre_ms = sum(r["step_ms"] for r in det if r.get("ctx_tokens", 0) > 0)
    ctx = sum(r.get("ctx_tokens", 0) for r in det); gen = sum(r.get("gen_tokens", 0) for r in det)
    # token-weighted split of mixed steps: prefill-only steps fully prefill, decode-only fully decode,
    # mixed steps split by tokens (an upper bound for decode's share, since a prefill token costs less than a step)
    pre_w = 0.0
    for r in det:
        c, g = r.get("ctx_tokens", 0), r.get("gen_tokens", 0)
        if c and not g:
            pre_w += r["step_ms"]
        elif c and g:
            pre_w += r["step_ms"] * c / (c + g)
    sched = [r for r in s if "kv_usage" in r]
    return dict(n_steps=len(det), sum_step_s=rnd(tot / 1000, 1), ctx_tokens=ctx, gen_tokens=gen,
                prefill_step_share=rnd(pre_ms / tot, 4), prefill_token_weighted_share=rnd(pre_w / tot, 4),
                preempted=sum(r.get("preempted", 0) for r in s), evictions_sampled=sum(r.get("evict_n", 0) for r in s),
                kv_usage_peak=rnd(max((r["kv_usage"] for r in sched), default=None), 4),
                running_mean=rnd(st.mean(r["running"] for r in sched), 1) if sched else None,
                waiting_mean=rnd(st.mean(r["waiting"] for r in sched), 1) if sched else None,
                decode_step_ms_p50=rnd(pct([r["step_ms"] for r in det if r.get("gen_tokens") and not r.get("ctx_tokens")], 50), 2))


def shares(tasks):
    T = sum(t.get("task_s") or 0 for t in tasks) or 1e-9
    return dict(llm_share=rnd(sum(t.get("llm_s") or 0 for t in tasks) / T, 4),
                db_share=rnd(sum(t.get("db_s") or 0 for t in tasks) / T, 4),
                db_queue_share=rnd(sum(t.get("db_queue_s") or 0 for t in tasks) / T, 4))


def max_in_flight(tasks):
    ev = []
    for t in tasks:
        if t.get("arrival_s") is not None and t.get("done_s") is not None:
            ev += [(t["arrival_s"], 1), (t["done_s"], -1)]
    n = m = 0
    for _, d in sorted(ev):
        n += d; m = max(m, n)
    return m


def analyze_job(d):
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(d, "cells.tsv"))][1:]
    pools = {}
    for i, l in enumerate(open(os.path.join(d, "kv_pool.txt")), 1):
        try:
            pools[i] = int(l.split("KV pool")[1].split()[0])
        except (IndexError, ValueError):
            pass
    steps = {}
    out = dict(job=os.path.basename(os.path.normpath(d)), cells={}, kv_pools=pools)
    import summarize
    for name, srv, t0, t1, rc in rows:
        srv, t0, t1 = int(srv), float(t0), float(t1)
        if srv not in steps:
            steps[srv] = jl(os.path.join(d, f"server_{srv}_steps.jsonl"))
        cd = os.path.join(d, name)
        kind = name.split("_", 2)[1]
        c = dict(server=srv, rc=int(rc), wall_s=rnd(t1 - t0, 1), steplog=bool(steps[srv]))
        if kind == "burst":
            b = json.load(open(os.path.join(cd, "burst.json")))
            c.update(kind="burst", out_tok_per_s=b["out_tok_per_s_mean"], instrumented=bool(steps[srv]))
        else:
            tasks, turns = jl(os.path.join(cd, "tasks.jsonl")), jl(os.path.join(cd, "turns.jsonl"))
            if kind == "closed":
                C, N = map(int, name.split("_")[2:4])
                ts = [t["task_s"] for t in tasks]
                c.update(kind="closed", c=C, n=len(tasks), p50=rnd(pct(ts, 50)), p95=rnd(pct(ts, 95)),
                         accuracy=rnd(sum(t["correct"] for t in tasks) / max(1, len(tasks)), 4),
                         turns_mean=rnd(st.mean(t["turns"] for t in tasks), 2) if tasks else None,
                         no_sql=sum(1 for t in tasks if not t.get("pred_sql")), in_flight_max=C, **shares(tasks))
            else:
                s = summarize.summarize_cell(cd)
                meas = [t for t in tasks if t.get("measured")]
                c.update(kind="open", rate=s["rate"], **{k: s.get(k) for k in s if k.startswith(("p50", "p95", "throughput",
                         "n_", "incomplete", "accuracy", "turns_mean", "unfinished"))},
                         in_flight_max=max_in_flight(tasks), **shares(meas))
            c["miss"] = miss_causes(turns)
            if steps[srv]:
                c["steps"] = steps_in(steps[srv], t0, t1)
                pool = pools.get(srv)
                if pool and c["steps"]["kv_usage_peak"] and c["in_flight_max"]:
                    kv_task = pool * c["steps"]["kv_usage_peak"] / c["in_flight_max"]
                    c.update(kv_per_task=round(kv_task), K=int(pool // kv_task))
        out["cells"][name] = c
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = [analyze_job(d) for d in a.jobs]
    for r in res:
        opens = sorted((c for c in r["cells"].values() if c.get("kind") == "open"), key=lambda c: c["rate"])
        ok = [c["rate"] for c in opens if (c.get("throughput_per_min") or 0) >= 0.95 * c["rate"]
              and not c.get("n_incomplete")]
        r["R_star"] = max(ok) if ok else None
        bursts = [c for c in r["cells"].values() if c.get("kind") == "burst"]
        on = [c["out_tok_per_s"] for c in bursts if c["instrumented"]]
        off = [c["out_tok_per_s"] for c in bursts if not c["instrumented"]]
        if on and off:
            r["logging_overhead_pct"] = round(100 * (1 - st.mean(on) / st.mean(off)), 2)
    json.dump(res, open(a.out, "w"), indent=1)
    for r in res:
        print(f"job {r['job']}: R* = {r.get('R_star')}, logging overhead {r.get('logging_overhead_pct')}%")
        for n, c in r["cells"].items():
            keep = {k: c.get(k) for k in ("kind", "rate", "c", "p50", "p95", "p50_s", "p95_s", "throughput_per_min",
                                          "n_incomplete", "accuracy", "llm_share", "db_share",
                                          "db_queue_share", "kv_per_task", "K", "out_tok_per_s") if c.get(k) is not None}
            if "miss" in c:
                keep["miss"] = c["miss"]
            if "steps" in c:
                keep["steps"] = {k: c["steps"][k] for k in ("prefill_step_share", "prefill_token_weighted_share",
                                                            "preempted", "kv_usage_peak", "running_mean", "waiting_mean")}
            print(f"  {n}: {json.dumps(keep)}")


if __name__ == "__main__":
    main()
