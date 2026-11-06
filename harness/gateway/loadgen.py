"""Open-loop Poisson load generator that runs the FROZEN agent's own run_task (PLAN 2f, Phases 2-3).

    python harness/gateway/loadgen.py --agent-dir DIR_WITH_FROZEN_run_bird.py --url http://127.0.0.1:9000 \
        --bird $DBKV_DATA/bird/dev_20240627 --rate 6 --warmup 120 --measure 480 --drain-cap 600 --seed 0 \
        [--briefs $DBKV_DATA/briefs/briefs_compact.jsonl --brief-name compact] \
        --metrics-urls http://127.0.0.1:8000[,...] [--gateway] --out CELLDIR

Arrivals: exponential inter-arrival times at --rate tasks/min from t=0 to warmup+measure (numpy seed
--seed); questions drawn uniformly with replacement from all of BIRD dev (all 11 DBs) with seed --seed+1.
Each task runs run_task(http, a, task, sem, turns, tasks) from the exported frozen run_bird.py, with:
  * a per-task aiohttp session whose default headers are x-task-id, x-task-start (arrival, epoch s), x-db;
  * a no-op semaphore and the args namespace run_bird.main() builds (briefs dict keyed by str(qid),
    brief = brief_name or "file"; otherwise brief "none" and briefs "").
The session is wrapped (no change to the agent) to time the first request and to detect the agent's last
LLM reply exactly as run_task decides it (HTTP error, or no tool call with a ```sql``` block, or the
tool_choice="none" last turn). That instant is the task's done time; with --gateway, POST /gw/task_end goes
out then, so grading (gold/pred SQL, done by run_task after the loop) never holds an admission slot.
Outputs in --out: tasks.jsonl / turns.jsonl (run_task's records + task_id, arrival, measured flag, e2e_s,
admission wait), arrivals.jsonl (schedule), metrics_<i>.jsonl (vLLM /metrics every 1 s per backend),
config.json, summary.json (via summarize.py).
"""
import argparse, asyncio, importlib.util, json, os, sys, time

import aiohttp
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
METRIC_KEYS = ("vllm:num_requests_running", "vllm:num_requests_waiting", "vllm:kv_cache_usage_perc",
               "vllm:prefix_cache_queries", "vllm:prefix_cache_hits", "vllm:num_preemptions")


