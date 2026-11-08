"""Test P, plan-cache feasibility (PLAN §2h), CPU only.

  python harness/plancache/test_p.py      # writes $DBKV_DATA/plancache/test_p.{json,md}

W part. For each stream, every question i >= 1 queries a BM25 index over questions 0..i-1 of the same stream (all
tenants). Tokens: lowercase alphabetic words ([a-z]+ after lowercasing; digits are dropped, so parameter numbers
never match), no stop list, BM25 k1 = 1.2, b = 0.75, IDF = ln(1 + (N - df + 0.5)/(df + 0.5)) over the earlier
questions. The hint is the template of the top-1 earlier question (ties -> the most recent); a top-1 score of 0
gives no hint. Position 0 never gets a hint.
  P1h  among repeat questions: share whose hint exists, is above the threshold, and has the right template
       (below threshold = miss). Also reported with no threshold.
  P2h  among non-repeat questions: share given an above-threshold hint with a WRONG template ("false hint", §2h).
       Under the strict definition every hint to a non-repeat is wrong by construction.
  Threshold: on the seed-1 calibration streams, pooled over r20/r50/r80, the lowest score threshold (= largest
  recall) whose non-repeat false-hint rate is <= 10%. Judged on seed 0 at r20/r50/r80; the verdict uses r80.
Two repeat definitions are evaluated side by side (see make_streams.py for why both exist):
  strict  is_repeat: template appeared anywhere earlier in the stream (§2h's definition, the interface field)
  window  is_repeat_w: template appeared in the previous 25 questions (what the r00/r20/r50/r80 labels control)
Each has its own calibrated threshold.

BIRD part (report only). Plan skeleton of each gold SQL with sqlglot: parse as SQLite; replace every literal
(number/string) with a placeholder `?`; lowercase every identifier (tables, columns, aliases) and quote it only
when it is not a plain [a-z_][a-z0-9_]* name; render
back as SQLite SQL. Aliases are kept as written (T1/T2 are BIRD's near-universal convention). In dev.json order:
share of questions with an earlier same-DB question of the same skeleton, and for those, BM25 top-1 recall
(top-1 over earlier same-DB questions, document = question + evidence, same tokenizer) of a same-skeleton question.
"""
import json, math, os, re, sys
from collections import Counter, defaultdict

DATA = os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv")
STREAMS = os.path.join(DATA, "plancache", "streams")
RATES = [0, 20, 50, 80]


def toks(text):
    return re.findall(r"[a-z]+", text.lower())


class BM25:
    def __init__(self, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.docs, self.tfs, self.df, self.total = [], [], Counter(), 0

    def add(self, tokens):
        tf = Counter(tokens)
        self.docs.append(tokens); self.tfs.append(tf); self.total += len(tokens)
        self.df.update(tf.keys())

    def top1(self, tokens, candidates=None):
        """(index, score) of the best earlier doc; ties -> latest; (None, 0.0) if nothing scores > 0."""
        n = len(self.docs)
        if n == 0:
            return None, 0.0
        avg = self.total / n
        q = set(tokens)
        idf = {w: math.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5)) for w in q if self.df[w]}
        best, bi = 0.0, None
        for j in (range(n) if candidates is None else candidates):
            tf, dl = self.tfs[j], len(self.docs[j])
            s = 0.0
            for w, wi in idf.items():
                f = tf.get(w)
                if f:
                    s += wi * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avg))
            if s > 0 and s >= best:
                best, bi = s, j
        return bi, best


def retrieve(rows):
    idx = BM25()
    out = []
    for r in rows:
        t = toks(r["question"] + " " + r.get("evidence", ""))
        j, s = idx.top1(t)
        out.append(dict(pos=r["pos"], tpl=r["template_id"], strict=r["is_repeat"], window=r["is_repeat_w"],
                        gap=r["gap"], hint=rows[j]["template_id"] if j is not None else None, score=s,
                        hint_gap=(r["pos"] - j) if j is not None else None))
        idx.add(t)
    return out


