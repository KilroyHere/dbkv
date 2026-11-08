"""Test P2, plan-cache re-test on CPU (PLAN §2i). Run inside an srun job after make_streams_w2.py.

  python harness/plancache/test_p2.py                  # writes $DBKV_DATA/plancache/w2/test_p2.{json,md} (+ m2_lexicon.json)
  python harness/plancache/test_p2.py --allow-partial  # development on w2/dev_partial streams: smoke checks only,
                                                       # prints no metric and writes nothing

Records. Every question of every stream is one record, position 0 included (it is a non-repeat that can never get a
hint; §2i counts "120 non-repeats at r80" = 4 seeds x 30 new questions, which includes position 0).

Matcher M2 (features from the question text and the two schemas only; template metadata is used only as the cache's
knowledge of EARLIER questions' templates, for the hint and for s2):
  1. Typed literal slots, a regex pass over the raw question, applied in this order (the order resolves overlaps;
     e.g. an ISO date must be replaced before its year):
       DATE   ISO yyyy-mm-dd, US mm/dd/yyyy (or yy), and "<Month> d[, ]yyyy"          -> <DATE>
       YEAR   4-digit 1900-2099 not part of a longer number                             -> <YEAR>
       MONTH  January ... December (capitalized, so the verb "may"/"march" is kept)      -> <MONTH>
       STATE  the 50 US state names + District of Columbia (capitalized) and the 51 two-letter codes (uppercase
              only, so "in"/"or"/"me" stay words)                                       -> <STATE>
       STR    a quoted string ('...' with no letter/digit just outside the quotes, so apostrophes such as
              "customer's" never open one; "..."; curly quotes). If its content is exactly one type token already
              (e.g. '<STATE>'), it becomes that token; otherwise                         -> <STR>
       PCT    a number followed by % or the word "percent"                             -> <PCT>
       NUM    any other number (digits with optional thousands commas / decimals)       -> <NUM>
     Then tokens = the type tokens + lowercase words [a-z]+ (no stop list, as §2h).
  2. Schema-entity tokens. Lexicon from information_schema.columns of tpcds_sf1 and tpch_sf1 (schema main): each
     table name and each column name is split on "_"; a column's first segment is dropped when it is the prefix
     shared by every column of that table (ss_, d_, l_, ps_, ...); every word loses one trailing "s" (words longer
     than 2 letters). The question's word tokens (type tokens act as breakers) get the same trailing-s rule, and
     every n-gram (n = 1..3) equal to a name's word sequence adds E:<table> or E:<table>.<column>; a sequence
     shared by several names (e.g. "name") adds all of them. Overlapping n-grams all count.
  3. BM25 (k1 1.2, b 0.75, IDF ln(1 + (N - df + 0.5)/(df + 0.5)), test_p.BM25) over all earlier questions of the
     same stream (all tenants). s1 = top score, top-1 = the latest earlier question with score s1 (s1 > 0), the
     candidate hint = its template. s2 = best score among earlier questions whose template differs from the hint
     (0 if none). margin = (s1 - s2)/s1. Hint iff s1 >= tau and margin >= m.
  Calibration: seeds 1 and 5 pooled over r20/r50/r80; tau over every observed s1 > 0, m in {0, 0.05, ..., 0.50};
  maximize repeat recall (hint given and correct) s.t. non-repeat hint rate <= 10% (counts: 10 * hints <= n);
  ties -> larger m, then larger tau. If nothing is feasible, no hint is ever given. Evaluation seeds 0/2/3/4 are
  then scored once, pooled per rate.
  P1i repeats: hint given and correct >= 0.80; P2i non-repeats: hint given <= 0.10; P3i hints given: correct >= 0.95.
  Pass = all three at r80 and r50.
Also reported (no pass/fail): ablation ladder (L0 §2h words + threshold, L1 + typed slots, L2 + schema entities,
L3 + margin = M2; L0-L2 calibrate tau with m fixed at 0), the TPC-DS-only pool (its own streams from
make_streams_w2.py; r20 infeasible with 99 templates, so calibration pools r50/r80), the per-benchmark breakdown,
and the most-confused template pairs.
"""
import argparse, json, math, os, re, sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_p import BM25, toks as toks_words  # noqa: E402

