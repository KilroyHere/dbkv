"""Summarize load-generator cells (PLAN 2f Phases 2-3; self-checks S2/S3).

    python harness/gateway/summarize.py JOBDIR_OR_CELLDIR [...] [--out PREFIX]

A cell dir is one loadgen --out (config.json, tasks.jsonl, metrics_<i>.jsonl, optional gateway.jsonl).
A job dir holds cell dirs. Writes PREFIX.md and PREFIX.json (default: <first arg>/summary.{md,json}).

Per cell, over tasks that ARRIVE in the measured window [warmup, warmup + measure):
  p50/p95 task time = arrival -> the agent's last LLM reply (includes any gateway queue wait);
  throughput = tasks completed (any arrival time) inside the window per measured minute, plus
    completed-measured-arrivals per measured minute; accuracy; incomplete (drain-cancelled / exceptions);
  admission wait (gateway queue_ms of each task's first request, from /gw/task_end) and client-side
    arrival -> first reply; gateway overhead p50/p95 (ms/request, requests inside the window);
  per backend: GPU idle fraction (share of 1 s samples with num_requests_running == 0), mean running /
    waiting / KV usage, prefix-cache hit rate and preemptions from counter deltas over the window.
"""
import argparse, json, os, sys


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    lo = int(k); hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def jl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # torn last line of a killed run
    return out


def rnd(x, n=3):
    return None if x is None else round(x, n)


def summarize_cell(d):
    cfg = json.load(open(os.path.join(d, "config.json")))
    W, M = cfg["warmup"], cfg["measure"]
    w0, w1 = cfg["window"]
    tasks = jl(os.path.join(d, "tasks.jsonl"))
    meas = [t for t in tasks if t.get("measured")]
    bad = lambda t: str(t.get("status", "")).startswith(("drain_cancelled", "exception"))
    ok = [t for t in meas if not bad(t)]
    e2e = [t["e2e_s"] for t in meas]
    done_in = [t for t in tasks if not bad(t) and W <= t["done_s"] < W + M]
    qw = [t.get("gw_queue_ms") for t in meas]
    s = dict(cell=os.path.basename(os.path.normpath(d)), label=cfg.get("label"), rate=cfg["rate"],
             url=cfg["url"], gateway=cfg.get("gateway"), brief=cfg.get("agent_brief"),
             n_arrivals=len(tasks), n_measured=len(meas), n_incomplete=len(meas) - len(ok),
             p50_s=rnd(pct(e2e, 50)), p95_s=rnd(pct(e2e, 95)), mean_s=rnd(sum(e2e) / len(e2e)) if e2e else None,
             throughput_per_min=rnd(len(done_in) / (M / 60.0)),
             throughput_measured_arrivals_per_min=rnd(len(ok) / (M / 60.0)),
             accuracy=rnd(sum(bool(t.get("correct")) for t in meas) / len(meas), 4) if meas else None,
             answered_frac=rnd(sum(t.get("status") == "answered" for t in meas) / len(meas), 4) if meas else None,
             turns_mean=rnd(sum(t.get("turns") or 0 for t in ok) / len(ok), 2) if ok else None,
             admission_wait_ms_mean=rnd(sum(x for x in qw if x is not None) / max(1, sum(x is not None for x in qw)), 1)
             if any(x is not None for x in qw) else None,
             admission_wait_ms_p50=rnd(pct(qw, 50), 1), admission_wait_ms_p95=rnd(pct(qw, 95), 1),
             admission_queued_frac=rnd(sum((x or 0) > 1.0 for x in qw) / len(qw), 3) if any(x is not None for x in qw) else None,
             first_reply_s_p50=rnd(pct([t.get("first_reply_s") for t in meas], 50)),
             first_reply_s_p95=rnd(pct([t.get("first_reply_s") for t in meas], 95)))
    gw = jl(os.path.join(d, "gateway.jsonl"))
    if gw:
        reqs = [r for r in gw if "ev" not in r]
        inw = [r for r in reqs if w0 <= r["ts"] < w1]
        s.update(gw_requests=len(reqs), gw_errors=sum(r["status"] != 200 for r in reqs),
                 gw_overhead_ms_p50=rnd(pct([r["overhead_ms"] for r in inw], 50)),
                 gw_overhead_ms_p95=rnd(pct([r["overhead_ms"] for r in inw], 95)),
                 gw_overhead_ms_p50_all=rnd(pct([r["overhead_ms"] for r in reqs], 50)),
                 gw_idle_releases=sum(r.get("ev") == "idle_release" for r in gw),
                 gw_policy={k: next((r.get(k) for r in gw if r.get("ev") == "start"), None)
                            for k in ("admission", "priority", "route", "cap")},
                 gw_tasks_per_backend={})
        for t in meas:
            if t.get("gw_backend") is not None:
                b = str(t["gw_backend"])
                s["gw_tasks_per_backend"][b] = s["gw_tasks_per_backend"].get(b, 0) + 1
    backends = []
    i = 0
    while os.path.exists(os.path.join(d, f"metrics_{i}.jsonl")):
        ms = [m for m in jl(os.path.join(d, f"metrics_{i}.jsonl")) if "error" not in m]
        inw = [m for m in ms if w0 <= m["t"] < w1]
        b = dict(backend=ms[0]["backend"] if ms else None, samples=len(inw))
        if inw:
            run = [m.get("vllm:num_requests_running", 0) for m in inw]
            b.update(idle_frac=rnd(sum(x == 0 for x in run) / len(run)), running_mean=rnd(sum(run) / len(run), 2),
                     waiting_mean=rnd(sum(m.get("vllm:num_requests_waiting", 0) for m in inw) / len(inw), 2),
                     kv_mean=rnd(sum(m.get("vllm:kv_cache_usage_perc", 0) for m in inw) / len(inw)))
            first, last = inw[0], inw[-1]
            dq = last.get("vllm:prefix_cache_queries", 0) - first.get("vllm:prefix_cache_queries", 0)
            dh = last.get("vllm:prefix_cache_hits", 0) - first.get("vllm:prefix_cache_hits", 0)
            b.update(prefix_hit=rnd(dh / dq) if dq > 0 else None,
                     preemptions=last.get("vllm:num_preemptions", 0) - first.get("vllm:num_preemptions", 0))
        backends.append(b)
        i += 1
    s["backends"] = backends
    if backends and all("idle_frac" in b for b in backends):
        s["gpu_idle_frac"] = rnd(sum(b["idle_frac"] for b in backends) / len(backends))
        tq = sum(b.get("prefix_hit") is not None for b in backends)
        s["prefix_hit_mean"] = rnd(sum(b["prefix_hit"] or 0 for b in backends) / tq) if tq else None
    return s


