"""Login-node tests for option B (goodput gateway): no GPU, a few seconds of CPU.

    python harness/gateway/test_goodput.py [--runs $DBKV_DATA/runs/p1] [--table T.json]

1. LAST / NUDGE in goodput.py are identical to the frozen agent's (harness/agent_duckdb/run_w.py).
2. Feature extraction on real Phase 1 turns: every task's history is rebuilt as the chat `messages` the agent
   sends (assistant tool calls, tool results with the tools' error texts, nudges), and the gateway's
   features_from_messages must equal the fitter's StateAcc state at every turn. Also the time per request.
3. Priority ordering: value_priority is monotone; worse states (timeouts, errors, late turns, runaway output)
   get lower value than a fresh state of the same tenant; the table's per-turn P(success) falls with turn.
4. Force-final rewrite: force_final_body unit checks; then mock vLLM + gateway subprocesses:
   (a) flags off: body passed through unchanged; (b) --turn-limit 3: turn-3 request rewritten, turn-2 not;
   (c) --goodput --force-final 0 with admission 2 and one task queued: the low-value task's request is
       rewritten (LAST, tool_choice none, priority 0) and logged as ev force_final, the other task's is not;
       no rewrite while nothing waits; (d) the frozen agent (run_w.run_task) on a tiny DuckDB file through the
       gateway with --turn-limit 2 ends "answered" at turn 2 (3 turns without the limit).
Without --table, a table is fitted from --runs into a temp dir (excluding the 140/180 cells).
"""
import argparse, ast, asyncio, importlib.util, json, os, random, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import goodput as GP  # noqa: E402
import fit_goodput as F  # noqa: E402

FAILS = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


# ---------- 1 ----------
def test_texts():
    print("1. agent texts")
    tree = ast.parse(open(os.path.join(REPO, "harness", "agent_duckdb", "run_w.py")).read())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    check(consts.get("LAST") == GP.LAST, "goodput.LAST == run_w.LAST")
    check(consts.get("NUDGE") == GP.NUDGE, "goodput.NUDGE == run_w.NUDGE")


# ---------- 2 ----------
def tool_text(name, err, rng):
    if err is None:
        return "col_a | col_b\n1 | 2" if name == "execute_sql" else "c_custkey BIGINT PRIMARY KEY"
    if err == "no_such_table" and name == "describe_table" and rng.random() < 0.5:
        return "Error: no such table foo"
    if err == "timeout":
        return "Error (timeout): INTERRUPT Error: Interrupted!"
    return f"Error ({err}): Binder Error: something went wrong\nColumns of the tables in your query: x(a, b)"


def messages_from_rows(task, rng):
    """The agent's message list before each turn, rebuilt from turns.jsonl rows (run_w.run_task's loop)."""
    msgs = [{"role": "system", "content": "SYSTEM + brief"}, {"role": "user", "content": "question"}]
    before = []
    for r in task["turns"]:
        before.append(list(msgs))
        tools = r.get("tools") or []
        if not tools:
            msgs.append({"role": "assistant", "content": "I will now run the query." if r.get("nudged") else "```sql\nSELECT 1\n```"})
            if r.get("nudged"):
                msgs.append({"role": "user", "content": GP.NUDGE})
            continue
        calls = [{"id": f"call_{r['turn']}_{i}", "type": "function",
                  "function": {"name": t["name"], "arguments": json.dumps({"sql": t.get("sql") or ""})}}
                 for i, t in enumerate(tools)]
        msgs.append({"role": "assistant", "content": "", "tool_calls": calls})
        for c, t in zip(calls, tools):
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": tool_text(t["name"], t.get("error"), rng)})
    return before


