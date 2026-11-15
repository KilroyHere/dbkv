"""Fixed synthetic burst against a vLLM server (logging-overhead control, PLAN 2j Phase 0 smoke job).

  python harness/w3/burst.py --url $VLLM_URL --n 64 --prompt-tokens 2000 --max-tokens 256 --reps 3 --out FILE.json

All --n requests are sent at once (completions API, ignore_eos, temperature 0), prompts are deterministic random
token-id strings (seed fixed, one distinct prompt per request so no prefix sharing beyond the first block), and the
prefix cache is reset before each rep (POST /reset_prefix_cache needs VLLM_SERVER_DEV_MODE=1; if it fails, prompts
are re-seeded per rep instead). Reports per rep: wall s, output tokens/s, request latency p50/p95.
"""
import argparse, asyncio, json, random, statistics as st, time

import aiohttp


async def one(http, url, model, prompt, max_tokens):
    body = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0.0, "ignore_eos": True}
    t = time.monotonic()
    async with http.post(url + "/v1/completions", json=body) as r:
        js = await r.json()
    return time.monotonic() - t, js.get("usage", {}).get("completion_tokens", 0)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", default=__import__("os").environ.get("DBKV_MODEL", "Qwen/Qwen3-32B"))
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--prompt-tokens", type=int, default=2000)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None)) as http:
        await one(http, a.url, a.model, [1, 2, 3], 4)  # warm-up
        for rep in range(a.reps):
            reset = False
            try:
                async with http.post(a.url + "/reset_prefix_cache") as r:
                    reset = r.status == 200
            except Exception:  # noqa: BLE001
                pass
            rng = random.Random(f"burst-{rep if not reset else 0}")
            prompts = [[rng.randrange(1000, 100000) for _ in range(a.prompt_tokens)] for _ in range(a.n)]
            t = time.monotonic()
            out = await asyncio.gather(*[one(http, a.url, a.model, p, a.max_tokens) for p in prompts])
            wall = time.monotonic() - t
            lat = sorted(x[0] for x in out)
            toks = sum(x[1] for x in out)
            r = dict(label=a.label, rep=rep, prefix_reset=reset, wall_s=round(wall, 3), out_tokens=toks,
                     out_tok_per_s=round(toks / wall, 1), lat_p50=round(lat[len(lat) // 2], 3),
                     lat_p95=round(lat[int(0.95 * (len(lat) - 1))], 3))
            print(json.dumps(r), flush=True)
            res.append(r)
    summ = dict(label=a.label, n=a.n, prompt_tokens=a.prompt_tokens, max_tokens=a.max_tokens, reps=res,
                out_tok_per_s_mean=round(st.mean(r["out_tok_per_s"] for r in res), 1))
    json.dump(summ, open(a.out, "w"), indent=1)
    print("burst", json.dumps({k: v for k, v in summ.items() if k != "reps"}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
