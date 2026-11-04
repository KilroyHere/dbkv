"""G1: iteration-level simulator of N SQL agents sharing one GPU's KV pool.

Workload (same shape as harness/replay.py): each agent runs tasks of TURNS LLM turns on one growing
context. Turn 0 prefills a fresh context of C0 tokens; each later turn follows a SQL pause, appends
TOOL_IN tokens and decodes OUT tokens. C0 = C - TURNS*(TOOL_IN+OUT)/2, so the context averages ~C.

Engine (vLLM-like, simplified):
  * KV pool of M tokens. A paused agent's KV stays resident ("cached") until evicted.
  * Retention policy = a pin TTL chosen when the agent pauses. Pinned KV is never evicted (except to
    break a deadlock); after the TTL it is ordinary prefix cache, evicted LRU-first, tail-first.
  * Admission: waiting requests in priority order (program-level FCFS = task start time, or
    request-arrival FCFS for stock vLLM). A request needs KV for ctx - resident tokens.
  * Chunked prefill with a per-iteration token budget; decode 1 token per running request.
    If decode growth can't be allocated, the lowest-priority running request is preempted (recompute).
  * Iteration time = t0 + c_pf*prefill_tokens + c_dec*decoding_seqs + c_att*resident_tokens_of_running.
    Defaults are back-of-envelope A100-40GB / Qwen3-8B numbers; G3 replaces them with measurements.

Policies (TTL at pause start; T = true pause length):
  lru            stock vLLM: TTL 0 (KV is cached, evictable)
  keep           TTL inf (always keep; deadlock breaker evicts LRU pinned)
  ttl:X          fixed per-tool TTL X seconds (the "Continuum best timeout" sweep)
  cont2          released Continuum code: pin 2 s if the tool's running-mean duration < 2 s, else 0
  contpaper      Continuum paper Eq. 1: tau* = argmax_tau P(T<=tau)*B(r) - (m_r/mean_m)*tau, with P from
                 this tool's history and B(r) = re-prefill time of the context (per tool, not per call)
  oracle:TH      knows T: pin for T if T <= TH, else TTL 0
  noisy:S:TH     like oracle but sees T*exp(S*z), z ~ N(0,1): a stand-in for EXPLAIN until G2
"""
import heapq, math
from dataclasses import dataclass, field

import numpy as np

try:
    from . import pauses
except ImportError:
    import pauses


@dataclass
class Cfg:
    ctx: int = 8192
    sessions: int = 16
    kv_tokens: int = 132_512        # prediction 1a (mid)
    turns: int = 6
    tool_in: int = 300
    out: int = 150
    mix: str = "redshift"
    policy: str = "lru"
    sched: str = "program"          # "program" (task-start FCFS) or "request" (arrival FCFS)
    budget: int = 8192              # prefill token budget per iteration
    t0: float = 0.012               # s per iteration (weights read + launch)
    c_pf: float = 1.0e-4            # s per prefill token (~10k tok/s)
    c_dec: float = 2.0e-4           # s per decoding sequence
    c_att: float = 1.0e-7           # s per resident context token of running seqs (~144 KiB / 1.5 TB/s)
    warmup: float = 120.0
    horizon: float = 1320.0         # 20 min measured after warm-up
    seed: int = 0


@dataclass
class Agent:
    i: int
    ctx: int = 0            # logical context tokens
    kv: int = 0             # resident tokens on GPU
    state: str = "wait"     # wait | run | pause
    pin_until: float = 0.0
    last_used: float = 0.0
    task_start: float = 0.0
    arrival: float = 0.0
    turn: int = 0
    prefill_left: int = 0
    decode_left: int = 0
    new_tokens: int = 0     # tokens that are genuinely new this turn (not recompute)
    first_tok: bool = False


