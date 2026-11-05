"""Brief (iii): narrow the compact brief (i) with one cheap model pass per question (no gold information).

  python harness/brief/llm_select.py --url http://127.0.0.1:8000 --bird $DBKV_DATA/bird/dev_20240627 \
      --out briefs_llm.jsonl [--concurrency 8] [--eval]

One chat call per question (same Qwen3-8B server, non-thinking, temperature 0, max_tokens 300, no tools):
given brief (i) and the question + evidence, return the needed tables and columns as JSON. Names are
validated against the schema; join keys and join-path tables are added (build.join_closure). If the
reply can't be parsed or selects nothing, the question falls back to the full compact brief (flagged).
build_s = wall time of that call (+ rendering), measured under --concurrency, and is added to task time.
"""
import argparse, asyncio, json, os, re, sys, time

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

PROMPT = """Database schema:
{schema}

Question: {question}
{hint}
Which tables and columns are needed to write the SQL query for this question? Reply with JSON only, in the form
{{"tables": ["table", ...], "columns": ["table.column", ...]}}"""


def parse(text, db):
    m = build.meta(db)
    real_t = {t.lower(): t for t in m["tables"]}
    real_c = {t: {c.lower() for c, _, _ in m["cols"][t]} for t in m["tables"]}
    js = re.search(r"\{.*\}", text or "", re.S)
    if not js:
        return None
    try:
        obj = json.loads(js.group(0))
    except json.JSONDecodeError:
        return None
    clean = lambda x: str(x).strip().strip("`\"'[]").lower()  # noqa: E731
    sel = {}
    for t in obj.get("tables", []) or []:
        if clean(t) in real_t:
            sel.setdefault(real_t[clean(t)], set())
    for c in obj.get("columns", []) or []:
        c = str(c)
        if "." in c:
            t, col = c.split(".", 1)
            t, col = clean(t), clean(col)
            if t in real_t and col in real_c[real_t[t]]:
                sel.setdefault(real_t[t], set()).add(col)
        else:
            col = clean(c)
            for t in sel:
                if col in real_c[t]:
                    sel[t].add(col)
    return sel or None


async def one(http, a, task, sem, out):
    db = os.path.join(a.bird, "dev_databases", task["db_id"], task["db_id"] + ".sqlite")
    ev = task.get("evidence") or ""
    content = PROMPT.format(schema=build.render(db), question=task["question"], hint=f"Hint: {ev}\n" if ev else "")
    body = {"model": a.model, "messages": [{"role": "user", "content": content}], "temperature": 0.0,
            "max_tokens": 300, "chat_template_kwargs": {"enable_thinking": False}}
    async with sem:
        t0 = time.monotonic()
        async with http.post(a.url + "/v1/chat/completions", json=body) as r:
            resp = await r.json() if r.status == 200 else {}
        text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        sel = parse(text, db)
        fallback = sel is None
        sel = build.join_closure(db, sel) if sel else None
        brief = build.render(db, sel)
        build_s = time.monotonic() - t0
    m = build.meta(db)
    tabs = list(sel) if sel is not None else m["tables"]
    cols = [[t, c] for t in tabs for c, _, pk in m["cols"][t] if sel is None or not sel[t] or c.lower() in sel[t] or pk]
    u = resp.get("usage") or {}
    out.append(dict(qid=task["question_id"], db=task["db_id"], brief=brief, build_s=round(build_s, 4), tables=tabs,
                    columns=cols, fallback=fallback, sel_prompt_tokens=u.get("prompt_tokens"),
                    sel_output_tokens=u.get("completion_tokens")))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--bird", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--n", type=int, default=0, help="first N questions only (smoke)")
    ap.add_argument("--eval", action="store_true")
    a = ap.parse_args()
    dev = json.load(open(os.path.join(a.bird, "dev.json")))
    if a.n:
        dev = dev[:a.n]
    out = []
    sem = asyncio.Semaphore(a.concurrency)
    t = time.monotonic()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0, force_close=True)) as http:
        await asyncio.gather(*[one(http, a, task, sem, out) for task in dev])
    out.sort(key=lambda r: r["qid"])
    with open(a.out, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in out)
    bs = sorted(r["build_s"] for r in out)
    print(f"llm: {len(out)} briefs in {time.monotonic() - t:.0f} s; build_s p50 {bs[len(bs) // 2]:.2f} "
          f"p95 {bs[int(0.95 * len(bs))]:.2f}; fallbacks {sum(r['fallback'] for r in out)}; "
          f"mean {sum(len(r['brief']) for r in out) / len(out):.0f} chars", flush=True)
    if a.eval:
        print(json.dumps(build.selection_metrics(out, json.load(open(os.path.join(a.bird, "dev.json"))), a.bird)), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
