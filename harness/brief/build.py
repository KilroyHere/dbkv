"""Schema briefs for the BIRD SQL agent (D2), built from the database alone (no gold information),
except the `oracle` reference arm.

  python harness/brief/build.py --bird $DBKV_DATA/bird/dev_20240627 --variant compact --out briefs_compact.jsonl
  variants: full     the full schema + 3 sample values per column (Test 3's arm (b), tools.schema)
            compact  (i)  every table: columns with types, keys, joins, 2 sample values per text column
            lexical  (ii) (i) narrowed to tables/columns that match the question + evidence (BM25 over
                          table/column names, BIRD column descriptions and sample values), plus join keys
                          and the tables on the join path between selected tables
            oracle   reference only: (i)'s format narrowed to the gold SQL's tables/columns (sqlglot)
  (iii) the cheap-model selection is harness/brief/llm_select.py (needs a running vLLM server).

Each JSONL line: qid, db, brief, build_s (selection time, counted in task latency), tables, columns.
`--eval` also prints selection recall/precision against the gold SQL's tables and columns.
"""
import argparse, functools, json, math, os, re, sqlite3, sys, time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import tools  # noqa: E402

STOP = set("""a an the of in on at to for from by with and or not no is are was were be been being what which who whom
whose how many much list give show find name names number count all any each per their its his her than that this
these those there please among between does do did have has had as it they them into most more least less top
highest lowest average total among""".split())


