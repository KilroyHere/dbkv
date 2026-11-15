"""Open-loop Poisson load generator for W3 (PLAN 2j, Phase 1 on): runs the exported agent-32b-v1 run_task.

    python harness/w3/loadgen_w3.py --agent-dir DIR_WITH_run_w.py+tools_duckdb.py --url URL \
        --stream $DBKV_DATA/w3/streams/w3_mix_s0.jsonl --rate 10 --warmup 120 --measure 480 --drain-cap 600 \
        --seed 0 --metrics-urls http://127.0.0.1:PORT [--gateway] --out CELLDIR

Same design as harness/gateway/loadgen.py (the 8B / BIRD load generator; its schedule, TaskHTTP, NoSem and sampler
are reused unchanged): Poisson arrivals at --rate tasks/min over warmup+measure (numpy seed --seed); arrival k runs
stream task k (the stream is already a fixed-seed random draw; it must hold at least as many tasks as arrivals).
Each task gets headers x-task-id, x-task-start (arrival epoch), x-db (tenant); with --gateway, POST /gw/task_end
when the agent's last LLM reply arrives, so grading never holds an admission slot.
DB tool calls run in a fixed thread pool of --db-workers threads (default 32) so DB queueing is the same on every
node; each task records db_s (query time), db_queue_s (pool wait + connect) and llm_s (chat time).
Outputs in --out: tasks.jsonl, turns.jsonl, arrivals.jsonl, metrics_<i>.jsonl (1 s), config.json, summary.json.
"""
import argparse, asyncio, concurrent.futures, importlib.util, json, os, sys, time

import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gateway"))
import loadgen as L  # noqa: E402  (schedule, TaskHTTP, NoSem, sampler)


