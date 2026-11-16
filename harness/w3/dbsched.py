"""Option D (PLAN 2j, Phase 2): EXPLAIN query scheduling in front of DuckDB, without touching the agent.

The frozen agent (agent-32b-v1) runs every tool call as `await asyncio.to_thread(tools.call, db_path, name, args)`
and grades with `asyncio.to_thread(tools.run_query, db_path, sql, ...)`. to_thread submits
`functools.partial(ctx.run, fn, *args)` to the event loop's *default executor*, so the load generator can install
an executor that sees every DuckDB call (function, db path, tool name, SQL) and the caller's contextvars (the task
id and task start time, set by loadgen_w3.py).

    make_executor("off", workers=32)       # a plain ThreadPoolExecutor(32): today's behaviour, byte for byte
    make_executor("explain", workers=32, long_cap=2, heavy_cap=6, order="taskstart", log_path=...)
    make_executor("observe", workers=32, log_path=...)   # FIFO like off, but classifies in the background and logs

SchedExecutor ("explain"):
  1. classify: execute_sql (and grading run_query) SQL gets `EXPLAIN (FORMAT JSON)` on a small classifier pool
     (its own read-only connection, same settings as the agent's tools); the G2 plan features
     (calib/g2_run.plan_features) go through a log-linear model (dbsched_model.json, fit by bench_dbsched.py
     calib) to a predicted runtime -> class short (< 0.25 s) / medium (< 2 s) / long. list_tables,
     describe_table and sample_rows are class "meta" (no EXPLAIN); SQL whose EXPLAIN fails (syntax, binder) is
     class "error" (it fails fast). Non-DuckDB submissions (e.g. getaddrinfo) bypass the scheduler.
  2. schedule: at most `workers` DuckDB calls run at once (same as off). Waiting calls are served in class order
     meta/error < short < medium < long, then by task start time (order=taskstart: older tasks first, the GPU
     gateway's task-start priority) or FIFO, then submission order. Caps: at most `long_cap` long and
     `heavy_cap` heavy calls run at once; a blocked call is skipped and later calls backfill free slots.
     Heavy = predicted medium or long, or any running call that has exceeded `long_s` (runtime demotion: a
     misclassified query cannot hold a short slot while more heavy ones start). Demoted calls count toward
     heavy_cap only, not long_cap (otherwise slow mediums clog the long slots: CPU smoke, Nov 16).
     Starvation guard: a call waiting more than `starve_s` is served before all non-aged calls and ignores
     heavy_cap (long_cap still applies, and long calls release it in order).
  4. db_threads (optional, any mode incl. off via loadgen --db-threads): DuckDB's `threads` is per database
     instance (per file), not per query, so the only per-query-thread lever is the agent tools module's THREADS
     constant, which tools.connect applies on every connection. Default: unchanged (8).
  The agent's 60 s query timer starts inside tools.call, so time spent waiting here never counts toward it.
  3. log: one JSONL row per DuckDB call (class, prediction, features, EXPLAIN ms, wait, run, runtime, error,
     running counts) and a per-class summary (`summary()`).

Why caps matter on DuckDB (checked Nov 16, duckdb 2.0.0): in one process every connection to the same file shares
ONE database instance, so `SET threads=8` and `memory_limit=16GB` from tools.connect are per *file*, not per
query: all concurrent SF100 queries share 8 scheduler threads (+ their caller threads) and 16 GB. Unbounded heavy
concurrency means processor sharing plus spilling, and queries hit the 60 s timeout and lose all their work.
"""
import concurrent.futures as cf
import contextvars, functools, json, math, os, sys, threading, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "calib"))

# Set by the load generator in each task's coroutine; to_thread copies the context into the submission.
TASK = contextvars.ContextVar("dbkv_task", default=None)  # (task_id, task_start_epoch)

CLASSES = ["meta", "error", "short", "medium", "long"]
RANK = {"meta": 0, "error": 0, "short": 1, "medium": 2, "long": 3, "unclassified": 1}
DEFAULT_MODEL = os.path.join(HERE, "dbsched_model.json")


