"""Goodput gateway (PLAN 2j, option B): task state from the tool channel -> lookup table -> value-based priority.

A *state* is what the gateway knows when a task sends the request for turn n (turns 1..n-1 are done):

    turn       n (= assistant messages so far + 1; nudge turns count, as in the agent's own loop)
    tenant     x-db header (tpch_sf10 / tpch_sf100 / tpcds_sf10)
    n_timeout  tool results that were "Error (timeout): ..." (60 s SQL timeouts)
    n_err      other tool errors ("Error (<class>): ...", "Error: no such table ...", "Error: unknown tool ...")
    n_ok       successful execute_sql calls
    since_ok   turns since the last turn with a successful execute_sql (None = never)
    last       what turn n-1 did: start (n = 1) / nudge (prose, no SQL) / explore / ok / err / timeout
    nudges     prose replies without a tool call or a final SQL block (the agent then sends NUDGE)
    out_tok    output tokens generated so far (the gateway sums usage.completion_tokens per task; estimated from
               the message text when it has no count)

Two sources give the same state: `features_from_messages` (the gateway: a chat request's `messages`) and
`StateAcc.add_turn_row` (the fitter: harness rows in turns.jsonl). test_goodput.py checks they agree on every
Phase 1 turn.

The table (`fit_goodput.py` writes it) is a hierarchy of binned keys, from coarse to fine (LEVELS). Every
observed key stores smoothed estimates of
    p    = P(task correct | state)
    out  = E[remaining output tokens | state]            (this turn and every later one)
    pre  = E[remaining uncached prompt tokens | state]   (prompt - cached, this turn and every later one)
    db   = E[remaining tool wall seconds | state]        (not LLM work; enters work only with db_weight > 0)
Smoothing: est_k = (sum_k + m * est_{k-1}) / (n_k + m), i.e. shrink each bin toward its parent with m pseudo-
requests. Lookup takes the deepest level whose key exists (a missing key's estimate equals its parent's).
value = p / work with work = out + prefill_weight * pre (+ db_weight * db). Priority for vLLM = round(-1000 * log10(value)),
so a higher value is served sooner (lower number). Pure dict lookups: ~10 us per request.
"""
import json, math, re

BINS_VERSION = 3

# The agent's own last-turn text and switch (harness/agent_duckdb/run_w.py, agent-32b-v1): a forced final turn
# appends this user message and sets tool_choice "none". test_goodput.py checks it is identical to run_w.LAST.
LAST = ("This is your last reply. Do not call tools. Give the final answer now as one DuckDB query in a "
        "```sql ... ``` block.")
NUDGE = ("Continue. Either call a tool, or, if you are done, reply with the final answer as one DuckDB query "
         "in a ```sql ... ``` block.")

_ERR_RE = re.compile(r"^Error \(([A-Za-z_]+)\):")


def tool_error_class(text):
    """Error class of a tool result text (tools_duckdb.call), or None for a successful result."""
    if not isinstance(text, str) or not text.startswith("Error"):
        return None
    m = _ERR_RE.match(text)
    if m:
        return m.group(1)
    if text.startswith("Error: no such table"):
        return "no_such_table"
    if text.startswith("Error: unknown tool"):
        return "unknown_tool"
    return None


# ---------- bins ----------
def b_turn(n):
    return min(max(int(n), 1), 15)


def b_count(c, caps):
    """Bin a count: caps = (0, 1, 2, 3) -> '0', '1', '2', '3+'; caps = (0, 1, 3) -> '0', '1-2', '3+'."""
    for i, lo in enumerate(caps):
        hi = caps[i + 1] if i + 1 < len(caps) else None
        if hi is None:
            return f"{lo}+"
        if lo <= c < hi:
            return str(lo) if hi == lo + 1 else f"{lo}-{hi - 1}"
    return f"{caps[-1]}+"


def b_since(s):
    return "never" if s is None else b_count(s, (0, 1, 2, 3))


