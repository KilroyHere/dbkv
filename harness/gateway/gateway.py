"""Agent gateway: an aiohttp reverse proxy between SQL agents and one or more vLLM OpenAI servers (PLAN 2f).

    python harness/gateway/gateway.py --port 9000 --backends http://127.0.0.1:8000[,http://127.0.0.1:8001] \
        [--admission K] [--priority] [--route single|round_robin|least_loaded|affinity] [--cap 1.25] \
        [--goodput TABLE.json [--goodput-admit] [--force-final THRESH [--force-frac 0.1] [--force-min-turn 2]]] \
        [--turn-limit N] --log DIR/gateway.jsonl

Every agent request carries x-task-id, x-task-start (epoch seconds, set by the load generator) and x-db.
A task becomes *active* on its first request and stops being active on POST /gw/task_end {task_id}, or after
--idle-timeout s (default 120) with no request in flight (a safety net: counted in stats, logged as an event).

Policies (all off by default = a plain proxy, for self-check S2):
  --admission K   at most K active tasks; a new task's first request waits FIFO by x-task-start.
  --priority      inject "priority": int(task_start_ms - t0_ms) into the body (vLLM --scheduling-policy priority).
  --route         per-task sticky backend choice on the first request:
                  single (first backend), round_robin, least_loaded (fewest active tasks),
                  affinity (x-db -> home replica from a balanced greedy map over the 11 BIRD dev DBs; spill to
                  the least-loaded replica, ties -> home, when home's active tasks incl. this one
                  > cap * (total active incl. this one) / n_backends).
Option B, goodput (PLAN 2j; goodput.py, table from fit_goodput.py; all off by default):
  --goodput T     per request: state from the messages (turn, tool errors / timeouts, turns since the last good
                  execute_sql, output tokens so far from the usage the gateway has proxied) -> table T ->
                  p = P(success), work = E[remaining output + uncached prompt tokens]; vLLM priority =
                  round(-1000 log10(p / work)) instead of task start (higher value = sooner). Overrides --priority.
                  --prefill-weight / --db-weight override the table's work weights (work = out + w_pre * pre +
                  w_db * remaining tool seconds; table defaults 1 and 0).
  --goodput-admit order the admission queue by the first request's value (default: by x-task-start, as A(a)).
  --force-final THRESH  only while the admission queue holds more than THRESH tasks (overload): a request of an
                  active task at turn >= --force-min-turn whose value is among the lowest --force-frac of the
                  active tasks' current values is rewritten to a forced final answer (goodput.force_final_body:
                  append the agent's LAST user message, tool_choice "none"), and so is every later request of
                  that task. Needs --goodput. Logged as ev "force_final". With --goodput, a forced request gets
                  priority 0 (served first: one short turn that frees the task's admission slot).
  --turn-limit N  the static baseline: every request at turn >= N is forced final the same way (ev "force_final",
                  reason "turn_limit"). Independent of --goodput.

Endpoints: POST /v1/chat/completions (proxied, non-streaming), GET /metrics and /gw/stats (JSON stats),
POST /gw/task_end, GET /health.
Request log (JSONL, one line per request): ts, task_id, db, backend, status, queue_ms (admission wait),
upstream_ms (send -> full body read), overhead_ms (handler time outside queue + upstream, incl. writing the
response to the client), priority, bytes in/out. Events (idle releases, admissions) go to the same file with "ev".
"""
import argparse, asyncio, hashlib, heapq, itertools, json, time

import math, os, sys

import aiohttp
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import goodput as GP  # noqa: E402

# BIRD dev (dev_20240627) questions per DB; used only to balance the affinity map. Unknown DBs hash.
BIRD_DEV_COUNTS = {"card_games": 191, "codebase_community": 186, "formula_1": 174, "thrombosis_prediction": 163,
                   "student_club": 158, "toxicology": 145, "superhero": 129, "european_football_2": 129,
                   "financial": 106, "california_schools": 89, "debit_card_specializing": 64}