def make_executor(mode="off", workers=32, **kw):
    if mode == "off":
        return cf.ThreadPoolExecutor(workers)
    if mode == "explain":
        return SchedExecutor(workers, **kw).start()
    if mode == "observe":  # FIFO, no caps, never waits on EXPLAIN: the default's behaviour, with D's per-call log
        kw.update(long_cap=workers, heavy_cap=workers, order="fifo", gate=False, demote=False)
        return SchedExecutor(workers, **kw).start()
    raise ValueError(f"unknown db-sched mode {mode!r}")


def set_db_threads(tools_mod, n):
    """Per-instance DuckDB threads: overrides the agent tools module's THREADS (read by tools.connect at each
    connection). The agent's files are not changed; this is serving-side configuration."""
    tools_mod.THREADS = int(n)


class Model:
    """Predicted log10 seconds from G2 plan features. JSON: feats_log, feats_raw, mu, sd, b, short_s, long_s and
    long_decide_s (the predicted runtime above which a query is classed long; below long_s because the model
    under-predicts agent SQL: on SF100 agent SQL, 1.0 s gives long recall 0.72 / precision 0.88 vs 0.50 / 1.00)."""

    def __init__(self, path=None):
        self.path = path if path is not None else (DEFAULT_MODEL if os.path.exists(DEFAULT_MODEL) else "")
        if self.path:
            m = json.load(open(self.path))
            self.flog, self.fraw = m["feats_log"], m["feats_raw"]
            self.mu, self.sd, self.b = np.array(m["mu"]), np.array(m["sd"]), np.array(m["b"])
            self.short_s, self.long_s = m.get("short_s", 0.25), m.get("long_s", 2.0)
            self.long_decide_s = m.get("long_decide_s", self.long_s)
        else:  # fallback: log10 s = log10(sum_ec) - 7.2 (about 0.25 s at 1e6.6 and 2 s at 1e7.5 estimated rows)
            self.flog, self.fraw, self.short_s, self.long_s = ["sum_ec"], [], 0.25, 2.0
            self.mu, self.sd, self.b = np.zeros(1), np.full(1, math.log(10)), np.array([-7.2, 1.0])
            self.long_decide_s = self.long_s

    def x(self, f):
        return np.array([math.log1p(float(f.get(c, 0) or 0)) for c in self.flog] +
                        [float(f.get(c, 0) or 0) for c in self.fraw])

    def predict_log10(self, f):
        z = (self.x(f) - self.mu) / self.sd
        return float(self.b[0] + z @ self.b[1:])

    def cls(self, sec):
        return "short" if sec < self.short_s else ("medium" if sec < self.long_decide_s else "long")


class Explainer:
    """EXPLAIN (FORMAT JSON) + G2 plan features, with the agent's connection settings."""

    def __init__(self, model=None, timeout_s=5.0):
        import g2_run  # calib/g2_run.py: explain(), plan_features()
        self.g2 = g2_run
        self.model = model or Model()
        self.timeout_s = timeout_s
        self._base_rows = {}
        self._lock = threading.Lock()

    def base_rows(self, con, db_path):
        with self._lock:
            br = self._base_rows.get(db_path)
        if br is None:
            br = dict(con.execute("select table_name, estimated_size from duckdb_tables()").fetchall())
            with self._lock:
                self._base_rows[db_path] = br
        return br

    def classify(self, db_path, sql, connect):
        """Returns dict(cls, pred_s, explain_ms, feats, err). `connect` = the agent's tools.connect."""
        t = time.perf_counter()
        con = None
        try:
            con = connect(db_path)
            timer = threading.Timer(self.timeout_s, con.interrupt)
            timer.daemon = True
            timer.start()
            try:
                _, roots = self.g2.explain(con, sql)
                f = self.g2.plan_features(roots, self.base_rows(con, db_path))
            finally:
                timer.cancel()
            pred = 10 ** self.model.predict_log10(f)
            return dict(cls=self.model.cls(pred), pred_s=pred, explain_ms=(time.perf_counter() - t) * 1e3,
                        feats=f, err=None)
        except Exception as e:  # noqa: BLE001  (parse / bind errors: the query itself fails fast)
            name = type(e).__name__
            cls = "long" if "Interrupt" in name else "error"
            return dict(cls=cls, pred_s=None, explain_ms=(time.perf_counter() - t) * 1e3, feats=None,
                        err=f"{name}: {str(e)[:120]}")
        finally:
            if con is not None:
                con.close()


