"""Gateway --taskevict against harness/gateway/mock_vllm.py (no GPU, no vLLM import): request tagging and
the task_end signal (http and in-band), plus the default-off path."""
import contextlib, json, os, socket, subprocess, sys, tempfile, time, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GW = os.path.join(REPO, "harness", "gateway", "gateway.py")
MOCK = os.path.join(REPO, "harness", "gateway", "mock_vllm.py")
T0, T1 = "t00000@1700000000.000000", "t00001@1700000001.000000"   # engine task ids: id@start


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(url, t=20):
    end = time.time() + t
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    raise RuntimeError(f"{url} did not come up")


def post(url, body, headers=None, timeout=10):
    r = urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}),
        timeout=timeout)
    return json.loads(r.read())


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read())


@contextlib.contextmanager
def stack_ctx():
    procs = []
    tmp = tempfile.mkdtemp()

    def start(gw_args):
        mp, gp = free_port(), free_port()
        procs.append(subprocess.Popen([sys.executable, MOCK, "--port", str(mp), "--delay", "0.01"]))
        wait_up(f"http://127.0.0.1:{mp}/health")
        args = [a.replace("{MOCK}", str(mp)) for a in gw_args]
        log = os.path.join(tmp, f"gw{gp}.jsonl")
        procs.append(subprocess.Popen([sys.executable, GW, "--port", str(gp), "--backends",
                                       f"http://127.0.0.1:{mp}", "--log", log, *args]))
        wait_up(f"http://127.0.0.1:{gp}/health")
        return f"http://127.0.0.1:{mp}", f"http://127.0.0.1:{gp}", log

    try:
        yield start
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(10)


def run_tasks(gw, n_tasks=2, n_req=2, extra_xargs=None):
    for k in range(n_tasks):
        tid = f"t{k:05d}"
        hd = {"x-task-id": tid, "x-task-start": f"{1700000000 + k:.6f}", "x-db": "tpch_sf10"}
        for i in range(n_req):
            body = {"model": "Qwen/Qwen3-32B", "messages": [{"role": "user", "content": "q"}] * (1 + 2 * i)}
            if extra_xargs:
                body["vllm_xargs"] = dict(extra_xargs)
            post(gw + "/v1/chat/completions", body, hd)
        t0 = time.time()
        r = post(gw + "/gw/task_end", {"task_id": tid})
        assert r["known"] and time.time() - t0 < 2.0   # the engine signal never delays task_end


def wait_for(fn, t=5):
    end = time.time() + t
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


def test_off_by_default():
    with stack_ctx() as stack:
        _test_off_by_default(stack)


def _test_off_by_default(stack):
    mock, gw, _ = stack(["--priority"])
    run_tasks(gw)
    log = get(mock + "/mock/log")
    assert len(log) == 4 and all(e["xargs"] is None for e in log)
    assert all(e["priority"] is not None for e in log)
    time.sleep(0.3)
    assert get(mock + "/mock/task_ends") == []
    assert get(gw + "/gw/stats")["taskevict_sent"] == 0


def test_http_mode():
    with stack_ctx() as stack:
        _test_http_mode(stack)


def _test_http_mode(stack):
    mock, gw, logp = stack(["--priority", "--taskevict", "http",
                            "--taskevict-endpoints", "http://127.0.0.1:{MOCK}/task_end"])
    run_tasks(gw, extra_xargs={"keep": 1})
    log = get(mock + "/mock/log")
    assert [e["xargs"]["dbkv_task"] for e in log] == [T0, T0, T1, T1]
    assert log[0]["xargs"]["dbkv_task_start"] == 1700000000.0 and log[2]["xargs"]["dbkv_task_start"] == 1700000001.0
    assert all(e["xargs"]["keep"] == 1 for e in log)     # the client's own vllm_xargs are kept
    assert all(e["priority"] is not None for e in log)
    ends = wait_for(lambda: len(get(mock + "/mock/task_ends")) == 2 and get(mock + "/mock/task_ends"))
    assert [(e["task_id"], e["via"]) for e in ends] == [(T0, "http"), (T1, "http")]
    st = wait_for(lambda: get(gw + "/gw/stats")["taskevict_sent"] == 2 and get(gw + "/gw/stats"))
    assert st["taskevict_errors"] == 0
    evs = wait_for(lambda: [json.loads(x) for x in open(logp)], t=5)     # the gateway flushes its log every 1 s
    assert evs[0]["ev"] == "start" and evs[0]["taskevict"] == "http"
    te = wait_for(lambda: [e for e in (json.loads(x) for x in open(logp)) if e.get("ev") == "taskevict_end"], t=5)
    assert [(e["task_id"], e["status"]) for e in te] == [("t00000", 200), ("t00001", 200)]


def test_inband_mode():
    with stack_ctx() as stack:
        _test_inband_mode(stack)


def _test_inband_mode(stack):
    mock, gw, _ = stack(["--taskevict", "inband"])
    run_tasks(gw, n_tasks=1)
    log = get(mock + "/mock/log")
    assert all(e["xargs"]["dbkv_task"] == T0 for e in log) and all(e["priority"] is None for e in log)
    ends = wait_for(lambda: get(mock + "/mock/task_ends"))
    assert ends == [dict(ends[0], task_id=T0, via="inband", model="Qwen/Qwen3-32B")]


def test_http_mode_dead_endpoint():
    with stack_ctx() as stack:
        _test_http_mode_dead_endpoint(stack)


def _test_http_mode_dead_endpoint(stack):
    mock, gw, _ = stack(["--taskevict", "http", "--taskevict-endpoints", f"http://127.0.0.1:{free_port()}/task_end"])
    run_tasks(gw, n_tasks=1)
    st = wait_for(lambda: get(gw + "/gw/stats")["taskevict_errors"] == 1 and get(gw + "/gw/stats"))
    assert st["taskevict_errors"] == 1 and st["errors"] == 0