DATA = os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv")
W2 = os.path.join(DATA, "plancache", "w2")
RATES = [20, 50, 80]
EVAL_SEEDS = [0, 2, 3, 4]
CAL_SEEDS = [1, 5]
M_GRID = [round(0.05 * k, 2) for k in range(11)]
SCHEMA_DBS = [os.path.join(DATA, "tenants", "tpcds_sf1.duckdb"), os.path.join(DATA, "tpch", "tpch_sf1.duckdb")]
TARGET_FH = 0.10

# ---------------------------------------------------------------------- typed literal slots
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
STATE_NAMES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
               "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
               "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
               "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
               "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
               "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
               "West Virginia", "Wisconsin", "Wyoming", "District of Columbia"]
STATE_CODES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
               "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
               "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
TYPES = ["YEAR", "DATE", "MONTH", "STATE", "STR", "PCT", "NUM"]
_MON = "|".join(MONTHS)
_STATES = "|".join(sorted(STATE_NAMES, key=len, reverse=True))
SLOT_PASSES = [
    ("DATE", re.compile(r"(?<![\d.])(?:19|20)\d\d-\d{1,2}-\d{1,2}(?!\d)")),
    ("DATE", re.compile(r"(?<![\d./])\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?![\d/])")),
    ("DATE", re.compile(r"\b(?:" + _MON + r")\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d\d(?!\d)")),
    ("YEAR", re.compile(r"(?<![\d.,])(?:19|20)\d\d(?![\d]|[.,]\d)")),
    ("MONTH", re.compile(r"\b(?:" + _MON + r")\b")),
    ("STATE", re.compile(r"\b(?:" + _STATES + r")\b")),
    ("STATE", re.compile(r"\b(?:" + "|".join(STATE_CODES) + r")\b")),
]
_TYPE_ONLY = re.compile(r"\s*<(?:" + "|".join(TYPES) + r")>\s*")
STR_PASSES = [re.compile(r"(?<![A-Za-z0-9])'([^'\n]*)'(?![A-Za-z0-9])"), re.compile(r'"([^"\n]*)"'),
              re.compile(r"‘([^’\n]*)’"), re.compile(r"“([^”\n]*)”")]
PCT_PASS = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?\s?(?:%|percent\b)")
NUM_PASS = re.compile(r"(?<![\d.])\d+(?:,\d{3})*(?:\.\d+)?")
TOKEN_RE = re.compile(r"<(?:" + "|".join(TYPES) + r")>|[A-Za-z]+")


def typed_text(q):
    """The question with literals replaced by type tokens (surrounded by spaces)."""
    for typ, rx in SLOT_PASSES:
        q = rx.sub(f" <{typ}> ", q)

    def str_sub(m):
        inner = m.group(1)
        return f" {inner.strip()} " if _TYPE_ONLY.fullmatch(inner) else " <STR> "
    for rx in STR_PASSES:
        q = rx.sub(str_sub, q)
    q = PCT_PASS.sub(" <PCT> ", q)
    q = NUM_PASS.sub(" <NUM> ", q)
    return q


def toks_slots(q):
    return [t if t.startswith("<") else t.lower() for t in TOKEN_RE.findall(typed_text(q))]


# ---------------------------------------------------------------------- schema entities
def strip_s(w):
    return w[:-1] if len(w) > 2 and w.endswith("s") else w