def calibrate(recs, key, target=0.10):
    """Lowest threshold with false-hint rate among non-repeats <= target (hint iff score >= tau and score > 0)."""
    non = [x for x in recs if not x[key]]
    false_scores = sorted((x["score"] for x in non if x["hint"] is not None and x["hint"] != x["tpl"]), reverse=True)
    m = int(math.floor(target * len(non)))
    if len(false_scores) <= m:
        return 0.0, len(non)
    return false_scores[m] + 1e-9, len(non)


def rates(recs, key, tau):
    rep = [x for x in recs if x[key]]
    non = [x for x in recs if not x[key]]
    hit = lambda x, t: x["hint"] is not None and x["score"] >= t and x["hint"] == x["tpl"]  # noqa: E731
    false = lambda x, t: x["hint"] is not None and x["score"] >= t and x["hint"] != x["tpl"]  # noqa: E731
    anyh = lambda x, t: x["hint"] is not None and x["score"] >= t  # noqa: E731
    f = lambda xs, p, t: round(sum(p(x, t) for x in xs) / len(xs), 4) if xs else None  # noqa: E731
    return dict(n_repeat=len(rep), n_nonrepeat=len(non),
                P1h=f(rep, hit, tau), P1h_no_threshold=f(rep, hit, 0.0),
                P2h_false_hint=f(non, false, tau), nonrepeat_any_hint=f(non, anyh, tau),
                nonrepeat_false_hint_no_threshold=f(non, false, 0.0),
                repeat_false_hint=f(rep, false, tau))


def w_part():
    recs = {}
    for rate in RATES:
        for seed in (0, 1):
            name = f"w_r{rate:02d}_s{seed}"
            rows = [json.loads(l) for l in open(os.path.join(STREAMS, name + ".jsonl"))]
            recs[name] = retrieve(rows)[1:]  # position 0 cannot be hinted; excluded from every rate
    out = {}
    for key in ("strict", "window"):
        pool = [x for rate in (20, 50, 80) for x in recs[f"w_r{rate:02d}_s1"]]
        tau, n_cal = calibrate(pool, key)
        cal = rates(pool, key, tau)
        res = {}
        for rate in RATES:
            for seed in (0, 1):
                name = f"w_r{rate:02d}_s{seed}"
                rr = rates(recs[name], key, tau)
                xs = recs[name]
                rr["all_q_correct_hint"] = round(sum(x["hint"] == x["tpl"] and x["score"] >= tau for x in xs) / len(xs), 4)
                rr["all_q_top1_correct_no_threshold"] = round(sum(x["hint"] == x["tpl"] for x in xs) / len(xs), 4)
                rr["all_q_any_hint"] = round(sum(x["hint"] is not None and x["score"] >= tau for x in xs) / len(xs), 4)
                res[name] = rr
        r80 = res["w_r80_s0"]
        out[key] = dict(threshold=round(tau, 4), calibration_pool_nonrepeats=n_cal, calibration=cal, streams=res,
                        verdict_r80=dict(P1h=r80["P1h"], P1h_pass=r80["P1h"] >= 0.80,
                                         P2h=r80["P2h_false_hint"], P2h_pass=r80["P2h_false_hint"] <= 0.10))
    # confusion: which template pairs are mixed up (strict repeats, no threshold, seed 0 r80)
    conf = Counter((x["tpl"], x["hint"]) for x in recs["w_r80_s0"] if x["strict"] and x["hint"] != x["tpl"])
    out["top_confusions_r80_s0"] = [[a, b, n] for (a, b), n in conf.most_common(12)]
    # recall vs gap (strict repeats pooled over seed-0 streams, no threshold)
    gb = defaultdict(list)
    for rate in RATES:
        for x in recs[f"w_r{rate:02d}_s0"]:
            if x["strict"]:
                b = "1-5" if x["gap"] <= 5 else "6-25" if x["gap"] <= 25 else "26-100" if x["gap"] <= 100 else ">100"
                gb[b].append(x["hint"] == x["tpl"])
    out["top1_recall_by_gap_seed0"] = {b: [round(sum(v) / len(v), 4), len(v)] for b, v in gb.items()}
    out["figure_hit_rate_vs_repeat_rate"] = [
        dict(repeat_rate_target=rate,
             realized_window=round(sum(x["window"] for x in recs[f"w_r{rate:02d}_s0"]) / len(recs[f"w_r{rate:02d}_s0"]), 4),
             realized_strict=round(sum(x["strict"] for x in recs[f"w_r{rate:02d}_s0"]) / len(recs[f"w_r{rate:02d}_s0"]), 4),
             correct_hint_share_all_questions_strict_tau=out["strict"]["streams"][f"w_r{rate:02d}_s0"]["all_q_correct_hint"],
             correct_hint_share_all_questions_window_tau=out["window"]["streams"][f"w_r{rate:02d}_s0"]["all_q_correct_hint"],
             top1_correct_share_no_threshold=out["strict"]["streams"][f"w_r{rate:02d}_s0"]["all_q_top1_correct_no_threshold"],
             P1h_window=out["window"]["streams"][f"w_r{rate:02d}_s0"]["P1h"],
             P2h_window=out["window"]["streams"][f"w_r{rate:02d}_s0"]["P2h_false_hint"])
        for rate in RATES]
    return out


