"""Mock vLLM OpenAI server for login-node tests of the gateway and load generator (no GPU).

    python harness/gateway/mock_vllm.py --port 8100 [--delay 0.2] [--tool-turns 2] [--fcfs]

/v1/chat/completions: the first --tool-turns replies are tool calls (list_tables, then execute_sql), then a
final reply with a ```sql``` block (or at once when tool_choice == "none"). Each reply sleeps --delay s.
--fcfs rejects bodies with a "priority" field (400), like vLLM without --scheduling-policy priority.
/metrics: Prometheus text with num_requests_running/waiting, kv usage and prefix-cache counters.
/mock/log: JSON list of {t, priority, task_id, db, n_msgs} for each request received. /health.
"""
import argparse, asyncio, json, time

from aiohttp import web

STATE = dict(running=0, queries=0, hits=0, log=[])


async def chat(req):
    a = req.app["a"]
    body = await req.json()
    STATE["log"].append(dict(t=time.time(), priority=body.get("priority"), task_id=req.headers.get("x-task-id"),
                             db=req.headers.get("x-db"), n_msgs=len(body["messages"])))
    if a.fcfs and "priority" in body:
        return web.json_response({"error": "priority set but scheduling policy is fcfs"}, status=400)
    STATE["running"] += 1
    try:
        await asyncio.sleep(a.delay)
    finally:
        STATE["running"] -= 1
    n_asst = sum(m["role"] == "assistant" for m in body["messages"])
    STATE["queries"] += 100; STATE["hits"] += 80
    if body.get("tool_choice") == "none" or n_asst >= a.tool_turns:
        msg = {"role": "assistant", "content": "Final:\n```sql\nSELECT COUNT(*) FROM sqlite_master\n```"}
    else:
        call = ({"name": "list_tables", "arguments": "{}"} if n_asst == 0 else
                {"name": "execute_sql", "arguments": json.dumps({"sql": "SELECT 1"})})
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n_asst}", "type": "function",
                                                                   "function": call}]}
    return web.json_response({"id": "x", "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                              "usage": {"prompt_tokens": 500, "completion_tokens": 20,
                                        "prompt_tokens_details": {"cached_tokens": 400}},
                              "metrics": {"queue_time_ms": 1.0, "time_to_first_token_ms": 5.0,
                                          "generation_time_ms": a.delay * 1000}})


async def metrics(req):
    txt = (f'# HELP x\nvllm:num_requests_running{{model_name="m"}} {STATE["running"]}\n'
           f'vllm:num_requests_waiting{{model_name="m"}} 0\nvllm:kv_cache_usage_perc{{model_name="m"}} 0.1\n'
           f'vllm:prefix_cache_queries_total{{model_name="m"}} {STATE["queries"]}\n'
           f'vllm:prefix_cache_hits_total{{model_name="m"}} {STATE["hits"]}\n'
           f'vllm:num_preemptions_total{{model_name="m"}} 0\n')
    return web.Response(text=txt)


async def log(req):
    return web.json_response(STATE["log"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--tool-turns", type=int, default=2)
    ap.add_argument("--fcfs", action="store_true")
    a = ap.parse_args()
    app = web.Application()
    app["a"] = a
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_get("/metrics", metrics)
    app.router.add_get("/mock/log", log)
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    web.run_app(app, host="127.0.0.1", port=a.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