OUT_EDGES = (250, 500, 1000, 2000, 4000)


def b_out(t):
    for e in OUT_EDGES:
        if t < e:
            return f"<{e}"
    return f">={OUT_EDGES[-1]}"


TURN_C = ((1, 2), (3, 4), (5, 6), (7, 8), (9, 11), (12, 15))


def b_turn_c(n):
    n = b_turn(n)
    for lo, hi in TURN_C:
        if lo <= n <= hi:
            return f"{lo}-{hi}"


def b_out_c(t):
    return "<1000" if t < 1000 else "<2000" if t < 2000 else ">=2000"


def binned(f):
    return dict(tenant=f["tenant"] or "?", turn=b_turn(f["turn"]), turn_c=b_turn_c(f["turn"]),
                tmo=b_count(f["n_timeout"], (0, 1, 2, 3)), err=b_count(f["n_err"], (0, 1, 3, 5)), last=f["last"],
                since=b_since(f["since_ok"]), out=b_out(f["out_tok"]), out_c=b_out_c(f["out_tok"]),
                nudge="0" if f["nudges"] == 0 else "1+")


# Coarse to fine; each level extends the previous one (the fitter's parent of a key is its prefix). The
# tenant-independent level 1 carries the strong signals (turn, timeouts, errors, runaway output), so a state that
# is rare for one tenant (e.g. timeouts on tpch_sf10) backs off to what those signals mean across tenants.
LEVELS = [(),
          ("turn_c", "tmo", "err", "out_c"),
          ("turn_c", "tmo", "err", "out_c", "tenant"),
          ("turn_c", "tmo", "err", "out_c", "tenant", "turn"),
          ("turn_c", "tmo", "err", "out_c", "tenant", "turn", "last"),
          ("turn_c", "tmo", "err", "out_c", "tenant", "turn", "last", "since", "out", "nudge")]
assert all(LEVELS[i][:len(LEVELS[i - 1])] == LEVELS[i - 1] for i in range(1, len(LEVELS)))


def keys_of(f):
    """The table key of state f at every level (coarse to fine)."""
    b = binned(f)
    return [f"{i}|" + "|".join(str(b[c]) for c in lev) for i, lev in enumerate(LEVELS)]


# ---------- state accumulation ----------
class StateAcc:
    """Builds the state turn by turn. add_turn(calls, out_tokens) with calls = [(tool name, error class or None)]."""
    __slots__ = ("tenant", "turn", "n_timeout", "n_err", "n_ok", "last_ok_turn", "last", "nudges", "out_tok")

    def __init__(self, tenant=""):
        self.tenant = tenant or ""
        self.turn = 0  # completed turns
        self.n_timeout = self.n_err = self.n_ok = self.nudges = self.out_tok = 0
        self.last_ok_turn = None
        self.last = "start"

    def add_turn(self, calls, out_tokens=0):
        self.turn += 1
        self.out_tok += out_tokens or 0
        if not calls:
            self.nudges += 1
            self.last = "nudge"
            return
        kinds = []
        for name, err in calls:
            if err == "timeout":
                self.n_timeout += 1; kinds.append("timeout")
            elif err is not None:
                self.n_err += 1; kinds.append("err")
            elif name == "execute_sql":
                self.n_ok += 1; kinds.append("ok")
            else:
                kinds.append("explore")
        if "ok" in kinds:
            self.last_ok_turn = self.turn
        # a turn's outcome, worst-news-first among SQL outcomes: ok beats explore; timeout > err if no ok
        self.last = ("ok" if "ok" in kinds else "timeout" if "timeout" in kinds else "err" if "err" in kinds
                     else "explore")

    def add_turn_row(self, row):
        """A turns.jsonl row (harness/agent_duckdb/run_w.py) as one completed turn."""
        self.add_turn([(t["name"], t.get("error")) for t in row.get("tools") or []], row.get("output_tokens") or 0)

    def state(self):
        """Features of the request for the next turn."""
        n = self.turn + 1
        return dict(turn=n, tenant=self.tenant, n_timeout=self.n_timeout, n_err=self.n_err, n_ok=self.n_ok,
                    since_ok=None if self.last_ok_turn is None else self.turn - self.last_ok_turn,
                    last=self.last, nudges=self.nudges, out_tok=self.out_tok)


