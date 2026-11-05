"""Minimal ReAct SQL agent on BIRD dev (Tests 2 and 3; rules in PLAN §2b).

  python harness/agent/run_bird.py --url http://127.0.0.1:8000 --bird $DBKV_DATA/bird/dev_20240627 \
      --n 150 --seed 0 --concurrency 8 --brief none|full|oracle --out DIR

Qwen3-8B via vLLM's OpenAI chat API with native tool calling (serve with --enable-auto-tool-choice
--tool-call-parser hermes --enable-per-request-metrics), non-thinking mode, temperature 0, <= 15 turns.
Writes DIR/turns.jsonl (one LLM call each: tokens, client time, server queue/prefill/decode, tool,
SQL, tool runtime, error class) and DIR/tasks.jsonl (task time, turns, DB time, final SQL, correct).
"""
import argparse, asyncio, json, os, random, sys, time

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools  # noqa: E402

SYSTEM = """You are a careful data analyst answering a question about a SQLite database.
Use the tools to inspect the database and test queries. Each reply may call tools.
Never guess table or column names: check them with describe_table before using them, and quote names that
contain spaces or symbols with backticks.
When you are confident, reply WITHOUT a tool call. That final reply must contain exactly one SQLite query in a
```sql ... ``` block that computes the answer from the database itself: never copy numbers or values from
earlier results into the query. Return only the columns the question asks for.
You have at most {max_turns} replies in total."""


NUDGE = ("Continue. Either call a tool, or, if you are done, reply with the final answer as one SQLite query "
         "in a ```sql ... ``` block.")


async def chat(http, a, messages):
    body = {"model": a.model, "messages": messages, "tools": tools.TOOL_SPECS, "tool_choice": "auto",
            "temperature": 0.0, "max_tokens": a.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.monotonic()
    async with http.post(a.url + "/v1/chat/completions", json=body) as r:
        txt = await r.text()
        dt = time.monotonic() - t0
        if r.status != 200:
            return None, dt, txt[:300]
        return json.loads(txt), dt, None


def final_sql(text):
    m = tools.SQL_BLOCK.findall(text or "")
    return m[-1].strip() if m else None


async def run_task(http, a, task, sem, turns_out, tasks_out):
    db = os.path.join(a.bird, "dev_databases", task["db_id"], task["db_id"] + ".sqlite")
    sys_prompt = SYSTEM.format(max_turns=a.max_turns)
    if a.brief == "full":
        sys_prompt += "\n\nDatabase schema (with example values):\n" + await asyncio.to_thread(tools.schema, db)
    elif a.brief == "oracle":
        tabs, cols = await asyncio.to_thread(tools.gold_tables_columns, db, task["SQL"])
        sys_prompt += "\n\nRelevant schema (with example values):\n" + await asyncio.to_thread(tools.schema, db, tabs, cols)
    q = task["question"] + (f"\nHint: {task['evidence']}" if task.get("evidence") else "")
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": q}]
    async with sem:
        t_start = time.monotonic(); db_time = 0.0; last_ok_sql = None; answer = None; status = "max_turns"
        n = 0; prompt_tok = 0
        for n in range(1, a.max_turns + 1):
            resp, dt, err = await chat(http, a, messages)
            if resp is None:
                status = "llm_error:" + ("context" if "context" in (err or "").lower() or "maximum" in (err or "").lower() else "other")
                turns_out.append(dict(qid=task["question_id"], turn=n, error=status, detail=err, client_s=round(dt, 4)))
                break
            msg = resp["choices"][0]["message"]; u = resp.get("usage") or {}; m = resp.get("metrics") or {}
            prompt_tok += u.get("prompt_tokens", 0)
            calls = msg.get("tool_calls") or []
            row = dict(qid=task["question_id"], db=task["db_id"], turn=n, client_s=round(dt, 4),
                       prompt_tokens=u.get("prompt_tokens"), output_tokens=u.get("completion_tokens"),
                       cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                       queue_ms=m.get("queue_time_ms"), prefill_ms=m.get("time_to_first_token_ms"),
                       decode_ms=m.get("generation_time_ms"), tools=[], t=round(time.monotonic() - t_start, 3))
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             **({"tool_calls": calls} if calls else {})})
            if not calls:
                answer = final_sql(msg.get("content"))
                if answer:
                    status = "answered"; turns_out.append(row); break
                # Prose without a tool call or a final SQL block (e.g. "I will now run..."): nudge and continue.
                status = "no_sql"; row["nudged"] = True; turns_out.append(row)
                messages.append({"role": "user", "content": NUDGE})
                continue
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                text, info = await asyncio.to_thread(tools.call, db, name, args)
                db_time += info["runtime_s"]
                if name == "execute_sql" and info["error"] is None:
                    last_ok_sql = info["sql"]
                row["tools"].append(dict(name=name, sql=info["sql"], runtime_s=round(info["runtime_s"], 5),
                                         error=info["error"], rows=info["rows"]))
                messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": text})
            turns_out.append(row)
        task_s = time.monotonic() - t_start
        final_text = (messages[-1].get("content") or "")[:400] if messages[-1]["role"] == "assistant" else ""
    pred = answer or last_ok_sql
    correct, why = False, None
    if pred:
        gc, gr, _, ge, _ = await asyncio.to_thread(tools.run_query, db, task["SQL"])
        pc, pr, _, pe, _ = await asyncio.to_thread(tools.run_query, db, pred)
        correct = (pe is None and ge is None and set(map(tuple, pr)) == set(map(tuple, gr)))
        why = pe or ("gold_error" if ge else None)
    tasks_out.append(dict(qid=task["question_id"], db=task["db_id"], difficulty=task.get("difficulty"),
                          brief=a.brief, concurrency=a.concurrency, status=status, turns=n,
                          task_s=round(task_s, 3), db_s=round(db_time, 4), prompt_tokens=prompt_tok,
                          pred_sql=pred, used_answer=bool(answer), correct=bool(correct), pred_error=why,
                          final_text=final_text))
    print(f"[{len(tasks_out)}] q{task['question_id']} {status} turns={n} {task_s:.1f}s correct={correct}", flush=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--bird", required=True)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--brief", default="none", choices=["none", "full", "oracle"])
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dev = json.load(open(os.path.join(a.bird, "dev.json")))
    sel = random.Random(a.seed).sample(range(len(dev)), a.n)
    tasks = [dev[i] for i in sel]
    json.dump(dict(vars(a), qids=[t["question_id"] for t in tasks]), open(os.path.join(a.out, "config.json"), "w"), indent=1)
    turns_out, tasks_out = [], []
    sem = asyncio.Semaphore(a.concurrency)
    t = time.monotonic()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0, force_close=True),
                                     timeout=aiohttp.ClientTimeout(total=None, sock_read=900)) as http:
        await asyncio.gather(*[run_task(http, a, task, sem, turns_out, tasks_out) for task in tasks])
    with open(os.path.join(a.out, "turns.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in turns_out)
    with open(os.path.join(a.out, "tasks.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in tasks_out)
    acc = sum(r["correct"] for r in tasks_out) / len(tasks_out)
    print(f"done: {len(tasks_out)} tasks in {time.monotonic() - t:.0f} s, accuracy {acc:.3f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
