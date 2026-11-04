"""G2 query generator: TPC-H templates (qgen-style parameters), TPC-DS (tpcds_queries() with
light parameter variation) and agent-like exploration probes built from schema metadata.

Every query is a dict {qid, template, family, sql, meta}. `template` is the unit held out in
leave-one-template-out evaluation: tpch_q01..q22, tpcds_q01..q99, probe_<kind>.

Used by g2_run.py on the compute node (probe generation reads table stats from the database).
"""
import datetime as dt
import math
import random
import re

# ---------------------------------------------------------------- TPC-H (spec 2.4, qgen ranges)
NATIONS = [("ALGERIA", 0), ("ARGENTINA", 1), ("BRAZIL", 1), ("CANADA", 1), ("EGYPT", 4),
           ("ETHIOPIA", 0), ("FRANCE", 3), ("GERMANY", 3), ("INDIA", 2), ("INDONESIA", 2),
           ("IRAN", 4), ("IRAQ", 4), ("JAPAN", 2), ("JORDAN", 4), ("KENYA", 0), ("MOROCCO", 0),
           ("MOZAMBIQUE", 0), ("PERU", 1), ("CHINA", 2), ("ROMANIA", 3), ("SAUDI ARABIA", 4),
           ("VIETNAM", 2), ("RUSSIA", 3), ("UNITED KINGDOM", 3), ("UNITED STATES", 1)]
REGIONS = ["AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"]
SEGMENTS = ["AUTOMOBILE", "BUILDING", "FURNITURE", "MACHINERY", "HOUSEHOLD"]
TYPE_S1 = ["STANDARD", "SMALL", "MEDIUM", "LARGE", "ECONOMY", "PROMO"]
TYPE_S2 = ["ANODIZED", "BURNISHED", "PLATED", "POLISHED", "BRUSHED"]
TYPE_S3 = ["TIN", "NICKEL", "BRASS", "STEEL", "COPPER"]
CONT_S1 = ["SM", "LG", "MED", "JUMBO", "WRAP"]
CONT_S2 = ["CASE", "BOX", "BAG", "JAR", "PKG", "PACK", "CAN", "DRUM"]
SHIPMODES = ["REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"]
COLORS = ("almond antique aquamarine azure beige bisque black blanched blue blush brown burlywood "
          "burnished chartreuse chiffon chocolate coral cornflower cornsilk cream cyan dark deep dim "
          "dodger drab firebrick floral forest frosted gainsboro ghost goldenrod green grey honeydew "
          "hot indian ivory khaki lace lavender lawn lemon light lime linen magenta maroon medium "
          "metallic midnight mint misty moccasin navajo navy olive orange orchid pale papaya peach "
          "peru pink plum powder puff purple red rose rosy royal saddle salmon sandy seashell sienna "
          "sky slate smoke snow spring steel tan thistle tomato turquoise violet wheat white "
          "yellow").split()