def load_frozen(agent_dir):
    path = os.path.join(agent_dir, "run_bird.py")
    spec = importlib.util.spec_from_file_location("run_bird_frozen", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # inserts agent_dir on sys.path and imports its tools.py
    tf = os.path.abspath(mod.tools.__file__)
    if os.path.dirname(tf) != os.path.abspath(agent_dir):
        raise SystemExit(f"frozen agent imported the wrong tools module: {tf}")
    return mod


def schedule(rate_per_min, horizon_s, n_dev, seed):
    """Poisson arrival offsets (s) in [0, horizon) and dev indices; reproducible from seed."""
    rng = np.random.default_rng(seed)
    t, out = 0.0, []
    while True:
        t += rng.exponential(60.0 / rate_per_min)
        if t >= horizon_s:
            break
        out.append(t)
    idx = np.random.default_rng(seed + 1).integers(0, n_dev, size=len(out))
    return out, [int(i) for i in idx]


class _Resp:
    def __init__(self, r, on_text):
        self._r, self._on = r, on_text
        self.status = r.status

    async def text(self):
        txt = await self._r.text()
        self._on(self._r.status, txt)
        return txt


class _Ctx:
    def __init__(self, cm, body, owner):
        self._cm, self._body, self._o = cm, body, owner

    async def __aenter__(self):
        o = self._o
        if o.t_first_send is None:
            o.t_first_send = time.monotonic()
        r = await self._cm.__aenter__()
        return _Resp(r, lambda st, txt: o.on_reply(self._body, st, txt))

    async def __aexit__(self, *exc):
        return await self._cm.__aexit__(*exc)


class TaskHTTP:
    """What run_task sees as `http`: forwards .post to the per-task session and watches the replies."""

    def __init__(self, session, final_sql, on_done):
        self.s, self.final_sql, self.on_done = session, final_sql, on_done
        self.t_first_send = self.t_first_reply = self.t_done = None

    def post(self, url, json=None, **kw):
        return _Ctx(self.s.post(url, json=json, **kw), json, self)

    def on_reply(self, body, status, txt):
        now = time.monotonic()
        if self.t_first_reply is None:
            self.t_first_reply = now
        if self.t_done is not None:
            return
        done = status != 200 or (body or {}).get("tool_choice") == "none"
        if not done:
            try:
                msg = json.loads(txt)["choices"][0]["message"]
                done = not msg.get("tool_calls") and bool(self.final_sql(msg.get("content")))
            except Exception:  # noqa: BLE001  (run_task itself would raise here; count as done)
                done = True
        if done:
            self.t_done = now
            self.on_done()


class NoSem:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def sampler(urls, out_dir, stop):
    files = [open(os.path.join(out_dir, f"metrics_{i}.jsonl"), "a") for i in range(len(urls))]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s:
        while not stop.is_set():
            t_next = time.monotonic() + 1.0
            for i, u in enumerate(urls):
                d = {"t": time.time(), "backend": u}
                try:
                    async with s.get(u + "/metrics") as r:
                        txt = await r.text()
                    for line in txt.splitlines():
                        if not line or line[0] == "#":
                            continue
                        name = line.split("{")[0].split(" ")[0]
                        for k in METRIC_KEYS:
                            if name in (k, k + "_total"):
                                d[k] = d.get(k, 0.0) + float(line.rsplit(" ", 1)[1])
                except Exception as e:  # noqa: BLE001
                    d["error"] = type(e).__name__
                files[i].write(json.dumps(d) + "\n"); files[i].flush()
            await asyncio.sleep(max(0.0, t_next - time.monotonic()))
    for f in files:
        f.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", required=True, help="dir with the exported frozen run_bird.py + tools.py")
    ap.add_argument("--url", required=True, help="gateway (or, for direct mode, vLLM) base URL")
    ap.add_argument("--gateway", action="store_true", help="POST /gw/task_end to --url when a task finishes")
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--bird", required=True)
    ap.add_argument("--rate", type=float, required=True, help="tasks per minute")
    ap.add_argument("--warmup", type=float, default=120.0)
    ap.add_argument("--measure", type=float, default=480.0)
    ap.add_argument("--drain-cap", type=float, default=600.0, help="max s after the last arrival")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--briefs", default="")
    ap.add_argument("--brief-name", default="")
    ap.add_argument("--max-turns", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--metrics-urls", default="", help="comma-separated vLLM base URLs to sample")
    ap.add_argument("--label", default="")
    ap.add_argument("--dry-run", action="store_true", help="print the schedule and exit")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dev = json.load(open(os.path.join(a.bird, "dev.json")))
    horizon = a.warmup + a.measure
    offs, idx = schedule(a.rate, horizon, len(dev), a.seed)
    if a.dry_run:
        print(json.dumps(dict(n=len(offs), first=[round(x, 3) for x in offs[:5]], qids=[dev[i]["question_id"] for i in idx[:5]])))
        return

    rb = load_frozen(a.agent_dir)
    # Reproduce run_bird.main()'s args namespace.
    ns = argparse.Namespace(url=a.url.rstrip("/"), model=a.model, bird=a.bird, n=len(offs), seed=a.seed,
                            concurrency=0, brief="none", briefs="", brief_name=a.brief_name,
                            max_turns=a.max_turns, max_tokens=a.max_tokens, out=a.out)
    if a.briefs:
        ns.briefs = {str(json.loads(l)["qid"]): json.loads(l) for l in open(a.briefs)}
        ns.brief = a.brief_name or "file"
    cfg = dict(vars(a), agent_file=os.path.abspath(rb.__file__), tools_file=os.path.abspath(rb.tools.__file__),
               n_arrivals=len(offs), agent_brief=ns.brief)
    with open(os.path.join(a.out, "arrivals.jsonl"), "w") as f:
        for k, (o, i) in enumerate(zip(offs, idx)):
            f.write(json.dumps(dict(task_id=f"t{k:05d}", offset_s=round(o, 4), qid=dev[i]["question_id"],
                                    db=dev[i]["db_id"])) + "\n")

    turns_f = open(os.path.join(a.out, "turns.jsonl"), "w")
    tasks_f = open(os.path.join(a.out, "tasks.jsonl"), "w")
    ctl = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    stop = asyncio.Event()
    murls = [u.rstrip("/") for u in a.metrics_urls.split(",") if u]
    samp = asyncio.create_task(sampler(murls, a.out, stop)) if murls else None
    done_count = [0]

    t0_mono = time.monotonic()
    t0_epoch = time.time()
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
            headers={"x-task-id": tid, "x-task-start": f"{arr_epoch:.6f}", "x-db": task["db_id"]},
            connector=aiohttp.TCPConnector(limit=0, force_close=True),
            timeout=aiohttp.ClientTimeout(total=None, sock_read=900))
        http = TaskHTTP(sess, rb.final_sql, lambda: end_tasks.append(asyncio.create_task(send_end())))
        my_turns, my_tasks = [], []
        status_override = None
        try:
            await rb.run_task(http, ns, task, NoSem(), my_turns, my_tasks)
        except asyncio.CancelledError:
            status_override = "drain_cancelled"
        except Exception as e:  # noqa: BLE001
            status_override = "exception:" + type(e).__name__
            print(f"{tid} exception {e!r}", flush=True)
        finally:
            await sess.close()
        t_ret = time.monotonic()
        if http.t_done is None:  # no detected last reply (exception/cancel): end now
            http.t_done = t_ret
            end_tasks.append(asyncio.create_task(send_end()))
        await asyncio.gather(*end_tasks)
        rec = my_tasks[0] if my_tasks else dict(qid=task["question_id"], db=task["db_id"],
                                                difficulty=task.get("difficulty"), status=status_override,
                                                correct=False)
        if status_override and my_tasks:
            rec["status"] = status_override
        rec.update(task_id=tid, arrival_s=round(arr_mono - t0_mono, 4), arrival_epoch=round(arr_epoch, 4),
                   measured=bool(a.warmup <= off < horizon), rate=a.rate,
                   e2e_s=round(http.t_done - arr_mono, 4),
                   done_s=round(http.t_done - t0_mono, 4),
                   first_reply_s=None if http.t_first_reply is None else round(http.t_first_reply - arr_mono, 4),
                   start_lag_s=None if http.t_first_send is None else round(http.t_first_send - arr_mono, 4),
                   grade_s=round(t_ret - http.t_done, 4),
                   gw_queue_ms=end_info.get("queue_ms"), gw_backend=end_info.get("backend"),
                   gw_n_req=end_info.get("n_req"))
        for r in my_turns:
            r["task_id"] = tid
            turns_f.write(json.dumps(r) + "\n")
        tasks_f.write(json.dumps(rec) + "\n")
        turns_f.flush(); tasks_f.flush()
        done_count[0] += 1

    print(f"{len(offs)} arrivals over {horizon:.0f} s at {a.rate}/min (warmup {a.warmup:.0f}, measure "
          f"{a.measure:.0f}); agent {rb.__file__} brief={ns.brief}", flush=True)
    jobs = [asyncio.create_task(one(k, o, dev[i])) for k, (o, i) in enumerate(zip(offs, idx))]
    await asyncio.sleep(max(0.0, t0_mono + horizon - time.monotonic()))
    print(f"arrivals done at {time.monotonic() - t0_mono:.0f} s; {done_count[0]} finished; draining "
          f"(cap {a.drain_cap:.0f} s)", flush=True)
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
    print(f"done at {time.monotonic() - t0_mono:.0f} s", flush=True)
    sys.path.insert(0, HERE)
    import summarize
    s = summarize.summarize_cell(a.out)
    json.dump(s, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
    print(summarize.one_line(s), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
