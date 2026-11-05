"""Stage 1.2: does the adapter's SFT split touch BIRD dev? Also picks the 3 few-shot examples for arm (b).

  python -I harness/expert/contam.py --sft $DBKV_DATA/expert/sft/splits/dbdev4_train_5160.jsonl \
      --dev $DBKV_DATA/bird/dev_20240627/dev.json --out results/expert_contam.md --fewshot harness/expert/fewshot.json

Few-shot rule (EXPERT.md, written before Stage 1 data): seed 0, one simple / moderate / challenging, 3 different DBs.
Amended before Stage 1 data: the split has no difficulty or db_id field, so difficulty = SQL-length tertile and
DB = the schema's set of table names.
"""
import argparse, json, os, random, re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TASK = re.compile(r"\ATask\n(.*?)\n\nEvidence\n(.*?)\n\nComplete SQLite schema with column meanings\n(.*)\Z", re.S)
SQL = re.compile(r"<sql>\s*(.*?)\s*</sql>", re.S)


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def schema_excerpt(schema, sql):
    """The CREATE TABLE blocks (without column meanings) of the tables the SQL uses."""
    blocks = [b.split("\nColumn meanings:")[0].strip() for b in schema.split("\n\n") if b.startswith("CREATE")]
    low = sql.lower()
    keep = []
    for b in blocks:
        m = re.match(r'CREATE TABLE\s+[`"\[]?([^`"\]\s(]+)', b, re.I)
        if m and re.search(r"(?<![a-z0-9_])" + re.escape(m.group(1).lower()) + r"(?![a-z0-9_])", low):
            keep.append(b)
    return "\n".join(keep)


def tables_of_schema(schema):
    return frozenset(m.lower() for m in re.findall(r'CREATE TABLE\s+[`"\[]?([^`"\]\s(]+)', schema, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sft", required=True); ap.add_argument("--dev", required=True)
    ap.add_argument("--qids", default="", help="config.json of a Test 3 run (its qids = our 150 tasks)")
    ap.add_argument("--out", required=True); ap.add_argument("--fewshot", required=True)
    a = ap.parse_args()
    dev = json.load(open(a.dev))
    dev_dbs = {d["db_id"] for d in dev}
    dev_tabs = {t["db_id"]: frozenset(x.lower() for x in t["table_names_original"])
                for t in json.load(open(os.path.join(os.path.dirname(a.dev), "dev_tables.json")))}
    dev_q = {norm(d["question"]): d for d in dev}
    ours = set(json.load(open(a.qids))["qids"]) if a.qids else set()
    our_q = {norm(d["question"]) for d in dev if d["question_id"] in ours}
    sysp = open(os.path.join(HERE, "expert_system_prompt.txt"), encoding="utf-8").read().strip()
    recs = [json.loads(l) for l in open(a.sft, encoding="utf-8")]
    dbs = Counter(r.get("db_id") for r in recs)
    sys_same = sum(r["messages"][0]["content"].strip() == sysp for r in recs)
    parsed, q_hits, q_hits_ours, ev_hits, sql_hits = [], [], 0, 0, 0
    dev_sql = {norm(d["SQL"]) for d in dev}
    dev_ev = {norm(d["evidence"]) for d in dev if len(norm(d.get("evidence", ""))) > 40}
    for r in recs:
        u = next(m["content"] for m in r["messages"] if m["role"] == "user")
        asst = next(m["content"] for m in r["messages"] if m["role"] == "assistant")
        m = TASK.match(u)
        q, ev, sch = (m.group(1), m.group(2), m.group(3)) if m else ("", "", "")
        s = SQL.findall(asst); s = s[-1].strip() if s else ""
        fp = tables_of_schema(sch)
        parsed.append(dict(r=r, q=q, ev=ev, schema=sch, sql=s, fp=fp, db="+".join(sorted(fp))[:60]))
        if norm(q) in dev_q:
            q_hits.append((r.get("db_id"), q))
        q_hits_ours += norm(q) in our_q
        ev_hits += norm(ev) in dev_ev
        sql_hits += norm(s) in dev_sql
    fps = Counter(p["fp"] for p in parsed)
    jac = lambda x, y: len(x & y) / len(x | y) if x | y else 0
    near = sorted({(d, round(max(jac(f, t) for f in fps), 2)) for d, t in dev_tabs.items()}, key=lambda x: -x[1])
    db_overlap = [d for d, j in near if j >= 0.5]
    L = ["# Expert Stage 1.2: adapter SFT split vs BIRD dev", "",
         f"- SFT split `{os.path.basename(a.sft)}`: {len(recs)} records, {len(fps)} distinct schemas (no db_id field; DB = set of table names); "
         f"{sum(1 for p in parsed if p['q'])} parsed as Task/Evidence/Schema",
         f"- system prompt identical to `harness/expert/expert_system_prompt.txt`: {sys_same} / {len(recs)}",
         f"- **database overlap with BIRD dev's {len(dev_dbs)} DBs (table-set Jaccard ≥ 0.5 with any SFT schema): {len(db_overlap)}** {db_overlap}; "
         f"highest Jaccard per dev DB: {near}",
         f"- **exact (normalized) question matches with BIRD dev ({len(dev)} questions): {len(q_hits)}**; "
         f"with our 150 tasks: {q_hits_ours}",
         f"- evidence-text matches (dev evidence > 40 chars): {ev_hits}; target-SQL matches with dev gold SQL: {sql_hits}",
         ]
    for db, q in q_hits[:10]:
        L.append(f"  - match: [{db}] {q[:120]}")
    # few-shot selection
    rng = random.Random(0)
    ok = [p for p in parsed if p["q"] and p["sql"]]
    lens = sorted(len(p["sql"]) for p in ok); t1, t2 = lens[len(lens) // 3], lens[2 * len(lens) // 3]
    tier = lambda p: "short" if len(p["sql"]) < t1 else ("medium" if len(p["sql"]) < t2 else "long")
    chosen, used = [], set()
    for diff in ("short", "medium", "long"):
        pool = [p for p in ok if tier(p) == diff and p["fp"] not in used]
        rng.shuffle(pool)
        for p in pool:
            ex = schema_excerpt(p["schema"], p["sql"])
            if ex and len(ex) < 2500:
                chosen.append(dict(db_id=p["db"], difficulty="sql-length " + diff, question_id=p["r"].get("question_id"),
                                   question=p["q"].strip(),
                                   evidence="" if p["ev"].strip() == "No additional evidence." else p["ev"].strip(),
                                   schema=ex, sql=p["sql"]))
                used.add(p["fp"]); break
    json.dump(chosen, open(a.fewshot, "w"), indent=1, ensure_ascii=False)
    L += ["", f"Few-shot examples for arm (b) (`{os.path.relpath(a.fewshot)}`, seed 0): "
          + "; ".join(f"{c['difficulty']} [{c['db_id']}] q{c['question_id']}" for c in chosen)
          + "; none on a BIRD-dev schema: "
          + str(all(max(jac(frozenset(c["db_id"].split("+")), t) for t in dev_tabs.values()) < 0.5 for c in chosen))]
    open(a.out, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