TPCH = {
 1: """select l_returnflag, l_linestatus, sum(l_quantity) as sum_qty, sum(l_extendedprice) as sum_base_price,
  sum(l_extendedprice*(1-l_discount)) as sum_disc_price, sum(l_extendedprice*(1-l_discount)*(1+l_tax)) as sum_charge,
  avg(l_quantity) as avg_qty, avg(l_extendedprice) as avg_price, avg(l_discount) as avg_disc, count(*) as count_order
from lineitem where l_shipdate <= date '1998-12-01' - interval '{delta}' day
group by l_returnflag, l_linestatus order by l_returnflag, l_linestatus""",
 2: """select s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
from part, supplier, partsupp, nation, region
where p_partkey = ps_partkey and s_suppkey = ps_suppkey and p_size = {size} and p_type like '%{type}'
  and s_nationkey = n_nationkey and n_regionkey = r_regionkey and r_name = '{region}'
  and ps_supplycost = (select min(ps_supplycost) from partsupp, supplier, nation, region
    where p_partkey = ps_partkey and s_suppkey = ps_suppkey and s_nationkey = n_nationkey
      and n_regionkey = r_regionkey and r_name = '{region}')
order by s_acctbal desc, n_name, s_name, p_partkey limit 100""",
 3: """select l_orderkey, sum(l_extendedprice*(1-l_discount)) as revenue, o_orderdate, o_shippriority
from customer, orders, lineitem
where c_mktsegment = '{segment}' and c_custkey = o_custkey and l_orderkey = o_orderkey
  and o_orderdate < date '{date}' and l_shipdate > date '{date}'
group by l_orderkey, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10""",
 4: """select o_orderpriority, count(*) as order_count from orders
where o_orderdate >= date '{date}' and o_orderdate < date '{date}' + interval '3' month
  and exists (select * from lineitem where l_orderkey = o_orderkey and l_commitdate < l_receiptdate)
group by o_orderpriority order by o_orderpriority""",
 5: """select n_name, sum(l_extendedprice*(1-l_discount)) as revenue
from customer, orders, lineitem, supplier, nation, region
where c_custkey = o_custkey and l_orderkey = o_orderkey and l_suppkey = s_suppkey
  and c_nationkey = s_nationkey and s_nationkey = n_nationkey and n_regionkey = r_regionkey
  and r_name = '{region}' and o_orderdate >= date '{date}' and o_orderdate < date '{date}' + interval '1' year
group by n_name order by revenue desc""",
 6: """select sum(l_extendedprice*l_discount) as revenue from lineitem
where l_shipdate >= date '{date}' and l_shipdate < date '{date}' + interval '1' year
  and l_discount between {disc} - 0.01 and {disc} + 0.01 and l_quantity < {qty}""",
 7: """select supp_nation, cust_nation, l_year, sum(volume) as revenue from (
  select n1.n_name as supp_nation, n2.n_name as cust_nation, extract(year from l_shipdate) as l_year,
         l_extendedprice*(1-l_discount) as volume
  from supplier, lineitem, orders, customer, nation n1, nation n2
  where s_suppkey = l_suppkey and o_orderkey = l_orderkey and c_custkey = o_custkey
    and s_nationkey = n1.n_nationkey and c_nationkey = n2.n_nationkey
    and ((n1.n_name = '{n1}' and n2.n_name = '{n2}') or (n1.n_name = '{n2}' and n2.n_name = '{n1}'))
    and l_shipdate between date '1995-01-01' and date '1996-12-31') as shipping
group by supp_nation, cust_nation, l_year order by supp_nation, cust_nation, l_year""",
 8: """select o_year, sum(case when nation = '{nation}' then volume else 0 end)/sum(volume) as mkt_share from (
  select extract(year from o_orderdate) as o_year, l_extendedprice*(1-l_discount) as volume, n2.n_name as nation
  from part, supplier, lineitem, orders, customer, nation n1, nation n2, region
  where p_partkey = l_partkey and s_suppkey = l_suppkey and l_orderkey = o_orderkey and o_custkey = c_custkey
    and c_nationkey = n1.n_nationkey and n1.n_regionkey = r_regionkey and r_name = '{region}'
    and s_nationkey = n2.n_nationkey and o_orderdate between date '1995-01-01' and date '1996-12-31'
    and p_type = '{type}') as all_nations
group by o_year order by o_year""",
 9: """select nation, o_year, sum(amount) as sum_profit from (
  select n_name as nation, extract(year from o_orderdate) as o_year,
         l_extendedprice*(1-l_discount) - ps_supplycost*l_quantity as amount
  from part, supplier, lineitem, partsupp, orders, nation
  where s_suppkey = l_suppkey and ps_suppkey = l_suppkey and ps_partkey = l_partkey and p_partkey = l_partkey
    and o_orderkey = l_orderkey and s_nationkey = n_nationkey and p_name like '%{color}%') as profit
group by nation, o_year order by nation, o_year desc""",
 10: """select c_custkey, c_name, sum(l_extendedprice*(1-l_discount)) as revenue, c_acctbal, n_name, c_address,
  c_phone, c_comment
from customer, orders, lineitem, nation
where c_custkey = o_custkey and l_orderkey = o_orderkey and o_orderdate >= date '{date}'
  and o_orderdate < date '{date}' + interval '3' month and l_returnflag = 'R' and c_nationkey = n_nationkey
group by c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment order by revenue desc limit 20""",
 11: """select ps_partkey, sum(ps_supplycost*ps_availqty) as value from partsupp, supplier, nation
where ps_suppkey = s_suppkey and s_nationkey = n_nationkey and n_name = '{nation}'
group by ps_partkey having sum(ps_supplycost*ps_availqty) > (
  select sum(ps_supplycost*ps_availqty)*{fraction} from partsupp, supplier, nation
  where ps_suppkey = s_suppkey and s_nationkey = n_nationkey and n_name = '{nation}')
order by value desc""",
 12: """select l_shipmode,
  sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
  sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from orders, lineitem
where o_orderkey = l_orderkey and l_shipmode in ('{m1}', '{m2}') and l_commitdate < l_receiptdate
  and l_shipdate < l_commitdate and l_receiptdate >= date '{date}' and l_receiptdate < date '{date}' + interval '1' year
group by l_shipmode order by l_shipmode""",
 13: """select c_count, count(*) as custdist from (
  select c_custkey, count(o_orderkey) as c_count
  from customer left outer join orders on c_custkey = o_custkey and o_comment not like '%{w1}%{w2}%'
  group by c_custkey) as c_orders
group by c_count order by custdist desc, c_count desc""",
 14: """select 100.00*sum(case when p_type like 'PROMO%' then l_extendedprice*(1-l_discount) else 0 end)
  / sum(l_extendedprice*(1-l_discount)) as promo_revenue
from lineitem, part
where l_partkey = p_partkey and l_shipdate >= date '{date}' and l_shipdate < date '{date}' + interval '1' month""",
 15: """with revenue as (select l_suppkey as supplier_no, sum(l_extendedprice*(1-l_discount)) as total_revenue
  from lineitem where l_shipdate >= date '{date}' and l_shipdate < date '{date}' + interval '3' month
  group by l_suppkey)
select s_suppkey, s_name, s_address, s_phone, total_revenue from supplier, revenue
where s_suppkey = supplier_no and total_revenue = (select max(total_revenue) from revenue)
order by s_suppkey""",
 16: """select p_brand, p_type, p_size, count(distinct ps_suppkey) as supplier_cnt from partsupp, part
where p_partkey = ps_partkey and p_brand <> '{brand}' and p_type not like '{type}%' and p_size in ({sizes})
  and ps_suppkey not in (select s_suppkey from supplier where s_comment like '%Customer%Complaints%')
group by p_brand, p_type, p_size order by supplier_cnt desc, p_brand, p_type, p_size""",
 17: """select sum(l_extendedprice)/7.0 as avg_yearly from lineitem, part
where p_partkey = l_partkey and p_brand = '{brand}' and p_container = '{container}'
  and l_quantity < (select 0.2*avg(l_quantity) from lineitem where l_partkey = p_partkey)""",
 18: """select c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, sum(l_quantity)
from customer, orders, lineitem
where o_orderkey in (select l_orderkey from lineitem group by l_orderkey having sum(l_quantity) > {qty})
  and c_custkey = o_custkey and o_orderkey = l_orderkey
group by c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice order by o_totalprice desc, o_orderdate limit 100""",
 19: """select sum(l_extendedprice*(1-l_discount)) as revenue from lineitem, part
where (p_partkey = l_partkey and p_brand = '{b1}' and p_container in ('SM CASE','SM BOX','SM PACK','SM PKG')
       and l_quantity >= {q1} and l_quantity <= {q1} + 10 and p_size between 1 and 5
       and l_shipmode in ('AIR','AIR REG') and l_shipinstruct = 'DELIVER IN PERSON')
   or (p_partkey = l_partkey and p_brand = '{b2}' and p_container in ('MED BAG','MED BOX','MED PKG','MED PACK')
       and l_quantity >= {q2} and l_quantity <= {q2} + 10 and p_size between 1 and 10
       and l_shipmode in ('AIR','AIR REG') and l_shipinstruct = 'DELIVER IN PERSON')
   or (p_partkey = l_partkey and p_brand = '{b3}' and p_container in ('LG CASE','LG BOX','LG PACK','LG PKG')
       and l_quantity >= {q3} and l_quantity <= {q3} + 10 and p_size between 1 and 15
       and l_shipmode in ('AIR','AIR REG') and l_shipinstruct = 'DELIVER IN PERSON')""",
 20: """select s_name, s_address from supplier, nation
where s_suppkey in (select ps_suppkey from partsupp
    where ps_partkey in (select p_partkey from part where p_name like '{color}%')
      and ps_availqty > (select 0.5*sum(l_quantity) from lineitem where l_partkey = ps_partkey
        and l_suppkey = ps_suppkey and l_shipdate >= date '{date}' and l_shipdate < date '{date}' + interval '1' year))
  and s_nationkey = n_nationkey and n_name = '{nation}'
order by s_name""",
 21: """select s_name, count(*) as numwait from supplier, lineitem l1, orders, nation
where s_suppkey = l1.l_suppkey and o_orderkey = l1.l_orderkey and o_orderstatus = 'F'
  and l1.l_receiptdate > l1.l_commitdate
  and exists (select * from lineitem l2 where l2.l_orderkey = l1.l_orderkey and l2.l_suppkey <> l1.l_suppkey)
  and not exists (select * from lineitem l3 where l3.l_orderkey = l1.l_orderkey and l3.l_suppkey <> l1.l_suppkey
                  and l3.l_receiptdate > l3.l_commitdate)
  and s_nationkey = n_nationkey and n_name = '{nation}'
group by s_name order by numwait desc, s_name limit 100""",
 22: """select cntrycode, count(*) as numcust, sum(c_acctbal) as totacctbal from (
  select substring(c_phone from 1 for 2) as cntrycode, c_acctbal from customer
  where substring(c_phone from 1 for 2) in ({codes})
    and c_acctbal > (select avg(c_acctbal) from customer where c_acctbal > 0.00
                     and substring(c_phone from 1 for 2) in ({codes}))
    and not exists (select * from orders where o_custkey = c_custkey)) as custsale
group by cntrycode order by cntrycode""",
}