def ttl_fn(cfg, rng):
    p = cfg.policy
    hist = []  # observed pause durations of the (single) SQL tool, for history-based policies

    if p == "lru":
        return lambda a, T: 0.0, hist
    if p == "keep":
        return lambda a, T: math.inf, hist
    if p.startswith("ttl:"):
        x = float(p[4:]); return lambda a, T: x, hist
    if p == "cont2":
        return lambda a, T: (2.0 if (not hist or np.mean(hist) < 2.0) else 0.0), hist
    if p == "contpaper":
        mean_m = cfg.ctx  # average request memory ~ the average context

        def f(a, T):
            if len(hist) < 10:
                return 2.0  # cold start: behave like the released code
            h = np.sort(hist[-2000:]); cdf = np.arange(1, len(h) + 1) / len(h)
            B = cfg.c_pf * a.ctx + cfg.t0 * math.ceil(a.ctx / cfg.budget)
            score = cdf * B - (a.ctx / mean_m) * h
            k = int(np.argmax(score))
            return float(h[k]) if score[k] > 0 else 0.0
        return f, hist
    if p.startswith("oracle:"):
        th = float(p[7:]); return lambda a, T: (T + 1e-6 if T <= th else 0.0), hist
    if p.startswith("noisy:"):
        _, s, th = p.split(":"); s, th = float(s), float(th)

        def f(a, T):
            est = T * math.exp(s * rng.standard_normal())
            return est if est <= th else 0.0
        return f, hist
    raise ValueError(p)


