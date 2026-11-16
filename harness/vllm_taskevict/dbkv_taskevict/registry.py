"""Task state inside the vLLM engine-core process: live / ended / expired, plus the task_end channel.

Threading: everything except post_end() runs on the engine-core busy-loop thread (Scheduler.add_request,
Scheduler.schedule, Scheduler._free_request, KVCacheManager.free). post_end() may be called from the HTTP
listener thread; it only puts the id on a thread-safe SimpleQueue, drained by tick() at the start of the
next Scheduler.schedule().
"""
import json, queue, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TaskRegistry:
    def __init__(self, ttl=300.0, log_path="", log_every=10.0, clock=time.monotonic):
        self.ttl = float(ttl)
        self.clock = clock
        self.inbox = queue.SimpleQueue()
        self.ended = {}       # task -> clock time of end (kept 1 h, so late frees still see "ended")
        self.expired = {}     # task -> clock time of expiry (TTL with nothing in flight)
        self.last_seen = {}   # live task -> clock time of its last request add / finish
        self.inflight = {}    # live task -> requests added and not yet finished
        self.queues = []      # TaskTieredFreeQueue instances (one per caching BlockPool)
        self.counts = dict(end_msgs=0, end_dup=0, end_unseen=0, expirations=0, revived=0, late_requests=0,
                           requests=0)
        self._next_ttl = 0.0
        self._next_log = 0.0
        self.log_every = float(log_every)
        self.log = open(log_path, "a", buffering=1) if log_path else None
        self.last_snapshot = {}
        self.listener = None

    # ---- liveness ----
    def is_live(self, task):
        return task not in self.ended and task not in self.expired

    # ---- events ----
    def post_end(self, task):
        """Thread-safe."""
        self.inbox.put(str(task))

    def on_request_added(self, task):
        now = self.clock()
        self.counts["requests"] += 1
        if task in self.ended:
            self.counts["late_requests"] += 1
            return
        if self.expired.pop(task, None) is not None:
            self.counts["revived"] += 1
        self.last_seen[task] = now
        self.inflight[task] = self.inflight.get(task, 0) + 1

    def on_request_finished(self, task):
        if task in self.inflight:
            self.inflight[task] = max(0, self.inflight[task] - 1)
            self.last_seen[task] = self.clock()

    def _gone(self, task, ended):
        moved = 0
        for q in self.queues:
            moved += q.on_task_gone(task, ended)
        return moved

    def tick(self):
        """Drain task_end messages; expire idle tasks (TTL); write the periodic stats line."""
        now = self.clock()
        while True:
            try:
                t = self.inbox.get_nowait()
            except queue.Empty:
                break
            self.counts["end_msgs"] += 1
            if t in self.ended:
                self.counts["end_dup"] += 1
                continue
            if t not in self.last_seen and t not in self.expired:
                self.counts["end_unseen"] += 1
            self.ended[t] = now
            self.expired.pop(t, None)
            self.last_seen.pop(t, None)
            self.inflight.pop(t, None)
            self._gone(t, True)
        if now >= self._next_ttl:
            self._next_ttl = now + 1.0
            if self.ttl > 0:
                for t, ls in list(self.last_seen.items()):
                    if self.inflight.get(t, 0) == 0 and now - ls > self.ttl:
                        del self.last_seen[t]
                        self.inflight.pop(t, None)
                        self.expired[t] = now
                        self.counts["expirations"] += 1
                        self._gone(t, False)
            for d in (self.ended, self.expired):
                if len(d) > 1000:
                    for t in [t for t, x in d.items() if now - x > 3600]:
                        del d[t]
        if now >= self._next_log:
            self._next_log = now + self.log_every
            self.last_snapshot = self.snapshot()
            if self.log:
                self.log.write(json.dumps(self.last_snapshot) + "\n")

    def reset_tasks(self):
        """After a successful prefix-cache reset (between experiment cells): forget all task state, so a
        reused task id in the next cell is not taken for an ended task. Pending end messages are dropped."""
        while True:
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                break
        for d in (self.ended, self.expired, self.last_seen, self.inflight):
            d.clear()
        self.counts["resets"] = self.counts.get("resets", 0) + 1
        if self.log:
            self.log.write(json.dumps(dict(ev="reset", t=round(time.time(), 3))) + "\n")

    def snapshot(self):
        d = dict(t=round(time.time(), 3), live=len(self.last_seen),
                 inflight=sum(1 for v in self.inflight.values() if v), ended=len(self.ended),
                 expired=len(self.expired), **self.counts)
        if self.queues:
            d["pools"] = [q.snapshot() for q in self.queues]
        return d

    # ---- out-of-band task_end listener (engine-core process only) ----
    def start_listener(self, host, port):
        reg = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):  # noqa: N802
                if self.path.rstrip("/") != "/task_end":
                    return self._send(404, {"error": "POST /task_end"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    ids = body.get("task_ids") or [body["task_id"]]
                except Exception as e:  # noqa: BLE001
                    return self._send(400, {"error": f"body must be {{task_id}} or {{task_ids}}: {e!r}"})
                for t in ids:
                    reg.post_end(t)
                self._send(200, {"ok": True, "n": len(ids)})

            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") in ("/stats", ""):
                    return self._send(200, reg.last_snapshot)
                if self.path.rstrip("/") == "/health":
                    return self._send(200, {"ok": True})
                self._send(404, {"error": "GET /stats"})

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer((host, int(port)), H)
        srv.daemon_threads = True
        th = threading.Thread(target=srv.serve_forever, name="dbkv-taskevict-listener", daemon=True)
        th.start()
        self.listener = srv
        return srv
