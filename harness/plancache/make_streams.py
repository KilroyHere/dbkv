"""Write the W question streams (PLAN §2h; interface in the W spec).

  python harness/plancache/make_streams.py            # streams + brief
  python harness/plancache/make_streams.py --validate # also execute every gold SQL once (run inside srun)

Outputs ($DBKV_DATA/plancache/):
  streams/w_r{00,20,50,80}_s{0,1}.jsonl   300 questions each (seed 0 = evaluation, seed 1 = calibration)
  streams/summary.json                     realized repeat rates per prefix
  brief_tpcds_compact.txt                  compact brief from the sf1 tenant (harness/plancache/brief.py)
  gold_validation.json                     with --validate: per-stream empty/error rates, per-template runtimes

Repeat definition. With T = 30 templates a stream can contain at most 30 first occurrences, so the strict repeat rate
("template appeared at an earlier position", the interface's is_repeat) is >= 1 - 30/n: >= 80% over 150 questions and
>= 90% over 300. Strict 0/20/50% streams (and strict 80% over 300) are therefore impossible. The parent's fallback for
r00 ("new = not seen in the previous 150 questions") is also impossible, since it needs 151 distinct templates.
The streams are therefore built on a WINDOWED definition, the same for every rate:
  windowed repeat (is_repeat_w): the template appeared within the previous L = 25 positions
  windowed new:                  the template did not appear in the previous 25 positions
L = 25 < T, so a windowed-new template always exists (>= 5 candidates). New questions prefer templates never seen
before in the stream (uniform among them) and only fall back to "not in the last 25" (uniform) once all 30 have
appeared. A repeat picks a uniformly random template among those in the window (= the "already seen" set under the
windowed definition). The windowed repeat fraction is kept within +-1 question of the target over EVERY prefix
(randomized balanced walk; position 0 is always new). Each record carries both is_repeat (strict, interface) and
is_repeat_w, plus gap = positions since the template last appeared (null if never).
Tenants, phrasings and parameters are drawn independently and fresh for every question.
"""
import argparse, json, os, random, sys, time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import templates as T  # noqa: E402

DATA = os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv")
TENANTS = ["sf0.5", "sf1", "sf2", "sf5"]
RATES = [0, 20, 50, 80]
SEEDS = [0, 1]
N = 300
WINDOW = 25


def db_path(tenant):
    return os.path.join(DATA, "tenants", f"tpcds_{tenant}.duckdb")


def schedule(rate, rng, n=N):
    """is_repeat_w per position: |#repeats - r*(i+1)| < 1 for every prefix (0 is forced new)."""
    r = rate / 100
    out, k = [], 0
    for i in range(n):
        ok_rep = i > 0 and abs(k + 1 - r * (i + 1)) < 1
        ok_new = abs(k - r * (i + 1)) < 1
        if ok_rep and ok_new:
            rep = rng.random() < r
        else:
            rep = ok_rep
        out.append(rep)
        k += rep
    return out


def make_stream(rate, seed, cons):
    rng = random.Random(f"W-r{rate:02d}-s{seed}")
    ids = [t["id"] for t in T.TEMPLATES]
    sched = schedule(rate, rng)
    seq, last = [], {}
    rows = []
    for i, rep in enumerate(sched):
        window = {seq[j] for j in range(max(0, i - WINDOW), i)}
        if rep:
            tid = rng.choice(sorted(window))
        else:
            unseen = [t for t in ids if t not in last]
            cand = unseen if unseen else [t for t in ids if t not in window]
            tid = rng.choice(cand)
        tenant = rng.choice(TENANTS)
        tpl = T.BY_ID[tid]
        params = T.draw_params(tpl, rng, cons[tenant], tenant)
        ph = rng.randrange(len(tpl["phrasings"]))
        question, sql = T.render(tpl, params, ph)
        rows.append(dict(qid=f"r{rate:02d}s{seed}-{i:04d}", pos=i, tenant=tenant, db_path=db_path(tenant),
                         template_id=tid, phrasing_id=ph, params=params, question=question, evidence="",
                         gold_sql=sql, is_repeat=tid in last, is_repeat_w=tid in window,
                         gap=(i - last[tid]) if tid in last else None, complexity=tpl["complexity"]))
        assert (tid in window) == rep
        seq.append(tid)
        last[tid] = i
    return rows


