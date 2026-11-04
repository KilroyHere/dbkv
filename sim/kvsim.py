"""G1: iteration-level simulator of N SQL agents sharing one GPU's KV pool (v2).

Workload (same shape as harness/replay.py): each agent runs tasks of TURNS LLM turns on one growing
context. Turn 0 prefills a fresh context of C0 tokens; each later turn follows a SQL pause, appends
TOOL_IN tokens and decodes OUT tokens. C0 = C - TURNS*(TOOL_IN+OUT)/2, so the context averages ~C.

Engine (vLLM-like, simplified):
  * GPU KV pool of M tokens. A paused agent's KV stays resident ("cached") until evicted.
  * Retention policy = a pin TTL chosen when the agent pauses. Pinned KV is not evicted by normal
    admission; after the TTL it is ordinary prefix cache.
  * Victim order: LRU (last use) for policies without per-call knowledge; for oracle/noisy policies,
    farthest (estimated) return first, i.e. Belady with the policy's duration estimate.
  * Eviction is tail-first. With offload on, evicted tokens move to a host-RAM tier of H tokens
    (LRU-dropped when full) and come back at PCIe speed on resume instead of being recomputed.
  * Admission: waiting requests in priority order (program-level FCFS = task start time, or
    request-arrival FCFS for stock vLLM). A request needs GPU KV for ctx - resident tokens.
  * Deadlock breaker: if nothing is running and the head request still can't fit, evict *pinned*
    KV (same victim order). Counted per run (breaker_events, breaker_tokens), so a policy that only
    works because the breaker evicts for it is visible.
  * keep-ac (keep + admission control): a new task is admitted only if every live task's maximum
    context fits in the pool, so pinned KV never has to be broken. Breaker-free by construction.
  * Chunked prefill with a per-iteration token budget; decode 1 token per running request.
    If decode growth can't be allocated, the lowest-priority running request is preempted (recompute).
  * Iteration time = t0 + c_pf*prefill_tokens + c_dec*decoding_seqs + c_att*resident_tokens_of_running.
    Defaults are back-of-envelope A100-40GB / Qwen3-8B numbers; G3 replaces them (--cost-json).

Policies (TTL at pause start; T = true pause length):
  lru            stock vLLM: TTL 0 (KV is cached, evictable)
  keep           TTL inf; above the limit it relies on the deadlock breaker (reported as keep+breaker)
  keep-ac        TTL inf + program admission control (no breaker)
  ttl:X          fixed per-tool TTL X seconds
  cont2          released Continuum code: pin 2 s if the tool's running-mean duration < 2 s, else 0
  contpaper      Continuum paper Eq. 1, per tool (not per call)
  oracle:TH      knows T: pin for T if T <= TH, else TTL 0; Belady victim order
  noisy:S:TH     like oracle but sees T*exp(S*z), z ~ N(0,1): a stand-in for EXPLAIN until G2
"""
import heapq, math
from dataclasses import dataclass

import numpy as np

try:
    from . import pauses
except ImportError:
    import pauses


@dataclass
class Cfg:
    ctx: int = 8192
    sessions: int = 16
    kv_tokens: int = 134_448        # vLLM's measured pool (smoke job 60824741)
    turns: int = 6
    tool_in: int = 300
    out: int = 150
    mix: str = "redshift"
    pause_scale: float = 1.0        # multiply every pause by this
    pause_file: str = ""            # empirical pause seconds (one per line) instead of `mix`
    policy: str = "lru"
    sched: str = "program"          # "program" (task-start FCFS) or "request" (arrival FCFS)
    offload: bool = False
    host_kv_tokens: int = 250_000   # ~37 GB of host RAM at 144 KiB/token
    pcie_tok_s: float = 140_000.0   # ~20 GB/s effective / 144 KiB per token
    budget: int = 8192              # prefill token budget per iteration
    t0: float = 0.012               # s per iteration (weights read + launch)
    c_pf: float = 1.0e-4            # s per prefill token (~10k tok/s)
    c_dec: float = 2.0e-4           # s per decoding sequence
    c_att: float = 1.0e-7           # s per resident context token of running seqs
    warmup: float = 120.0
    horizon: float = 1320.0         # 20 min measured after warm-up
    seed: int = 0