def stable_hash(s):
    return int.from_bytes(hashlib.sha1(s.encode()).digest()[:8], "big")


def affinity_map(n, counts=BIRD_DEV_COUNTS):
    """Deterministic greedy: DBs by question count (desc, then name) each go to the least-loaded replica."""
    load = [0] * n
    home = {}
    for db in sorted(counts, key=lambda d: (-counts[d], d)):
        i = min(range(n), key=lambda j: (load[j], j))
        home[db] = i
        load[i] += counts[db]
    return home, load


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


class Task:
    __slots__ = ("tid", "start", "db", "backend", "active", "inflight", "last", "n_req", "queue_ms",
                 "admitted_at", "ended", "out_tok", "value", "forced")

    def __init__(self, tid, start, db):
        self.tid, self.start, self.db = tid, start, db
        self.backend = None; self.active = False; self.inflight = 0; self.last = time.monotonic()
        self.n_req = 0; self.queue_ms = 0.0; self.admitted_at = None; self.ended = False
        self.out_tok = 0; self.value = None; self.forced = None  # goodput: tokens so far, last value, force reason


class Gateway:
    def __init__(self, a):
        self.a = a
        self.backends = [b.rstrip("/") for b in a.backends.split(",") if b]
        self.n = len(self.backends)
        self.t0 = time.time()
        self.t0_ms = self.t0 * 1000.0
        self.tasks = {}
        self.active = set()
        self.waiting = []  # heap (task_start, seq, tid, future)
        self.seq = itertools.count()
        self.rr = itertools.count()
        self.load = [0] * self.n  # active tasks bound to each backend
        self.home, self.home_load = affinity_map(self.n)
        self.stats = dict(requests=0, errors=0, admitted=0, queued=0, task_end=0, idle_releases=0,
                          spills=0, routed=[0] * self.n, forced_goodput=0, forced_turn_limit=0, forced_requests=0)
        self.table = GP.Table.load(a.goodput, a.prefill_weight, a.db_weight) if a.goodput else None
        if a.force_final is not None and self.table is None:
            raise SystemExit("--force-final needs --goodput TABLE")
        self.inspect = bool(self.table or a.turn_limit)  # parse each body for the task state
        self.overheads = []  # last 100k overhead_ms values
        self.sessions = []
        self.log = open(a.log, "a", buffering=1 << 16) if a.log else None

    # ---------- logging ----------
    def emit(self, d):
        if self.log:
            self.log.write(json.dumps(d, separators=(",", ":")) + "\n")

    # ---------- lifecycle ----------
    async def startup(self, app):
        for _ in self.backends:
            self.sessions.append(aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=0, keepalive_timeout=60),
                timeout=aiohttp.ClientTimeout(total=None, sock_read=self.a.sock_read)))
        self.bg = [asyncio.create_task(self.reaper()), asyncio.create_task(self.flusher())]
        self.emit(dict(ev="start", ts=self.t0, backends=self.backends, admission=self.a.admission,
                       priority=self.a.priority, route=self.a.route, cap=self.a.cap,
                       idle_timeout=self.a.idle_timeout, affinity_home=self.home if self.a.route == "affinity" else None,
                       goodput=self.a.goodput or None, goodput_admit=self.a.goodput_admit,
                       force_final=self.a.force_final, force_frac=self.a.force_frac,
                       force_min_turn=self.a.force_min_turn, turn_limit=self.a.turn_limit or None,
                       work_weights=[self.table.w, self.table.wdb] if self.table else None,
                       table_meta=(self.table.d.get("meta") or {}).get("args") if self.table else None))
        print(f"gateway up: backends={self.backends} admission={self.a.admission} priority={self.a.priority} "
              f"route={self.a.route} cap={self.a.cap} goodput={self.a.goodput or None} "
              f"force_final={self.a.force_final} turn_limit={self.a.turn_limit or None}" +
              (f" affinity={self.home} questions/replica={self.home_load}" if self.a.route == "affinity" else ""),
              flush=True)

    async def cleanup(self, app):
        for t in self.bg:
            t.cancel()
        for s in self.sessions:
            await s.close()
        self.emit(dict(ev="stop", ts=time.time(), **self.snapshot()))
        if self.log:
            self.log.close()

    async def flusher(self):
        while True:
            await asyncio.sleep(1.0)
            if self.log:
                self.log.flush()

    async def reaper(self):
        """Safety net: release active tasks idle (nothing in flight) for longer than --idle-timeout."""
        while True:
            await asyncio.sleep(min(5.0, self.a.idle_timeout / 4))
            now = time.monotonic()
            for t in [self.tasks[x] for x in list(self.active)]:
                if t.inflight == 0 and now - t.last > self.a.idle_timeout:
                    self.stats["idle_releases"] += 1
                    self.emit(dict(ev="idle_release", ts=time.time(), task_id=t.tid, db=t.db,
                                   backend=t.backend, idle_s=round(now - t.last, 1)))
                    print(f"idle release: task {t.tid} after {now - t.last:.0f} s", flush=True)
                    self.release(t)

    # ---------- admission / routing ----------
    def route(self, t):
        if self.n == 1 or self.a.route == "single":
            return 0
        if self.a.route == "round_robin":
            return next(self.rr) % self.n
        if self.a.route == "least_loaded":
            return min(range(self.n), key=lambda j: (self.load[j], j))
        # affinity with a load cap
        h = self.home.get(t.db)
        if h is None:
            h = stable_hash(t.db or "") % self.n
        total = sum(self.load) + 1
        if self.load[h] + 1 > self.a.cap * total / self.n:
            j = min(range(self.n), key=lambda k: (self.load[k], k != h, k))
            if j != h:
                self.stats["spills"] += 1
            return j
        return h

    def activate(self, t):
        t.active = True
        t.admitted_at = time.monotonic()
        self.active.add(t.tid)
        if t.backend is None:  # sticky for the task's lifetime
            t.backend = self.route(t)
            self.stats["routed"][t.backend] += 1
        self.load[t.backend] += 1
        self.stats["admitted"] += 1

    def release(self, t):
        if not t.active:
            return
        t.active = False
        self.active.discard(t.tid)
        self.load[t.backend] -= 1
        self.pump()

    def pump(self):
        K = self.a.admission
        while self.waiting and (K <= 0 or len(self.active) < K):
            _, _, tid, fut = heapq.heappop(self.waiting)
            if fut.done():  # cancelled (client gone or task_end while queued)
                continue
            self.activate(self.tasks[tid])
            fut.set_result(None)

    async def admit(self, t):
        """Returns ms spent waiting at the gateway (0 when already active or capacity is free)."""
        if t.active:
            return 0.0
        K = self.a.admission
        if K <= 0 or (len(self.active) < K and not self.waiting):
            self.activate(t)
            return 0.0
        fut = asyncio.get_running_loop().create_future()
        key = -t.value if (self.a.goodput_admit and t.value is not None) else t.start
        heapq.heappush(self.waiting, (key, next(self.seq), t.tid, fut))
        self.stats["queued"] += 1
        q0 = time.monotonic()
        try:
            await fut
        except asyncio.CancelledError:
            fut.cancel()
            raise
        return (time.monotonic() - q0) * 1000.0

    # ---------- goodput (option B) ----------
    def n_waiting(self):
        return sum(1 for w in self.waiting if not w[3].done())

    def low_value(self, t):
        """Is t among the lowest --force-frac of the active tasks' current values?"""
        vals = [self.tasks[x].value for x in self.active if x in self.tasks and self.tasks[x].value is not None]
        if not vals:
            return False
        n_low = max(1, math.ceil(self.a.force_frac * len(vals)))
        return sum(v < t.value for v in vals) < n_low

    def force_reason(self, t, st):
        if t.forced:
            return t.forced
        if self.a.turn_limit and st["turn"] >= self.a.turn_limit:
            return "turn_limit"
        if (self.a.force_final is not None and st["turn"] >= self.a.force_min_turn and t.value is not None
                and self.n_waiting() > self.a.force_final and self.low_value(t)):
            return "goodput"
        return None

    # ---------- handlers ----------
    async def chat(self, req):
        h0 = time.monotonic()
        hd = req.headers
        tid = hd.get("x-task-id") or f"anon-{next(self.seq)}"
        t = self.tasks.get(tid)
        if t is None or t.ended:
            try:
                start = float(hd.get("x-task-start") or time.time())
            except ValueError:
                start = time.time()
            t = Task(tid, start, hd.get("x-db", ""))
            self.tasks[tid] = t
        raw = await req.read()
        t.inflight += 1
        t.last = time.monotonic()
        t.n_req += 1
        self.stats["requests"] += 1
        q_ms = up_ms = 0.0
        status = 0
        prio = None
        out = b""
        gp = None  # goodput log fields
        try:
            body = None
            if self.inspect:
                body = json.loads(raw)
                st = GP.features_from_messages(body.get("messages") or [], t.db,
                                               t.out_tok or None)  # None -> estimated from the text
                gp = dict(turn=st["turn"], tmo=st["n_timeout"], err=st["n_err"], out_tok=st["out_tok"])
                if self.table:
                    r = self.table.lookup(st)
                    t.value = r["value"]
                    gp.update(p=round(r["p"], 4), work=round(r["work"]), value=float(f"{r['value']:.4g}"),
                              lvl=r["level"])
            q_ms = await self.admit(t)
            if t.n_req == 1:
                t.queue_ms = q_ms
            if self.table:
                prio = GP.value_priority(t.value)
            elif self.a.priority:
                prio = int(t.start * 1000.0 - self.t0_ms)
            if gp is not None:
                why = self.force_reason(t, st)
                if why:
                    if not t.forced:
                        t.forced = why
                        self.stats["forced_" + why] += 1
                        self.emit(dict(ev="force_final", ts=round(time.time(), 4), task_id=tid, db=t.db,
                                       reason=why, waiting=self.n_waiting(), active=len(self.active), **gp))
                    self.stats["forced_requests"] += 1
                    GP.force_final_body(body)
                    gp["forced"] = why
                    if self.table:  # one short final turn left: serve it first so the task frees its slot
                        prio = 0
            if prio is not None or (gp is not None and gp.get("forced")):
                if body is None:
                    body = json.loads(raw)
                if prio is not None:
                    body["priority"] = prio
                raw = json.dumps(body).encode()
            u0 = time.monotonic()
            try:
                async with self.sessions[t.backend].post(
                        self.backends[t.backend] + "/v1/chat/completions", data=raw,
                        headers={"Content-Type": "application/json", "x-task-id": tid}) as r:
                    out = await r.read()
                    status = r.status
                    ctype = r.headers.get("Content-Type", "application/json")
                if self.table and status == 200:
                    try:
                        t.out_tok += int((json.loads(out).get("usage") or {}).get("completion_tokens") or 0)
                    except (ValueError, TypeError, AttributeError):
                        pass
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                status, ctype = 502, "application/json"
                out = json.dumps({"error": f"gateway upstream error: {type(e).__name__}: {e}"}).encode()
            up_ms = (time.monotonic() - u0) * 1000.0
            resp = web.Response(body=out, status=status, headers={"Content-Type": ctype})
            await resp.prepare(req)
            await resp.write_eof()
            return resp
        finally:
            t.inflight -= 1
            t.last = time.monotonic()
            if status != 200:
                self.stats["errors"] += 1
            ov = (time.monotonic() - h0) * 1000.0 - q_ms - up_ms
            if len(self.overheads) >= 100_000:
                self.overheads = self.overheads[50_000:]
            self.overheads.append(ov)
            self.emit(dict(ts=round(time.time(), 4), task_id=tid, db=t.db, backend=t.backend, status=status,
                           queue_ms=round(q_ms, 3), upstream_ms=round(up_ms, 3), overhead_ms=round(ov, 3),
                           priority=prio, n=t.n_req, bytes_in=len(raw), bytes_out=len(out),
                           **({"gp": gp} if gp is not None else {})))

    async def task_end(self, req):
        try:
            tid = str((await req.json())["task_id"])
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "body must be {task_id}"}, status=400)
        t = self.tasks.get(tid)
        if t is None:
            return web.json_response({"task_id": tid, "known": False})
        self.stats["task_end"] += 1
        was_active = t.active
        t.ended = True
        self.release(t)
        for i, (_, _, wtid, fut) in enumerate(self.waiting):  # ended while still queued
            if wtid == tid and not fut.done():
                fut.cancel()
        self.emit(dict(ev="task_end", ts=time.time(), task_id=tid, db=t.db, backend=t.backend,
                       queue_ms=round(t.queue_ms, 3), n_req=t.n_req, was_active=was_active))
        del self.tasks[tid]
        return web.json_response({"task_id": tid, "known": True, "backend": t.backend,
                                  "backend_url": self.backends[t.backend] if t.backend is not None else None,
                                  "queue_ms": round(t.queue_ms, 3), "n_req": t.n_req, "was_active": was_active})

    def snapshot(self):
        ov = self.overheads
        return dict(uptime_s=round(time.time() - self.t0, 1), active=len(self.active),
                    waiting=self.n_waiting(), load=list(self.load),
                    backends=self.backends, overhead_ms_p50=pct(ov, 50), overhead_ms_p95=pct(ov, 95),
                    **{k: (list(v) if isinstance(v, list) else v) for k, v in self.stats.items()})

    async def stats_h(self, req):
        return web.json_response(self.snapshot())

    async def health(self, req):
        return web.Response(text="ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--backends", required=True, help="comma-separated vLLM base URLs")
    ap.add_argument("--admission", type=int, default=0, help="max active tasks (0 = off)")
    ap.add_argument("--priority", action="store_true")
    ap.add_argument("--route", default="single", choices=["single", "round_robin", "least_loaded", "affinity"])
    ap.add_argument("--cap", type=float, default=1.25)
    ap.add_argument("--idle-timeout", type=float, default=120.0)
    ap.add_argument("--sock-read", type=float, default=900.0)
    ap.add_argument("--log", default="")
    ap.add_argument("--goodput", default="", help="goodput table JSON (fit_goodput.py): value-based priority")
    ap.add_argument("--goodput-admit", action="store_true", help="admission queue by value instead of task start")
    ap.add_argument("--prefill-weight", type=float, default=None, help="override the table's: work = out + w * uncached prompt")
    ap.add_argument("--db-weight", type=float, default=None,
                    help="override the table's (0): work += w * remaining tool wall seconds (token-equivalents per s)")
    ap.add_argument("--force-final", type=int, default=None, metavar="THRESH",
                    help="force a final answer for the lowest-value tasks while > THRESH tasks wait for admission")
    ap.add_argument("--force-frac", type=float, default=0.1)
    ap.add_argument("--force-min-turn", type=int, default=2)
    ap.add_argument("--turn-limit", type=int, default=0, help="static baseline: force final at turn >= N (0 = off)")
    a = ap.parse_args()
    gw = Gateway(a)
    app = web.Application(client_max_size=64 << 20)
    app.on_startup.append(gw.startup)
    app.on_cleanup.append(gw.cleanup)
    app.router.add_post("/v1/chat/completions", gw.chat)
    app.router.add_post("/gw/task_end", gw.task_end)
    app.router.add_get("/gw/stats", gw.stats_h)
    app.router.add_get("/metrics", gw.stats_h)
    app.router.add_get("/health", gw.health)
    web.run_app(app, host=a.host, port=a.port, access_log=None, print=None, backlog=4096)


if __name__ == "__main__":
    main()