def est_tokens(text):
    return int(len(text or "") / 3.6)


def features_from_messages(messages, tenant="", out_tokens=None):
    """State of a chat request (the agent's full history). out_tokens = the gateway's running sum of
    usage.completion_tokens for this task; None -> estimated from the assistant messages' text."""
    acc = StateAcc(tenant)
    est = 0
    i, n = 0, len(messages)
    while i < n:
        m = messages[i]
        if m.get("role") != "assistant":
            i += 1
            continue
        calls = m.get("tool_calls") or []
        est += est_tokens(m.get("content")) + sum(est_tokens((c.get("function") or {}).get("arguments")) + 8
                                                  for c in calls)
        names = {c.get("id"): (c.get("function") or {}).get("name") for c in calls}
        order = [(c.get("function") or {}).get("name") for c in calls]
        res = []
        j = i + 1
        while j < n and messages[j].get("role") == "tool":
            tm = messages[j]
            name = names.get(tm.get("tool_call_id")) or (order[len(res)] if len(res) < len(order) else None)
            res.append((name, tool_error_class(tm.get("content"))))
            j += 1
        acc.add_turn(res if calls else [], 0)
        i = j
    acc.out_tok = est if out_tokens is None else out_tokens
    return acc.state()


def force_final_body(body):
    """Rewrite a chat body exactly as the agent's own last turn: append LAST as a user message and set
    tool_choice "none" (tools stay in the body, as in run_w.chat(final=True)). Returns the same dict."""
    msgs = body.get("messages") or []
    if not (msgs and msgs[-1].get("role") == "user" and msgs[-1].get("content") == LAST):
        msgs.append({"role": "user", "content": LAST})
    body["messages"] = msgs
    body["tool_choice"] = "none"
    return body


# ---------- the table ----------
class Table:
    """prefill_weight / db_weight: work = out + prefill_weight * pre + db_weight * db (db = remaining tool wall
    seconds, in token-equivalents per second; 0 by default = LLM work only). Defaults come from the table."""

    def __init__(self, d, prefill_weight=None, db_weight=None):
        if d.get("bins_version") != BINS_VERSION:
            raise ValueError(f"table bins_version {d.get('bins_version')} != code {BINS_VERSION}")
        self.d = d
        self.entries = d["entries"]  # key -> [n, p, out, pre, db]
        self.w = float(d.get("prefill_weight", 1.0) if prefill_weight is None else prefill_weight)
        self.wdb = float(d.get("db_weight", 0.0) if db_weight is None else db_weight)
        self.floor = float(d.get("p_floor", 1e-3))

    @classmethod
    def load(cls, path, prefill_weight=None, db_weight=None):
        with open(path) as f:
            return cls(json.load(f), prefill_weight, db_weight)

    def lookup(self, f):
        """-> dict(p, out, pre, db, work, value, level)."""
        e, lvl = None, -1
        for i, k in enumerate(keys_of(f)):
            x = self.entries.get(k)
            if x is None:
                break
            e, lvl = x, i
        _, p, out, pre, db = e
        work = max(out + self.w * pre + self.wdb * db, 1.0)
        value = max(p, self.floor) / work
        return dict(p=p, out=out, pre=pre, db=db, work=work, value=value, level=lvl)


def value_priority(value):
    """vLLM priority (int, lower = sooner): higher value -> lower number. 1000 steps per decade of value."""
    return int(round(-1000.0 * math.log10(max(value, 1e-12))))