@dataclass
class Agent:
    i: int
    ctx: int = 0
    kv: int = 0             # GPU-resident prefix tokens
    host: int = 0           # host-resident tokens right after the GPU prefix
    state: str = "pause"    # wait | run | pause
    pin_until: float = 0.0
    est_return: float = math.inf   # policy's estimate of when the pause ends (oracle/noisy only)
    last_used: float = 0.0
    task_start: float = 0.0
    arrival: float = 0.0
    wake_t: float = -1.0
    ready_at: float = 0.0   # host->GPU reload finishes
    turn: int = 0
    prefill_left: int = 0
    decode_left: int = 0
    first_tok: bool = False
    recomp: int = 0
    live: bool = False      # holds an admitted task (keep-ac accounting)


def make_policy(cfg, nrng):
    """Returns (ttl(a, T, now) -> seconds, est(a, T, now) -> est return time or inf, hist)."""
    p = cfg.policy
    hist = []
    inf = lambda a, T, now: math.inf  # noqa: E731
    if p == "lru":
        return (lambda a, T, now: 0.0), inf, hist
    if p in ("keep", "keep-ac"):
        return (lambda a, T, now: math.inf), inf, hist
    if p.startswith("ttl:"):
        x = float(p[4:]); return (lambda a, T, now: x), inf, hist
    if p == "cont2":
        return (lambda a, T, now: 2.0 if (not hist or np.mean(hist) < 2.0) else 0.0), inf, hist
    if p == "contpaper":
        def f(a, T, now):
            if len(hist) < 10:
                return 2.0  # cold start: behave like the released code
            h = np.sort(hist[-2000:]); cdf = np.arange(1, len(h) + 1) / len(h)
            B = cfg.c_pf * a.ctx + cfg.t0 * math.ceil(a.ctx / cfg.budget)
            score = cdf * B - (a.ctx / cfg.ctx) * h
            k = int(np.argmax(score))
            return float(h[k]) if score[k] > 0 else 0.0
        return f, inf, hist
    if p.startswith("oracle:"):
        th = float(p[7:])
        return (lambda a, T, now: T + 1e-6 if T <= th else 0.0), (lambda a, T, now: now + T), hist
    if p.startswith("noisy:"):
        _, s, th = p.split(":"); s, th = float(s), float(th)
        cache = {}

        def est(a, T, now):
            e = T * math.exp(s * nrng.standard_normal()); cache[a.i] = e
            return now + e
        return (lambda a, T, now: cache[a.i] if cache[a.i] <= th else 0.0), est, hist
    raise ValueError(p)


