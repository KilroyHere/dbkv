"""Option C allocation policy: pure functions, no vLLM import.

Per step, with a token budget B:
  1. every running decode request gets its 1 verified token (decode first);
  2. the remainder R = B - n_decode is shared between draft (speculative)
     tokens and pending prefill tokens.

Value model. A request whose drafts are accepted position by position with
probability p (the conditional per-position acceptance) gets, from its k-th
draft token, an expected p**k extra tokens (token k counts only if tokens
1..k-1 were accepted too). One prefill token is worth `theta` such tokens:
`theta` is the exchange rate knob.

Allocation (greedy on marginal value, which is optimal here because p**k is
decreasing in k, so each request's chosen drafts are always a prefix):
  a. draft tokens with value >= theta, best first, up to R;
  b. prefill gets min(prefill_demand, what is left);
  c. if `fill_leftover`, draft tokens with value in [min_value, theta) take
     what is still left (this is what the static setting would have run).
Draft tokens with value < min_value are never scheduled.

theta = 0  -> drafts first (close to static speculation, but with a decode
              floor and acceptance-ordered trimming when B binds);
theta > 1  -> prefill first; drafts only use leftover budget.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Knobs:
    """Policy knobs, read from DBKV_JOINTSPEC_* env vars by `from_env`."""

    enabled: bool = False
    # Token budget per step. 0 = use vLLM's max_num_scheduled_tokens.
    # A value below it makes the budget bind (the GPU is compute-bound, so a
    # smaller step budget is the "free compute" being shared).
    budget: int = 0
    # Exchange rate: one prefill token is worth `theta` expected accepted
    # draft tokens. Draft tokens with p**k >= theta beat prefill.
    theta: float = 0.5
    # Never schedule a draft token whose expected value p**k is below this.
    min_value: float = 0.0
    # After prefill is served, give remaining budget to low-value drafts.
    fill_leftover: bool = True
    # EWMA decay per observation for acceptance counts (per request and global).
    ewma: float = 0.9
    # Prior pseudo-counts for the per-request estimate, centred on the global
    # estimate. Agent turns are short (p50 21 output tokens), so the global
    # rate dominates early in a request.
    prior_weight: float = 4.0
    # Initial global acceptance (PLAN 2h: 0.58-0.63 accepted/drafted on 8B).
    p_init: float = 0.6
    # Expected prefix-cache hit fraction for WAITING requests' prompts
    # (Phase 1: 93-95%); only used to estimate prefill demand.
    wait_hit: float = 0.9
    # Move running decode requests ahead of running prefill chunks.
    decode_first: bool = True
    # Optional JSONL decision log path ('' = off) and its sampling stride.
    log_path: str = ""
    log_every: int = 1

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Knobs":
        e = os.environ if env is None else env

        def f(name, default, conv):
            v = e.get("DBKV_JOINTSPEC_" + name)
            return default if v is None or v == "" else conv(v)

        def b(v: str) -> bool:
            return v.strip().lower() in ("1", "true", "yes", "on")

        enabled = b(e.get("DBKV_JOINTSPEC", "0"))
        return cls(
            enabled=enabled,
            budget=f("BUDGET", 0, int),
            theta=f("THETA", 0.5, float),
            min_value=f("MIN_VALUE", 0.0, float),
            fill_leftover=f("FILL_LEFTOVER", True, b),
            ewma=f("EWMA", 0.9, float),
            prior_weight=f("PRIOR", 4.0, float),
            p_init=f("P_INIT", 0.6, float),
            wait_hit=f("WAIT_HIT", 0.9, float),
            decode_first=f("DECODE_FIRST", True, b),
            log_path=f("LOG", "", str),
            log_every=max(1, f("LOG_EVERY", 1, int)),
        )


@dataclass
class Allocation:
    spec: dict  # req_id -> number of draft tokens to keep
    prefill: int  # prefill tokens the policy reserved
    n_decode: int
    budget: int
    spec_hi: int = 0  # drafts placed before prefill
    spec_lo: int = 0  # drafts placed in leftover budget

    @property
    def n_spec(self) -> int:
        return sum(self.spec.values())

    @property
    def used(self) -> int:
        return self.n_decode + self.n_spec + self.prefill


def _clamp_p(p: float) -> float:
    return min(max(p, 1e-6), 1.0 - 1e-9)


def _n_at_least(p: float, n_avail: int, v: float) -> int:
    """Number of draft positions k in 1..n_avail with p**k >= v."""
    if n_avail <= 0:
        return 0
    if v <= 0.0:
        return n_avail
    if v > 1.0:
        return 0
    p = _clamp_p(p)
    # p**k >= v  <=>  k <= log v / log p   (log p < 0)
    k = int(math.floor(math.log(v) / math.log(p) + 1e-9))
    return max(0, min(n_avail, k))


def _take_best(drafts, already: dict, lo_v: float, hi_v: float, limit: int) -> dict:
    """Greedy: among draft positions with value in [lo_v, hi_v) not yet taken,
    take up to `limit` of the highest value. Returns extra counts per request.
    Ties broken by smaller k first, then by request order (stable)."""
    if limit <= 0:
        return {}
    items = []  # (-value, k, idx, rid)
    for idx, (rid, n_avail, p) in enumerate(drafts):
        k0 = already.get(rid, 0)
        k_hi = _n_at_least(p, n_avail, lo_v)
        lp = math.log(_clamp_p(p))
        for k in range(k0 + 1, k_hi + 1):
            val = math.exp(k * lp)
            if val >= hi_v:
                continue
            items.append((-val, k, idx, rid))
    if len(items) > limit:
        items.sort()
        items = items[:limit]
    extra: dict = {}
    for _, _, _, rid in items:
        extra[rid] = extra.get(rid, 0) + 1
    return extra


def allocate(
    budget: int,
    n_decode: int,
    drafts: list,
    prefill_demand: int,
    theta: float = 0.5,
    min_value: float = 0.0,
    fill_leftover: bool = True,
) -> Allocation:
    """Split one step's budget. `drafts` is a list of (req_id, n_available,
    p_accept) for running decode requests that have drafts. Pure function."""
    budget = max(0, int(budget))
    n_decode = max(0, int(n_decode))
    prefill_demand = max(0, int(prefill_demand))
    rem = max(0, budget - n_decode)
    spec: dict = {}

    hi_floor = max(theta, min_value)
    hi = _take_best(drafts, spec, hi_floor, math.inf, rem)
    for rid, k in hi.items():
        spec[rid] = spec.get(rid, 0) + k
    n_hi = sum(hi.values())
    rem -= n_hi

    prefill = min(prefill_demand, rem)
    rem -= prefill

    n_lo = 0
    if fill_leftover and rem > 0 and min_value < hi_floor:
        lo = _take_best(drafts, spec, min_value, hi_floor, rem)
        for rid, k in lo.items():
            spec[rid] = spec.get(rid, 0) + k
        n_lo = sum(lo.values())

    # Keep requests with 0 drafts explicit so the caller trims them.
    for rid, n_avail, _ in drafts:
        spec.setdefault(rid, 0)
    return Allocation(spec, prefill, n_decode, budget, n_hi, n_lo)


@dataclass
class _Acc:
    acc: float = 0.0  # EWMA accepted positions
    trials: float = 0.0  # EWMA trials (accepted + 1 if a rejection ended it)


@dataclass
class AcceptanceTracker:
    """Per-position conditional acceptance estimate, per request and global.

    One verification step with n drafted and m accepted tokens (m <= n,
    accepted tokens are a prefix) is m successes and, if m < n, one failure
    of a geometric process: the MLE of p is m / (m + [m < n]).
    """

    ewma: float = 0.9
    prior_weight: float = 4.0
    p_init: float = 0.6
    glob: _Acc = field(default_factory=_Acc)
    per_req: dict = field(default_factory=dict)

    def __post_init__(self):
        # Seed the global estimate with prior_weight pseudo-trials.
        w = max(self.prior_weight, 1.0)
        self.glob = _Acc(self.p_init * w, w)

    def observe(self, req_id, n_draft: int, n_accepted: int) -> None:
        if n_draft <= 0:
            return
        m = max(0, min(int(n_accepted), int(n_draft)))
        t = m + (1 if m < n_draft else 0)
        g = self.glob
        g.acc = self.ewma * g.acc + m
        g.trials = self.ewma * g.trials + t
        r = self.per_req.get(req_id)
        if r is None:
            r = self.per_req[req_id] = _Acc()
        r.acc = self.ewma * r.acc + m
        r.trials = self.ewma * r.trials + t

    def global_p(self) -> float:
        g = self.glob
        return g.acc / g.trials if g.trials > 0 else self.p_init

    def p(self, req_id) -> float:
        pg = self.global_p()
        r = self.per_req.get(req_id)
        if r is None:
            return pg
        w = self.prior_weight
        return (r.acc + w * pg) / (r.trials + w)

    def forget(self, live_ids) -> None:
        live = set(live_ids)
        for rid in [k for k in self.per_req if k not in live]:
            del self.per_req[rid]