def unwrap(fn, args):
    """(inner_fn, inner_args, ctx) for a to_thread submission, else (fn, args, None)."""
    if isinstance(fn, functools.partial) and not fn.keywords:
        owner = getattr(fn.func, "__self__", None)
        if isinstance(owner, contextvars.Context) and fn.args and not args:
            return fn.args[0], fn.args[1:], owner
    return fn, args, None


def describe(inner, iargs):
    """(source, db_path, tool, sql) for the agent's DuckDB calls, else None."""
    mod = sys.modules.get(getattr(inner, "__module__", None) or "")
    if mod is None or not hasattr(mod, "run_query") or not hasattr(mod, "connect"):
        return None
    name = getattr(inner, "__name__", "")
    if name == "call" and len(iargs) >= 3:
        db, tool, targs = iargs[0], iargs[1], iargs[2] or {}
        sql = str(targs.get("sql", "")) if tool == "execute_sql" else None
        return "tool", db, tool, sql
    if name == "run_query" and len(iargs) >= 2:
        return "grade", iargs[0], "run_query", str(iargs[1])
    return None


class _Item:
    __slots__ = ("seq", "fn", "fut", "src", "db", "tool", "sql", "connect", "task_id", "task_start", "t_submit",
                 "t_ready", "t_start", "cls", "pred_s", "explain_ms", "feats", "explain_err", "demoted", "classified")