def simulate(cfg: Cfg):
    rng = np.random.default_rng(cfg.seed)
    prng = np.random.default_rng([cfg.seed, 7])   # pauses: identical stream across policies
    nrng = np.random.default_rng([cfg.seed, 11])  # estimator noise
    if cfg.pause_file:
        emp = np.loadtxt(cfg.pause_file, ndmin=1)
        draw = lambda: float(emp[prng.integers(len(emp))]) * cfg.pause_scale  # noqa: E731
    else:
        draw = lambda: float(pauses.sample(prng, mix=cfg.mix)) * cfg.pause_scale  # noqa: E731
    ttl, est, hist = make_policy(cfg, nrng)
    belady = cfg.policy.startswith(("oracle:", "noisy:"))
    ac = cfg.policy == "keep-ac"
    per_turn = cfg.tool_in + cfg.out
    c0 = max(256, cfg.ctx - cfg.turns * per_turn // 2)
    max_task_ctx = c0 + (cfg.turns - 1) * cfg.tool_in + cfg.turns * cfg.out
    M, H = cfg.kv_tokens, (cfg.host_kv_tokens if cfg.offload else 0)
    agents = [Agent(i) for i in range(cfg.sessions)]
    wake = []
    st = dict(used=0, host_used=0, recomputed=0, reloaded=0, preempt=0, brk_events=0, brk_tokens=0,
              pinned_token_s=0.0, live=0)
    tasks, resumes, gen = [], [], []

    for a, s in zip(agents, rng.uniform(0, 20.0, cfg.sessions)):
        heapq.heappush(wake, (s, a.i, "new"))

    def prio(a):
        return a.task_start if cfg.sched == "program" else a.arrival

    def order(cands, now):
        if belady:  # farthest estimated return first; overdue estimates count as "returning now"
            return sorted(cands, key=lambda b: -max(b.est_return, now))
        return sorted(cands, key=lambda b: b.last_used)

    def drop_host(b, n):
        n = min(n, b.host); b.host -= n; st["host_used"] -= n; return n

    def host_make_room(n, now, exclude):
        free = H - st["host_used"]
        if free >= n:
            return True
        cands = order([b for b in agents if b.host > 0 and b.i not in exclude and b.state == "pause"], now)
        for b in cands:
            free += drop_host(b, n - free)
            if free >= n:
                return True
        return False

    def evict(need, now, exclude, pinned):
        """Free `need` GPU tokens from paused agents (tail-first). pinned=True is the breaker."""
        freed = 0
        cands = [b for b in agents if b.state == "pause" and b.kv > 0 and b.i not in exclude
                 and (pinned or b.pin_until <= now)]
        for b in order(cands, now):
            if freed >= need:
                break
            take = min(b.kv, need - freed)
            b.kv -= take; st["used"] -= take; freed += take
            if H and host_make_room(take, now, exclude | {b.i}):
                b.host += take; st["host_used"] += take       # moved, contiguous with the host part
            else:
                drop_host(b, b.host)                          # a gap makes the host part useless
        return freed

    def end_task(a):
        st["used"] -= a.kv; a.kv = 0; drop_host(a, a.host)
        if a.live:
            a.live = False; st["live"] -= 1

    def start_task(a, now):
        end_task(a)
        a.ctx = c0; a.turn = 0; a.task_start = now; a.arrival = now; a.wake_t = -1.0
        a.state = "wait"; a.prefill_left = c0; a.decode_left = cfg.out; a.first_tok = False
        a.recomp = 0; a.est_return = math.inf; a.pin_until = 0.0

    running = []
    t = 0.0
    while t < cfg.horizon:
        while wake and wake[0][0] <= t:
            _, i, kind = heapq.heappop(wake)
            a = agents[i]
            if kind == "new":
                start_task(a, t); continue
            usable = a.kv + a.host
            a.recomp = max(0, a.ctx - usable)
            a.ctx += cfg.tool_in
            a.state = "wait"; a.arrival = t; a.wake_t = t
            a.prefill_left = a.ctx - usable
            a.decode_left = cfg.out; a.first_tok = False; a.est_return = math.inf

        # admission
        waiting = sorted((a for a in agents if a.state == "wait"), key=prio)
        for a in waiting:
            if ac and not a.live:
                if (st["live"] + 1) * max_task_ctx > M:
                    if cfg.sched == "program":
                        break
                    continue
            need = a.ctx - a.kv          # host part + recompute + new tokens all need GPU room
            free = M - st["used"]
            if need > free:
                free += evict(need - free, t, {a.i}, pinned=False)
            if need > free and not running:
                got = evict(need - free, t, {a.i}, pinned=True)
                if got:
                    st["brk_events"] += 1; st["brk_tokens"] += got; free += got
            if need > free:
                if cfg.sched == "program":
                    break
                continue
            if ac and not a.live:
                a.live = True; st["live"] += 1
            # a.kv counts *allocated* GPU tokens: the whole context is allocated at admission
            # (resident prefix + reloaded host part + room for the prefill still to compute).
            if a.host:
                a.ready_at = t + a.host / cfg.pcie_tok_s
                st["reloaded"] += a.host; st["host_used"] -= a.host; a.host = 0
            else:
                a.ready_at = t
            st["used"] += need; a.kv = a.ctx
            st["recomputed"] += a.recomp; a.recomp = 0
            a.state = "run"; running.append(a)

        active = [a for a in running if a.ready_at <= t]
        if not active:
            nxt = [a.ready_at for a in running]
            if wake:
                nxt.append(wake[0][0])
            if not nxt:
                break
            t = max(t, min(nxt)); continue

        # one engine iteration
        active.sort(key=prio)
        budget = cfg.budget
        pf_tokens = 0
        decoders = [a for a in active if a.prefill_left == 0]
        budget -= len(decoders)
        for a in active:
            if a.prefill_left > 0 and budget > 0:
                take = min(a.prefill_left, budget)
                a.prefill_left -= take; budget -= take; pf_tokens += take
        grow = len(decoders)
        free = M - st["used"]
        if grow > free:
            free += evict(grow - free, t, {a.i for a in running}, pinned=False)
        running.sort(key=prio)
        while grow > free and len(running) > 1:
            v = running.pop()  # lowest priority
            if v in decoders:
                decoders.remove(v); grow -= 1
            if v in active:
                active.remove(v)
            st["used"] -= v.kv; free += v.kv
            v.recomp = v.ctx - v.prefill_left   # everything already computed is recomputed
            v.kv = 0; v.prefill_left = v.ctx; v.state = "wait"; st["preempt"] += 1
        resident = sum(a.kv for a in active)
        dt = cfg.t0 + cfg.c_pf * pf_tokens + cfg.c_dec * len(decoders) + cfg.c_att * resident
        st["pinned_token_s"] += dt * sum(b.kv for b in agents if b.state == "pause" and b.pin_until > t)
        t += dt
        for a in decoders:
            a.kv += 1; st["used"] += 1; a.ctx += 1; a.decode_left -= 1; a.last_used = t
            if not a.first_tok:
                a.first_tok = True
                if a.turn > 0 and a.wake_t >= cfg.warmup:
                    resumes.append(t - a.wake_t)
            if a.decode_left == 0:
                running.remove(a)
                if a.turn > 0 and a.wake_t >= cfg.warmup:
                    gen.append(t - a.wake_t)
                a.turn += 1
                if a.turn == cfg.turns:
                    if a.task_start >= cfg.warmup:
                        tasks.append(t - a.task_start)
                    a.state = "pause"
                    heapq.heappush(wake, (t, a.i, "new"))
                else:
                    T = draw()
                    a.state = "pause"
                    a.est_return = est(a, T, t)
                    a.pin_until = t + ttl(a, T, t)
                    hist.append(T)
                    heapq.heappush(wake, (t + T, a.i, "resume"))

    tasks, resumes, gen = np.array(tasks), np.array(resumes), np.array(gen)
    span = cfg.horizon - cfg.warmup

    def q(x, p):
        return float(np.percentile(x, p)) if len(x) else float("nan")
    return dict(
        ctx=cfg.ctx, sessions=cfg.sessions, mix=cfg.mix if not cfg.pause_file else "file",
        pause_scale=cfg.pause_scale, policy=cfg.policy, sched=cfg.sched, offload=int(cfg.offload),
        seed=cfg.seed, kv_tokens=M, tasks=len(tasks), throughput=len(tasks) / span,
        task_p50=q(tasks, 50), task_p95=q(tasks, 95), task_mean=float(tasks.mean()) if len(tasks) else float("nan"),
        resume_p50=q(resumes, 50), resume_p95=q(resumes, 95),
        gen_mean=float(gen.mean()) if len(gen) else float("nan"),   # tool return -> turn done
        pause_mean=float(np.mean(hist)) if hist else float("nan"),
        recomputed=int(st["recomputed"]), reloaded=int(st["reloaded"]), preemptions=st["preempt"],
        breaker_events=st["brk_events"], breaker_tokens=int(st["brk_tokens"]),
        pinned_token_s=st["pinned_token_s"])