def prefix_stats(rows):
    out = {}
    for n in (50, 100, 150, 200, 250, 300):
        sub = rows[:n]
        out[n] = dict(strict=round(sum(r["is_repeat"] for r in sub) / n, 4),
                      window=round(sum(r["is_repeat_w"] for r in sub) / n, 4))
    w = [sum(r["is_repeat_w"] for r in rows[:n]) / n for n in range(150, len(rows) + 1)]
    out["window_min_max_over_prefixes_ge150"] = [round(min(w), 4), round(max(w), 4)]
    out["distinct_templates"] = len({r["template_id"] for r in rows})
    out["first_occurrences"] = sum(not r["is_repeat"] for r in rows)
    out["tenants"] = dict(Counter(r["tenant"] for r in rows))
    return out


def is_empty(res):
    return len(res) == 0 or all(all(v is None for v in row) for row in res)


def validate(streams, cons):
    per_tpl = defaultdict(list)
    per_stream = {}
    for name, rows in streams.items():
        n_empty = n_err = 0
        for r in rows:
            con = cons[r["tenant"]]
            t0 = time.perf_counter()
            try:
                res = con.execute(r["gold_sql"]).fetchall()
                dt = time.perf_counter() - t0
                emp = is_empty(res)
                per_tpl[r["template_id"]].append((r["tenant"], dt, emp, len(res), None))
                n_empty += emp
            except Exception as e:  # noqa: BLE001
                n_err += 1
                per_tpl[r["template_id"]].append((r["tenant"], time.perf_counter() - t0, False, 0, str(e)[:200]))
        per_stream[name] = dict(n=len(rows), empty_rate=round(n_empty / len(rows), 4), error_rate=round(n_err / len(rows), 4))
        print(name, per_stream[name], flush=True)
    tpl_out = {}
    for tid, xs in sorted(per_tpl.items()):
        ts = sorted(x[1] for x in xs)
        by_t = defaultdict(list)
        for x in xs:
            by_t[x[0]].append(x[1])
        tpl_out[tid] = dict(n=len(xs), empty_rate=round(sum(x[2] for x in xs) / len(xs), 4),
                            errors=sum(x[4] is not None for x in xs),
                            error_examples=list({x[4] for x in xs if x[4]})[:2],
                            median_s=round(ts[len(ts) // 2], 4), max_s=round(ts[-1], 4),
                            median_rows=sorted(x[3] for x in xs)[len(xs) // 2],
                            max_s_by_tenant={t: round(max(v), 4) for t, v in sorted(by_t.items())})
    return dict(per_stream=per_stream, per_template=tpl_out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    import duckdb
    cons = {}
    for t in TENANTS:
        c = duckdb.connect(db_path(t), read_only=True)
        c.execute("SET memory_limit='16GB'"); c.execute(f"SET threads={a.threads}")
        cons[t] = c
    out_dir = os.path.join(DATA, "plancache", "streams")
    os.makedirs(out_dir, exist_ok=True)
    streams, summary = {}, {}
    for rate in RATES:
        for seed in SEEDS:
            T._DB_CACHE.clear()
            rows = make_stream(rate, seed, cons)
            name = f"w_r{rate:02d}_s{seed}"
            with open(os.path.join(out_dir, name + ".jsonl"), "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
            streams[name] = rows
            summary[name] = prefix_stats(rows)
            print(name, json.dumps(summary[name]), flush=True)
    summary["definition"] = (f"is_repeat_w = template in previous {WINDOW} positions (controlled to the target "
                             "within +-1 question over every prefix); is_repeat = strict (appeared anywhere earlier)")
    json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1)

    import brief
    text = brief.render(cons["sf1"])
    open(os.path.join(DATA, "plancache", "brief_tpcds_compact.txt"), "w").write(text + "\n")
    print(f"brief: {len(text)} chars, ~{len(text) // 4} tokens")

    if a.validate:
        v = validate(streams, cons)
        v["brief_chars"] = len(text)
        v["brief_tokens_est"] = len(text) // 4
        json.dump(v, open(os.path.join(DATA, "plancache", "gold_validation.json"), "w"), indent=1)
        for tid, x in v["per_template"].items():
            print(tid, x)


if __name__ == "__main__":
    main()