def _month(r, y0, m0, y1, m1):
    """Random first-of-month date in [y0-m0, y1-m1]."""
    n = (y1 - y0) * 12 + (m1 - m0)
    k = r.randint(0, n)
    y, m = y0 + (m0 - 1 + k) // 12, (m0 - 1 + k) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


def _brand(r):
    return f"Brand#{r.randint(1, 5)}{r.randint(1, 5)}"


def tpch_params(q, r, sf):
    nat = lambda: r.choice(NATIONS)[0]  # noqa: E731
    jan1 = lambda: f"{r.randint(1993, 1997)}-01-01"  # noqa: E731
    if q == 1: return dict(delta=r.randint(60, 120))
    if q == 2: return dict(size=r.randint(1, 50), type=r.choice(TYPE_S3), region=r.choice(REGIONS))
    if q == 3: return dict(segment=r.choice(SEGMENTS), date=f"1995-03-{r.randint(1, 31):02d}")
    if q == 4: return dict(date=_month(r, 1993, 1, 1997, 10))
    if q == 5: return dict(region=r.choice(REGIONS), date=jan1())
    if q == 6: return dict(date=jan1(), disc=f"0.0{r.randint(2, 9)}", qty=r.randint(24, 25))
    if q == 7:
        a, b = r.sample(NATIONS, 2)
        return dict(n1=a[0], n2=b[0])
    if q == 8:
        n, reg = r.choice(NATIONS)
        return dict(nation=n, region=REGIONS[reg],
                    type=f"{r.choice(TYPE_S1)} {r.choice(TYPE_S2)} {r.choice(TYPE_S3)}")
    if q == 9: return dict(color=r.choice(COLORS))
    if q == 10: return dict(date=_month(r, 1993, 2, 1995, 1))
    if q == 11: return dict(nation=nat(), fraction=f"{0.0001 / sf:.10f}")
    if q == 12:
        a, b = r.sample(SHIPMODES, 2)
        return dict(m1=a, m2=b, date=jan1())
    if q == 13:
        return dict(w1=r.choice(["special", "pending", "unusual", "express"]),
                    w2=r.choice(["packages", "requests", "accounts", "deposits"]))
    if q == 14: return dict(date=_month(r, 1993, 1, 1997, 12))
    if q == 15: return dict(date=_month(r, 1993, 1, 1997, 10))
    if q == 16:
        return dict(brand=_brand(r), type=f"{r.choice(TYPE_S1)} {r.choice(TYPE_S2)}",
                    sizes=", ".join(str(x) for x in r.sample(range(1, 51), 8)))
    if q == 17: return dict(brand=_brand(r), container=f"{r.choice(CONT_S1)} {r.choice(CONT_S2)}")
    if q == 18: return dict(qty=r.randint(312, 315))
    if q == 19:
        return dict(b1=_brand(r), b2=_brand(r), b3=_brand(r),
                    q1=r.randint(1, 10), q2=r.randint(10, 20), q3=r.randint(20, 30))
    if q == 20: return dict(color=r.choice(COLORS), date=jan1(), nation=nat())
    if q == 21: return dict(nation=nat())
    if q == 22: return dict(codes=", ".join(f"'{c}'" for c in r.sample(range(10, 35), 7)))
    raise ValueError(q)


