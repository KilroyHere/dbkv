"""G3 synthetic session replayer against a running vLLM OpenAI server.

Each session runs agent "tasks" back to back. A task is TURNS LLM turns on one growing context:
  turn 0: prefill a fresh random context of C0 tokens, generate OUT tokens
  turn k>0: pause (sampled SQL time) -> append TOOL_IN random tokens -> generate OUT tokens
C0 = C - TURNS*(TOOL_IN+OUT)/2, so the context averages ~C over a task.
Generated token ids are appended verbatim (return_token_ids), so a resumed turn's prompt is an
exact extension of the previous one and prefix caching can hit if the KV survived the pause.
Every task uses fresh random tokens, so sessions never share prefixes.

Per point (C, N) it writes turns.csv, tasks.csv, metrics.jsonl (1 s samples) and summary.json:
  resume TTFT = tool return -> first token (turns k>0); recomputed = prompt - cached - new tokens
  (a full hit still recomputes <=16 tokens: the last partial block (<=15) plus the final sampled token,
  whose KV is never written; measured 2-16 in smoke job 60824741).

  python harness/replay.py --url http://127.0.0.1:8000 --points 4096:8,20480:6 --out DIR
"""
import argparse, asyncio, csv, json, os, sys, time

import aiohttp
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sim import pauses  # noqa: E402

VOCAB = 151_643  # Qwen3 ordinary-token range (special tokens start here)
COUNTERS = ["vllm:prefix_cache_queries", "vllm:prefix_cache_hits", "vllm:num_preemptions",
            "vllm:prompt_tokens", "vllm:prompt_tokens_cached", "vllm:generation_tokens"]
GAUGES = ["vllm:kv_cache_usage_perc", "vllm:num_requests_running", "vllm:num_requests_waiting"]


def parse_metrics(text):
    """Sum each metric family over its label sets (one engine, one model)."""
    out = {}
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        for base in COUNTERS + GAUGES:
            if name in (base, base + "_total"):
                out[base] = out.get(base, 0.0) + float(line.rsplit(" ", 1)[1])
    return out


async def metrics(http, url):
    async with http.get(url + "/metrics") as r:
        return parse_metrics(await r.text())


async def turn(http, a, prompt, priority=None):
    """One streamed completion. Returns (ttft, e2e, output token ids, usage)."""
    body = {"model": a.model, "prompt": prompt, "max_tokens": a.out_tokens, "ignore_eos": True,
            "temperature": 0.0, "stream": True, "return_token_ids": True,
            "stream_options": {"include_usage": True}}
    if priority is not None:  # needs `vllm serve --scheduling-policy priority`; lower runs first
        body["priority"] = priority
    t0 = time.monotonic(); ttft = None; toks = []; usage = {}
    async with http.post(a.url + "/v1/completions", json=body) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:300]}")
        async for raw in r.content:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            msg = json.loads(line[5:])
            for ch in msg.get("choices") or []:
                ids = ch.get("token_ids") or []
                if ids and ttft is None:
                    ttft = time.monotonic() - t0
                toks.extend(ids)
            if msg.get("usage"):
                usage = msg["usage"]
    return ttft, time.monotonic() - t0, toks, usage


