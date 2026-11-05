"""Stage 1.3 of the SQL-expert test (docs/EXPERT.md): the base agent (harness/agent/run_bird.py, unchanged) in three arms.

  python harness/expert/run_expert.py --arm a|b|d [--fewshot harness/expert/fewshot.json] [--expert-model expert] \
      <all run_bird.py args, e.g. --url URL --bird DIR --n 150 --seed 0 --concurrency 8 --brief full --out DIR>

  (a) base agent: run_bird exactly.
  (b) + 3 few-shot SQL examples (BIRD train) appended to the system prompt.
  (d) + write_sql(intent) tool: the LoRA adapter (served as --expert-model by the same vLLM) writes the SQL from the
      question, the intent and the same brief the agent has; the SQL is executed and returned with its result.
      Adapter calls are logged to OUT/adapter_calls.jsonl (not agent turns).

Patches only module attributes that run_bird reads at call time (SYSTEM, run_task, tools.TOOL_SPECS, tools.call).
"""
import argparse, asyncio, contextvars, json, os, re, subprocess, sys, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(os.path.dirname(HERE), "agent")
sys.path.insert(0, AGENT)
import tools  # noqa: E402
import run_bird  # noqa: E402

CUR_TASK = contextvars.ContextVar("task", default=None)

# The adapter's native system prompt (craboy4/text-to-sql-struct-distillation, teacher_generation/generate_teacher_data.py)
EXPERT_SYSTEM = open(os.path.join(HERE, "expert_system_prompt.txt"), encoding="utf-8").read().strip()

WRITE_SQL_SPEC = {"type": "function", "function": {
    "name": "write_sql",
    "description": ("Ask a SQL expert to write and run the query. Describe in plain words what the query must compute "
                    "(what to return, filters, joins, grouping, ordering). Returns the expert's SQLite query and its "
                    "result (first 40 rows)."),
    "parameters": {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}}}

D_SUFFIX = ("\nYou can call write_sql(intent) to have a SQL expert write and run the query for you; prefer it over "
            "writing complex SQL yourself. If its query answers the question, give it as your final ```sql``` block.")

TAGGED_SQL = re.compile(r"<sql>\s*(.*?)\s*(?:</sql>|\Z)", re.S)

_log, _lock = [], threading.Lock()
_brief_cache = {}


def agent_brief(db, task, brief):
    """The same schema text run_bird puts in the agent's system prompt."""
    key = (task["question_id"], brief)
    if key not in _brief_cache:
        if brief == "full":
            _brief_cache[key] = tools.schema(db)
        elif brief == "oracle":
            tabs, cols = tools.gold_tables_columns(db, task["SQL"])
            _brief_cache[key] = tools.schema(db, tabs, cols)
        else:
            _brief_cache[key] = tools.schema(db, samples=0)
    return _brief_cache[key]