def simulate(cfg: Cfg):
    rng = np.random.default_rng(cfg.seed)
    prng = np.random.default_rng([cfg.seed, 7])   # pauses: identical stream across policies
    nrng = np.random.default_rng([cfg.seed, 11])  # estimator noise
    ttl, hist = ttl_fn(cfg, nrng)
    per_turn = cfg.tool_in + cfg.out
    c0 = max(256, cfg.ctx - cfg.turns * per_turn // 2)
    M = cfg.kv_tokens
    agents = [Agent(i) for i in range(cfg.sessions)]
    wake = []  # (time, agent) pause ends
    used = 0
    t = 0.0
    tasks, resumes = [], []
    recomputed = 0
    preempt = 0
    deadlock_evict = 0
    hold_time_pinned = 0.0  # token-seconds of pinned paused KV (memory cost of retention)

    def start_task(a, now):
        nonlocal used
        used -= a.kv; a.kv = 0
        a.ctx = c0; a.turn = 0; a.task_start = now; a.arrival = now
        a.state = "wait"; a.prefill_left = c0; a.new_tokens = c0; a.decode_left = cfg.out; a.first_tok = False

    # stagger initial arrivals over 20 s so the start isn't one giant burst
    starts = rng.uniform(0, 20.0, cfg.sessions)
    for a, s in zip(agents, starts):
        a.state = "pause"; heapq.heappush(wake, (s, a.i, "new"))

    def prio(a):
        return a.task_start if cfg.sched == "program" else a.arrival

    def evict(need, now, exclude, allow_pinned=False):
        """Free `need` tokens from paused agents' KV, LRU agent first. Returns tokens freed."""
        nonlocal used
        freed = 0
        cands = [b for b in agents if b.state == "pause" and b.kv > 0 and b.i not in exclude
                 and (allow_pinned or b.pin_until <= now)]
        cands.sort(key=lambda b: b.last_used)
        for b in cands:
            if freed >= need:
                break
            take = min(b.kv, need - freed)
            b.kv -= take; used -= take; freed += take
        return freed

    running = []
    while t < cfg.horizon:
        # wake agents whose pause ended
        while wake and wake[0][0] <= t:
            _, i, kind = heapq.heappop(wake)
            a = agents[i]
            if kind == "new":
                start_task(a, t); continue
            a.ctx += cfg.tool_in
            a.state = "wait"; a.arrival = t
            a.prefill_left = a.ctx - a.kv      # recompute anything evicted + the new tool tokens
            recomputed_now = max(0, a.prefill_left - cfg.tool_in)
            a.new_tokens = cfg.tool_in
            a.decode_left = cfg.out; a.first_tok = False
            a.recomp = recomputed_now
            a.wake_t = t

        # admission
        waiting = sorted((a for a in agents if a.state == "wait"), key=prio)
        for a in waiting:
            need = a.prefill_left
            free = M - used
            if need > free:
                free += evict(need - free, t, {a.i})
            if need > free and not running:
                free += evict(need - free, t, {a.i}, allow_pinned=True)
                deadlock_evict += 1
            if need > free:
                if cfg.sched == "program":
                    break  # strict FCFS: don't let later programs jump ahead
                continue
            a.kv += need; used += need
            a.state = "run"; running.append(a)
            if getattr(a, "recomp", 0):
                recomputed += a.recomp; a.recomp = 0

        if not running:
            if wake:
                t = max(t, wake[0][0]); continue
            break

        # one engine iteration
        running.sort(key=prio)
        budget = cfg.budget
        pf_tokens = 0
        decoders = [a for a in running if a.prefill_left == 0]
        budget -= len(decoders)
        for a in running:
            if a.prefill_left > 0 and budget > 0:
                take = min(a.prefill_left, budget)
                a.prefill_left -= take; budget -= take; pf_tokens += take
        # decode growth: +1 token each; preempt lowest priority if the pool is full
        grow = len(decoders)
        free = M - used
        if grow > free:
            free += evict(grow - free, t, {a.i for a in running})
        while grow > free and len(running) > 1:
            v = running.pop()  # lowest priority
            if v in decoders:
                decoders.remove(v); grow -= 1
            used -= v.kv; free += v.kv
            v.prefill_left = v.ctx; v.recomp = v.ctx; v.kv = 0
            v.state = "wait"; preempt += 1
        resident = sum(a.kv for a in running)
        dt = cfg.t0 + cfg.c_pf * pf_tokens + cfg.c_dec * len(decoders) + cfg.c_att * resident
        # memory cost of pinned paused KV over this step
        hold_time_pinned += dt * sum(b.kv for b in agents if b.state == "pause" and b.pin_until > t)
        t += dt
        for a in decoders:
            a.kv += 1; used += 1; a.ctx += 1; a.decode_left -= 1; a.last_used = t
            if not a.first_tok:
                a.first_tok = True
                if a.turn > 0 and getattr(a, "wake_t", None) is not None and a.wake_t >= cfg.warmup:
                    resumes.append(t - a.wake_t)
            if a.decode_left == 0:
                running.remove(a)
                a.turn += 1
                if a.turn == cfg.turns:
                    if a.task_start >= cfg.warmup:
                        tasks.append(t - a.task_start)
                    a.state = "pause"
                    heapq.heappush(wake, (t, a.i, "new"))
                else:
                    T = float(pauses.sample(prng, mix=cfg.mix))
                    a.state = "pause"
                    a.pin_until = t + ttl(a, T)
                    hist.append(T)
                    heapq.heappush(wake, (t + T, a.i, "resume"))

    tasks = np.array(tasks); resumes = np.array(resumes)
    span = cfg.horizon - cfg.warmup

    def q(x, p):
        return float(np.percentile(x, p)) if len(x) else float("nan")
    return dict(
        ctx=cfg.ctx, sessions=cfg.sessions, mix=cfg.mix, policy=cfg.policy, sched=cfg.sched, seed=cfg.seed,
        kv_tokens=M, tasks=len(tasks), throughput=len(tasks) / span,
        task_p50=q(tasks, 50), task_p95=q(tasks, 95), task_mean=float(tasks.mean()) if len(tasks) else float("nan"),
        resume_p50=q(resumes, 50), resume_p95=q(resumes, 95),
        recomputed=int(recomputed), preemptions=preempt, deadlock_evictions=deadlock_evict,
        pinned_token_s=hold_time_pinned)


if __name__ == "__main__":
    import sys, time
    for pol in sys.argv[1:] or ["lru", "keep", "cont2", "oracle:5"]:
        t = time.time()
        r = simulate(Cfg(ctx=8192, sessions=24, policy=pol, horizon=300, warmup=60))
        print(f"{pol:12s} {time.time() - t:5.1f}s  p50 {r['task_p50']:.2f}  p95 {r['task_p95']:.2f}  "
              f"tasks {r['tasks']}  recomputed {r['recomputed']}  preempt {r['preemptions']}  dl {r['deadlock_evictions']}")