async def session(http, a, C, sid, t_start, t_end, turns_out, tasks_out, seed):
    rng = np.random.default_rng(seed)
    per_turn = a.tool_in + a.out_tokens
    c0 = max(256, C - a.turns * per_turn // 2)
    await asyncio.sleep(rng.uniform(0, a.stagger))  # spread the initial prefill burst
    task = 0
    while time.monotonic() < t_end:
        ctx = rng.integers(0, VOCAB, c0).tolist()
        t_task = time.monotonic(); done = True
        for k in range(a.turns):
            pause = 0.0
            if k > 0:
                pause = float(pauses.sample(rng, mix=a.mix))
                if time.monotonic() + pause >= t_end:
                    done = False; break
                await asyncio.sleep(pause)
                ctx += rng.integers(0, VOCAB, a.tool_in).tolist()
            new = c0 if k == 0 else a.tool_in
            t_req = time.monotonic()
            prio = int((t_task - t_start) * 1000) if a.priority == "task_start" else None
            ttft, e2e, out, usage = await turn(http, a, ctx, prio)
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            ptoks = usage.get("prompt_tokens", len(ctx))
            turns_out.append(dict(
                sid=sid, task=task, turn=k, t_req=round(t_req - t_start, 4), ctx=len(ctx),
                pause=round(pause, 4), ttft=round(ttft or e2e, 4), e2e=round(e2e, 4),
                prompt=ptoks, cached=cached, out=len(out),
                recomputed=None if cached is None else max(0, ptoks - cached - new)))
            ctx += out
        if done:
            tasks_out.append(dict(sid=sid, task=task, t_start=round(t_task - t_start, 4),
                                  dur=round(time.monotonic() - t_task, 4), ctx_end=len(ctx)))
        task += 1


def pct(xs, p):
    return round(float(np.percentile(xs, p)), 4) if len(xs) else None


async def run_point(http, a, C, N, rep, outdir):
    os.makedirs(outdir, exist_ok=True)
    async with http.post(a.url + "/reset_prefix_cache") as r:
        reset_ok = r.status == 200
    m0 = await metrics(http, a.url)
    t_start = time.monotonic(); t_end = t_start + a.warmup + a.duration
    turns_out, tasks_out, samples = [], [], []

    async def sampler():
        while True:
            m = await metrics(http, a.url)
            samples.append({"t": round(time.monotonic() - t_start, 2), **{g: m.get(g) for g in GAUGES}})
            await asyncio.sleep(1.0)

    smp = asyncio.create_task(sampler())
    seeds = np.random.SeedSequence([a.seed, C, N, rep]).spawn(N)
    await asyncio.gather(*[session(http, a, C, i, t_start, t_end, turns_out, tasks_out,
                                   int(seeds[i].generate_state(1)[0])) for i in range(N)])
    smp.cancel()
    m1 = await metrics(http, a.url)
    wall = time.monotonic() - t_start

    w = a.warmup  # measurement window: after warm-up
    res = [t for t in turns_out if t["turn"] > 0 and t["t_req"] >= w]
    tsk = [t for t in tasks_out if t["t_start"] >= w]
    usage = [s["vllm:kv_cache_usage_perc"] for s in samples if s["t"] >= w and s["vllm:kv_cache_usage_perc"] is not None]
    waiting = [s["vllm:num_requests_waiting"] for s in samples if s["t"] >= w and s["vllm:num_requests_waiting"] is not None]
    recomp = [t["recomputed"] for t in res if t["recomputed"] is not None]
    d = {k: m1.get(k, 0) - m0.get(k, 0) for k in COUNTERS}
    summary = dict(
        ctx=C, sessions=N, rep=rep, mix=a.mix, priority=a.priority, turns=a.turns, warmup=a.warmup, duration=a.duration,
        wall=round(wall, 1), prefix_reset=reset_ok,
        resume_turns=len(res), resume_ttft_p50=pct([t["ttft"] for t in res], 50),
        resume_ttft_p95=pct([t["ttft"] for t in res], 95), turn_e2e_p95=pct([t["e2e"] for t in res], 95),
        tasks=len(tsk), task_p50=pct([t["dur"] for t in tsk], 50), task_p95=pct([t["dur"] for t in tsk], 95),
        recomputed_tokens=int(sum(recomp)), resume_full_hit_frac=round(float(np.mean([r <= 16 for r in recomp])), 4) if recomp else None,
        kv_usage_mean=round(float(np.mean(usage)), 4) if usage else None,
        kv_usage_max=round(float(np.max(usage)), 4) if usage else None,
        waiting_mean=round(float(np.mean(waiting)), 2) if waiting else None,
        preemptions=int(d["vllm:num_preemptions"]),
        prefix_hit_rate=round(d["vllm:prefix_cache_hits"] / d["vllm:prefix_cache_queries"], 4) if d["vllm:prefix_cache_queries"] else None,
        prompt_tokens=int(d["vllm:prompt_tokens"]), prompt_tokens_cached=int(d["vllm:prompt_tokens_cached"]),
        generation_tokens=int(d["vllm:generation_tokens"]))
    for name, rows in (("turns.csv", turns_out), ("tasks.csv", tasks_out)):
        if rows:
            with open(os.path.join(outdir, name), "w", newline="") as f:
                wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    with open(os.path.join(outdir, "metrics.jsonl"), "w") as f:
        f.writelines(json.dumps(s) + "\n" for s in samples)
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    return summary


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--points", required=True, help="CTX:N[,CTX:N...]")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--duration", type=float, default=300, help="measured seconds per point")
    ap.add_argument("--warmup", type=float, default=60)
    ap.add_argument("--stagger", type=float, default=20, help="spread session starts over this many s")
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--tool-in", type=int, default=300)
    ap.add_argument("--out-tokens", type=int, default=150)
    ap.add_argument("--mix", default="redshift", choices=list(pauses.KNOTS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--priority", default="none", choices=["none", "task_start"],
                    help="task_start: priority = task start (ms), i.e. program-level FCFS")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    points = [tuple(int(x) for x in p.split(":")) for p in a.points.split(",")]
    os.makedirs(a.out, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=None, sock_read=600)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0), timeout=timeout) as http:
        for rep in range(a.reps):
            for C, N in points:
                s = await run_point(http, a, C, N, rep, os.path.join(a.out, f"c{C}_n{N}_r{rep}"))
                with open(os.path.join(a.out, "summary.jsonl"), "a") as f:
                    f.write(json.dumps(s) + "\n")
                print(json.dumps(s), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
