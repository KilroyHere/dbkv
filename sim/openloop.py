"""Open-loop extension of the G1 simulator: Poisson task arrivals of the real explore SQL agent.

Workload: each arriving task replays one real task (sampled with replacement) from the frozen agent's
explore arm on all 1,534 BIRD dev questions (job 60873599, concurrency 8). Only token counts and tool
times are taken from the trace (its timing fields reflect c = 8 load):
  turn k: prompt P_k tokens, of which cached_k were a prefix-cache hit at c = 8 (low KV pressure, so
          cached_k is the reusable part of the previous turn's context: Qwen3's chat template does not
          re-emit everything the model decoded, so cached_k < P_{k-1} + O_{k-1} by ~16-50 tokens);
          then decode O_k tokens; then pause = that turn's tool runtime + a fixed off-GPU per-turn
          overhead (HTTP + API server + agent, measured client_s - server time at c = 8, median 15 ms).
  The ~464-token system prompt is shared by every task and stays resident (charged to the pool once).

Engine: kvsim's iteration model (kvsim.py v2), re-implemented for a dynamic task population:
  * KV pool M tokens (139,232 measured); a paused task's private KV stays resident until evicted
    (LRU, tail-first). On resume the task reuses min(resident, cached_k) and recomputes the rest.
  * Chunked prefill with a per-iteration token budget (vLLM's API-server default on a <70 GB GPU is
    2048); max 256 running sequences; decode 1 token per running sequence per iteration.
  * Waiting requests are admitted in priority order; a request needs GPU KV for its whole prompt
    minus its resident prefix; if it doesn't fit, admission stops (vLLM V1 breaks on the head).
  * If decode growth can't be allocated (after evicting paused KV), the lowest-priority running
    request is preempted and later recomputed from scratch.
  * Iteration time = t0 + c_pf*prefill_tokens + c_dec*decoding_seqs + c_att*context_tokens_of_running
    (g3_costs.json). Context tokens per running sequence include the shared prefix.

Policies:
  stock      request-arrival FCFS, no gateway limit
  priority   priority = task arrival (program FCFS); preemption hits the lowest priority first
  admission  gateway admits at most K tasks; the rest wait in a FIFO queue (wait counts in task time)
  both       admission + priority
(Stock also preempts the lowest-priority = most recently arrived request, as kvsim does.)
"""
import heapq, json, math, os
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TRACE = os.path.expandvars("$SCRATCH/dbkv/runs/d2/60873599/explore")
COSTS = os.path.join(HERE, "..", "results", "g3_costs.json")
SHARED = 464          # system-prompt tokens every task shares (turn-1 cached_tokens for 1,512/1,534 tasks)
OVH = 0.015           # s off-GPU per turn (client_s - queue - prefill - decode, median at c = 8)


def load_traces(path=TRACE, shared=SHARED, ovh=OVH):
    """Returns a list of tasks; each is a tuple of int/float arrays (P, C, O, W) in private tokens."""
    by = {}
    with open(os.path.join(path, "turns.jsonl")) as f:
        for line in f:
            t = json.loads(line)
            by.setdefault(t["qid"], []).append(t)
    tasks = []
    for q in sorted(by):
        v = sorted(by[q], key=lambda x: x["turn"])
        P = np.array([max(1, x["prompt_tokens"] - shared) for x in v], dtype=np.int64)
        C = np.array([max(0, (x["cached_tokens"] or 0) - shared) for x in v], dtype=np.int64)
        C[0] = 0
        O = np.array([max(1, x["output_tokens"]) for x in v], dtype=np.int64)
        W = np.array([sum((tt.get("runtime_s") or 0.0) for tt in x["tools"]) + ovh for x in v])
        tasks.append((P, C, O, W))
    return tasks


@dataclass
class OCfg:
    lam: float = 100.0              # task arrivals per minute (open loop)
    closed: int = 0                 # >0: closed loop with this many concurrent agents instead
    policy: str = "stock"           # stock | priority | admission | both
    K: int = 0                      # gateway limit for admission/both
    kv_tokens: int = 139_232
    shared: int = SHARED
    budget: int = 2048
    max_seqs: int = 256
    t0: float = 0.011592
    c_pf: float = 8.736e-05
    c_dec: float = 7.23e-05
    c_att: float = 8.145e-08
    warmup: float = 120.0
    measure: float = 480.0
    drain: float = 600.0            # keep simulating (arrivals continue) so in-window tasks can finish
    seed: int = 0
    track_ctx: bool = False         # time-average of active-task context (for K)


def load_costs(path=COSTS):
    with open(path) as f:
        return json.load(f)


class T:  # one task in flight
    __slots__ = ("id", "tr", "turn", "arr", "admit", "rq_arr", "kv", "ctx", "state", "pf", "dec",
                 "last", "done")

    def __init__(self, i, tr, arr):
        self.id = i; self.tr = tr; self.turn = 0; self.arr = arr; self.admit = -1.0
        self.rq_arr = arr; self.kv = 0; self.ctx = 0; self.state = "gw"; self.pf = 0; self.dec = 0
        self.last = arr; self.done = -1.0