def gen_tpch(r, sf, instances):
    out = []
    for q in range(1, 23):
        seen = set()
        for i in range(instances * 3):
            if len(seen) >= instances:
                break
            p = tpch_params(q, r, sf)
            sql = TPCH[q].format(**p)
            if sql in seen:
                continue
            seen.add(sql)
            out.append(dict(template=f"tpch_q{q:02d}", family="tpch", sql=sql, meta=p))
    return out


# ---------------------------------------------------------------- TPC-DS
_YEAR = re.compile(r"\b(19[89]\d|200\d)\b")
_DATE = re.compile(r"'(\d{4})-(\d\d)-(\d\d)'")
_MOY = re.compile(r"(d_moy\s*=\s*)(\d{1,2})\b")


def _ds_years(sql):
    ys = [int(m.group(1)) for m in _YEAR.finditer(sql) if "year" in sql[max(0, m.start() - 60):m.start()].lower()]
    ys += [int(m.group(1)) for m in _DATE.finditer(sql)]
    return ys


def _ds_variant(sql, off, r):
    def yr(m):
        if "year" not in sql[max(0, m.start() - 60):m.start()].lower():
            return m.group(0)
        return str(int(m.group(1)) + off)

    def dte(m):
        y, mo, d = int(m.group(1)) + off, m.group(2), m.group(3)
        if mo == "02" and d == "29":
            d = "28"
        return f"'{y:04d}-{mo}-{d}'"

    s = _YEAR.sub(yr, sql)
    s = _DATE.sub(dte, s)
    s = re.sub(r"(d_month_seq\s+between\s+)(\d{4})", lambda m: m.group(1) + str(int(m.group(2)) + 12 * off), s)
    s = re.sub(r"(d_month_seq\s*=\s*)(\d{4})", lambda m: m.group(1) + str(int(m.group(2)) + 12 * off), s)
    if r.random() < 0.5:
        s = _MOY.sub(lambda m: m.group(1) + str(r.randint(1, 12)), s)
    return s