def toks(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    out = []
    for w in re.split(r"[^A-Za-z0-9]+", text.lower()):
        if not w or w in STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


@functools.lru_cache(maxsize=None)
def meta(db):
    """Schema metadata: tables -> [(col, type, pk)], joins, samples, descriptions."""
    con = tools.connect(db)
    try:
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        cols, samples, joins = {}, {}, set()
        for t in tabs:
            info = con.execute(f"PRAGMA table_info({tools.quote(t)})").fetchall()
            cols[t] = [(r[1], r[2] or "", bool(r[5])) for r in info]
            for c, typ, _ in cols[t]:
                vals = []
                if "CHAR" in typ.upper() or "TEXT" in typ.upper() or typ == "":
                    try:
                        vals = [str(v[0])[:30] for v in con.execute(
                            f"SELECT DISTINCT {tools.quote(c)} FROM {tools.quote(t)} WHERE {tools.quote(c)} IS NOT NULL "
                            f"AND length({tools.quote(c)}) <= 60 LIMIT 3")]
                    except sqlite3.Error:
                        pass
                samples[(t, c)] = vals
            for f in con.execute(f"PRAGMA foreign_key_list({tools.quote(t)})").fetchall():
                if f[2] and f[3]:
                    ref = next((x for x in tabs if x.lower() == f[2].lower()), f[2])
                    tocol = f[4] or next((c for c, _, pk in cols.get(ref, []) if pk), None) if ref in cols else f[4]
                    if tocol is None:
                        info2 = con.execute(f"PRAGMA table_info({tools.quote(ref)})").fetchall()
                        tocol = next((r[1] for r in info2 if r[5]), None)
                    if tocol:
                        joins.add((t, f[3], ref, tocol))
        # inferred joins: a column with the same name as another table's primary key
        pks = {t: [c for c, _, pk in cols[t] if pk] for t in tabs}
        for t in tabs:
            for c, _, pk in cols[t]:
                for u in tabs:
                    if u != t and len(pks[u]) == 1 and pks[u][0].lower() == c.lower() and c.lower() not in ("id",):
                        if not any((j[0], j[2]) in ((t, u), (u, t)) for j in joins):
                            joins.add((t, c, u, pks[u][0]))
        return dict(tables=tabs, cols=cols, samples=samples, joins=sorted(joins), desc=tools.descriptions(db))
    finally:
        con.close()


def q(name):
    return f"`{name}`" if re.search(r"[^A-Za-z0-9_]", name) else name


def render(db, sel=None, samples=2):
    """Compact brief. sel: {table: set(columns lower)} or None for everything."""
    m = meta(db)
    lines = []
    tabs = [t for t in m["tables"] if sel is None or t in sel]
    for t in tabs:
        parts = []
        for c, typ, pk in m["cols"][t]:
            if sel is not None and sel[t] and c.lower() not in sel[t] and not pk:
                continue
            s = f"{q(c)} {typ}".strip() + (" PK" if pk else "")
            v = m["samples"].get((t, c), [])[:samples]
            if v:
                s += " e.g. " + ", ".join(repr(x) for x in v)
            parts.append(s)
        lines.append(f"{q(t)}: " + "; ".join(parts))
    js = [f"{q(a)}.{q(b)} = {q(c)}.{q(d)}" for a, b, c, d in m["joins"] if a in tabs and c in tabs]
    if js:
        lines.append("Joins: " + "; ".join(js))
    return "\n".join(lines)


def join_closure(db, chosen):
    """Add join-key columns and tables on shortest join paths between chosen tables."""
    m = meta(db)
    adj = defaultdict(set)
    for a, b, c, d in m["joins"]:
        adj[a].add(c); adj[c].add(a)
    chosen = dict(chosen)
    ts = list(chosen)
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            prev = {ts[i]: None}; frontier = [ts[i]]
            while frontier and ts[j] not in prev:
                nxt = []
                for x in frontier:
                    for y in adj[x]:
                        if y not in prev:
                            prev[y] = x; nxt.append(y)
                frontier = nxt
            if ts[j] in prev:
                x = ts[j]
                while x is not None:
                    chosen.setdefault(x, set()); x = prev[x]
    for a, b, c, d in m["joins"]:
        if a in chosen and c in chosen:
            chosen[a].add(b.lower()); chosen[c].add(d.lower())
    return chosen


def lexical_select(db, question, evidence, max_tables=4, rel=0.35, max_cols=15):
    m = meta(db)
    qt = toks(question) + toks(evidence)
    qset = set(qt)
    raw = (question + " " + evidence).lower()
    docs = {}
    for t in m["tables"]:
        for c, typ, pk in m["cols"][t]:
            d = toks(t) + toks(c) * 2 + toks(m["desc"].get(t.lower(), {}).get(c.lower(), "")) + \
                [w for v in m["samples"].get((t, c), []) for w in toks(v)]
            docs[(t, c)] = d
    n = len(docs); avg = sum(len(d) for d in docs.values()) / max(1, n)
    df = Counter(w for d in docs.values() for w in set(d))
    score = {}
    for key, d in docs.items():
        tf = Counter(d); s = 0.0
        for w in qset:
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        if key[1].lower() in raw and len(key[1]) > 2:   # exact column name in question/evidence
            s += 5.0
        score[key] = s
    tscore = {t: max([score[(t, c)] for c, _, _ in m["cols"][t]] + [0]) + (3.0 if t.lower() in raw else 0) for t in m["tables"]}
    best = max(tscore.values()) if tscore else 0
    tabs = sorted([t for t in m["tables"] if best and tscore[t] >= rel * best], key=lambda t: -tscore[t])[:max_tables]
    chosen = {}
    for t in tabs:
        ranked = sorted([c for c, _, _ in m["cols"][t] if score[(t, c)] > 0], key=lambda c: -score[(t, c)])[:max_cols]
        chosen[t] = {c.lower() for c in ranked}
    return join_closure(db, chosen)


def gold_select(db, sql):
    tabs, cols = tools.gold_tables_columns(db, sql)
    m = meta(db)
    real = {t.lower(): t for t in m["tables"]}
    return {real[t]: set(cols.get(t, set())) for t in tabs if t in real}


def gold_sets(db, sql):
    """Gold tables and (table, column) pairs referenced by the gold SQL."""
    import sqlglot
    from sqlglot import exp
    m = meta(db)
    tree = sqlglot.parse_one(sql, read="sqlite")
    real = {t.lower(): t for t in m["tables"]}
    gt = {real[t.name.lower()] for t in tree.find_all(exp.Table) if t.name and t.name.lower() in real}
    names = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
    gc = {(t, c.lower()) for t in gt for c, _, _ in m["cols"][t] if c.lower() in names}
    return gt, gc


def build(a, task):
    db = os.path.join(a.bird, "dev_databases", task["db_id"], task["db_id"] + ".sqlite")
    t0 = time.perf_counter()
    if a.variant == "full":
        sel = None; brief = tools.schema(db)
    elif a.variant == "compact":
        sel = None; brief = render(db)
    elif a.variant == "lexical":
        sel = lexical_select(db, task["question"], task.get("evidence", "")); brief = render(db, sel)
    elif a.variant == "oracle":
        sel = join_closure(db, gold_select(db, task["SQL"])); brief = render(db, sel)
    else:
        raise ValueError(a.variant)
    build_s = time.perf_counter() - t0 if a.variant == "lexical" else 0.0  # only per-question selection counts
    m = meta(db)
    tabs = list(sel) if sel is not None else m["tables"]
    cols = [[t, c] for t in tabs for c, _, pk in m["cols"][t]
            if sel is None or not sel[t] or c.lower() in sel[t] or pk]
    return dict(qid=task["question_id"], db=task["db_id"], brief=brief, build_s=round(build_s, 5), tables=tabs, columns=cols)


def selection_metrics(rows, dev, bird):
    """Recall/precision of selected tables and (table, column) pairs vs the gold SQL."""
    byq = {t["question_id"]: t for t in dev}
    tr, tp, cr, cp, n = [], [], [], [], 0
    for r in rows:
        t = byq[r["qid"]]
        db = os.path.join(bird, "dev_databases", t["db_id"], t["db_id"] + ".sqlite")
        try:
            gt, gc = gold_sets(db, t["SQL"])
        except Exception:  # noqa: BLE001
            continue
        st = set(r["tables"]); sc = {(a, b.lower()) for a, b in r["columns"]}
        if gt:
            tr.append(len(gt & st) / len(gt)); tp.append(len(gt & st) / max(1, len(st)))
        if gc:
            cr.append(len(gc & sc) / len(gc)); cp.append(len(gc & sc) / max(1, len(sc)))
        n += 1
    f = lambda x: round(float(sum(x) / len(x)), 4) if x else None  # noqa: E731
    return dict(n=n, table_recall=f(tr), table_precision=f(tp), column_recall=f(cr), column_precision=f(cp),
                table_all_recalled=f([x == 1.0 for x in tr]), column_all_recalled=f([x == 1.0 for x in cr]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bird", required=True)
    ap.add_argument("--variant", required=True, choices=["full", "compact", "lexical", "oracle"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--eval", action="store_true")
    a = ap.parse_args()
    dev = json.load(open(os.path.join(a.bird, "dev.json")))
    rows = [build(a, t) for t in dev]
    with open(a.out, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    print(f"{a.variant}: {len(rows)} briefs, mean {sum(len(r['brief']) for r in rows) / len(rows):.0f} chars, "
          f"mean build {1000 * sum(r['build_s'] for r in rows) / len(rows):.2f} ms")
    if a.eval:
        print(json.dumps(selection_metrics(rows, dev, a.bird)))


if __name__ == "__main__":
    main()