def simulate(cfg: OCfg, traces):
    rng = np.random.default_rng(cfg.seed)
    M = cfg.kv_tokens - cfg.shared
    prio_task = cfg.policy in ("priority", "both")
    gate = cfg.policy in ("admission", "both")
    end_win = cfg.warmup + cfg.measure
    t_end = end_win + cfg.drain
    ev = []                 # (time, seq, kind, task)
    seq = 0
    st = dict(used=0, preempt=0, recomputed=0, prefill=0, idle=0.0, busy=0.0, active_tw=0.0,
              ctx_tw=0.0, tw=0.0, run_tw=0.0, iters=0)
    gwq = []                # gateway FIFO
    active_n = 0            # tasks admitted past the gateway and not finished
    waiting, running, paused = [], [], set()
    alltasks = []
    nid = 0
    # snapshots of the gateway queue + active tasks at window start/end (for capacity)
    snap = {}

    def prio(a):
        return a.arr if prio_task else a.rq_arr

    def push(t, kind, a):
        nonlocal seq
        heapq.heappush(ev, (t, seq, kind, a)); seq += 1

    def new_task(now):
        nonlocal nid
        a = T(nid, traces[rng.integers(len(traces))], now); nid += 1
        alltasks.append(a)
        return a

    def admit_gw(now):
        nonlocal active_n
        while gwq and (not gate or active_n < cfg.K):
            a = gwq.pop(0); active_n += 1; a.admit = now
            start_turn(a, now)

    def start_turn(a, now):
        P, C, O, W = a.tr
        k = a.turn
        reuse = min(a.kv, int(C[k])) if k else 0
        if a.kv > reuse:
            st["used"] -= a.kv - reuse
        st["recomputed"] += (int(C[k]) - reuse) if k else 0
        a.kv = reuse
        a.ctx = int(P[k]); a.pf = a.ctx - reuse; a.dec = int(O[k])
        a.state = "wait"; a.rq_arr = now
        paused.discard(a)
        waiting.append(a)

    def evict(need, now, me=None):
        """LRU, tail-first, over KV not held by a running request: paused tasks' prefixes and the
        resident prefixes of waiting requests (in vLLM both are free-but-cached blocks)."""
        freed = 0
        cands = [b for b in paused if b.kv > 0] + [b for b in waiting if b.kv > 0 and b is not me]
        for b in sorted(cands, key=lambda b: b.last):
            if freed >= need:
                break
            take = min(b.kv, need - freed)
            b.kv -= take; st["used"] -= take; freed += take
            if b.state == "wait":
                st["recomputed"] += take
        return freed

    if cfg.closed:
        for _ in range(cfg.closed):
            push(float(rng.uniform(0, 5.0)), "arr", None)
    else:
        push(float(rng.exponential(60.0 / cfg.lam)), "arr", None)

    t = 0.0
    while t < t_end:
        while ev and ev[0][0] <= t:
            te, _, kind, a = heapq.heappop(ev)
            if kind == "arr":
                b = new_task(te); gwq.append(b)
                if not cfg.closed:
                    push(te + float(rng.exponential(60.0 / cfg.lam)), "arr", None)
            else:  # resume after a pause
                start_turn(a, te)
        admit_gw(t)
        if "s" not in snap and t >= cfg.warmup:
            snap["s"] = (len(gwq), active_n)
        if "e" not in snap and t >= end_win:
            snap["e"] = (len(gwq), active_n)

        # engine admission (waiting -> running), in priority order, stop at the first that can't fit
        if waiting:
            waiting.sort(key=prio)
            k = 0
            while k < len(waiting) and len(running) < cfg.max_seqs:
                a = waiting[k]
                need = a.ctx - a.kv
                free = M - st["used"]
                if need > free:
                    free += evict(need - free, t, a)
                if need > free:
                    break
                st["used"] += need; a.pf = a.ctx - a.kv; a.kv = a.ctx; a.state = "run"
                running.append(a); k += 1
            del waiting[:k]

        if not running:
            nxt = ev[0][0] if ev else t_end
            if t >= cfg.warmup and t < end_win:
                st["idle"] += min(nxt, end_win) - t
            t = max(t, nxt)
            continue

        running.sort(key=prio)
        budget = cfg.budget
        decoders = [a for a in running if a.pf == 0]
        budget -= len(decoders)
        pf_tok = 0
        for a in running:
            if a.pf > 0 and budget > 0:
                take = min(a.pf, budget); a.pf -= take; budget -= take; pf_tok += take
        grow = len(decoders)
        free = M - st["used"]
        if grow > free:
            free += evict(grow - free, t)
        while grow > free and len(running) > 1:
            v = running.pop()
            if v in decoders:
                decoders.remove(v); grow -= 1
            st["used"] -= v.kv; free += v.kv
            st["recomputed"] += v.ctx - v.pf
            v.kv = 0; v.pf = v.ctx; v.state = "wait"; st["preempt"] += 1
            waiting.append(v)
        ctx_run = sum(a.kv for a in running) + cfg.shared * len(running)
        dt = cfg.t0 + cfg.c_pf * pf_tok + cfg.c_dec * len(decoders) + cfg.c_att * ctx_run
        st["prefill"] += pf_tok
        if t >= cfg.warmup and t < end_win:
            st["busy"] += dt; st["iters"] += 1
            st["run_tw"] += dt * len(running)
            if cfg.track_ctx:
                # context of every active task (admitted, unfinished): resident/allocated + shared
                act = [x for x in alltasks if x.admit >= 0 and x.done < 0]
                st["active_tw"] += dt * len(act)
                st["ctx_tw"] += dt * sum(max(x.ctx, x.kv) + cfg.shared for x in act)
                st["tw"] += dt
        t += dt
        for a in decoders:
            a.kv += 1; st["used"] += 1; a.ctx += 1; a.dec -= 1; a.last = t
            if a.dec == 0:
                running.remove(a)
                P, C, O, W = a.tr
                if a.turn == len(P) - 1:
                    st["used"] -= a.kv; a.kv = 0; a.state = "done"; a.done = t + OVH
                    active_n -= 1
                    if cfg.closed:
                        push(t + OVH, "arr", None)
                else:
                    a.state = "pause"; paused.add(a)
                    push(t + float(W[a.turn]), "res", a)
                    a.turn += 1

    # ---- metrics
    win = [a for a in alltasks if cfg.warmup <= a.arr < end_win]
    fin = np.array([a.done - a.arr for a in win if a.done > 0])
    unfinished = [t_end - a.arr for a in win if a.done < 0]
    # censored tasks count with their elapsed time (a lower bound) so percentiles aren't flattered
    allt = np.concatenate([fin, np.array(unfinished)]) if unfinished else fin
    wait = np.array([a.admit - a.arr for a in win if a.admit >= 0])
    compl_in_win = [a for a in alltasks if cfg.warmup <= a.done < end_win]
    ct = np.array([a.done - a.arr for a in compl_in_win])
    mins = cfg.measure / 60.0

    def q(x, p):
        return float(np.percentile(x, p)) if len(x) else float("nan")
    out = dict(policy=cfg.policy, lam=cfg.lam, closed=cfg.closed, K=cfg.K, seed=cfg.seed,
               measure=cfg.measure, arrived=len(win), finished=len(fin), unfinished=len(unfinished),
               p50=q(allt, 50), p95=q(allt, 95), mean=float(allt.mean()) if len(allt) else float("nan"),
               thr=len(compl_in_win) / mins, compl_ratio=len(compl_in_win) / max(1, len(win)),
               p50_done_in_win=q(ct, 50), p95_done_in_win=q(ct, 95),
               wait_mean=float(wait.mean()) if len(wait) else float("nan"), wait_p95=q(wait, 95),
               preempt=st["preempt"], recomputed=st["recomputed"],
               idle_frac=st["idle"] / cfg.measure,
               iter_ms=1000 * st["busy"] / max(1, st["iters"]), mean_running=st["run_tw"] / cfg.measure,
               gw_q_start=snap.get("s", (0, 0))[0], gw_q_end=snap.get("e", (0, 0))[0],
               active_start=snap.get("s", (0, 0))[1], active_end=snap.get("e", (0, 0))[1])
    if cfg.track_ctx and st["tw"] > 0:
        out["mean_active"] = st["active_tw"] / st["tw"]
        out["ctx_per_active"] = st["ctx_tw"] / max(1e-9, st["active_tw"])
    return out


def cfg_from_costs(**kw):
    c = load_costs()
    base = dict(t0=c["t0"], c_pf=c["c_pf"], c_dec=c["c_dec"], c_att=c["c_att"], kv_tokens=c["kv_tokens"])
    base.update(kw)
    return OCfg(**base)


if __name__ == "__main__":
    import argparse, time
    ap = argparse.ArgumentParser()
    ap.add_argument("--lam", type=float, default=100)
    ap.add_argument("--closed", type=int, default=0)
    ap.add_argument("--policy", default="stock")
    ap.add_argument("--K", type=int, default=0)
    ap.add_argument("--measure", type=float, default=480)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    tr = load_traces()
    t = time.time()
    r = simulate(cfg_from_costs(lam=a.lam, closed=a.closed, policy=a.policy, K=a.K,
                                measure=a.measure, seed=a.seed, track_ctx=True), tr)
    r["wall_s"] = round(time.time() - t, 1)
    print(json.dumps(r, indent=1))
