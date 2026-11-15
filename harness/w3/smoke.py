"""Phase 0 (g) smoke test (PLAN 2j): the ported agent (agent-32b-v1 candidate) on Qwen3-32B TP=4, W3.

Run inside slurm/node_serve.sbatch (VLLM_URL, OUT set):
  sbatch --time=00:45:00 --job-name=n32_smoke slurm/node_serve.sbatch \
      python -u harness/w3/smoke.py --url '$VLLM_URL' --out '$OUT/smoke' --n 20 --concurrency 4

1. Tool-call probe: one chat request with the agent's tools and enable_thinking=False; checks that vLLM's hermes
   parser returns structured tool_calls (not "<tool_call>" text in content) and that no "<think>" text appears.
2. The agent (harness/agent_duckdb/run_w.py from the working tree, or --agent-dir) on the first N tasks of the W3
   stream at concurrency C, with the per-bench compact briefs.
3. Summary -> OUT/smoke_summary.json; PASS iff 0 tasks end without SQL and the probe parsed a tool call.
Exit 0 on PASS, 4 on FAIL.
"""
import argparse, json, os, statistics as st, subprocess, sys, time, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DATA = os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv")


def probe(url, model, agent_dir):
    sys.path.insert(0, agent_dir)
    import tools_duckdb as tools
    body = {"model": model, "temperature": 0.0, "max_tokens": 256, "tools": tools.TOOL_SPECS, "tool_choice": "auto",
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": "You are a careful data analyst answering a question about a "
                          "DuckDB database. Use the tools to inspect the database."},
                         {"role": "user", "content": "Which tables does the database have? Use a tool."}]}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.monotonic()
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    msg = r["choices"][0]["message"]
    content = msg.get("content") or ""
    calls = msg.get("tool_calls") or []
    return dict(latency_s=round(time.monotonic() - t, 3), tool_calls=[c["function"] for c in calls],
                content=content[:300], finish_reason=r["choices"][0].get("finish_reason"),
                usage=r.get("usage"), parsed_ok=bool(calls) and "<tool_call>" not in content,
                think_text="<think>" in content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-32B"))
    ap.add_argument("--stream", default=os.path.join(DATA, "w3", "streams", "w3_mix_s0.jsonl"))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--agent-dir", default=os.path.join(REPO, "harness", "agent_duckdb"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pr = probe(a.url, a.model, a.agent_dir)
    print("probe:", json.dumps(pr), flush=True)
    bmap = f"tpch={DATA}/w3/brief_tpch_compact.txt,tpcds={DATA}/w3/brief_tpcds_compact.txt"
    cmd = [sys.executable, "-u", os.path.join(a.agent_dir, "run_w.py"), "--url", a.url, "--model", a.model,
           "--stream", a.stream, "--n", str(a.n), "--concurrency", str(a.concurrency), "--brief-map", bmap,
           "--out", a.out]
    print("agent:", " ".join(cmd), flush=True)
    t = time.monotonic()
    rc = subprocess.call(cmd)
    wall = time.monotonic() - t
    tasks = [json.loads(l) for l in open(os.path.join(a.out, "tasks.jsonl"))]
    turns = [json.loads(l) for l in open(os.path.join(a.out, "turns.jsonl"))]
    no_sql = [r["qid"] for r in tasks if not r.get("pred_sql")]
    ts = sorted(r["task_s"] for r in tasks)
    dec = [r["output_tokens"] / (r["decode_ms"] / 1000) for r in turns
           if r.get("decode_ms") and r.get("output_tokens", 0) > 8]
    summ = dict(agent_rc=rc, wall_s=round(wall, 1), n=len(tasks), no_sql=len(no_sql), no_sql_qids=no_sql,
                accuracy=round(sum(r["correct"] for r in tasks) / max(1, len(tasks)), 3),
                accuracy_by_bench={b: f"{sum(r['correct'] for r in tasks if r.get('bench') == b)}/"
                                      f"{sum(1 for r in tasks if r.get('bench') == b)}" for b in ("tpch", "tpcds")},
                status=dict(__import__("collections").Counter(r["status"] for r in tasks)),
                turns_mean=round(st.mean(r["turns"] for r in tasks), 2),
                task_s_p50=ts[len(ts) // 2], task_s_max=ts[-1],
                llm_share=round(sum(r.get("llm_s", 0) for r in tasks) / max(1e-9, sum(r["task_s"] for r in tasks)), 3),
                db_share=round(sum(r["db_s"] for r in tasks) / max(1e-9, sum(r["task_s"] for r in tasks)), 3),
                decode_tok_per_s_per_seq_p50=round(sorted(dec)[len(dec) // 2], 1) if dec else None,
                llm_errors=sum(1 for r in turns if r.get("error")), probe=pr)
    summ["PASS"] = summ["no_sql"] == 0 and pr["parsed_ok"] and rc == 0
    json.dump(summ, open(os.path.join(a.out, "smoke_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1), flush=True)
    print("SMOKE", "PASS" if summ["PASS"] else "FAIL", flush=True)
    sys.exit(0 if summ["PASS"] else 4)


if __name__ == "__main__":
    main()
