"""G2 analysis: does the EXPLAIN estimate rank and classify query runtimes, and does it beat
per-template history on templates it has not seen?

  python calib/g2_analyze.py <run_dir> [--short 0.25 --long 2.0]

Reads <run_dir>/results.csv (g2_run.py), writes <run_dir>/summary.json and summary.md.
Predictors (fit per database; pooled metrics concatenate the per-database predictions):
  explain   robust (Huber) linear fit of log runtime on log-EC plan features
  explain1  same, single feature log(max EC)  (the simplest usable score)
  history   median log runtime of the template's other (training) instances; global median if none
  global    global median of the training set
Splits: LOTO (leave-one-template-out: unseen templates) and random 5-fold (seen templates).
Censored (timed-out) queries keep runtime = timeout: they rank last and fall in the long class.
"""
import argparse, json, math, os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

LOGF = ["root_ec", "sum_ec", "max_ec", "scan_ec_sum", "scan_base_rows", "max_base_rows",
        "join_ec_sum", "max_join_ec", "agg_in_ec"]
RAWF = ["logsum_ec", "n_ops", "n_scans", "n_joins", "n_aggs", "n_filters", "n_order", "n_topn", "n_window",
        "n_cte", "depth"]
SCORES = LOGF + ["logsum_ec", "n_ops", "n_joins"]  # single-feature rank checks
CLS = ["short", "medium", "long"]


def design(df):
    X = np.column_stack([np.log1p(df[c].astype(float).values) for c in LOGF] +
                        [df[c].astype(float).values for c in RAWF])
    return X


def huber_fit(X, y, delta=1.0, lam=1e-2, iters=50):
    """Huber-loss linear regression (IRLS) with a small ridge on standardized features."""
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.ones(len(y))
    P = lam * np.eye(Z.shape[1])
    P[0, 0] = 0
    b = np.zeros(Z.shape[1])
    for _ in range(iters):
        W = Z * w[:, None]
        b_new = np.linalg.solve(Z.T @ W + P * len(y), W.T @ y)
        r = y - Z @ b_new
        s = np.median(np.abs(r)) / 0.6745 + 1e-9
        a = np.abs(r) / (delta * s)
        w = np.where(a <= 1, 1.0, 1.0 / np.maximum(a, 1e-12))
        if np.allclose(b, b_new, atol=1e-7):
            b = b_new
            break
        b = b_new
    return lambda Xn: np.column_stack([np.ones(len(Xn)), (Xn - mu) / sd]) @ b


def to_cls(sec, short, long):
    sec = np.asarray(sec)
    return np.where(sec < short, 0, np.where(sec < long, 1, 2))


def predict_split(d, train, test):
    """Return dict predictor -> predicted log10 seconds for rows `test` given rows `train`."""
    y = np.log10(d["y"].values)
    X = design(d)
    out = {}
    out["explain"] = huber_fit(X[train], y[train])(X[test])
    x1 = np.log1p(d["max_ec"].astype(float).values)[:, None]
    out["explain1"] = huber_fit(x1[train], y[train])(x1[test])
    g = np.median(y[train])
    out["global"] = np.full(len(test), g)
    tmed = pd.Series(y[train]).groupby(d["template"].values[train]).median()
    out["history"] = np.array([tmed.get(t, g) for t in d["template"].values[test]])
    return out


def evaluate(d, mode, seed=0, folds=5):
    n = len(d)
    preds = {k: np.full(n, np.nan) for k in ("explain", "explain1", "global", "history")}
    if mode == "loto":
        groups = [np.where(d["template"].values == t)[0] for t in d["template"].unique()]
    else:
        perm = np.random.default_rng(seed).permutation(n)
        groups = [perm[i::folds] for i in range(folds)]
    for test in groups:
        train = np.setdiff1d(np.arange(n), test)
        if len(train) < 10:
            continue
        for k, v in predict_split(d, train, test).items():
            preds[k][test] = v
    return preds


def metrics(y_sec, pred_log10, short, long):
    ok = ~np.isnan(pred_log10)
    t, p = to_cls(y_sec[ok], short, long), to_cls(10 ** pred_log10[ok], short, long)
    cm = np.zeros((3, 3), int)
    for a, b in zip(t, p):
        cm[a, b] += 1
    rho = spearmanr(pred_log10[ok], y_sec[ok]).statistic if np.ptp(pred_log10[ok]) > 0 else float("nan")
    return dict(n=int(ok.sum()), acc=float((t == p).mean()), rho=None if math.isnan(rho) else float(rho),
                mae_log10=float(np.mean(np.abs(pred_log10[ok] - np.log10(y_sec[ok])))),
                confusion=cm.tolist())