def test_features(runs):
    print("2. feature extraction on real Phase 1 turns")
    dirs = F.cell_dirs([runs])
    tasks = F.load_tasks(dirs, censored="include")
    check(len(tasks) > 1000, f"loaded {len(tasks)} tasks from {len(dirs)} cells")
    rng = random.Random(0)
    n_req = mism = 0
    worst = None
    for t in tasks:
        acc = GP.StateAcc(t["tenant"])
        befores = messages_from_rows(t, rng)
        for r, msgs in zip(t["turns"], befores):
            want = acc.state()
            got = GP.features_from_messages(msgs, t["tenant"], out_tokens=want["out_tok"])
            n_req += 1
            if got != want:
                mism += 1
                if mism <= 3:
                    print("   mismatch", t["qid"], r["turn"], got, want)
            acc.add_turn_row(r)
            if worst is None or want["n_timeout"] > worst[1]["n_timeout"]:
                worst = (t, want)
    check(mism == 0, f"messages == turns.jsonl state on all {n_req} requests ({mism} mismatches)")
    t, st = worst
    print(f"   most timeouts: {t['qid']} ({t['tenant']}, {os.path.basename(t['cell'])}) state at turn {st['turn']}: {st}")
    check(st["n_timeout"] >= 5, "a Phase 1 task with >= 5 SQL timeouts is seen as such (h18-like)")
    # runaway generation
    big = max(((t, sum(r.get("output_tokens") or 0 for r in t["turns"])) for t in tasks), key=lambda x: x[1])
    print(f"   most output: {big[0]['qid']} {big[1]} output tokens over {len(big[0]['turns'])} turns")
    # speed: the longest history
    longest = max(tasks, key=lambda t: len(t["turns"]))
    msgs = messages_from_rows(longest, rng)[-1]
    return tasks, msgs


def test_speed(table, msgs):
    T = GP.Table(table)
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        st = GP.features_from_messages(msgs, "tpcds_sf10", out_tokens=5000)
        GP.value_priority(T.lookup(st)["value"])
    us = (time.perf_counter() - t0) / n * 1e6
    check(us < 1000, f"features + lookup + priority on a {len(msgs)}-message history: {us:.0f} us per request")


# ---------- 3 ----------
def S(tenant, turn, **kw):
    d = dict(turn=turn, tenant=tenant, n_timeout=0, n_err=0, n_ok=0, since_ok=None, last="explore", nudges=0, out_tok=60 * turn)
    if turn == 1:
        d["last"] = "start"
    d.update(kw)
    return d


def test_priority(table):
    print("3. priority ordering")
    T = GP.Table(table)
    vals = [10 ** (-x / 10) for x in range(5, 80)]
    pr = [GP.value_priority(v) for v in vals]
    check(all(a < b for a, b in zip(pr, pr[1:])), "value_priority strictly increasing as value falls (0.1 decade steps)")
    TD = GP.Table(table, db_weight=50.0)  # work counts a DB second as 50 tokens
    for ten in ("tpch_sf10", "tpch_sf100", "tpcds_sf10"):
        fresh, fresh_d = T.lookup(S(ten, 3)), TD.lookup(S(ten, 3))
        rows = [("2 timeouts", S(ten, 4, n_timeout=2, last="timeout")),
                ("3 errors", S(ten, 4, n_err=3, last="err")),
                ("turn 10", S(ten, 10)),
                ("runaway 5k out", S(ten, 6, out_tok=5000, nudges=2, last="nudge"))]
        line = [f"fresh t3 p={fresh['p']:.3f} w={fresh['work']:.0f} db={fresh['db']:.0f}s prio={GP.value_priority(fresh['value'])}"]
        for name, st in rows:
            r, rd = T.lookup(st), TD.lookup(st)
            line.append(f"{name}: p={r['p']:.3f} w={r['work']:.0f} db={r['db']:.0f}s prio={GP.value_priority(r['value'])}"
                        f" (db_weight 50: {GP.value_priority(rd['value'])} vs {GP.value_priority(fresh_d['value'])})")
            check(r["p"] < fresh["p"], f"{ten}: {name} has lower P(success) than a fresh turn-3 state")
            if name == "2 timeouts":  # little LLM work is left after timeouts, but much DB time
                check(rd["value"] < fresh_d["value"], f"{ten}: {name} has lower value with db_weight 50")
            else:
                check(r["value"] < fresh["value"], f"{ten}: {name} has lower value than a fresh turn-3 state")
        print("   " + "\n     ".join(line))
    ps = [T.lookup(S("tpch_sf10", n))["p"] for n in (2, 8, 11, 14)]
    check(all(ps[0] > b for b in ps[1:]), f"tpch_sf10 P(success) at turn 2 above turns 8/11/14: {[round(p, 3) for p in ps]}")
    ok = T.lookup(S("tpch_sf10", 4, n_ok=1, since_ok=0, last="ok"))
    check(ok["work"] < T.lookup(S("tpch_sf10", 4))["work"], "after a good execute_sql the remaining work is smaller")


