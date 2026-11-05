"""Test 1 (D5) idle probe: single requests on an otherwise idle vLLM server, plus tokenizer timing.

  python harness/d5_probe.py --url http://127.0.0.1:8000 --out DIR

Writes DIR/idle.csv: kind (one_token | fresh | resume), ctx, client_ttft_ms, client_e2e_ms,
queue_ms, engine_ttft_ms, gen_ms, rest_ms (= client_ttft - queue - engine_ttft), and
DIR/tokenize.csv: ctx, ms (HF tokenizer encode of ctx tokens' worth of text).
Server must run with --enable-per-request-metrics.
"""
import argparse, asyncio, csv, json, os, sys, time

import aiohttp
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay import turn, VOCAB  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=20)
    a = ap.parse_args()
    a.priority = "none"
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(5)
    rows = []

    def row(kind, ctx, ttft, e2e, usage):
        m = usage.get("_srv", {})
        q, et = m.get("queue_time_ms"), m.get("time_to_first_token_ms")
        rows.append(dict(kind=kind, ctx=ctx, client_ttft_ms=round(1000 * ttft, 3), client_e2e_ms=round(1000 * e2e, 3),
                         queue_ms=q, engine_ttft_ms=et, gen_ms=m.get("generation_time_ms"),
                         rest_ms=None if q is None or et is None else round(1000 * ttft - q - et, 3),
                         cached=(usage.get("prompt_tokens_details") or {}).get("cached_tokens")))

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0, force_close=True)) as http:
        await http.post(a.url + "/reset_prefix_cache")
        for _ in range(3):  # warm the path
            a.out_tokens = 1; await turn(http, a, [int(rng.integers(0, VOCAB))])
        for _ in range(a.reps):
            a.out_tokens = 1
            ttft, e2e, _, u = await turn(http, a, [int(rng.integers(0, VOCAB))]); row("one_token", 1, ttft, e2e, u)
        for ctx in (4096, 8192, 20480):
            for _ in range(a.reps):
                a.out_tokens = 16
                p = rng.integers(0, VOCAB, ctx - 300).tolist()
                ttft, e2e, out, u = await turn(http, a, p); row("fresh", len(p), ttft, e2e, u)
                p = p + out + rng.integers(0, VOCAB, 300).tolist()   # resume: cached prefix + 300 new
                ttft, e2e, out, u = await turn(http, a, p); row("resume", len(p), ttft, e2e, u)
    with open(os.path.join(a.out, "idle.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    # tokenizer time for re-sending the prompt as text (what a real agent does)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    trows = []
    for ctx in (4096, 8192, 20480):
        text = tok.decode(rng.integers(1000, 100000, ctx).tolist())
        tok(text)  # warm
        ts = []
        for _ in range(10):
            t = time.perf_counter(); n = len(tok(text)["input_ids"]); ts.append(1000 * (time.perf_counter() - t))
        trows.append(dict(ctx=ctx, tokens=n, ms=round(float(np.median(ts)), 3)))
    with open(os.path.join(a.out, "tokenize.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trows[0])); w.writeheader(); w.writerows(trows)
    for k in ("one_token", "fresh", "resume"):
        for ctx in sorted({r["ctx"] for r in rows if r["kind"] == k}):
            rs = [r for r in rows if r["kind"] == k and r["ctx"] == ctx]
            med = lambda f: float(np.median([r[f] for r in rs if r[f] is not None]))  # noqa: E731
            print(f"{k:9s} ctx {ctx:6d}: client ttft {med('client_ttft_ms'):8.1f}  queue {med('queue_ms'):6.1f}  "
                  f"engine ttft {med('engine_ttft_ms'):8.1f}  rest {med('rest_ms'):6.1f} ms")
    print("tokenize:", trows)


if __name__ == "__main__":
    asyncio.run(main())
