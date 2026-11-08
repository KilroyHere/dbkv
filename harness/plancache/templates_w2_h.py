"""Workload W2, TPC-H part: templates for all 22 TPC-H queries, same format as templates.py (TPC-DS).

Each template is a dict with the same keys as in templates.py (id, qnum, complexity, sql, slots, derive, phrasings,
optional notes) plus "bench": "tpch". Ids are "hNN" (NN = TPC-H query number).
  sql   DuckDB SQL from `SELECT query FROM tpch_queries() WHERE query_nr = qnum`, with the TPC-H substitution
        parameters (TPC-H spec 2.4.x.3) turned into {slot}s; other literals are kept as in the official text.
  slots ranges follow the spec's substitution-parameter domains (dates within 1993-1998, sizes 1-50, quantity
        312-315, ...). Categorical values with a small domain stored in the data (region, nation, market segment,
        brand, container, type) are "db" slots on the tenant; spec-fixed vocabularies with no cheap source column
        (ship modes on the big lineitem table, type syllables, p_name colours, comment words) are fixed lists.
  complexity  same convention as templates.py: "simple" (<= 3 tables, flat), "medium" (4-7 tables or a
        subquery), "complex" (CTEs / self-joins / nested multi-level subqueries).

The tenant DB for "db" slots is a TPC-H file (e.g. /pscratch/sd/a/ap2568/dbkv/tpch/tpch_sf1.duckdb or tpch_sf10);
every db-slot query reads region, nation, customer or part only. Use templates.draw_params / templates.render
(re-exported here) unchanged.
"""
try:
    from . import templates as _T
except ImportError:  # imported as a top-level module (sys.path contains harness/plancache)
    import templates as _T

from itertools import product as _product

MONTHS = _T.MONTHS
_sql_list, _nl_list, _pretty_date = _T._sql_list, _T._nl_list, _T._pretty_date
draw_params, render, db_values = _T.draw_params, _T.render, _T.db_values

YEARS_H = (1993, 1997)
SHIPMODES = ["REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"]
TYPE_S1 = ["STANDARD", "SMALL", "MEDIUM", "LARGE", "ECONOMY", "PROMO"]
TYPE_S2 = ["ANODIZED", "BURNISHED", "PLATED", "POLISHED", "BRUSHED"]
TYPE_S3 = ["TIN", "NICKEL", "BRASS", "STEEL", "COPPER"]
TYPE_12 = [f"{a} {b}" for a, b in _product(TYPE_S1, TYPE_S2)]
COLORS = ["almond", "antique", "aquamarine", "azure", "beige", "bisque", "black", "blanched", "blue", "blush",
          "brown", "burlywood", "burnished", "chartreuse", "chiffon", "chocolate", "coral", "cornflower", "cornsilk",
          "cream", "cyan", "dark", "deep", "dim", "dodger", "drab", "firebrick", "floral", "forest", "frosted",
          "gainsboro", "ghost", "goldenrod", "green", "grey", "honeydew", "hot", "indian", "ivory", "khaki", "lace",
          "lavender", "lawn", "lemon", "light", "lime", "linen", "magenta", "maroon", "medium", "metallic",
          "midnight", "mint", "misty", "moccasin", "navajo", "navy", "olive", "orange", "orchid", "pale", "papaya",
          "peach", "peru", "pink", "plum", "powder", "puff", "purple", "red", "rose", "rosy", "royal", "saddle",
          "salmon", "sandy", "seashell", "sienna", "sky", "slate", "smoke", "snow", "spring", "steel", "tan",
          "thistle", "tomato", "turquoise", "violet", "wheat", "white", "yellow"]
WORD1 = ["special", "pending", "unusual", "express"]
WORD2 = ["packages", "requests", "accounts", "deposits"]

Q_REGION = "SELECT r_name FROM region"
Q_NATION = "SELECT n_name FROM nation"
Q_NATION_REGION = "SELECT n_name || '|' || r_name FROM nation, region WHERE n_regionkey = r_regionkey"
Q_SEGMENT = "SELECT DISTINCT c_mktsegment FROM customer"
Q_BRAND = "SELECT DISTINCT p_brand FROM part"
Q_CONTAINER = "SELECT DISTINCT p_container FROM part"
Q_TYPE = "SELECT DISTINCT p_type FROM part"


def _month(y, m, add=0):
    """ISO date of the first day of month (y, m) shifted by `add` months."""
    k = y * 12 + (m - 1) + add
    return f"{k // 12:04d}-{k % 12 + 1:02d}-01"


def _month_nl(y, m, add=0):
    k = y * 12 + (m - 1) + add
    return f"{MONTHS[k % 12]} {k // 12}"


def _quarter_from(p):
    """Three-month window starting at (year, moy): SQL bounds and NL names."""
    y, m = p["year"], p["moy"]
    return dict(start=_month(y, m), end=_month(y, m, 3), start_nl=_month_nl(y, m), last_nl=_month_nl(y, m, 2))


QUARTER = {k: (lambda p, k=k: _quarter_from(p)[k]) for k in ("start", "end", "start_nl", "last_nl")}
NEXT_YEAR = {"next_year": lambda p: str(p["year"] + 1)}