# ---------------------------------------------------------------------- BIRD
def skeleton(sql):
    import sqlglot
    from sqlglot import exp

    def tf(node):
        if isinstance(node, exp.Literal):
            return exp.Placeholder()
        if isinstance(node, exp.Identifier):
            name = node.name.lower()
            return exp.Identifier(this=name, quoted=not re.fullmatch(r"[a-z_][a-z0-9_]*", name))
        return node
    tree = sqlglot.parse_one(sql, read="sqlite")
    return tree.transform(tf).sql(dialect="sqlite")


def bird_part():
    dev = json.load(open(os.path.join(DATA, "bird", "dev_20240627", "dev.json")))
    sk, fails = [], 0
    for t in dev:
        try:
            sk.append(skeleton(t["SQL"]))
        except Exception:  # noqa: BLE001
            fails += 1
            sk.append("FAIL:" + re.sub(r"'[^']*'|\b\d+(\.\d+)?\b", "?", t["SQL"].lower()))
    idx = defaultdict(BM25)
    members = defaultdict(list)  # db -> dev indices in index order
    n_has, n_hit, by_db = 0, 0, Counter()
    for i, t in enumerate(dev):
        db = t["db_id"]
        tk = toks(t["question"] + " " + t.get("evidence", ""))
        earlier = members[db]
        if any(sk[k] == sk[i] for k in earlier):
            n_has += 1; by_db[db] += 1
            j, s = idx[db].top1(tk)
            if j is not None and sk[earlier[j]] == sk[i]:
                n_hit += 1
        idx[db].add(tk); earlier.append(i)
    return dict(n=len(dev), parse_failures=fails, distinct_skeletons=len(set(zip([t["db_id"] for t in dev], sk))),
                share_with_earlier_same_db_skeleton=round(n_has / len(dev), 4), n_with_earlier=n_has,
                bm25_top1_recall_of_same_skeleton=round(n_hit / n_has, 4) if n_has else None,
                prediction="<= 15% and <= 50%", by_db=dict(by_db.most_common()),
                example_skeleton=sk[0])