def _null_const_rho(r, mode):
    """Global (and LOTO history, which equals global) are one constant per fold: rho is an artifact."""
    r["global"]["rho"] = None
    if mode == "loto":
        r["history"]["rho"] = None


def within_template_rho(d, feat="max_ec", min_n=5):
    rs = []
    for _, g in d.groupby("template"):
        if len(g) >= min_n and g[feat].nunique() > 1 and g["y"].nunique() > 1:
            rs.append(spearmanr(g[feat], g["y"]).statistic)
    return (float(np.nanmean(rs)) if rs else None), len(rs)


def analyze(df, short, long, name):
    d = df.reset_index(drop=True)
    y = d["y"].values
    res = dict(db=name, n=len(d), n_templates=int(d["template"].nunique()),
               n_censored=int(d["censored"].sum()),
               runtime_s=dict(zip(["min", "p10", "p50", "p90", "p99", "max"],
                                  [float(np.percentile(y, q)) for q in (0, 10, 50, 90, 99, 100)])),
               class_counts=dict(zip(CLS, np.bincount(to_cls(y, short, long), minlength=3).tolist())),
               explain_ms=dict(mean=float(d["explain_ms"].mean()), p50=float(d["explain_ms"].median()),
                               p99=float(d["explain_ms"].quantile(.99)),
                               mean_second_call=float(d["explain_ms2"].mean())))
    res["rho_feature"] = {f: float(spearmanr(d[f], y).statistic) for f in SCORES if d[f].nunique() > 1}
    res["rho_within_template_max_ec"], res["n_templates_within"] = within_template_rho(d)
    res["by_family_rho_max_ec"] = {fam: float(spearmanr(g["max_ec"], g["y"]).statistic)
                                   for fam, g in d.groupby("family") if len(g) > 5}
    for mode in ("loto", "random"):
        res[mode] = {}
        for k, p in evaluate(d, mode).items():
            res[mode][k] = metrics(y, p, short, long)
        _null_const_rho(res[mode], mode)
        res[mode]["_preds"] = None
    return res


def per_db_preds(df):
    """Pooled metrics: predictions fit within each database, then concatenated."""
    allp = {m: {k: [] for k in ("explain", "explain1", "global", "history")} for m in ("loto", "random")}
    ys = []
    for _, g in df.groupby("db"):
        g = g.reset_index(drop=True)
        ys.append(g["y"].values)
        for m in allp:
            for k, v in evaluate(g, m).items():
                allp[m][k].append(v)
    return np.concatenate(ys), {m: {k: np.concatenate(v) for k, v in p.items()} for m, p in allp.items()}