def expert_sql(A, db, task, intent):
    ev = (task.get("evidence") or "").strip() or "No additional evidence."
    user = (f"Task\n{task['question'].strip()}\nAnalyst's intent: {intent.strip()}\n\nEvidence\n{ev}\n\n"
            f"Complete SQLite schema with column meanings\n{agent_brief(db, task, A.brief)}\n")
    body = {"model": A.expert_model, "messages": [{"role": "system", "content": EXPERT_SYSTEM},
                                                  {"role": "user", "content": user}],
            "temperature": 0.0, "max_tokens": A.expert_max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.monotonic()
    req = urllib.request.Request(A.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            resp = json.loads(r.read())
        err = None
    except Exception as e:  # noqa: BLE001
        resp, err = None, str(e)[:300]
    dt = time.monotonic() - t0
    rec = dict(qid=task["question_id"], db=task["db_id"], intent=intent, client_s=round(dt, 4), error=err)
    sql = None
    if resp:
        content = resp["choices"][0]["message"].get("content") or ""
        u = resp.get("usage") or {}; m = resp.get("metrics") or {}
        rec.update(prompt_tokens=u.get("prompt_tokens"), output_tokens=u.get("completion_tokens"),
                   cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                   queue_ms=m.get("queue_time_ms"), prefill_ms=m.get("time_to_first_token_ms"),
                   decode_ms=m.get("generation_time_ms"), content=content[:4000])
        mm = TAGGED_SQL.findall(content) or tools.SQL_BLOCK.findall(content)
        if mm:
            sql = mm[-1].strip().strip("`").strip()
    rec["sql"] = sql
    return sql, rec, dt


def make_call(A, orig_call):
    def call(db_path, name, args):
        if name != "write_sql":
            return orig_call(db_path, name, args)
        task = CUR_TASK.get()
        intent = str(args.get("intent", ""))
        sql, rec, dt = expert_sql(A, db_path, task, intent)
        if not sql:
            rec["exec_error"] = "expert_no_sql"
            with _lock:
                _log.append(rec)
            return ("Error (expert_no_sql): the expert returned no SQL. Rephrase the intent or write the SQL yourself.",
                    dict(sql=None, runtime_s=dt, error="expert_no_sql", rows=0))
        text, info = orig_call(db_path, "execute_sql", {"sql": sql})
        rec["exec_error"] = info["error"]; rec["exec_s"] = info["runtime_s"]
        with _lock:
            _log.append(rec)
        info = dict(info, runtime_s=dt + info["runtime_s"])  # tool wall time = adapter + execution
        return f"Expert's SQL:\n{sql}\n\nResult:\n{text}", info
    return call


def fewshot_block(path):
    ex = json.load(open(path))
    parts = ["Examples of correct answers on OTHER databases (never reuse their tables or columns):"]
    for i, e in enumerate(ex, 1):
        parts.append(f"Example {i} (database {e['db_id']})\nQuestion: {e['question']}"
                     + (f"\nHint: {e['evidence']}" if e.get("evidence") else "")
                     + f"\nTables used:\n{e['schema']}\nFinal answer:\n```sql\n{e['sql']}\n```")
    return "\n\n" + "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["a", "b", "d"])
    ap.add_argument("--fewshot", default=os.path.join(HERE, "fewshot.json"))
    ap.add_argument("--expert-model", default="expert")
    ap.add_argument("--expert-max-tokens", type=int, default=1024)
    A, rest = ap.parse_known_args()
    rb = argparse.ArgumentParser(add_help=False)
    for k in ("--url", "--brief", "--out"):
        rb.add_argument(k)
    ra, _ = rb.parse_known_args(rest)
    A.url = ra.url or "http://127.0.0.1:8000"; A.brief = ra.brief or "none"; out = ra.out
    os.makedirs(out, exist_ok=True)
    commit = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    agent_commit = subprocess.run(["git", "-C", HERE, "log", "-1", "--format=%H", "--", AGENT],
                                  capture_output=True, text=True).stdout.strip()
    json.dump(dict(arm=A.arm, fewshot=A.fewshot if A.arm == "b" else None, expert_model=A.expert_model,
                   expert_max_tokens=A.expert_max_tokens, repo_commit=commit, agent_commit=agent_commit, argv=rest),
              open(os.path.join(out, "expert_config.json"), "w"), indent=1)

    if A.arm == "b":
        run_bird.SYSTEM = run_bird.SYSTEM + fewshot_block(A.fewshot).replace("{", "{{").replace("}", "}}")
    if A.arm == "d":
        run_bird.SYSTEM = run_bird.SYSTEM + D_SUFFIX
        tools.TOOL_SPECS = tools.TOOL_SPECS + [WRITE_SQL_SPEC]
        tools.call = make_call(A, tools.call)
    orig_task = run_bird.run_task

    async def run_task(http, a, task, *rest_):
        CUR_TASK.set(task)  # copied into asyncio.to_thread workers, so tools.call sees it
        return await orig_task(http, a, task, *rest_)
    run_bird.run_task = run_task

    sys.argv = [sys.argv[0]] + rest
    asyncio.run(run_bird.main())
    if A.arm == "d":
        with open(os.path.join(out, "adapter_calls.jsonl"), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in _log)
        print(f"adapter calls: {len(_log)}", flush=True)


if __name__ == "__main__":
    main()