def one_line(s):
    return (f"{s['cell']}: rate {s['rate']}/min n={s['n_measured']} (incomplete {s['n_incomplete']}) "
            f"p50 {s['p50_s']} s p95 {s['p95_s']} s thr {s['throughput_per_min']}/min acc {s['accuracy']} "
            f"adm.wait p95 {s.get('admission_wait_ms_p95')} ms gw.ovh p50/p95 {s.get('gw_overhead_ms_p50')}/"
            f"{s.get('gw_overhead_ms_p95')} ms idle {s.get('gpu_idle_frac')} hit {s.get('prefix_hit_mean')}")


COLS = [("cell", "cell"), ("rate", "λ/min"), ("n_measured", "n"), ("n_incomplete", "incompl."), ("p50_s", "p50 s"),
        ("p95_s", "p95 s"), ("throughput_per_min", "thr/min"), ("accuracy", "acc"),
        ("admission_wait_ms_p50", "adm.wait p50 ms"), ("admission_wait_ms_p95", "adm.wait p95 ms"),
        ("gw_overhead_ms_p50", "gw ovh p50 ms"), ("gw_overhead_ms_p95", "gw ovh p95 ms"),
        ("gw_idle_releases", "idle rel."), ("gpu_idle_frac", "GPU idle"), ("prefix_hit_mean", "prefix hit")]


def to_md(cells):
    out = ["| " + " | ".join(h for _, h in COLS) + " |", "|" + "---|" * len(COLS)]
    for s in cells:
        out.append("| " + " | ".join("" if s.get(k) is None else str(s.get(k)) for k, _ in COLS) + " |")
    out += ["", "Per backend:", "", "| cell | backend | tasks | idle | running | waiting | KV | prefix hit | preempt |",
            "|---|---|---|---|---|---|---|---|---|"]
    for s in cells:
        tpb = s.get("gw_tasks_per_backend") or {}
        for i, b in enumerate(s["backends"]):
            out.append(f"| {s['cell']} | {b.get('backend')} | {tpb.get(str(i), '')} | {b.get('idle_frac')} | "
                       f"{b.get('running_mean')} | {b.get('waiting_mean')} | {b.get('kv_mean')} | "
                       f"{b.get('prefix_hit')} | {b.get('preemptions')} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cells = []
    for d in a.dirs:
        if os.path.exists(os.path.join(d, "config.json")):
            cells.append(d)
        else:
            cells += sorted(os.path.join(d, x) for x in os.listdir(d)
                            if os.path.exists(os.path.join(d, x, "config.json")))
    sums = []
    for c in cells:
        try:
            sums.append(summarize_cell(c))
        except Exception as e:  # noqa: BLE001
            print(f"skip {c}: {e!r}", file=sys.stderr)
    prefix = a.out or os.path.join(a.dirs[0], "summary")
    json.dump(sums, open(prefix + ".json", "w"), indent=1)
    md = to_md(sums)
    open(prefix + ".md", "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