def gen_tpcds(con, r, instances):
    """instance 0 is the stock query; others shift years (kept inside 1998-2002) and maybe d_moy."""
    con.execute("LOAD tpcds")
    rows = con.execute("select query_nr, query from tpcds_queries() order by query_nr").fetchall()
    out = []
    for nr, sql in rows:
        sql = sql.strip().rstrip(";")
        ys = _ds_years(sql)
        offs = [o for o in range(-2, 3) if ys and min(ys) + o >= 1998 and max(ys) + o <= 2002] or [0]
        seen = {sql}
        out.append(dict(template=f"tpcds_q{nr:02d}", family="tpcds", sql=sql, meta=dict(off=0)))
        for _ in range(instances * 4):
            if len(seen) >= instances:
                break
            off = r.choice(offs)
            v = _ds_variant(sql, off, r)
            if v in seen:
                continue
            seen.add(v)
            out.append(dict(template=f"tpcds_q{nr:02d}", family="tpcds", sql=v, meta=dict(off=off)))
    return out


# ---------------------------------------------------------------- probes from schema metadata
NUM = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
       "UBIGINT", "FLOAT", "DOUBLE", "REAL")


def _isnum(t):
    return t.startswith("DECIMAL") or t in NUM


def _isdate(t):
    return t in ("DATE", "TIMESTAMP")