def build_lexicon(db_paths=SCHEMA_DBS):
    """{word tuple: sorted entity tokens} from the table/column names of the given DBs."""
    import duckdb
    lex = defaultdict(set)
    schema = {}
    for p in db_paths:
        con = duckdb.connect(p, read_only=True)
        con.execute("SET threads=4")
        rows = con.execute("SELECT table_name, column_name FROM information_schema.columns "
                           "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
        con.close()
        for t, c in rows:
            schema.setdefault(t.lower(), [])
            if c.lower() not in schema[t.lower()]:
                schema[t.lower()].append(c.lower())
    for t in sorted(schema):
        cols = schema[t]
        lex[tuple(strip_s(w) for w in t.split("_") if w)].add(f"E:{t}")
        firsts = {c.split("_")[0] for c in cols}
        prefix = firsts.pop() if len(firsts) == 1 and all("_" in c for c in cols) else None
        for c in cols:
            segs = [w for w in c.split("_") if w]
            if prefix is not None and segs[0] == prefix and len(segs) > 1:
                segs = segs[1:]
            lex[tuple(strip_s(w) for w in segs)].add(f"E:{t}.{c}")
    return {k: sorted(v) for k, v in lex.items()}, schema


def entity_tokens(tokens, lex):
    words = [None if t.startswith("<") else strip_s(t) for t in tokens]
    out = []
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if None in g:
                continue
            out.extend(lex.get(tuple(g), ()))
    return out


def make_tokenizers(lex):
    def m2(q):
        t = toks_slots(q)
        return t + entity_tokens(t, lex)
    return {"words": lambda q: toks_words(q), "slots": toks_slots, "m2": m2}


# ---------------------------------------------------------------------- retrieval
def all_scores(idx, tokens):
    """BM25 score of every earlier doc (same formula as test_p.BM25.top1)."""
    n = len(idx.docs)
    if n == 0:
        return []
    avg = idx.total / n
    idf = {w: math.log(1 + (n - idx.df[w] + 0.5) / (idx.df[w] + 0.5)) for w in set(tokens) if idx.df[w]}
    out = []
    for j in range(n):
        tf, dl = idx.tfs[j], len(idx.docs[j])
        s = 0.0
        for w, wi in idf.items():
            f = tf.get(w)
            if f:
                s += wi * f * (idx.k1 + 1) / (f + idx.k1 * (1 - idx.b + idx.b * dl / avg))
        out.append(s)
    return out


def retrieve(rows, tokfn):
    idx, out = BM25(), []
    for r in rows:
        t = tokfn(r["question"])
        sc = all_scores(idx, t)
        s1, j = 0.0, None
        for jj, s in enumerate(sc):
            if s > 0 and s >= s1:
                s1, j = s, jj
        hint = rows[j]["template_id"] if j is not None else None
        s2 = max((s for jj, s in enumerate(sc) if rows[jj]["template_id"] != hint), default=0.0) if hint else 0.0
        out.append(dict(qid=r["qid"], pos=r["pos"], tpl=r["template_id"], bench=r.get("bench", "tpcds"),
                        rep=bool(r["is_repeat"]), s1=s1, s2=s2, margin=(s1 - s2) / s1 if s1 > 0 else 0.0,
                        hint=hint, hint_bench=rows[j].get("bench", "tpcds") if j is not None else None))
        idx.add(t)
    return out


def arrays(recs):
    s1 = np.array([x["s1"] for x in recs], dtype=float)
    mg = np.array([x["margin"] for x in recs], dtype=float)
    has = np.array([x["hint"] is not None for x in recs])
    corr = np.array([x["hint"] is not None and x["hint"] == x["tpl"] for x in recs])
    rep = np.array([x["rep"] for x in recs])
    return s1, mg, has, corr, rep


def calibrate(recs, m_grid):
    """(tau, m, info): max repeat recall s.t. non-repeat hint rate <= 10%; ties -> larger m, then larger tau."""
    s1, mg, has, corr, rep = arrays(recs)
    n_rep, n_non = int(rep.sum()), int((~rep).sum())
    taus = np.unique(s1[has & (s1 > 0)])
    best = None  # (hits, m, tau, n_false)
    for m in m_grid:
        ok = has & (mg >= m)
        given = ok[:, None] & (s1[:, None] >= taus[None, :])
        hits = (given & (rep & corr)[:, None]).sum(0)
        false = (given & (~rep)[:, None]).sum(0)
        feas = 10 * false <= n_non
        for k in np.nonzero(feas)[0]:
            key = (int(hits[k]), m, float(taus[k]))
            if best is None or key > best[:3]:
                best = key + (int(false[k]),)
    if best is None:
        return math.inf, max(m_grid), dict(feasible=False, n_repeat=n_rep, n_nonrepeat=n_non, n_tau=len(taus))
    return best[2], best[1], dict(feasible=True, n_repeat=n_rep, n_nonrepeat=n_non, n_tau=len(taus),
                                  repeat_recall=round(best[0] / n_rep, 4) if n_rep else None,
                                  nonrepeat_hint_rate=round(best[3] / n_non, 4) if n_non else None)


def given_mask(recs, tau, m):
    s1, mg, has, corr, rep = arrays(recs)
    return has & (s1 >= tau) & (mg >= m), corr, rep


def metrics(recs, tau, m):
    g, corr, rep = given_mask(recs, tau, m)
    n_rep, n_non, n_g = int(rep.sum()), int((~rep).sum()), int(g.sum())
    f = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    p1 = f(int((g & corr & rep).sum()), n_rep)
    p2 = f(int((g & ~rep).sum()), n_non)
    p3 = f(int((g & corr).sum()), n_g)
    _, _, has, _, _ = arrays(recs)
    return dict(n=len(recs), n_repeat=n_rep, n_nonrepeat=n_non, n_hints=n_g,
                P1i_repeat_recall=p1, P2i_nonrepeat_hint_rate=p2, P3i_hint_precision=p3,
                repeat_wrong_hint=f(int((g & ~corr & rep).sum()), n_rep),
                repeat_top1_correct_no_gate=f(int((has & corr & rep).sum()), n_rep),
                nonrepeat_any_top1_no_gate=f(int((has & ~rep).sum()), n_non))


def judge(mt):
    p1, p2, p3 = mt["P1i_repeat_recall"], mt["P2i_nonrepeat_hint_rate"], mt["P3i_hint_precision"]
    return dict(P1i=p1 is not None and p1 >= 0.80, P2i=p2 is not None and p2 <= 0.10, P3i=p3 is not None and p3 >= 0.95)


# ---------------------------------------------------------------------- driver
def load_streams(d, prefix):
    out = {}
    for rate in RATES:
        for seed in sorted(EVAL_SEEDS + CAL_SEEDS):
            p = os.path.join(d, f"{prefix}_r{rate:02d}_s{seed}.jsonl")
            if os.path.exists(p):
                out[(rate, seed)] = [json.loads(l) for l in open(p)]
    return out


def evaluate(streams, tokfn, m_grid):
    recs = {k: retrieve(rows, tokfn) for k, rows in sorted(streams.items())}
    cal = [x for (rate, seed), v in sorted(recs.items()) if seed in CAL_SEEDS for x in v]
    tau, m, info = calibrate(cal, m_grid)
    res = dict(tau=tau if math.isfinite(tau) else None, m=m, calibration=info,
               calibration_rates=sorted({rate for (rate, seed) in recs if seed in CAL_SEEDS}),
               calibration_metrics=metrics(cal, tau, m), eval={})
    for rate in RATES:
        ev = [x for (r, s), v in sorted(recs.items()) if r == rate and s in EVAL_SEEDS for x in v]
        if ev:
            res["eval"][f"r{rate}"] = metrics(ev, tau, m)
    return res, recs


def eval_recs(recs, rate):
    return [x for (r, s), v in sorted(recs.items()) if r == rate and s in EVAL_SEEDS for x in v]


def confusions(recs, tau, m, top=15):
    ev = [x for rate in RATES for x in eval_recs(recs, rate)]
    g, corr, rep = given_mask(ev, tau, m)
    wrong_rep, wrong_non, unordered, top1 = Counter(), Counter(), Counter(), Counter()
    for x, gi, ci in zip(ev, g, corr):
        if x["hint"] is not None and x["rep"] and x["hint"] != x["tpl"]:
            top1[tuple(sorted((x["tpl"], x["hint"])))] += 1
        if gi and not ci:
            (wrong_rep if x["rep"] else wrong_non)[(x["tpl"], x["hint"])] += 1
            unordered[tuple(sorted((x["tpl"], x["hint"])))] += 1
    fmt = lambda c: [[a, b, n] for (a, b), n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]  # noqa: E731
    return dict(wrong_hints_given_pairs_unordered=fmt(unordered),
                wrong_hints_to_repeats_true_hinted=fmt(wrong_rep),
                wrong_hints_to_nonrepeats_true_hinted=fmt(wrong_non),
                top1_confusions_repeats_no_gate_unordered=fmt(top1),
                n_wrong_hints_given=int((g & ~corr).sum()),
                n_cross_benchmark_wrong_hints=sum(1 for x, gi, ci in zip(ev, g, corr)
                                                  if gi and not ci and x["hint_bench"] != x["bench"]))


def per_bench(recs, tau, m):
    out = {}
    for rate in RATES:
        ev = eval_recs(recs, rate)
        for b in sorted({x["bench"] for x in ev}):
            out[f"r{rate}_{b}"] = metrics([x for x in ev if x["bench"] == b], tau, m)
    return out


def check_summary(d, want_size):
    p = os.path.join(d, "summary.json")
    if not os.path.exists(p):
        return None, f"no {p}"
    s = json.load(open(p))
    ok = s.get("complete") and s.get("pool_size") == want_size
    return s, None if ok else f"{p}: pool_size {s.get('pool_size')} complete {s.get('complete')} (need {want_size})"


def fmt_verdict(res):
    v = res["verdict"]
    L = [f"Test P2 verdict (PLAN §2i), calibrated tau = {res['M2']['tau']}, m = {res['M2']['m']}"]
    for rate in (80, 50):
        mt = res["M2"]["eval"][f"r{rate}"]
        j = v[f"r{rate}"]
        L.append(f"  r{rate}: P1i {mt['P1i_repeat_recall']} (>= 0.80) {'PASS' if j['P1i'] else 'FAIL'} | "
                 f"P2i {mt['P2i_nonrepeat_hint_rate']} (<= 0.10) {'PASS' if j['P2i'] else 'FAIL'} | "
                 f"P3i {mt['P3i_hint_precision']} (>= 0.95) {'PASS' if j['P3i'] else 'FAIL'}   "
                 f"[n_rep {mt['n_repeat']}, n_non {mt['n_nonrepeat']}, hints {mt['n_hints']}]")
    L.append(f"  OVERALL: {'PASS' if v['overall'] else 'FAIL'}")
    return "\n".join(L)


def md(res):
    def row(name, mt):
        return (f"| {name} | {mt['n_repeat']} | {mt['n_nonrepeat']} | {mt['n_hints']} | {mt['P1i_repeat_recall']} | "
                f"{mt['P2i_nonrepeat_hint_rate']} | {mt['P3i_hint_precision']} | {mt['repeat_wrong_hint']} | "
                f"{mt['repeat_top1_correct_no_gate']} |")
    hdr = ["| | n repeat | n non-repeat | hints | P1i recall | P2i non-rep hint | P3i precision | repeat wrong hint | "
           "repeat top-1 correct (no gate) |", "|---|---|---|---|---|---|---|---|---|"]
    L = ["# Test P2 (plan-cache re-test on CPU)", "",
         "Pre-registered in PLAN §2i (commit 4b6da42). Generated by `harness/plancache/test_p2.py` on the W2 streams "
         "from `harness/plancache/make_streams_w2.py`.", "", "## Verdict", "", "```", fmt_verdict(res), "```", "",
         "## Setup", "",
         f"- Pool: {res['pool']['pool_size']} templates {res['pool']['pool_info']['by_bench']}; 150-question streams, "
         "strict repeat rates 20/50/80% (within +-1 over every prefix); evaluation seeds 0/2/3/4 pooled per rate, "
         "calibration seeds 1/5 pooled over r20/r50/r80. Every position counts (position 0 = a non-repeat with no hint).",
         f"- M2 lexicon: {res['lexicon']['n_sequences']} word sequences -> {res['lexicon']['n_entities']} entity tokens "
         f"({res['lexicon']['n_tables']} tables); written to `m2_lexicon.json`.",
         f"- Calibration (M2): {res['M2']['calibration']}", "", "## M2 at the calibrated (tau, m)", ""] + hdr
    L.append(row("calibration pool", res["M2"]["calibration_metrics"]))
    for k, mt in res["M2"]["eval"].items():
        L.append(row(f"eval {k}", mt))
    L += ["", "## Ablation ladder (each calibrated the same way; L0-L2 have m = 0)", "",
          "| step | tau | m | r80 P1i / P2i / P3i | r50 P1i / P2i / P3i | r20 P1i / P2i / P3i |", "|---|---|---|---|---|---|"]
    for name, r in res["ladder"].items():
        cells = []
        for rate in (80, 50, 20):
            mt = r["eval"].get(f"r{rate}")
            cells.append(f"{mt['P1i_repeat_recall']} / {mt['P2i_nonrepeat_hint_rate']} / {mt['P3i_hint_precision']}"
                         if mt else "-")
        tau = round(r["tau"], 3) if r["tau"] is not None else None
        L.append(f"| {name} | {tau} | {r['m']} | " + " | ".join(cells) + " |")
    L += ["", "## Per-benchmark breakdown (M2, calibrated)", ""] + hdr
    for k, mt in res["per_benchmark"].items():
        L.append(row(k, mt))
    ds = res.get("tpcds_only")
    L += ["", "## TPC-DS-only pool (99 templates, same procedure, report only)", ""]
    if ds and "M2" in ds:
        L += [f"- Own streams (`streams_tpcds/`), own calibration on seeds 1/5 over {ds['M2']['calibration_rates']} "
              f"(r20 infeasible with 99 templates). tau = {ds['M2']['tau']}, m = {ds['M2']['m']}.", ""] + hdr
        for k, mt in ds["M2"]["eval"].items():
            L.append(row(f"eval {k}", mt))
        L += ["", f"Would-pass flags (not a verdict): {ds['would_pass']}"]
    else:
        L.append(f"- not run: {ds}")
    c = res["confusions"]
    L += ["", "## Most-confused template pairs (eval seeds, all rates, M2 calibrated)", "",
          f"- Wrong hints given: {c['n_wrong_hints_given']} ({c['n_cross_benchmark_wrong_hints']} across benchmarks).",
          f"- Unordered pairs among wrong hints given: {c['wrong_hints_given_pairs_unordered']}",
          f"- Wrong hints to repeats (true, hinted): {c['wrong_hints_to_repeats_true_hinted']}",
          f"- Wrong hints to non-repeats (true, hinted): {c['wrong_hints_to_nonrepeats_true_hinted']}",
          f"- Top-1 confusions among repeats with no gating (unordered): {c['top1_confusions_repeats_no_gate_unordered']}",
          "", "## Tokenizer examples (r80 s0, first 3 questions)", ""]
    for e in res["token_examples"]:
        L += [f"- Q: {e['question']}", f"  - slots: `{' '.join(e['slots'])}`", f"  - entities: `{' '.join(e['entities'])}`"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-partial", action="store_true", help="development: smoke checks only, no metrics, no files")
    a = ap.parse_args()
    lex, schema = build_lexicon()
    tok = make_tokenizers(lex)
    d_all, d_ds = os.path.join(W2, "streams"), os.path.join(W2, "streams_tpcds")
    s_all, err_all = check_summary(d_all, 121)
    s_ds, err_ds = check_summary(d_ds, 99)
    if a.allow_partial:
        d_all, d_ds = os.path.join(W2, "dev_partial", "streams"), os.path.join(W2, "dev_partial", "streams_tpcds")
        streams = load_streams(d_all, "w2")
        print(f"SMOKE (partial pool; no metrics are printed): lexicon {len(lex)} sequences, {len(schema)} tables; "
              f"{len(streams)} streams loaded from {d_all}")
        ex = streams[(80, 0)][0]["question"] if (80, 0) in streams else "Sales in Texas on 2000-03-15, 'Books', 20%."
        print("example:", ex); print("  slots:", toks_slots(ex)); print("  entities:", entity_tokens(toks_slots(ex), lex))
        for name, tk, mg in (("L0", "words", [0.0]), ("L1", "slots", [0.0]), ("L2", "m2", [0.0]), ("L3", "m2", M_GRID)):
            res, recs = evaluate(streams, tok[tk], mg)
            print(f"  {name}: records {sum(len(v) for v in recs.values())}, calibration feasible "
                  f"{res['calibration']['feasible']}, eval rates {sorted(res['eval'])} -- ok")
        ds = load_streams(d_ds, "w2ds")
        if ds:
            res, recs = evaluate(ds, tok["m2"], M_GRID)
            print(f"  TPC-DS-only: {len(ds)} streams, calibration rates {res['calibration_rates']} -- ok")
        print("SMOKE done; nothing written.")
        return
    if err_all:
        sys.exit(f"refusing final scoring: {err_all}")

    streams = load_streams(d_all, "w2")
    want = {(r, s) for r in RATES for s in EVAL_SEEDS + CAL_SEEDS}
    if set(streams) != want:
        sys.exit(f"missing streams: {sorted(want - set(streams))}")
    res = dict(pool=dict(pool_size=s_all["pool_size"], pool_info=s_all["pool_info"]),
               stream_summary={k: {kk: v[kk] for kk in ("strict_rate", "max_prefix_deviation_questions", "new_templates",
                                                        "bench")} for k, v in s_all["streams"].items()})
    m2, recs = evaluate(streams, tok["m2"], M_GRID)
    res["M2"] = m2
    res["verdict"] = {f"r{rate}": judge(m2["eval"][f"r{rate}"]) for rate in (80, 50)}
    res["verdict"]["overall"] = all(all(res["verdict"][f"r{rate}"].values()) for rate in (80, 50))
    res["verdict"]["r20_reported_only"] = judge(m2["eval"]["r20"])
    tau, m = (m2["tau"] if m2["tau"] is not None else math.inf), m2["m"]
    res["per_benchmark"] = per_bench(recs, tau, m)
    res["confusions"] = confusions(recs, tau, m)
    res["ladder"] = {}
    for name, tk, mg in (("L0 §2h BM25 + threshold", "words", [0.0]), ("L1 + typed slots", "slots", [0.0]),
                         ("L2 + schema entities", "m2", [0.0]), ("L3 + margin (= M2)", "m2", M_GRID)):
        r, _ = evaluate(streams, tok[tk], mg) if name[:2] != "L3" else (m2, None)
        res["ladder"][name] = r
    if err_ds:
        res["tpcds_only"] = f"not run: {err_ds}"
    else:
        ds = load_streams(d_ds, "w2ds")
        r, _ = evaluate(ds, tok["m2"], M_GRID)
        res["tpcds_only"] = dict(M2=r, infeasible=s_ds.get("infeasible"),
                                 would_pass={k: judge(v) for k, v in r["eval"].items() if k in ("r80", "r50")})
    res["lexicon"] = dict(n_sequences=len(lex), n_entities=len({e for v in lex.values() for e in v}), n_tables=len(schema),
                          sources=SCHEMA_DBS)
    res["token_examples"] = [dict(question=row["question"], slots=toks_slots(row["question"]),
                                  entities=entity_tokens(toks_slots(row["question"]), lex)) for row in streams[(80, 0)][:3]]
    os.makedirs(W2, exist_ok=True)
    json.dump(res, open(os.path.join(W2, "test_p2.json"), "w"), indent=1, default=str)
    open(os.path.join(W2, "test_p2.md"), "w").write(md(res))
    json.dump({" ".join(k): v for k, v in sorted(lex.items())}, open(os.path.join(W2, "m2_lexicon.json"), "w"), indent=1)
    print(fmt_verdict(res))
    for name, r in res["ladder"].items():
        print(name, "tau", r["tau"], "m", r["m"], {k: (v["P1i_repeat_recall"], v["P2i_nonrepeat_hint_rate"],
                                                     v["P3i_hint_precision"]) for k, v in r["eval"].items()})
    print("wrote", os.path.join(W2, "test_p2.{json,md}"))


if __name__ == "__main__":
    main()