_ALL = [
    # ------------------------------------------------------------------ simple
    dict(id="h01", qnum=1, bench="tpch", complexity="simple",
         sql="""SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price,
       sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
       sum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge, avg(l_quantity) AS avg_qty,
       avg(l_extendedprice) AS avg_price, avg(l_discount) AS avg_disc, count(*) AS count_order
FROM lineitem
WHERE l_shipdate <= CAST('{cutoff}' AS date)
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus;""",
         slots=dict(delta=("int", 60, 120)),
         derive=dict(cutoff=lambda p: _T._plus_days("1998-12-01", -p["delta"]),
                     cutoff_nl=lambda p: _pretty_date(_T._plus_days("1998-12-01", -p["delta"]))),
         phrasings=[
             "Give me a pricing summary of every line item shipped on or before {cutoff_nl}, grouped by return flag and line status: total quantity, total base price, total discounted price, total charge including tax, average quantity, average price, average discount and the number of line items. Sort by return flag, then line status.",
             "From lineitem where l_shipdate <= '{cutoff}', group by l_returnflag, l_linestatus and return sum(l_quantity), sum(l_extendedprice), sum(l_extendedprice*(1-l_discount)), sum(l_extendedprice*(1-l_discount)*(1+l_tax)), avg(l_quantity), avg(l_extendedprice), avg(l_discount) and count(*), ordered by l_returnflag, l_linestatus.",
             "Lineitem summary through {cutoff} ({delta} days before 1998-12-01): per returnflag/linestatus, sums of qty, base price, disc price, charge; avg qty, price, discount; row count.",
             "I'm trying to see how much we had billed and shipped as of {cutoff_nl}, which is {delta} days before December 1, 1998. Could you split all lines shipped up to then by return flag and status, and for each combination tell me the total quantity, the total extended price, that total after discount, the total after discount plus tax, the average quantity, average extended price and average discount, and how many lines there were? Order it by return flag and then status.",
         ]),
    dict(id="h03", qnum=3, bench="tpch", complexity="simple",
         sql="""SELECT l_orderkey, sum(l_extendedprice * (1 - l_discount)) AS revenue, o_orderdate, o_shippriority
FROM customer, orders, lineitem
WHERE c_mktsegment = '{segment}' AND c_custkey = o_custkey AND l_orderkey = o_orderkey
  AND o_orderdate < CAST('{date}' AS date) AND l_shipdate > CAST('{date}' AS date)
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate
LIMIT 10;""",
         slots=dict(segment=("db", Q_SEGMENT), date=("date", "1995-03-01", "1995-03-31")),
         derive=dict(date_nl=lambda p: _pretty_date(p["date"])),
         phrasings=[
             "Which 10 unshipped orders from {segment} customers had the highest potential revenue as of {date_nl}? Consider orders placed before that date whose line items ship after it; show order key, revenue (extended price less discount), order date and ship priority, by revenue descending then order date.",
             "Join customer, orders, lineitem with c_mktsegment = '{segment}', o_orderdate < '{date}' and l_shipdate > '{date}'. Group by l_orderkey, o_orderdate, o_shippriority; return l_orderkey, sum(l_extendedprice*(1-l_discount)) AS revenue, o_orderdate, o_shippriority; order by revenue desc, o_orderdate; limit 10.",
             "Top 10 {segment} orders by discounted revenue, ordered before {date}, lines shipped after it: orderkey, revenue, orderdate, shippriority.",
             "Suppose today were {date_nl}. For customers in the {segment} market segment, I'd like to see the orders they placed before that day that still had lines due to ship afterwards, ranked by how much discounted revenue those outstanding lines represent. Just the top ten, with the order key, the revenue, the order date and the shipping priority, earlier orders first on ties.",
         ]),
    dict(id="h06", qnum=6, bench="tpch", complexity="simple",
         sql="""SELECT sum(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= CAST('{year}-01-01' AS date) AND l_shipdate < CAST('{next_year}-01-01' AS date)
  AND l_discount BETWEEN {disc_lo} AND {disc_hi} AND l_quantity < {qty};""",
         slots=dict(year=("int", *YEARS_H), disc=("int", 2, 9), qty=("int", 24, 25)),
         derive=dict(next_year=lambda p: str(p["year"] + 1), disc_lo=lambda p: f"{(p['disc'] - 1) / 100:.2f}",
                     disc_hi=lambda p: f"{(p['disc'] + 1) / 100:.2f}", disc_pct=lambda p: str(p["disc"])),
         phrasings=[
             "How much additional revenue would we have earned in {year} without discounts between {disc_lo} and {disc_hi} on line items with quantity below {qty}? That is the sum of extended price times discount over lines shipped in {year}. One number.",
             "SELECT sum(l_extendedprice * l_discount) from lineitem where l_shipdate >= '{year}-01-01' and l_shipdate < '{next_year}-01-01', l_discount between {disc_lo} and {disc_hi}, and l_quantity < {qty}.",
             "Discount revenue for {year} shipments, discount {disc_lo}-{disc_hi} inclusive, quantity < {qty}: sum(extprice*discount).",
             "Here's a what-if: looking at everything shipped in calendar year {year}, take the small lines (fewer than {qty} units) that got a discount of about {disc_pct}%, meaning anywhere from {disc_lo} to {disc_hi}, and add up extended price multiplied by the discount. I just need that single total.",
         ]),
    dict(id="h12", qnum=12, bench="tpch", complexity="simple",
         sql="""SELECT l_shipmode,
       sum(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH' THEN 1 ELSE 0 END) AS high_line_count,
       sum(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH' THEN 1 ELSE 0 END) AS low_line_count
FROM orders, lineitem
WHERE o_orderkey = l_orderkey AND l_shipmode IN ('{m1}', '{m2}') AND l_commitdate < l_receiptdate
  AND l_shipdate < l_commitdate AND l_receiptdate >= CAST('{year}-01-01' AS date)
  AND l_receiptdate < CAST('{next_year}-01-01' AS date)
GROUP BY l_shipmode
ORDER BY l_shipmode;""",
         slots=dict(modes=("sample", SHIPMODES, 2), year=("int", *YEARS_H)),
         derive=dict(m1=lambda p: p["modes"][0], m2=lambda p: p["modes"][1], **NEXT_YEAR),
         phrasings=[
             "Does shipping by {m1} or {m2} affect whether high-priority orders arrive late? For line items received in {year} that shipped before their commit date but were received after it, count lines from urgent or high priority orders and lines from all other priorities, per ship mode, ordered by ship mode.",
             "Join orders and lineitem; filter l_shipmode IN ('{m1}', '{m2}'), l_commitdate < l_receiptdate, l_shipdate < l_commitdate, l_receiptdate in ['{year}-01-01', '{next_year}-01-01'). Group by l_shipmode returning high_line_count (o_orderpriority '1-URGENT' or '2-HIGH') and low_line_count (any other priority); order by l_shipmode.",
             "{m1} vs {m2}, received in {year}, shipped before commit but received after: high- and low-priority line counts per mode.",
             "Let's compare two shipping methods, {m1} and {m2}. Among lines received during {year} that left before the committed date yet still showed up after it, how many belonged to 1-URGENT or 2-HIGH orders and how many to every other priority? One row per ship mode, sorted by mode name.",
         ]),
    dict(id="h14", qnum=14, bench="tpch", complexity="simple",
         sql="""SELECT 100.00 * sum(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END)
       / sum(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM lineitem, part
WHERE l_partkey = p_partkey AND l_shipdate >= CAST('{start}' AS date) AND l_shipdate < CAST('{end}' AS date);""",
         slots=dict(year=("int", *YEARS_H), moy=("int", 1, 12)),
         derive=dict(start=lambda p: _month(p["year"], p["moy"]), end=lambda p: _month(p["year"], p["moy"], 1),
                     month_name=lambda p: MONTHS[p["moy"] - 1]),
         phrasings=[
             "What percentage of revenue in {month_name} {year} came from promotional parts? Use line items shipped that month, revenue = extended price x (1 - discount), promotional = part type starting with 'PROMO'. One number.",
             "Over lineitem joined to part with l_shipdate >= '{start}' and < '{end}', compute 100 * sum(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice*(1-l_discount) ELSE 0 END) / sum(l_extendedprice*(1-l_discount)) AS promo_revenue.",
             "Promo revenue % of shipments in {month_name} {year}.",
             "Can you work out how big a slice of our discounted revenue was driven by promotions, for things that shipped during {month_name} of {year}? Treat a part as promotional if its type begins with PROMO, and give me that share as a percentage.",
         ]),
    dict(id="h19", qnum=19, bench="tpch", complexity="simple",
         sql="""SELECT sum(l_extendedprice * (1 - l_discount)) AS revenue
FROM lineitem, part
WHERE (p_partkey = l_partkey AND p_brand = '{b1}' AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
       AND l_quantity >= {q1} AND l_quantity <= {q1} + 10 AND p_size BETWEEN 1 AND 5
       AND l_shipmode IN ('AIR', 'AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (p_partkey = l_partkey AND p_brand = '{b2}' AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
       AND l_quantity >= {q2} AND l_quantity <= {q2} + 10 AND p_size BETWEEN 1 AND 10
       AND l_shipmode IN ('AIR', 'AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (p_partkey = l_partkey AND p_brand = '{b3}' AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
       AND l_quantity >= {q3} AND l_quantity <= {q3} + 10 AND p_size BETWEEN 1 AND 15
       AND l_shipmode IN ('AIR', 'AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON');""",
         slots=dict(brands=("db_sample", Q_BRAND, 3), q1=("int", 1, 10), q2=("int", 10, 20), q3=("int", 20, 30)),
         derive=dict(b1=lambda p: p["brands"][0], b2=lambda p: p["brands"][1], b3=lambda p: p["brands"][2],
                     q1_hi=lambda p: str(p["q1"] + 10), q2_hi=lambda p: str(p["q2"] + 10),
                     q3_hi=lambda p: str(p["q3"] + 10)),
         phrasings=[
             "What is the discounted revenue from air shipments delivered in person for three part groups: {b1} parts in small containers (SM CASE, BOX, PACK, PKG) of size 1-5 ordered in quantities {q1} to {q1_hi}; {b2} parts in medium containers (MED BAG, BOX, PKG, PACK) of size 1-10 with quantity {q2} to {q2_hi}; and {b3} parts in large containers (LG CASE, BOX, PACK, PKG) of size 1-15 with quantity {q3} to {q3_hi}? One total.",
             "sum(l_extendedprice*(1-l_discount)) over lineitem join part where l_shipmode IN ('AIR','AIR REG') and l_shipinstruct = 'DELIVER IN PERSON' and one of: (p_brand = '{b1}', p_container IN ('SM CASE','SM BOX','SM PACK','SM PKG'), l_quantity between {q1} and {q1_hi}, p_size between 1 and 5) or (p_brand = '{b2}', p_container IN ('MED BAG','MED BOX','MED PKG','MED PACK'), l_quantity between {q2} and {q2_hi}, p_size between 1 and 10) or (p_brand = '{b3}', p_container IN ('LG CASE','LG BOX','LG PACK','LG PKG'), l_quantity between {q3} and {q3_hi}, p_size between 1 and 15).",
             "Discounted revenue, AIR/AIR REG, DELIVER IN PERSON: {b1} SM containers size 1-5 qty {q1}-{q1_hi}; {b2} MED containers size 1-10 qty {q2}-{q2_hi}; {b3} LG containers size 1-15 qty {q3}-{q3_hi}.",
             "I need a single revenue number (extended price after discount) for lines shipped by air or regular air with the instruction to deliver in person, where the line fits one of three profiles: brand {b1} in a small case, box, pack or package, size between 1 and 5, quantity {q1} through {q1_hi}; brand {b2} in a medium bag, box, package or pack, size 1 to 10, quantity {q2} through {q2_hi}; or brand {b3} in a large case, box, pack or package, size 1 to 15, quantity {q3} through {q3_hi}.",
         ]),
    # ------------------------------------------------------------------ medium
    dict(id="h02", qnum=2, bench="tpch", complexity="medium",
         sql="""SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
FROM part, supplier, partsupp, nation, region
WHERE p_partkey = ps_partkey AND s_suppkey = ps_suppkey AND p_size = {size} AND p_type LIKE '%{type3}'
  AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey AND r_name = '{region}'
  AND ps_supplycost = (SELECT min(ps_supplycost) FROM partsupp, supplier, nation, region
                       WHERE p_partkey = ps_partkey AND s_suppkey = ps_suppkey AND s_nationkey = n_nationkey
                         AND n_regionkey = r_regionkey AND r_name = '{region}')
ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
LIMIT 100;""",
         slots=dict(size=("int", 1, 50), type3=("choice", TYPE_S3), region=("db", Q_REGION)), derive={},
         phrasings=[
             "In the {region} region, which suppliers offer {type3} parts of size {size} at the lowest supply cost available in that region? For each such part list the supplier's account balance, supplier name, nation, part key, manufacturer, supplier address, phone and comment, ordered by account balance descending, then nation, supplier name and part key; top 100.",
             "For part rows with p_size = {size} and p_type LIKE '%{type3}', return s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment for suppliers in region '{region}' whose ps_supplycost equals the minimum ps_supplycost of that part among {region} suppliers. ORDER BY s_acctbal DESC, n_name, s_name, p_partkey LIMIT 100.",
             "Cheapest {region} suppliers for size-{size} parts with type ending '{type3}': acctbal, supplier, nation, partkey, mfgr, address, phone, comment. Sort acctbal desc, nation, supplier, partkey; 100 rows.",
             "We're sourcing {type3} parts in size {size} and want to know, part by part, which supplier based in {region} quotes the cheapest supply cost among all suppliers in that region. Please show the supplier's account balance and name, their nation, the part key and manufacturer, and the supplier's address, phone and comment. Wealthiest suppliers first (by account balance), then by nation, supplier name and part key, and only the first 100.",
         ]),
    dict(id="h04", qnum=4, bench="tpch", complexity="medium",
         sql="""SELECT o_orderpriority, count(*) AS order_count
FROM orders
WHERE o_orderdate >= CAST('{start}' AS date) AND o_orderdate < CAST('{end}' AS date)
  AND EXISTS (SELECT * FROM lineitem WHERE l_orderkey = o_orderkey AND l_commitdate < l_receiptdate)
GROUP BY o_orderpriority
ORDER BY o_orderpriority;""",
         slots=dict(year=("int", *YEARS_H), moy=("int", 1, 10)), derive=QUARTER,
         phrasings=[
             "For orders placed during the three months from {start_nl} through {last_nl}, how many orders in each priority class had at least one line item received later than its commit date? List the priority and the count, ordered by priority.",
             "Count orders with o_orderdate >= '{start}' and o_orderdate < '{end}' for which some lineitem row has l_commitdate < l_receiptdate; group by o_orderpriority, order by o_orderpriority.",
             "Orders dated {start} up to (not incl.) {end} with any line received after commit date: count per orderpriority, sorted by priority.",
             "I want to check how well we kept our delivery promises over a quarter. Take every order placed starting in {start_nl} and running three months (so before {end}), keep the ones where at least one item arrived after the date we committed to, and tell me how many such orders fall into each order priority, sorted by priority.",
         ]),
    dict(id="h05", qnum=5, bench="tpch", complexity="medium",
         sql="""SELECT n_name, sum(l_extendedprice * (1 - l_discount)) AS revenue
FROM customer, orders, lineitem, supplier, nation, region
WHERE c_custkey = o_custkey AND l_orderkey = o_orderkey AND l_suppkey = s_suppkey AND c_nationkey = s_nationkey
  AND s_nationkey = n_nationkey AND n_regionkey = r_regionkey AND r_name = '{region}'
  AND o_orderdate >= CAST('{year}-01-01' AS date) AND o_orderdate < CAST('{next_year}-01-01' AS date)
GROUP BY n_name
ORDER BY revenue DESC;""",
         slots=dict(region=("db", Q_REGION), year=("int", *YEARS_H)), derive=NEXT_YEAR,
         phrasings=[
             "What was local-supplier revenue by nation in the {region} region for {year}? Count only line items where the customer and the supplier are in the same nation, on orders placed in {year}; revenue is extended price times (1 - discount). Show nation name and revenue, highest first.",
             "Join customer, orders, lineitem, supplier, nation, region with c_nationkey = s_nationkey, r_name = '{region}' and o_orderdate in ['{year}-01-01', '{next_year}-01-01'); return n_name and sum(l_extendedprice * (1 - l_discount)) AS revenue grouped by n_name, ordered by revenue DESC.",
             "{region}, {year} orders: discounted revenue per nation where customer and supplier share a nation, descending.",
             "Could you tell me, for each country in {region}, how much discounted revenue came from orders placed in {year} where the buyer and the supplier of a line were based in the same country? I'd like the nation name next to the revenue figure, sorted from the biggest earner down.",
         ]),
    dict(id="h09", qnum=9, bench="tpch", complexity="medium",
         sql="""SELECT nation, o_year, sum(amount) AS sum_profit
FROM (SELECT n_name AS nation, extract(year FROM o_orderdate) AS o_year,
             l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity AS amount
      FROM part, supplier, lineitem, partsupp, orders, nation
      WHERE s_suppkey = l_suppkey AND ps_suppkey = l_suppkey AND ps_partkey = l_partkey AND p_partkey = l_partkey
        AND o_orderkey = l_orderkey AND s_nationkey = n_nationkey AND p_name LIKE '%{color}%') AS profit
GROUP BY nation, o_year
ORDER BY nation, o_year DESC;""",
         slots=dict(color=("choice", COLORS)), derive={},
         phrasings=[
             "How much profit did we make on parts with '{color}' in their name, broken down by supplier nation and order year? Profit per line is discounted extended price minus supply cost times quantity. Show nation, year and total profit, sorted by nation and then most recent year first.",
             "For parts with p_name LIKE '%{color}%', join lineitem, partsupp (on partkey and suppkey), supplier, orders and nation, and sum l_extendedprice*(1-l_discount) - ps_supplycost*l_quantity AS sum_profit grouped by n_name AS nation and extract(year FROM o_orderdate) AS o_year. ORDER BY nation, o_year DESC.",
             "Profit (disc price - supplycost*qty) on '{color}' parts by supplier nation and order year; nation asc, year desc.",
             "We want a product-line profit view for anything whose part name contains the word '{color}'. For each supplier's country and each year the order was placed, add up what we earned (extended price less discount) minus what the parts cost us from that supplier (supply cost times quantity). List country, year and profit, alphabetical by country with the newest years first.",
         ]),
    dict(id="h10", qnum=10, bench="tpch", complexity="medium",
         sql="""SELECT c_custkey, c_name, sum(l_extendedprice * (1 - l_discount)) AS revenue, c_acctbal, n_name, c_address,
       c_phone, c_comment
FROM customer, orders, lineitem, nation
WHERE c_custkey = o_custkey AND l_orderkey = o_orderkey AND o_orderdate >= CAST('{start}' AS date)
  AND o_orderdate < CAST('{end}' AS date) AND l_returnflag = 'R' AND c_nationkey = n_nationkey
GROUP BY c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
ORDER BY revenue DESC
LIMIT 20;""",
         slots=dict(year=("int", 1993, 1994), moy=("int", 1, 12)), derive=QUARTER,
         phrasings=[
             "Which 20 customers caused the most lost revenue through returned items on orders placed in the quarter starting {start_nl}? For each, show customer key, name, lost revenue (discounted extended price of returned lines), account balance, nation, address, phone and comment, largest loss first.",
             "From customer, orders, lineitem, nation where o_orderdate >= '{start}' and < '{end}' and l_returnflag = 'R': group by c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment; select c_custkey, c_name, sum(l_extendedprice*(1-l_discount)) AS revenue, c_acctbal, n_name, c_address, c_phone, c_comment; order by revenue desc; limit 20.",
             "Top 20 customers by returned-line revenue, orders {start} to {end} exclusive: custkey, name, revenue, acctbal, nation, address, phone, comment.",
             "I'm putting together a list of customers who might be unhappy. Focus on orders they placed in the three months from {start_nl} through {last_nl}, and for each customer total the discounted value of the lines they sent back (return flag R). Give me the 20 with the largest returned amount, along with their customer key, name, account balance, nation, address, phone number and comment.",
         ]),
    dict(id="h11", qnum=11, bench="tpch", complexity="medium",
         sql="""SELECT ps_partkey, sum(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey AND s_nationkey = n_nationkey AND n_name = '{nation}'
GROUP BY ps_partkey
HAVING sum(ps_supplycost * ps_availqty) > (SELECT sum(ps_supplycost * ps_availqty) * 0.0001000000
                                           FROM partsupp, supplier, nation
                                           WHERE ps_suppkey = s_suppkey AND s_nationkey = n_nationkey
                                             AND n_name = '{nation}')
ORDER BY value DESC;""",
         slots=dict(nation=("db", Q_NATION)), derive={},
         notes="FRACTION kept at the official 0.0001 (the spec scales it as 0.0001/SF; not a slot here)",
         phrasings=[
             "Which parts make up a significant share of the stock value held by suppliers in {nation}? List each part key with its total value (supply cost times available quantity across {nation} suppliers), keeping only parts whose value exceeds 0.01% of the total {nation} stock value, highest value first.",
             "Over partsupp joined to supplier and nation with n_name = '{nation}', group by ps_partkey and compute sum(ps_supplycost * ps_availqty) AS value, keeping groups HAVING value > 0.0001 * the same sum over all {nation} partsupp rows. ORDER BY value DESC.",
             "{nation} suppliers: partkey and stock value (supplycost*availqty) for parts above 0.0001 of the national total, value desc.",
             "Looking only at suppliers based in {nation}, I'd like to find the important parts in their inventory: for each part, multiply supply cost by available quantity and sum over those suppliers, then keep only the parts worth more than one ten-thousandth of everything {nation}'s suppliers hold. Show part key and value, biggest first.",
         ]),
    dict(id="h13", qnum=13, bench="tpch", complexity="medium",
         sql="""SELECT c_count, count(*) AS custdist
FROM (SELECT c_custkey, count(o_orderkey)
      FROM customer LEFT OUTER JOIN orders ON c_custkey = o_custkey AND o_comment NOT LIKE '%{w1}%{w2}%'
      GROUP BY c_custkey) AS c_orders (c_custkey, c_count)
GROUP BY c_count
ORDER BY custdist DESC, c_count DESC;""",
         slots=dict(w1=("choice", WORD1), w2=("choice", WORD2)), derive={},
         phrasings=[
             "How are customers distributed by the number of orders they've placed, ignoring orders whose comment mentions '{w1}' followed by '{w2}'? For each order count (including zero), give how many customers have that many orders, sorted by number of customers descending, then order count descending.",
             "Left join customer to orders on c_custkey = o_custkey AND o_comment NOT LIKE '%{w1}%{w2}%'; count o_orderkey per c_custkey as c_count, then count(*) AS custdist per c_count. ORDER BY custdist DESC, c_count DESC.",
             "Orders-per-customer distribution, excluding comments matching '%{w1}%{w2}%': c_count, custdist; custdist desc, c_count desc.",
             "I'd like a histogram of how many orders each customer has, with customers who never ordered counted as zero. Leave out any order whose comment contains the word '{w1}' somewhere before '{w2}'. For each order count, tell me how many customers fall into it, most common bucket first and larger counts first when tied.",
         ]),
    dict(id="h16", qnum=16, bench="tpch", complexity="medium",
         sql="""SELECT p_brand, p_type, p_size, count(DISTINCT ps_suppkey) AS supplier_cnt
FROM partsupp, part
WHERE p_partkey = ps_partkey AND p_brand <> '{brand}' AND p_type NOT LIKE '{type2}%' AND p_size IN ({sizes_sql})
  AND ps_suppkey NOT IN (SELECT s_suppkey FROM supplier WHERE s_comment LIKE '%Customer%Complaints%')
GROUP BY p_brand, p_type, p_size
ORDER BY supplier_cnt DESC, p_brand, p_type, p_size;""",
         slots=dict(brand=("db", Q_BRAND), type2=("choice", TYPE_12), sizes=("sample", list(range(1, 51)), 8)),
         derive=dict(sizes_sql=lambda p: ", ".join(map(str, p["sizes"])), sizes_nl=lambda p: _nl_list(p["sizes"], "or")),
         phrasings=[
             "How many suppliers can supply parts of size {sizes_nl} that are not brand {brand} and whose type doesn't start with '{type2}'? Exclude suppliers with customer complaints on record (comment like '%Customer%Complaints%'). Count distinct suppliers by brand, type and size, sorted by supplier count descending, then brand, type, size.",
             "From partsupp join part: p_brand <> '{brand}', p_type NOT LIKE '{type2}%', p_size IN ({sizes_sql}), and ps_suppkey NOT IN (s_suppkey of suppliers with s_comment LIKE '%Customer%Complaints%'). Group by p_brand, p_type, p_size; select count(DISTINCT ps_suppkey) AS supplier_cnt; order by supplier_cnt DESC, p_brand, p_type, p_size.",
             "Distinct supplier count per brand/type/size, sizes {sizes_sql}, not {brand}, type not '{type2}%', no complaint suppliers; count desc, brand, type, size.",
             "A customer wants parts in one of these sizes: {sizes_nl}. They don't want anything from {brand} or any type beginning with {type2}. For every remaining brand, type and size combination, how many different suppliers could provide it, leaving out suppliers whose comment mentions Customer Complaints? Put the most widely supplied combinations first, then sort by brand, type and size.",
         ]),
    dict(id="h17", qnum=17, bench="tpch", complexity="medium",
         sql="""SELECT sum(l_extendedprice) / 7.0 AS avg_yearly
FROM lineitem, part
WHERE p_partkey = l_partkey AND p_brand = '{brand}' AND p_container = '{container}'
  AND l_quantity < (SELECT 0.2 * avg(l_quantity) FROM lineitem WHERE l_partkey = p_partkey);""",
         slots=dict(brand=("db", Q_BRAND), container=("db", Q_CONTAINER)), derive={},
         phrasings=[
             "What would be the average yearly revenue loss if we stopped filling small orders of {brand} parts packed in '{container}'? Small means a line quantity under 20% of that part's average line quantity; report the total extended price of such lines divided by 7 years.",
             "sum(l_extendedprice) / 7.0 AS avg_yearly over lineitem join part where p_brand = '{brand}', p_container = '{container}' and l_quantity < 0.2 * avg(l_quantity) of the same part (correlated on l_partkey = p_partkey).",
             "{brand}, {container}: total extended price of lines under 20% of the part's mean quantity, divided by 7.",
             "For parts of brand {brand} that ship in a {container}, I want to know how much revenue per year comes from unusually small orders, that is lines whose quantity is less than a fifth of what that part normally sells per line. Add up the extended price of those lines and divide by seven to get a yearly figure.",
         ]),
    dict(id="h18", qnum=18, bench="tpch", complexity="medium",
         sql="""SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, sum(l_quantity)
FROM customer, orders, lineitem
WHERE o_orderkey IN (SELECT l_orderkey FROM lineitem GROUP BY l_orderkey HAVING sum(l_quantity) > {qty})
  AND c_custkey = o_custkey AND o_orderkey = l_orderkey
GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
ORDER BY o_totalprice DESC, o_orderdate
LIMIT 100;""",
         slots=dict(qty=("int", 312, 315)), derive={},
         phrasings=[
             "Who are our large-volume customers? List orders whose total quantity across line items exceeds {qty}, with customer name, customer key, order key, order date, order total price and total quantity; most expensive orders first, then by order date; top 100.",
             "Select c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, sum(l_quantity) from customer, orders, lineitem where o_orderkey is in the lineitem orderkeys HAVING sum(l_quantity) > {qty}; group by the five non-aggregate columns; order by o_totalprice DESC, o_orderdate; limit 100.",
             "Orders with total line quantity > {qty}: customer name, custkey, orderkey, orderdate, totalprice, summed qty. Totalprice desc, date; 100.",
             "I'd like to find the really big orders, anything where the quantities on all the line items add up to more than {qty} units. For each one show me who ordered it (name and customer key), the order key and date, the order's total price and the summed quantity. Sort by total price from highest down, earlier dates first on ties, and stop at 100 rows.",
         ]),
    dict(id="h22", qnum=22, bench="tpch", complexity="medium",
         sql="""SELECT cntrycode, count(*) AS numcust, sum(c_acctbal) AS totacctbal
FROM (SELECT substring(c_phone FROM 1 FOR 2) AS cntrycode, c_acctbal
      FROM customer
      WHERE substring(c_phone FROM 1 FOR 2) IN ({codes_sql})
        AND c_acctbal > (SELECT avg(c_acctbal) FROM customer
                         WHERE c_acctbal > 0.00 AND substring(c_phone FROM 1 FOR 2) IN ({codes_sql}))
        AND NOT EXISTS (SELECT * FROM orders WHERE o_custkey = c_custkey)) AS custsale
GROUP BY cntrycode
ORDER BY cntrycode;""",
         slots=dict(codes=("sample", [str(i) for i in range(10, 35)], 7)),
         derive=dict(codes_sql=lambda p: _sql_list(p["codes"]), codes_nl=lambda p: _nl_list(p["codes"], "or")),
         phrasings=[
             "In the countries with phone codes {codes_nl}, how many customers have an above-average account balance but have never placed an order, and what is their total balance? Above average means more than the mean positive balance of customers with those codes. Show country code, customer count and total balance, by country code.",
             "With cntrycode = substring(c_phone, 1, 2) IN ({codes_sql}): pick customers with c_acctbal > avg(c_acctbal) over customers in those codes having c_acctbal > 0, and with no rows in orders. Group by cntrycode returning count(*) AS numcust and sum(c_acctbal) AS totacctbal; order by cntrycode.",
             "Customers with no orders and balance above the positive-balance average, phone prefixes {codes_sql}: count and balance sum per prefix.",
             "We'd like to win back dormant customers. Taking only customers whose phone number starts with {codes_nl}, find the ones who have never ordered anything yet hold more in their account than the average positive balance across those same country codes. For each two-digit country code, tell me how many there are and their combined account balance, sorted by code.",
         ]),
    # ------------------------------------------------------------------ complex
    dict(id="h07", qnum=7, bench="tpch", complexity="complex",
         sql="""SELECT supp_nation, cust_nation, l_year, sum(volume) AS revenue
FROM (SELECT n1.n_name AS supp_nation, n2.n_name AS cust_nation, extract(year FROM l_shipdate) AS l_year,
             l_extendedprice * (1 - l_discount) AS volume
      FROM supplier, lineitem, orders, customer, nation n1, nation n2
      WHERE s_suppkey = l_suppkey AND o_orderkey = l_orderkey AND c_custkey = o_custkey
        AND s_nationkey = n1.n_nationkey AND c_nationkey = n2.n_nationkey
        AND ((n1.n_name = '{n1}' AND n2.n_name = '{n2}') OR (n1.n_name = '{n2}' AND n2.n_name = '{n1}'))
        AND l_shipdate BETWEEN CAST('1995-01-01' AS date) AND CAST('1996-12-31' AS date)) AS shipping
GROUP BY supp_nation, cust_nation, l_year
ORDER BY supp_nation, cust_nation, l_year;""",
         slots=dict(nations=("db_sample", Q_NATION, 2)),
         derive=dict(n1=lambda p: p["nations"][0], n2=lambda p: p["nations"][1]),
         phrasings=[
             "What was the shipping volume between {n1} and {n2} in 1995 and 1996, in both directions? For each supplier nation, customer nation and ship year, give the discounted revenue (extended price x (1 - discount)) of line items shipped from a supplier in one country to a customer in the other, sorted by supplier nation, customer nation and year.",
             "With n1 = supplier nation and n2 = customer nation, keep (n1, n2) = ('{n1}', '{n2}') or ('{n2}', '{n1}') and l_shipdate between 1995-01-01 and 1996-12-31; group by supp_nation, cust_nation, extract(year FROM l_shipdate) AS l_year and sum l_extendedprice*(1-l_discount) AS revenue. Order by supp_nation, cust_nation, l_year.",
             "{n1}/{n2} two-way trade, ships 1995-1996: revenue by supplier nation, customer nation, ship year.",
             "I'm curious how much business flowed between {n1} and {n2} over 1995 and 1996. Look at lines shipped in those two years where the supplier sits in one of the two countries and the customer in the other, and give me the discounted revenue broken out by supplier country, customer country and year shipped, sorted in that order.",
         ]),
    dict(id="h08", qnum=8, bench="tpch", complexity="complex",
         sql="""SELECT o_year, sum(CASE WHEN nation = '{nation}' THEN volume ELSE 0 END) / sum(volume) AS mkt_share
FROM (SELECT extract(year FROM o_orderdate) AS o_year, l_extendedprice * (1 - l_discount) AS volume, n2.n_name AS nation
      FROM part, supplier, lineitem, orders, customer, nation n1, nation n2, region
      WHERE p_partkey = l_partkey AND s_suppkey = l_suppkey AND l_orderkey = o_orderkey AND o_custkey = c_custkey
        AND c_nationkey = n1.n_nationkey AND n1.n_regionkey = r_regionkey AND r_name = '{region}'
        AND s_nationkey = n2.n_nationkey
        AND o_orderdate BETWEEN CAST('1995-01-01' AS date) AND CAST('1996-12-31' AS date)
        AND p_type = '{ptype}') AS all_nations
GROUP BY o_year
ORDER BY o_year;""",
         slots=dict(nat_reg=("db", Q_NATION_REGION), ptype=("db", Q_TYPE)),
         derive=dict(nation=lambda p: p["nat_reg"].split("|")[0], region=lambda p: p["nat_reg"].split("|")[1]),
         notes="NATION and its REGION drawn together as one 'NATION|REGION' db value (the spec ties REGION to NATION)",
         phrasings=[
             "What market share did {nation} suppliers have among {region} customers for '{ptype}' parts in 1995 and 1996? For each order year give {nation}'s share of the discounted revenue (extended price x (1 - discount)), ordered by year.",
             "For lineitems of parts with p_type = '{ptype}', orders dated 1995-01-01 to 1996-12-31, and customers whose nation is in region '{region}': per extract(year FROM o_orderdate) AS o_year compute sum(volume where the supplier's n_name = '{nation}') / sum(volume) AS mkt_share, with volume = l_extendedprice*(1-l_discount). Order by o_year.",
             "{nation} supplier share of {region} customer revenue on '{ptype}', per order year 1995-1996.",
             "Within the {region} region, I'd like to know what fraction of the money customers spent on {ptype} parts went to suppliers located in {nation}. Please do it separately for orders placed in 1995 and in 1996, counting revenue as extended price after discount, and list each year with its share in year order.",
         ]),
    dict(id="h15", qnum=15, bench="tpch", complexity="complex",
         sql="""WITH revenue AS (SELECT l_suppkey AS supplier_no, sum(l_extendedprice * (1 - l_discount)) AS total_revenue
                 FROM lineitem
                 WHERE l_shipdate >= CAST('{start}' AS date) AND l_shipdate < CAST('{end}' AS date)
                 GROUP BY supplier_no)
SELECT s_suppkey, s_name, s_address, s_phone, total_revenue
FROM supplier, revenue
WHERE s_suppkey = supplier_no AND total_revenue = (SELECT max(total_revenue) FROM revenue)
ORDER BY s_suppkey;""",
         slots=dict(year=("int", *YEARS_H), moy=("int", 1, 10)), derive=QUARTER,
         phrasings=[
             "Who was the top supplier in the quarter starting {start_nl}? Find the supplier(s) with the highest total discounted revenue from line items shipped from {start} up to {end} (exclusive) and show supplier key, name, address, phone and total revenue, ordered by supplier key.",
             "Compute revenue per l_suppkey as sum(l_extendedprice*(1-l_discount)) for l_shipdate in ['{start}', '{end}'); return s_suppkey, s_name, s_address, s_phone, total_revenue for the supplier(s) whose total_revenue equals the max over all suppliers, ordered by s_suppkey.",
             "Highest-revenue supplier for shipments {start_nl} to {last_nl}: suppkey, name, address, phone, revenue.",
             "For goods shipped over the three months from the start of {start_nl} to the end of {last_nl}, I'd like to know which supplier brought in the most money after discounts. Give me their key, name, address and phone along with the revenue figure, and if several suppliers tie for the top, list all of them by supplier key.",
         ]),
    dict(id="h20", qnum=20, bench="tpch", complexity="complex",
         sql="""SELECT s_name, s_address
FROM supplier, nation
WHERE s_suppkey IN (SELECT ps_suppkey FROM partsupp
                    WHERE ps_partkey IN (SELECT p_partkey FROM part WHERE p_name LIKE '{color}%')
                      AND ps_availqty > (SELECT 0.5 * sum(l_quantity) FROM lineitem
                                         WHERE l_partkey = ps_partkey AND l_suppkey = ps_suppkey
                                           AND l_shipdate >= CAST('{year}-01-01' AS date)
                                           AND l_shipdate < CAST('{next_year}-01-01' AS date)))
  AND s_nationkey = n_nationkey AND n_name = '{nation}'
ORDER BY s_name;""",
         slots=dict(color=("choice", COLORS), year=("int", *YEARS_H), nation=("db", Q_NATION)), derive=NEXT_YEAR,
         phrasings=[
             "Which suppliers in {nation} have excess stock of '{color}' parts? A supplier qualifies if, for some part whose name starts with '{color}', its available quantity is more than half the quantity of that part it shipped in {year}. List supplier name and address, sorted by name.",
             "Select s_name, s_address from supplier join nation (n_name = '{nation}') where s_suppkey IN (ps_suppkey from partsupp where ps_partkey is a part with p_name LIKE '{color}%' and ps_availqty > 0.5 * sum(l_quantity) of lineitems for that partkey/suppkey with l_shipdate in ['{year}-01-01', '{next_year}-01-01')). Order by s_name.",
             "{nation} suppliers whose availqty exceeds half their {year} shipped qty for some '{color}%' part: name, address, by name.",
             "We're thinking of running a promotion on parts whose names begin with '{color}' and want to find suppliers in {nation} who are overstocked on them, meaning that for at least one such part they have more available than half of what they shipped of it during {year}. Show each such supplier's name and address, alphabetically.",
         ]),
    dict(id="h21", qnum=21, bench="tpch", complexity="complex",
         sql="""SELECT s_name, count(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE s_suppkey = l1.l_suppkey AND o_orderkey = l1.l_orderkey AND o_orderstatus = 'F'
  AND l1.l_receiptdate > l1.l_commitdate
  AND EXISTS (SELECT * FROM lineitem l2 WHERE l2.l_orderkey = l1.l_orderkey AND l2.l_suppkey <> l1.l_suppkey)
  AND NOT EXISTS (SELECT * FROM lineitem l3 WHERE l3.l_orderkey = l1.l_orderkey AND l3.l_suppkey <> l1.l_suppkey
                    AND l3.l_receiptdate > l3.l_commitdate)
  AND s_nationkey = n_nationkey AND n_name = '{nation}'
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100;""",
         slots=dict(nation=("db", Q_NATION)), derive={},
         phrasings=[
             "Which {nation} suppliers kept multi-supplier orders waiting? Count, per supplier, the line items in finished ('F') orders where that supplier was the only one to deliver late (receipt after commit date) while the other suppliers on the same order delivered on time. Show supplier name and count, most waiting first, then by name; top 100.",
             "For suppliers with n_name = '{nation}': count lineitem l1 rows in orders with o_orderstatus = 'F' where l1.l_receiptdate > l1.l_commitdate, EXISTS a lineitem on the same order with a different l_suppkey, and NOT EXISTS a different-supplier lineitem on that order with l_receiptdate > l_commitdate. Group by s_name, count AS numwait; order by numwait DESC, s_name; limit 100.",
             "{nation} suppliers that were the sole late supplier on filled multi-supplier orders: s_name, numwait; numwait desc, name; 100.",
             "I want to name and shame suppliers from {nation}. Look at completed orders (status F) that involved more than one supplier, and find cases where this supplier's line was received after its commit date but every other supplier on that order was on time. For each supplier, how many such lines are there? Show the name and the count, worst offenders first, alphabetical on ties, up to 100.",
         ]),
]

TEMPLATES = sorted(_ALL, key=lambda t: t["qnum"])
BY_ID = {t["id"]: t for t in TEMPLATES}