# ---------- 4 ----------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start(cmd, port):
    p = subprocess.Popen([sys.executable] + cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    import urllib.request
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    p.kill()
    raise RuntimeError(f"{cmd} did not start")


def base_msgs():
    return [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


def hist(kind, n_turns):
    """Messages before turn n_turns + 1: n_turns tool turns of one kind (timeout / ok / explore)."""
    m = base_msgs()
    for i in range(n_turns):
        name = "describe_table" if kind == "explore" else "execute_sql"
        m.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
                  "function": {"name": name, "arguments": "{}"}}]})
        txt = {"timeout": "Error (timeout): INTERRUPT Error: Interrupted!", "ok": "x\n1", "explore": "a INT"}[kind]
        m.append({"role": "tool", "tool_call_id": f"c{i}", "content": txt})
    return m


def body(msgs):
    return {"model": "m", "messages": msgs, "tools": [{"type": "function", "function": {"name": "execute_sql"}}],
            "tool_choice": "auto", "temperature": 0.0, "max_tokens": 64}


async def post(s, url, tid, db, b):
    async with s.post(url + "/v1/chat/completions", json=b,
                      headers={"x-task-id": tid, "x-task-start": f"{time.time():.6f}", "x-db": db}) as r:
        return r.status, await r.json()


async def mock_log(s, murl, since):
    async with s.get(murl + "/mock/log") as r:
        return (await r.json())[since:]


def gw_events(path):
    return [json.loads(l) for l in open(path) if '"ev"' in l]


