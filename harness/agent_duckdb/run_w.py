"""The frozen ReAct SQL agent (agent-frozen-v1:harness/agent/run_bird.py) on the W workload (PLAN §2h).

  python harness/agent_duckdb/run_w.py --url http://127.0.0.1:8000 \
      --stream $DBKV_DATA/plancache/streams/w_r80_s0.jsonl --n 150 --concurrency 4 \
      --brief $DBKV_DATA/plancache/brief_tpcds_compact.txt --out DIR

Same loop, prompt, decoding and chat body as the frozen agent; only the tool backend (DuckDB, tools_duckdb)
and the task source (a W stream file, first --n questions, one shared brief file) change. See README.md.
Writes DIR/turns.jsonl (as the frozen agent, plus turn_type) and DIR/tasks.jsonl (as the frozen agent, plus
tenant, template_id, phrasing_id, is_repeat, pos).
"""
import argparse, asyncio, json, os, sys, time

import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools_duckdb as tools  # noqa: E402

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


LAST = ("This is your last reply. Do not call tools. Give the final answer now as one SQLite query in a "
        "```sql ... ``` block.")


async def chat(http, a, messages, final=False):
    body = {"model": a.model, "messages": messages, "tools": tools.TOOL_SPECS, "tool_choice": "none" if final else "auto",
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


def turn_type(calls):
    """PLAN §2h / W interface: final = no tool call; execute_sql = any execute_sql call; explore = otherwise
    (all calls are list_tables / describe_table / sample_rows)."""
    names = [c["function"]["name"] for c in calls]
    if not names:
        return "final"
    return "execute_sql" if "execute_sql" in names else "explore"


async def run_task(http, a, task, sem, turns_out, tasks_out):
    db = task["db_path"]
    sys_prompt = SYSTEM.format(max_turns=a.max_turns)
    build_s = 0.0
    if a.brief_text:  # one shared brief for every tenant, placed exactly like the frozen agent's --briefs
        sys_prompt += "\n\nDatabase schema:\n" + a.brief_text
    q = task["question"] + (f"\nHint: {task['evidence']}" if task.get("evidence") else "")
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": q}]
    async with sem:
        t_start = time.monotonic(); db_time = 0.0; last_ok_sql = None; answer = None; status = "max_turns"
        n = 0; prompt_tok = 0
        for n in range(1, a.max_turns + 1):
            final = n == a.max_turns  # turn budget: the last reply must be the answer
            if final:
                messages.append({"role": "user", "content": LAST})
            resp, dt, err = await chat(http, a, messages, final=final)
            if resp is None:
                status = "llm_error:" + ("context" if "context" in (err or "").lower() or "maximum" in (err or "").lower() else "other")
                turns_out.append(dict(qid=task["qid"], turn=n, error=status, detail=err, client_s=round(dt, 4)))
                break
            msg = resp["choices"][0]["message"]; u = resp.get("usage") or {}; m = resp.get("metrics") or {}
            prompt_tok += u.get("prompt_tokens", 0)
            calls = msg.get("tool_calls") or []
            row = dict(qid=task["qid"], db=task["tenant"], turn=n, client_s=round(dt, 4),
                       prompt_tokens=u.get("prompt_tokens"), output_tokens=u.get("completion_tokens"),
                       cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                       queue_ms=m.get("queue_time_ms"), prefill_ms=m.get("time_to_first_token_ms"),
                       decode_ms=m.get("generation_time_ms"), tools=[], t=round(time.monotonic() - t_start, 3),
                       turn_type=turn_type(calls))
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
        task_s = time.monotonic() - t_start + build_s
        final_text = (messages[-1].get("content") or "")[:400] if messages[-1]["role"] == "assistant" else ""
    pred = answer or last_ok_sql
    correct, why = False, None
    if pred:  # execution match on the task's tenant (read-only): pred and gold result rows as sets
        gc, gr, _, ge, _ = await asyncio.to_thread(tools.run_query, db, task["gold_sql"])
        pc, pr, _, pe, _ = await asyncio.to_thread(tools.run_query, db, pred)
        correct = (pe is None and ge is None and set(map(tuple, pr)) == set(map(tuple, gr)))
        why = pe or ("gold_error" if ge else None)
    tasks_out.append(dict(qid=task["qid"], db=task["tenant"], difficulty=task.get("difficulty"),
                          brief=a.brief_name, build_s=round(build_s, 4), concurrency=a.concurrency, status=status, turns=n,
                          task_s=round(task_s, 3), db_s=round(db_time, 4), prompt_tokens=prompt_tok,
                          pred_sql=pred, used_answer=bool(answer), correct=bool(correct), pred_error=why,
                          final_text=final_text, tenant=task["tenant"], template_id=task["template_id"],
                          phrasing_id=task["phrasing_id"], is_repeat=bool(task["is_repeat"]), pos=task.get("pos")))
    print(f"[{len(tasks_out)}] {task['qid']} {status} turns={n} {task_s:.1f}s correct={correct}", flush=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--stream", required=True, help="W stream JSONL (harness/plancache/make_streams.py)")
    ap.add_argument("--n", type=int, default=150, help="first N questions of the stream")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--brief", default="none", help="brief text file shared by all tenants, or 'none'")
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stream = [json.loads(l) for l in open(a.stream) if l.strip()]
    if len(stream) < a.n:
        sys.exit(f"stream {a.stream} has {len(stream)} questions < --n {a.n}")
    tasks = stream[:a.n]
    a.brief_text = "" if a.brief in ("", "none") else open(a.brief).read().strip()
    a.brief_name = "none" if not a.brief_text else os.path.splitext(os.path.basename(a.brief))[0]
    cfg = {k: v for k, v in vars(a).items() if k != "brief_text"}
    cfg["brief_chars"] = len(a.brief_text)
    json.dump(dict(cfg, qids=[t["qid"] for t in tasks]), open(os.path.join(a.out, "config.json"), "w"), indent=1)
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