def _isstr(t):
    return t.startswith("VARCHAR") or t.startswith("CHAR")


def _lit(v, t):
    if v is None:
        return "NULL"
    if _isdate(t):
        return f"DATE '{v.isoformat()[:10]}'" if t == "DATE" else f"TIMESTAMP '{v}'"
    if _isstr(t):
        return "'" + str(v).replace("'", "''") + "'"
    return repr(v) if isinstance(v, float) else str(v)


def schema_stats(con, sample_rows=64):
    """Per table: rows, columns (name,type), min/max for numeric/date, approx distinct, sample rows."""
    tabs = con.execute("select table_name, estimated_size from duckdb_tables() "
                       "where schema_name='main' order by table_name").fetchall()
    S = {}
    for t, n in tabs:
        if not n:
            continue
        cols = con.execute("select column_name, data_type from duckdb_columns() where table_name=? "
                           "and schema_name='main' order by column_index", [t]).fetchall()
        exprs = []
        for c, ty in cols:
            exprs.append(f'approx_count_distinct("{c}")')
            if _isnum(ty) or _isdate(ty):
                exprs += [f'min("{c}")', f'max("{c}")']
        row = con.execute(f"select {', '.join(exprs)} from {t}").fetchone()
        k, info = 0, {}
        for c, ty in cols:
            d = dict(type=ty, ndv=row[k] or 1)
            k += 1
            if _isnum(ty) or _isdate(ty):
                d["min"], d["max"] = row[k], row[k + 1]
                k += 2
            info[c] = d
        sample = con.execute(f"select * from {t} using sample {sample_rows} rows").fetchall()
        S[t] = dict(rows=n, cols=info, colnames=[c for c, _ in cols], sample=sample)
    # FK edges: a table's first column is its key if (nearly) unique; another table's column joins
    # to it if its name (minus the table prefix) ends with the key's name minus prefix.
    keys = {}
    for t, s in S.items():
        c0 = s["colnames"][0]
        if (c0.endswith("key") or c0.endswith("_sk")) and s["cols"][c0]["ndv"] >= 0.9 * s["rows"]:
            keys[t] = c0
    edges = []  # (child, child_col, parent, parent_col)
    for p, pk in keys.items():
        suf = pk.split("_", 1)[1] if "_" in pk else pk
        for t, s in S.items():
            if t == p:
                continue
            for c in s["colnames"]:
                cs = c.split("_", 1)[1] if "_" in c else c
                if cs.endswith(suf) and s["cols"][c]["type"] == S[p]["cols"][pk]["type"]:
                    edges.append((t, c, p, pk))
    return S, edges