def md(res):
    L = ["# Test P (plan-cache feasibility), draft", "",
         "Pre-registered in PLAN §2h (commit 357ff09). Generated by `harness/plancache/test_p.py`.", "",
         "## Method", "",
         "- BM25 (k1 1.2, b 0.75) over all earlier questions of the same stream, all tenants; tokens = lowercase "
         "alphabetic words, digits dropped. Hint = template of the top-1 earlier question (ties: most recent).",
         "- Threshold: seed-1 streams r20/r50/r80 pooled; lowest threshold with non-repeat false-hint rate <= 10%.",
         "- **Repeat definitions.** With 30 templates the strict definition (template seen anywhere earlier) cannot "
         "produce 0/20/50% streams: strict repeat rate is >= 80% over 150 questions and >= 90% over 300. The streams "
         "control a windowed rate (template seen in the previous 25 questions). Both are evaluated, each with its own "
         "threshold.", ""]
    for key in ("strict", "window"):
        r = res["W"][key]
        L += [f"## W, {key} definition (threshold {r['threshold']})", "",
              "| stream | n repeat | n non-repeat | P1h | P1h no threshold | P2h false hint | non-repeat any hint |",
              "|---|---|---|---|---|---|---|"]
        for rate in RATES:
            for seed in (0, 1):
                s = r["streams"][f"w_r{rate:02d}_s{seed}"]
                L.append(f"| r{rate:02d} s{seed} | {s['n_repeat']} | {s['n_nonrepeat']} | {s['P1h']} | "
                         f"{s['P1h_no_threshold']} | {s['P2h_false_hint']} | {s['nonrepeat_any_hint']} |")
        v = r["verdict_r80"]
        L += ["", f"Verdict (r80, seed 0): P1h = {v['P1h']} ({'pass' if v['P1h_pass'] else 'FAIL'}, needs >= 0.80); "
                  f"P2h = {v['P2h']} ({'pass' if v['P2h_pass'] else 'FAIL'}, needs <= 0.10).", ""]
    L += ["## Figure data: correct-hint share of all questions vs repeat rate (seed 0)", "",
          "| target | realized window | realized strict | correct hint (strict tau) | correct hint (window tau) | top-1 correct, no threshold |",
          "|---|---|---|---|---|---|"]
    for f in res["W"]["figure_hit_rate_vs_repeat_rate"]:
        L.append(f"| {f['repeat_rate_target']}% | {f['realized_window']} | {f['realized_strict']} | "
                 f"{f['correct_hint_share_all_questions_strict_tau']} | {f['correct_hint_share_all_questions_window_tau']} | "
                 f"{f['top1_correct_share_no_threshold']} |")
    L += ["", f"Top-1 recall by gap since the template last appeared (strict repeats, seed 0, no threshold): "
              f"{res['W']['top1_recall_by_gap_seed0']}", "",
          f"Most frequent confusions (true, hinted, count) at r80 s0: {res['W']['top_confusions_r80_s0']}", ""]
    b = res["BIRD"]
    L += ["## BIRD, unfavourable end (report only)", "",
          f"- {b['n']} dev questions, {b['parse_failures']} sqlglot parse failures (regex fallback), "
          f"{b['distinct_skeletons']} distinct (db, skeleton) pairs.",
          f"- Share with an earlier same-DB same-skeleton question: **{b['share_with_earlier_same_db_skeleton']}** "
          f"({b['n_with_earlier']}). Prediction <= 15%.",
          f"- BM25 top-1 recall of a same-skeleton question among those: **{b['bm25_top1_recall_of_same_skeleton']}**. "
          "Prediction <= 50%.",
          "- Skeleton: sqlglot parse (SQLite), every literal -> `?`, identifiers lowercased (quoted only if not a plain name), aliases "
          "kept, rendered back to SQLite.", ""]
    return "\n".join(L)


def main():
    res = dict(W=w_part(), BIRD=bird_part())
    out = os.path.join(DATA, "plancache")
    json.dump(res, open(os.path.join(out, "test_p.json"), "w"), indent=1)
    open(os.path.join(out, "test_p.md"), "w").write(md(res))
    for key in ("strict", "window"):
        r = res["W"][key]
        print(key, "tau", r["threshold"], "verdict", r["verdict_r80"])
        for rate in RATES:
            s = r["streams"][f"w_r{rate:02d}_s0"]
            print(f"  r{rate:02d}s0 P1h {s['P1h']} (no thr {s['P1h_no_threshold']}) P2h {s['P2h_false_hint']} "
                  f"anyhint_nonrep {s['nonrepeat_any_hint']} n_rep {s['n_repeat']} n_non {s['n_nonrepeat']}")
    print("gap", res["W"]["top1_recall_by_gap_seed0"])
    print("conf", res["W"]["top_confusions_r80_s0"])
    print("BIRD", {k: v for k, v in res["BIRD"].items() if k != "by_db"})


if __name__ == "__main__":
    main()