async def run_gateway_tests(table_path, tmp):
    import aiohttp
    print("4. force-final rewrite (mock vLLM + gateway)")
    t = {"messages": base_msgs() + [{"role": "user", "content": GP.NUDGE}], "tool_choice": "auto", "tools": [1]}
    GP.force_final_body(t)
    check(t["messages"][-1] == {"role": "user", "content": GP.LAST} and t["tool_choice"] == "none" and t["tools"] == [1],
          "force_final_body appends LAST, sets tool_choice none, keeps tools")
    n = len(t["messages"]); GP.force_final_body(t)
    check(len(t["messages"]) == n, "force_final_body is idempotent")

    mport = free_port(); murl = f"http://127.0.0.1:{mport}"
    mock = start([os.path.join(HERE, "mock_vllm.py"), "--port", str(mport), "--delay", "0.3", "--tool-turns", "2"], mport)
    procs = [mock]
    try:
        async with aiohttp.ClientSession() as s:
            # (a) flags off
            gport = free_port(); gurl = f"http://127.0.0.1:{gport}"; glog = os.path.join(tmp, "gw_off.jsonl")
            g = start([os.path.join(HERE, "gateway.py"), "--port", str(gport), "--backends", murl, "--log", glog], gport)
            procs.append(g)
            k = len(await mock_log(s, murl, 0))
            await post(s, gurl, "off1", "tpch_sf10", body(hist("timeout", 5)))
            L = await mock_log(s, murl, k)
            check(L[0]["tool_choice"] == "auto" and L[0]["priority"] is None and L[0]["last_role"] == "tool",
                  "(a) flags off: request passed unchanged")
            g.terminate(); g.wait()

            # (b) turn limit
            gport = free_port(); gurl = f"http://127.0.0.1:{gport}"; glog = os.path.join(tmp, "gw_tl.jsonl")
            g = start([os.path.join(HERE, "gateway.py"), "--port", str(gport), "--backends", murl, "--turn-limit", "3",
                       "--priority", "--log", glog], gport)
            procs.append(g)
            k = len(await mock_log(s, murl, 0))
            await post(s, gurl, "tl2", "tpch_sf10", body(hist("explore", 1)))   # turn 2
            await post(s, gurl, "tl3", "tpch_sf10", body(hist("explore", 2)))   # turn 3
            L = await mock_log(s, murl, k)
            check(L[0]["tool_choice"] == "auto", "(b) --turn-limit 3: turn-2 request not rewritten")
            check(L[1]["tool_choice"] == "none" and L[1]["last_content"] == GP.LAST and L[1]["priority"] is not None,
                  "(b) --turn-limit 3: turn-3 request rewritten (LAST, tool_choice none), task-start priority kept")
            g.terminate(); g.wait()
            ev = [e for e in gw_events(glog) if e["ev"] == "force_final"]
            check(len(ev) == 1 and ev[0]["reason"] == "turn_limit" and ev[0]["turn"] == 3, "(b) one force_final event, reason turn_limit")

            # (c) goodput + force-final under overload
            gport = free_port(); gurl = f"http://127.0.0.1:{gport}"; glog = os.path.join(tmp, "gw_gp.jsonl")
            g = start([os.path.join(HERE, "gateway.py"), "--port", str(gport), "--backends", murl, "--admission", "2",
                       "--goodput", table_path, "--force-final", "0", "--force-frac", "0.5", "--log", glog], gport)
            procs.append(g)
            k = len(await mock_log(s, murl, 0))
            await asyncio.gather(post(s, gurl, "A", "tpch_sf100", body(base_msgs())),
                                 post(s, gurl, "B", "tpch_sf10", body(base_msgs())))
            # nothing waits yet: no rewrite even for a bad state
            await post(s, gurl, "A", "tpch_sf100", body(hist("timeout", 1)))
            C = asyncio.create_task(post(s, gurl, "C", "tpcds_sf10", body(base_msgs())))  # queued (K = 2)
            await asyncio.sleep(0.3)
            async with s.get(gurl + "/gw/stats") as r:
                stt = await r.json()
            check(stt["waiting"] == 1 and stt["active"] == 2, f"(c) admission 2: A, B active, C waiting ({stt['active']}/{stt['waiting']})")
            rA, rB = await asyncio.gather(post(s, gurl, "A", "tpch_sf100", body(hist("timeout", 3))),
                                          post(s, gurl, "B", "tpch_sf10", body(hist("ok", 2))))
            check(rA[0] == 200 and not rA[1]["choices"][0]["message"].get("tool_calls"), "(c) A's forced reply is a final answer")
            async with s.post(gurl + "/gw/task_end", json={"task_id": "A"}) as r:
                await r.json()
            await C
            L = await mock_log(s, murl, k)
            by = {}
            for x in L:
                by.setdefault(x["task_id"], []).append(x)
            check(all(x["tool_choice"] == "auto" for x in by["A"][:2]), "(c) A not rewritten while the queue was empty")
            a3, b3 = by["A"][2], by["B"][1]
            check(a3["tool_choice"] == "none" and a3["last_content"] == GP.LAST and a3["priority"] == 0,
                  "(c) A (3 timeouts, tpch_sf100) rewritten under overload: LAST, tool_choice none, priority 0")
            check(b3["tool_choice"] == "auto" and b3["priority"] > 0, f"(c) B (good execute_sql) not rewritten, priority {b3['priority']}")
            check(by["B"][0]["priority"] < by["A"][0]["priority"],
                  f"(c) turn-1 priorities by tenant value: tpch_sf10 {by['B'][0]['priority']} < tpch_sf100 {by['A'][0]['priority']}")
            check(len(by.get("C", [])) == 1, "(c) C admitted after A's task_end")
            g.terminate(); g.wait()
            ev = [e for e in gw_events(glog) if e["ev"] == "force_final"]
            check(len(ev) == 1 and ev[0]["task_id"] == "A" and ev[0]["reason"] == "goodput" and ev[0]["waiting"] == 1,
                  "(c) one force_final event: task A, reason goodput, waiting 1")
            reqs = [json.loads(l) for l in open(glog) if '"gp"' in l]
            check(all("value" in r["gp"] and "p" in r["gp"] for r in reqs), "(c) request log carries gp {turn, p, work, value}")
            print("   e.g.", json.dumps(ev[0]))
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return murl, mock