def _range_pred(r, t, c, info, sel, alias=None):
    lo, hi, ty = info["min"], info["max"], info["type"]
    col = f'{alias}."{c}"' if alias else f'"{c}"'
    if lo is None or hi is None:
        return None
    u = r.random() * (1 - sel)
    if _isdate(ty):
        span = (hi - lo).days if hasattr(hi - lo, "days") else 0
        a = lo + dt.timedelta(days=int(u * span))
        b = a + dt.timedelta(days=max(0, int(sel * span)))
        return f"{col} between {_lit(a, ty)} and {_lit(b, ty)}"
    lo, hi = float(lo), float(hi)
    a = lo + u * (hi - lo)
    b = a + sel * (hi - lo)
    if ty.startswith("DECIMAL") or ty in ("FLOAT", "DOUBLE", "REAL"):
        return f"{col} between {a:.2f} and {b:.2f}"
    return f"{col} between {int(math.floor(a))} and {int(math.ceil(b))}"


def _sel(r, lo=-4):
    return 10 ** r.uniform(lo, 0)


def gen_probes(con, r, per_family):
    S, edges = schema_stats(con)
    tabs = list(S)
    big = [t for t in tabs if S[t]["rows"] >= 1000] or tabs

    def pick_col(t, pred):
        cs = [c for c, d in S[t]["cols"].items() if pred(d["type"])]
        return r.choice(cs) if cs else None

    def any_range(t, sel):
        c = pick_col(t, lambda ty: _isnum(ty) or _isdate(ty))
        return (_range_pred(r, t, c, S[t]["cols"][c], sel), c) if c else (None, None)

    out = []

    def add(kind, sql, **meta):
        out.append(dict(template=f"probe_{kind}", family="probe", sql=sql, meta=meta))

    for _ in range(per_family):
        # point lookup on the first column (key) or a sampled value of any column
        t = r.choice(tabs)
        s = S[t]
        row = r.choice(s["sample"])
        j = 0 if r.random() < 0.7 else r.randrange(len(s["colnames"]))
        c = s["colnames"][j]
        add("point", f'select * from {t} where "{c}" = {_lit(row[j], s["cols"][c]["type"])} limit 1000',
            table=t, col=c)
        # range filter with log-uniform selectivity
        t = r.choice(big)
        sel = _sel(r)
        p, c = any_range(t, sel)
        x = pick_col(t, _isnum) or c
        add("range", f'select count(*), avg("{x}") from {t} where {p}', table=t, col=c, sel=sel)
        # group by an arbitrary column (low to very high cardinality)
        t = r.choice(big)
        g = r.choice(S[t]["colnames"])
        x = pick_col(t, _isnum)
        agg = f', sum("{x}") as s' if x and r.random() < 0.6 else ""
        w = ""
        if r.random() < 0.4:
            p, _ = any_range(t, _sel(r, -2))
            w = f" where {p}" if p else ""
        add("groupby", f'select "{g}", count(*) as n{agg} from {t}{w} group by "{g}" order by n desc limit 20',
            table=t, col=g, ndv=S[t]["cols"][g]["ndv"])
        # count / count distinct / count with equality filter
        t = r.choice(big)
        c = r.choice(S[t]["colnames"])
        k = r.random()
        if k < 0.3:
            sql = f"select count(*) from {t}"
        elif k < 0.7:
            sql = f'select count(distinct "{c}") from {t}'
        else:
            jj = S[t]["colnames"].index(c)
            v = r.choice(S[t]["sample"])[jj]
            sql = f'select count(*) from {t} where "{c}" = {_lit(v, S[t]["cols"][c]["type"])}'
        add("count", sql, table=t, col=c)
        # 2-4 way join along FK edges; each table gets at most one child (no sibling fan-out)
        if edges:
            out_j = _join(r, S, edges)
            if out_j:
                add("join", out_j[0], tables=out_j[1])
        # order by ... limit
        t = r.choice(big)
        c = r.choice(S[t]["colnames"])
        w = ""
        if r.random() < 0.5:
            p, _ = any_range(t, _sel(r, -3))
            w = f" where {p}" if p else ""
        add("topk", f'select * from {t}{w} order by "{c}" {r.choice(["asc", "desc"])} '
                    f'limit {r.choice([10, 100, 1000])}', table=t, col=c)
        # LIKE on a string column with a word from a sampled value
        cands = [(t, c) for t in big for c, d in S[t]["cols"].items() if _isstr(d["type"])]
        if cands:
            t, c = r.choice(cands)
            jj = S[t]["colnames"].index(c)
            v = str(r.choice(S[t]["sample"])[jj] or "a")
            words = [w for w in re.split(r"[^A-Za-z0-9#]+", v) if len(w) >= 3] or [v[:3] or "a"]
            wd = r.choice(words)
            pat = r.choice([f"%{wd}%", f"{wd}%", f"%{wd}%{r.choice(words)}%"]).replace("'", "''")
            if r.random() < 0.5:
                sql = f"select count(*) from {t} where \"{c}\" like '{pat}'"
            else:
                sql = f"select * from {t} where \"{c}\" like '{pat}' limit 50"
            add("like", sql, table=t, col=c)
    # dedupe by SQL text
    seen, uniq = set(), []
    for q in out:
        if q["sql"] not in seen:
            seen.add(q["sql"])
            uniq.append(q)
    return uniq