def load_agent(agent_dir):
    spec = importlib.util.spec_from_file_location("run_w_frozen", os.path.join(agent_dir, "run_w.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tf = os.path.abspath(mod.tools.__file__)
    if os.path.dirname(tf) != os.path.abspath(agent_dir):
        raise SystemExit(f"agent imported the wrong tools module: {tf}")
    return mod


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--gateway", action="store_true")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-32B"))
    ap.add_argument("--stream", required=True)
    ap.add_argument("--brief-map", default="")
    ap.add_argument("--rate", type=float, required=True, help="tasks per minute")
    ap.add_argument("--warmup", type=float, default=120.0)
    ap.add_argument("--measure", type=float, default=480.0)
    ap.add_argument("--drain-cap", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--db-workers", type=int, default=32)
    ap.add_argument("--metrics-urls", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stream = [json.loads(l) for l in open(a.stream) if l.strip()]
    horizon = a.warmup + a.measure
    offs, _ = L.schedule(a.rate, horizon, len(stream), a.seed)
    if len(offs) > len(stream):
        raise SystemExit(f"{len(offs)} arrivals > {len(stream)} stream tasks")
    if a.dry_run:
        print(json.dumps(dict(n=len(offs), first=[round(x, 3) for x in offs[:5]], qids=[t["qid"] for t in stream[:5]])))
        return
    asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(a.db_workers))
    rw = load_agent(a.agent_dir)
    ns = argparse.Namespace(url=a.url.rstrip("/"), model=a.model, concurrency=0, max_turns=a.max_turns,
                            max_tokens=a.max_tokens, brief="none", brief_text="", brief_name="none", brief_by_bench={})
    for kv in filter(None, a.brief_map.split(",")):
        b, f = kv.split("=", 1)
        ns.brief_by_bench[b] = open(f).read().strip()
    if ns.brief_by_bench:
        ns.brief_name = "map:" + ",".join(sorted(ns.brief_by_bench))
    cfg = dict(vars(a), agent_file=os.path.abspath(rw.__file__), n_arrivals=len(offs), brief_name=ns.brief_name)
    with open(os.path.join(a.out, "arrivals.jsonl"), "w") as f:
        for k, o in enumerate(offs):
            t = stream[k]
            f.write(json.dumps(dict(task_id=f"t{k:05d}", offset_s=round(o, 4), qid=t["qid"], db=t["tenant"],
                                    template_id=t["template_id"])) + "\n")
    turns_f = open(os.path.join(a.out, "turns.jsonl"), "w")
    tasks_f = open(os.path.join(a.out, "tasks.jsonl"), "w")
    ctl = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    stop = asyncio.Event()
    murls = [u.rstrip("/") for u in a.metrics_urls.split(",") if u]
    samp = asyncio.create_task(L.sampler(murls, a.out, stop)) if murls else None
    done = [0]
    t0_mono, t0_epoch = time.monotonic(), time.time()
    cfg.update(t0_epoch=t0_epoch, window=[t0_epoch + a.warmup, t0_epoch + horizon])
    json.dump(cfg, open(os.path.join(a.out, "config.json"), "w"), indent=1)

    async def one(k, off, task):
        tid = f"t{k:05d}"
        await asyncio.sleep(max(0.0, t0_mono + off - time.monotonic()))
        arr_mono = time.monotonic()
        arr_epoch = t0_epoch + (arr_mono - t0_mono)
        end_info = {}

        async def send_end():
            if a.gateway:
                try:
                    async with ctl.post(ns.url + "/gw/task_end", json={"task_id": tid}) as r:
                        end_info.update(await r.json())
                except Exception as e:  # noqa: BLE001
                    end_info["error"] = repr(e)

        end_tasks = []
        sess = aiohttp.ClientSession(
            headers={"x-task-id": tid, "x-task-start": f"{arr_epoch:.6f}", "x-db": task["tenant"]},
            connector=aiohttp.TCPConnector(limit=0, force_close=True),
            timeout=aiohttp.ClientTimeout(total=None, sock_read=1800))
        http = L.TaskHTTP(sess, rw.final_sql, lambda: end_tasks.append(asyncio.create_task(send_end())))
        my_turns, my_tasks, override = [], [], None
        try:
            await rw.run_task(http, ns, task, L.NoSem(), my_turns, my_tasks)
        except asyncio.CancelledError:
            override = "drain_cancelled"
        except Exception as e:  # noqa: BLE001
            override = "exception:" + type(e).__name__
            print(f"{tid} exception {e!r}", flush=True)
        finally:
            await sess.close()
        t_ret = time.monotonic()
        if http.t_done is None:
            http.t_done = t_ret
            end_tasks.append(asyncio.create_task(send_end()))
        await asyncio.gather(*end_tasks)
        rec = my_tasks[0] if my_tasks else dict(qid=task["qid"], db=task["tenant"], tenant=task["tenant"],
                                                bench=task.get("bench"), template_id=task["template_id"],
                                                status=override, correct=False)
        if override and my_tasks:
            rec["status"] = override
        rec.update(task_id=tid, arrival_s=round(arr_mono - t0_mono, 4), arrival_epoch=round(arr_epoch, 4),
                   measured=bool(a.warmup <= off < horizon), rate=a.rate, e2e_s=round(http.t_done - arr_mono, 4),
                   done_s=round(http.t_done - t0_mono, 4),
                   first_reply_s=None if http.t_first_reply is None else round(http.t_first_reply - arr_mono, 4),
                   start_lag_s=None if http.t_first_send is None else round(http.t_first_send - arr_mono, 4),
                   grade_s=round(t_ret - http.t_done, 4), gw_queue_ms=end_info.get("queue_ms"),
                   gw_backend=end_info.get("backend"), gw_n_req=end_info.get("n_req"))
        for r in my_turns:
            r["task_id"] = tid
            turns_f.write(json.dumps(r) + "\n")
        tasks_f.write(json.dumps(rec) + "\n")
        turns_f.flush(); tasks_f.flush()
        done[0] += 1

    print(f"{len(offs)} arrivals over {horizon:.0f} s at {a.rate}/min; agent {rw.__file__} brief={ns.brief_name}",
          flush=True)
    jobs = [asyncio.create_task(one(k, o, stream[k])) for k, o in enumerate(offs)]
    await asyncio.sleep(max(0.0, t0_mono + horizon - time.monotonic()))
    print(f"arrivals done; {done[0]} finished; draining (cap {a.drain_cap:.0f} s)", flush=True)
    _, pending = await asyncio.wait(jobs, timeout=a.drain_cap)
    if pending:
        print(f"drain cap hit: cancelling {len(pending)} tasks", flush=True)
        for j in pending:
            j.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    stop.set()
    if samp:
        await samp
    await ctl.close()
    turns_f.close(); tasks_f.close()
    import summarize
    s = summarize.summarize_cell(a.out)
    json.dump(s, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    print(summarize.one_line(s), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