class SchedExecutor(cf.ThreadPoolExecutor):
    """See module docstring. Subclasses ThreadPoolExecutor because asyncio's set_default_executor requires it;
    the base pool runs both the admitted DuckDB calls (at most `workers`) and pass-through work."""

    def __init__(self, workers=32, long_cap=2, heavy_cap=6, order="taskstart", starve_s=30.0, model_path=None,
                 classify_workers=4, demote=True, log_path=None, passthrough_extra=8, gate=True, db_threads=0):
        super().__init__(max_workers=workers + passthrough_extra, thread_name_prefix="dbsched")
        self.workers, self.long_cap, self.heavy_cap = workers, long_cap, heavy_cap
        self.order, self.starve_s, self.demote, self.gate = order, starve_s, demote, gate
        self.db_threads = db_threads
        self.explainer = Explainer(Model(model_path))
        self.long_s = self.explainer.model.long_s
        self._cls_pool = cf.ThreadPoolExecutor(classify_workers, thread_name_prefix="dbsched-explain")
        self._lock = threading.Lock()
        self._wait, self._run = [], {}
        self._seq = 0
        self._log = open(log_path, "a") if log_path else None
        self._log_lock = threading.Lock()
        self._rows = []
        self.config = dict(mode="explain" if gate else "observe", workers=workers, long_cap=long_cap, heavy_cap=heavy_cap, order=order,
                           starve_s=starve_s, demote=demote, classify_workers=classify_workers,
                           model=self.explainer.model.path or "fallback:sum_ec",
                           short_s=self.explainer.model.short_s, long_s=self.long_s,
                           long_decide_s=self.explainer.model.long_decide_s, db_threads=db_threads)

    # ---- submission -------------------------------------------------------------------------------------------
    def submit(self, fn, /, *args, **kwargs):
        inner, iargs, ctx = unwrap(fn, args) if not kwargs else (fn, args, None)
        d = describe(inner, iargs) if ctx is not None else None
        if d is None:
            return super().submit(fn, *args, **kwargs)  # pass-through (not a DuckDB call)
        it = _Item()
        it.src, it.db, it.tool, it.sql = d
        it.fn, it.fut = fn, cf.Future()
        mod = sys.modules[inner.__module__]
        if self.db_threads and getattr(mod, "THREADS", None) != self.db_threads:
            set_db_threads(mod, self.db_threads)
        it.connect = mod.connect
        tk = ctx.get(TASK, None)
        it.task_id, it.task_start = (tk if tk else (None, None))
        it.t_submit = time.time()
        it.t_start = it.t_ready = None
        it.cls, it.pred_s, it.explain_ms, it.feats, it.explain_err, it.demoted = "meta", None, 0.0, None, None, False
        it.classified = threading.Event()
        with self._lock:
            self._seq += 1
            it.seq = self._seq
        if it.sql is None:  # list_tables / describe_table / sample_rows: tiny, no EXPLAIN
            it.classified.set()
            self._enqueue(it)
        elif self.gate:
            self._cls_pool.submit(self._classify, it, True)
        else:  # observe: run now, classify alongside for the log only
            if it.sql is not None:
                it.cls = "unclassified"
            self._cls_pool.submit(self._classify, it, False)
            self._enqueue(it)
        return it.fut

    def _classify(self, it, enqueue):
        try:
            r = self.explainer.classify(it.db, it.sql, it.connect)
        except Exception as e:  # noqa: BLE001
            r = dict(cls="medium", pred_s=None, explain_ms=None, feats=None, err=repr(e))
        it.cls, it.pred_s, it.explain_ms, it.feats, it.explain_err = r["cls"], r["pred_s"], r["explain_ms"], \
            r["feats"], r["err"]
        it.classified.set()
        if enqueue:
            self._enqueue(it)

    def _enqueue(self, it):
        it.t_ready = time.time()
        with self._lock:
            self._wait.append(it)
        self._dispatch()

    # ---- scheduling -------------------------------------------------------------------------------------------
    def _key(self, it, now):
        aged = (now - it.t_submit) > self.starve_s
        tie = it.task_start if (self.order == "taskstart" and it.task_start is not None) else it.t_submit
        return (0 if aged else 1, RANK[it.cls], tie, it.seq)

    def _heavy(self, it, now):
        if it.cls in ("medium", "long"):
            return True
        if self.demote and now - it.t_start > self.long_s:
            it.demoted = True
            return True
        return False

    def _dispatch(self):
        start = []
        with self._lock:
            now = time.time()
            n_long = n_heavy = 0
            for r in self._run.values():
                n_long += r.cls == "long"
                n_heavy += self._heavy(r, now)
            n_run = len(self._run)
            keep = []
            for it in sorted(self._wait, key=lambda x: self._key(x, now)):
                if it.fut.cancelled():
                    continue
                aged = now - it.t_submit > self.starve_s
                ok = n_run < self.workers
                if ok and it.cls == "long":
                    ok = n_long < self.long_cap and (aged or n_heavy < self.heavy_cap)
                elif ok and it.cls == "medium":
                    ok = aged or n_heavy < self.heavy_cap
                if not ok:
                    keep.append(it)  # backfilling: later (shorter or other-class) calls may still start
                    continue
                if not it.fut.set_running_or_notify_cancel():
                    continue
                it.t_start = now
                self._run[it.seq] = it
                n_run += 1
                n_long += it.cls == "long"
                n_heavy += it.cls in ("medium", "long")
                start.append(it)
            self._wait = keep
            snap = (n_run, n_long, n_heavy, len(keep))
        for it in start:
            super().submit(self._execute, it, snap)

    def _execute(self, it, snap):
        t0 = time.time()
        err, res = None, None
        try:
            res = it.fn()
            it.fut.set_result(res)
        except BaseException as e:  # noqa: BLE001
            err = e
            it.fut.set_exception(e)
        t1 = time.time()
        with self._lock:
            self._run.pop(it.seq, None)
        self._record(it, t0, t1, res, err, snap)
        self._dispatch()

    def _tick(self):
        # Runtime demotion and ageing change admission without a completion; re-check periodically.
        while not self._stop.wait(0.5):
            if self._wait:
                self._dispatch()

    # ---- logging ----------------------------------------------------------------------------------------------
    def _record(self, it, t0, t1, res, err, snap):
        it.classified.wait(2.0)  # observe mode: the background EXPLAIN normally finished long ago
        rt, qerr, rows = None, None, None
        if err is None and isinstance(res, tuple):
            if it.src == "tool" and len(res) == 2 and isinstance(res[1], dict):
                rt, qerr, rows = res[1].get("runtime_s"), res[1].get("error"), res[1].get("rows")
            elif it.src == "grade" and len(res) == 5:
                rt, qerr, rows = res[2], res[3], len(res[1])
        elif err is not None:
            qerr = "exception:" + type(err).__name__
        row = dict(t_submit=round(it.t_submit, 4), task_id=it.task_id,
                   task_start=None if it.task_start is None else round(it.task_start, 4), db=os.path.basename(it.db),
                   src=it.src, tool=it.tool, cls=it.cls, demoted=it.demoted,
                   pred_s=None if it.pred_s is None else round(it.pred_s, 4),
                   explain_ms=None if it.explain_ms is None else round(it.explain_ms, 2),
                   classify_s=round(it.t_ready - it.t_submit, 4), wait_s=round(t0 - it.t_submit, 4),
                   queue_s=round(t0 - it.t_ready, 4), run_s=round(t1 - t0, 4),
                   runtime_s=None if rt is None else round(rt, 4), error=qerr, rows=rows,
                   running_at_start=snap[0], long_at_start=snap[1], heavy_at_start=snap[2], waiting_at_start=snap[3],
                   explain_err=it.explain_err, sql=it.sql[:2000] if it.sql else None)
        if it.feats:
            row["feats"] = {k: it.feats[k] for k in ("sum_ec", "max_ec", "scan_base_rows", "n_joins", "n_aggs")}
        with self._log_lock:
            self._rows.append(row)
            if self._log:
                self._log.write(json.dumps(row) + "\n")
                self._log.flush()

    def summary(self):
        with self._log_lock:
            rows = list(self._rows)
        out = dict(config=self.config, n=len(rows), by_class={})
        for c in CLASSES:
            rs = [r for r in rows if r["cls"] == c]
            if not rs:
                continue
            p = lambda k, q: round(float(np.percentile([r[k] for r in rs], q)), 4)  # noqa: E731
            out["by_class"][c] = dict(n=len(rs), wait_p50=p("wait_s", 50), wait_p95=p("wait_s", 95),
                                      run_p50=p("run_s", 50), run_p95=p("run_s", 95),
                                      timeouts=sum(r["error"] == "timeout" for r in rs),
                                      demoted=sum(r["demoted"] for r in rs))
        ex = [r["explain_ms"] for r in rows if r["explain_ms"]]
        if ex:
            out["explain_ms_p50"], out["explain_ms_p99"] = (round(float(np.percentile(ex, q)), 2) for q in (50, 99))
        return out

    # ---- lifecycle --------------------------------------------------------------------------------------------
    def start(self):
        self._stop = threading.Event()
        threading.Thread(target=self._tick, daemon=True, name="dbsched-tick").start()
        return self

    def shutdown(self, wait=True, *, cancel_futures=False):
        if hasattr(self, "_stop"):
            self._stop.set()
        self._cls_pool.shutdown(wait=wait, cancel_futures=cancel_futures)
        if wait:  # let queued DuckDB calls drain into the base pool before it closes
            while True:
                with self._lock:
                    if not self._wait and not self._run:
                        break
                time.sleep(0.05)
                self._dispatch()
        super().shutdown(wait=wait, cancel_futures=cancel_futures)
        if self._log:
            with self._log_lock:
                self._log.close()
                self._log = None