def _join(r, S, edges):
    n = r.choice([2, 2, 3, 3, 4])
    t0 = r.choice(sorted({e[0] for e in edges} | {e[2] for e in edges}))
    alias = {t0: "t0"}
    conds, has_child = [], set()
    for _ in range(n - 1):
        opts = []
        for (ch, cc, pa, pc) in edges:
            if ch in alias and pa not in alias:           # add a parent (dimension): no fan-out
                opts.append((pa, f'{alias[ch]}."{cc}" = {{new}}."{pc}"', None))
            elif pa in alias and ch not in alias and pa not in has_child:   # add one child
                opts.append((ch, f'{{new}}."{cc}" = {alias[pa]}."{pc}"', pa))
        if not opts:
            break
        new, cond, parent = r.choice(opts)
        alias[new] = f"t{len(alias)}"
        conds.append(cond.format(new=alias[new]))
        if parent:
            has_child.add(parent)
    if len(alias) < 2:
        return None
    frm = ", ".join(f"{t} {a}" for t, a in alias.items())
    where = list(conds)
    if r.random() < 0.6:
        t = r.choice(list(alias))
        cs = [c for c, d in S[t]["cols"].items() if _isnum(d["type"]) or _isdate(d["type"])]
        if cs:
            c = r.choice(cs)
            p = _range_pred(r, t, c, S[t]["cols"][c], _sel(r, -3), alias=alias[t])
            if p:
                where.append(p)
    lowcard = [(t, c) for t in alias for c, d in S[t]["cols"].items() if d["ndv"] <= 2000]
    if lowcard and r.random() < 0.5:
        t, c = r.choice(lowcard)
        sql = (f'select {alias[t]}."{c}", count(*) as n from {frm} where {" and ".join(where)} '
               f'group by 1 order by n desc limit 20')
    else:
        sql = f'select count(*) from {frm} where {" and ".join(where)}'
    return sql, list(alias)


# ---------------------------------------------------------------- entry point
def detect(con):
    tabs = {t for (t,) in con.execute("select table_name from duckdb_tables()").fetchall()}
    if "lineitem" in tabs:
        n = con.execute("select estimated_size from duckdb_tables() where table_name='orders'").fetchone()[0]
        return "tpch", max(n / 1_500_000, 0.001)
    if "store_sales" in tabs:
        return "tpcds", None
    return "other", None


def generate(con, seed=0, tpch_instances=20, tpcds_instances=5, probes_per_family=80):
    r = random.Random(seed)
    kind, sf = detect(con)
    qs = []
    if kind == "tpch":
        qs += gen_tpch(r, sf, tpch_instances)
    elif kind == "tpcds":
        qs += gen_tpcds(con, r, tpcds_instances)
    qs += gen_probes(con, r, probes_per_family)
    for i, q in enumerate(qs):
        q["qid"] = i
    return kind, sf, qs