def fmt_md(S, short, long):
    L = [f"# G2 EXPLAIN calibration: run `{S['run_id']}`", "",
         f"Classes: short < {short} s <= medium < {long} s <= long. Median of timed runs; timeouts censored "
         f"at the timeout (long class). Predictors fit per database.", ""]
    for r in S["dbs"] + [S["pooled"]]:
        L += [f"## {r['db']}: {r['n']} queries, {r['n_templates']} templates, {r['n_censored']} censored", "",
              "runtime s: " + ", ".join(f"{k} {v:.4g}" for k, v in r["runtime_s"].items()),
              f"  \nclass counts: {r['class_counts']}  \nEXPLAIN latency: mean {r['explain_ms']['mean']:.2f} ms, "
              f"p50 {r['explain_ms']['p50']:.2f}, p99 {r['explain_ms']['p99']:.2f} "
              f"(repeat call mean {r['explain_ms']['mean_second_call']:.2f})", ""]
        if "rho_feature" in r:
            top = sorted(r["rho_feature"].items(), key=lambda kv: -abs(kv[1]))[:6]
            L += ["Spearman rho, single EXPLAIN feature vs runtime: " +
                  ", ".join(f"{k} {v:.3f}" for k, v in top) +
                  f"  \nmean within-template rho (max_ec): {r['rho_within_template_max_ec']}", ""]
        L += ["| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |", "|---|---|---|---|---|---|"]
        for m in ("loto", "random"):
            for k in ("explain", "explain1", "history", "global"):
                x = r[m][k]
                rho = "nan" if x["rho"] is None else f"{x['rho']:.3f}"
                L.append(f"| {m} | {k} | {x['acc']:.3f} | {rho} | {x['mae_log10']:.3f} | {x['confusion']} |")
        L.append("")
    k = S["kill_rule"]
    L += ["## Kill rule (PLAN §3 G2)", "",
          f"- rho(EXPLAIN regressor, LOTO, pooled) = {k['rho_explain_loto']:.3f} (kill if < 0.5)",
          f"- LOTO acc EXPLAIN {k['acc_explain_loto']:.3f} vs history {k['acc_history_loto']:.3f}; "
          f"MAE log10 {k['mae_explain_loto']:.3f} vs {k['mae_history_loto']:.3f}",
          f"- **killed: {k['killed']}** (rho < 0.5, or LOTO accuracy not above history)",
          f"- classes degenerate (>=95% in one class; accuracy test uninformative): {k['classes_degenerate']}", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--short", type=float, default=0.25)
    ap.add_argument("--long", type=float, default=2.0)
    ap.add_argument("--families", default=None, help="comma list to keep (tpch,tpcds,probe)")
    ap.add_argument("--tertiles", action="store_true",
                    help="diagnostic: set short/long to the runtime tertiles instead of fixed seconds")
    a = ap.parse_args()
    df = pd.read_csv(os.path.join(a.run_dir, "results.csv"))
    n_err = int((df["status"] == "error").sum())
    df = df[df["status"].isin(["ok", "timeout"])].copy()
    if a.families:
        df = df[df["family"].isin(a.families.split(","))]
    df["y"] = df["median_s"].astype(float).clip(lower=1e-5)
    if a.tertiles:
        a.short, a.long = (float(x) for x in np.percentile(df["y"], [100 / 3, 200 / 3]))
    S = dict(run_id=str(df["run_id"].iloc[0]), short=a.short, long=a.long, n_errors_dropped=n_err, dbs=[])
    for name, g in df.groupby("db"):
        r = analyze(g, a.short, a.long, name)
        for m in ("loto", "random"):
            r[m].pop("_preds", None)
        S["dbs"].append(r)
    # pooled
    y, P = per_db_preds(df)
    pooled = dict(db="pooled", n=len(df), n_templates=int(df["template"].nunique()),
                  n_censored=int(df["censored"].sum()),
                  runtime_s=dict(zip(["min", "p10", "p50", "p90", "p99", "max"],
                                     [float(np.percentile(y, q)) for q in (0, 10, 50, 90, 99, 100)])),
                  class_counts=dict(zip(CLS, np.bincount(to_cls(y, a.short, a.long), minlength=3).tolist())),
                  explain_ms=dict(mean=float(df["explain_ms"].mean()), p50=float(df["explain_ms"].median()),
                                  p99=float(df["explain_ms"].quantile(.99)),
                                  mean_second_call=float(df["explain_ms2"].mean())),
                  rho_feature={f: float(spearmanr(df[f], df["y"]).statistic) for f in SCORES},
                  rho_within_template_max_ec=within_template_rho(df)[0])
    for m in ("loto", "random"):
        pooled[m] = {k: metrics(y, v, a.short, a.long) for k, v in P[m].items()}
        _null_const_rho(pooled[m], m)
    S["pooled"] = pooled
    L = pooled["loto"]
    rho = L["explain"]["rho"] or 0.0
    S["kill_rule"] = dict(rho_explain_loto=rho, acc_explain_loto=L["explain"]["acc"],
                          acc_history_loto=L["history"]["acc"], mae_explain_loto=L["explain"]["mae_log10"],
                          mae_history_loto=L["history"]["mae_log10"],
                          killed=bool(rho < 0.5 or L["explain"]["acc"] <= L["history"]["acc"]))
    cc = pooled["class_counts"]
    # With >=95% of queries in one class, LOTO history (= global median) also gets ~all right, so the
    # accuracy comparison is a tie by construction; the class test is then uninformative.
    S["kill_rule"]["classes_degenerate"] = bool(max(cc.values()) >= 0.95 * len(df))
    json.dump(S, open(os.path.join(a.run_dir, "summary.json"), "w"), indent=1)
    md = fmt_md(S, a.short, a.long)
    open(os.path.join(a.run_dir, "summary.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