async def run_agent_e2e(tmp):
    """(d) the frozen agent through the gateway, forced at turn 2 by --turn-limit 2."""
    import aiohttp
    import duckdb
    spec = importlib.util.spec_from_file_location("run_w_test", os.path.join(REPO, "harness", "agent_duckdb", "run_w.py"))
    rw = importlib.util.module_from_spec(spec); spec.loader.exec_module(rw)
    dbp = os.path.join(tmp, "tiny.duckdb")
    con = duckdb.connect(dbp); con.execute("CREATE TABLE t AS SELECT 1 AS a"); con.close()
    mport = free_port(); murl = f"http://127.0.0.1:{mport}"
    procs = [start([os.path.join(HERE, "mock_vllm.py"), "--port", str(mport), "--delay", "0.05", "--tool-turns", "2"], mport)]
    try:
        res = {}
        for lim in (0, 2):
            gport = free_port(); gurl = f"http://127.0.0.1:{gport}"
            cmd = [os.path.join(HERE, "gateway.py"), "--port", str(gport), "--backends", murl,
                   "--log", os.path.join(tmp, f"gw_e2e_{lim}.jsonl")] + (["--turn-limit", str(lim)] if lim else [])
            g = start(cmd, gport); procs.append(g)
            ns = argparse.Namespace(url=gurl, model="m", concurrency=0, max_turns=15, max_tokens=64, brief="none",
                                    brief_text="", brief_name="none", brief_by_bench={})
            task = dict(qid="w3mix-s9-0000", db_path=dbp, tenant="tpch_sf10", bench="tpch", question="how many?",
                        template_id="h00", phrasing_id=0, is_repeat=False, pos=0, gold_rows=[["1"]])
            turns, tasks = [], []
            async with aiohttp.ClientSession(headers={"x-task-id": f"e2e{lim}", "x-task-start": f"{time.time():.6f}",
                                                      "x-db": "tpch_sf10"}) as http:
                await rw.run_task(http, ns, task, asyncio.Semaphore(1), turns, tasks)
            res[lim] = tasks[0]
            g.terminate(); g.wait()
        check(res[0]["status"] == "answered" and res[0]["turns"] == 3, f"(d) agent without limit: {res[0]['status']} at turn {res[0]['turns']}")
        check(res[2]["status"] == "answered" and res[2]["turns"] == 2 and res[2]["used_answer"],
              f"(d) agent with --turn-limit 2: {res[2]['status']} at turn {res[2]['turns']} (forced final used as the answer)")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(os.environ.get("DBKV_DATA", os.path.expandvars("$SCRATCH/dbkv")), "runs", "p1"))
    ap.add_argument("--table", default="")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="test_goodput_", dir=os.environ.get("TMPDIR"))
    test_texts()
    tasks, msgs = test_features(a.runs)
    if a.table:
        table_path = a.table
        table = json.load(open(table_path))
    else:
        dirs = [d for d in F.cell_dirs([a.runs]) if "open_140" not in d and "open_180" not in d]
        table = F.fit(F.samples(F.load_tasks(dirs)), 20.0, 1.0)
        table_path = os.path.join(tmp, "table.json")
        json.dump(table, open(table_path, "w"))
    test_speed(table, msgs)
    test_priority(table)
    asyncio.run(run_gateway_tests(table_path, tmp))
    asyncio.run(run_agent_e2e(tmp))
    print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED'} (temp files in {tmp})")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
