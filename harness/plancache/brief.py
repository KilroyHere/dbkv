"""Compact schema brief for a DuckDB TPC-DS tenant, same rules as harness/brief/build.py render(variant compact).

build.py's meta() reads SQLite pragmas (table_info, foreign_key_list) through tools.connect, so it cannot read DuckDB.
This is the equivalent for DuckDB with the same output format:
  "<table>: <col> <TYPE>[ PK][ e.g. 'v1', 'v2']; ..."  one line per table (tables sorted by name, columns in table order)
  "Joins: a.x = b.y; ..."
Rules carried over:
  - types as declared (DuckDB names: INTEGER, VARCHAR, DECIMAL(7,2), DATE, ...)
  - 2 sample values per text column (CHAR/VARCHAR/TEXT): the first 3 distinct non-null values of length <= 60
    (first-occurrence order, by rowid, which is deterministic), truncated to 30 chars, 2 shown
  - PK flags and joins: the dsdgen DuckDB files have no constraints (duckdb_constraints() is empty), so PKs are the
    TPC-DS spec's primary keys and joins are the spec's foreign keys, recovered from the TPC-DS key naming: a column
    named <prefix>_<role>_<entity>_sk references the dimension whose surrogate key is <entity>_sk (date, time, item,
    customer, cdemo -> customer_demographics, hdemo -> household_demographics, addr -> customer_address, store, promo,
    warehouse, ship_mode, call_center, catalog_page, web_page, web_site, reason, income_band); plus the returns -> sales
    links (ticket/order number) that the spec defines. build.py's own inference (same column name as another table's
    single-column PK) finds nothing here because TPC-DS prefixes every column.

  python harness/plancache/brief.py DB.duckdb OUT.txt
"""
import re
import sys

import duckdb

PK = {
    "call_center": ["cc_call_center_sk"], "catalog_page": ["cp_catalog_page_sk"],
    "catalog_returns": ["cr_item_sk", "cr_order_number"], "catalog_sales": ["cs_item_sk", "cs_order_number"],
    "customer": ["c_customer_sk"], "customer_address": ["ca_address_sk"], "customer_demographics": ["cd_demo_sk"],
    "date_dim": ["d_date_sk"], "household_demographics": ["hd_demo_sk"], "income_band": ["ib_income_band_sk"],
    "inventory": ["inv_date_sk", "inv_item_sk", "inv_warehouse_sk"], "item": ["i_item_sk"], "promotion": ["p_promo_sk"],
    "reason": ["r_reason_sk"], "ship_mode": ["sm_ship_mode_sk"], "store": ["s_store_sk"],
    "store_returns": ["sr_item_sk", "sr_ticket_number"], "store_sales": ["ss_item_sk", "ss_ticket_number"],
    "time_dim": ["t_time_sk"], "warehouse": ["w_warehouse_sk"], "web_page": ["wp_web_page_sk"],
    "web_returns": ["wr_item_sk", "wr_order_number"], "web_sales": ["ws_item_sk", "ws_order_number"],
    "web_site": ["web_site_sk"],
}
# FK suffix -> (table, pk column); longest suffixes first
FK_SUFFIX = [
    ("_catalog_page_sk", "catalog_page", "cp_catalog_page_sk"), ("_call_center_sk", "call_center", "cc_call_center_sk"),
    ("_income_band_sk", "income_band", "ib_income_band_sk"), ("_ship_mode_sk", "ship_mode", "sm_ship_mode_sk"),
    ("_warehouse_sk", "warehouse", "w_warehouse_sk"), ("_web_page_sk", "web_page", "wp_web_page_sk"),
    ("_web_site_sk", "web_site", "web_site_sk"), ("_customer_sk", "customer", "c_customer_sk"),
    ("_reason_sk", "reason", "r_reason_sk"), ("_cdemo_sk", "customer_demographics", "cd_demo_sk"),
    ("_hdemo_sk", "household_demographics", "hd_demo_sk"), ("_promo_sk", "promotion", "p_promo_sk"),
    ("_store_sk", "store", "s_store_sk"), ("_addr_sk", "customer_address", "ca_address_sk"),
    ("_item_sk", "item", "i_item_sk"), ("_date_sk", "date_dim", "d_date_sk"), ("_time_sk", "time_dim", "t_time_sk"),
]
RETURN_LINKS = [("store_returns", "sr_ticket_number", "store_sales", "ss_ticket_number"),
                ("catalog_returns", "cr_order_number", "catalog_sales", "cs_order_number"),
                ("web_returns", "wr_order_number", "web_sales", "ws_order_number")]


def q(name):
    return f"`{name}`" if re.search(r"[^A-Za-z0-9_]", name) else name


def meta(con):
    tabs = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()]
    cols, samples, joins = {}, {}, set()
    for t in tabs:
        info = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='main' "
                           "AND table_name=? ORDER BY ordinal_position", [t]).fetchall()
        pk = set(PK.get(t, []))
        cols[t] = [(c, typ, c in pk) for c, typ in info]
        for c, typ in info:
            vals = []
            if any(k in typ.upper() for k in ("CHAR", "TEXT", "STRING")):
                vals = [str(v[0])[:30] for v in con.execute(
                    f"SELECT {q(c)} FROM (SELECT {q(c)}, min(rowid) r FROM {q(t)} WHERE {q(c)} IS NOT NULL "
                    f"AND length({q(c)}) <= 60 GROUP BY {q(c)}) ORDER BY r LIMIT 3").fetchall()]
            samples[(t, c)] = vals
            for suf, rt, rc in FK_SUFFIX:
                if c.endswith(suf):
                    if rt in tabs and c != rc:
                        joins.add((t, c, rt, rc))
                    break
    for a, b, c, d in RETURN_LINKS:
        if a in tabs and c in tabs:
            joins.add((a, b, c, d))
    return dict(tables=tabs, cols=cols, samples=samples, joins=sorted(joins))


def render(con, samples=2):
    m = meta(con)
    lines = []
    for t in m["tables"]:
        parts = []
        for c, typ, pk in m["cols"][t]:
            s = f"{q(c)} {typ}".strip() + (" PK" if pk else "")
            v = m["samples"].get((t, c), [])[:samples]
            if v:
                s += " e.g. " + ", ".join(repr(x) for x in v)
            parts.append(s)
        lines.append(f"{q(t)}: " + "; ".join(parts))
    js = [f"{q(a)}.{q(b)} = {q(c)}.{q(d)}" for a, b, c, d in m["joins"]]
    if js:
        lines.append("Joins: " + "; ".join(js))
    return "\n".join(lines)


if __name__ == "__main__":
    con = duckdb.connect(sys.argv[1], read_only=True)
    text = render(con)
    open(sys.argv[2], "w").write(text + "\n")
    print(f"{len(text)} chars, ~{len(text) // 4} tokens (chars/4), {text.count(chr(10)) + 1} lines")
