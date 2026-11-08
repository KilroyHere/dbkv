"""Workload W2, TPC-DS part B: templates for TPC-DS queries 51-99 that are not in templates.py.

Same template format as templates.py (id, qnum, complexity, sql, slots, derive, phrasings, notes) plus
"bench": "tpcds"; use templates.draw_params / templates.render on these dicts unchanged.

Query numbers in 51-99 already in templates.py (skipped here): 55 62 65 68 73 79 82 84 90 91 93 96 97 99.
Written here (35): 51 52 53 54 56 57 58 59 60 61 63 64 66 67 69 70 71 72 74 75 76 77 78 80 81 83 85 86 87 88 89
92 94 95 98. None of these is multi-statement in DuckDB's tpcds_queries(), so every template is phrased in full.

The SQL is the DuckDB tpcds_queries() text with the substitution literals made variable; some long queries are
compacted (t66 and t88 are generated below from their repeated blocks). Not executed by the W2 test.
"""
try:
    from .templates import (MONTHS, CATEGORIES, YEARS, MARITAL, _plus_days, _sql_list, _nl_list,  # noqa: F401
                            _pretty_date, _mseq, MONTH_NAME)
except ImportError:
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from templates import (MONTHS, CATEGORIES, YEARS, MARITAL, _plus_days, _sql_list, _nl_list,  # noqa: E402,F401
                           _pretty_date, _mseq, MONTH_NAME)

# ---------------------------------------------------------------------- slot sources (dimension tables only)
DB_STORE_GMT = ("db", "SELECT DISTINCT CAST(s_gmt_offset AS INTEGER) FROM store WHERE s_gmt_offset IS NOT NULL")
DB_CA_GMT = ("db", "SELECT DISTINCT CAST(ca_gmt_offset AS INTEGER) FROM customer_address WHERE ca_gmt_offset IS NOT NULL")
DB_CA_STATE = "SELECT DISTINCT ca_state FROM customer_address WHERE ca_state IS NOT NULL"
DB_COLOR = "SELECT DISTINCT i_color FROM item WHERE i_color IS NOT NULL"
DB_CATCLASS = ("db", "SELECT DISTINCT i_category || '|' || i_class FROM item "
                     "WHERE i_category IS NOT NULL AND i_class IS NOT NULL")
DB_CARRIER = "SELECT DISTINCT sm_carrier FROM ship_mode WHERE sm_carrier IS NOT NULL"
DB_STORE_NAME = ("db", "SELECT DISTINCT s_store_name FROM store WHERE s_store_name IS NOT NULL")
DB_WEB_COMPANY = ("db", "SELECT DISTINCT web_company_name FROM web_site WHERE web_company_name IS NOT NULL")
DB_BUY_POT = ("db", "SELECT DISTINCT hd_buy_potential FROM household_demographics WHERE hd_buy_potential IS NOT NULL")

NEXT_YEAR = {"next_year": lambda p: str(p["year"] + 1)}
PREV_YEAR = {"prev_year": lambda p: str(p["year"] - 1)}


def _window(days, key="start"):
    return dict(end=lambda p: _plus_days(p[key], days), start_nl=lambda p: _pretty_date(p[key]),
                end_nl=lambda p: _pretty_date(_plus_days(p[key], days)))


# fixed item groups of q53 / q63 / q89 (kept as in the official text)
_Q53_ITEMS = """((i_category IN ('Books', 'Children', 'Electronics') AND i_class IN ('personal', 'portable', 'reference', 'self-help')
        AND i_brand IN ('scholaramalgamalg #14', 'scholaramalgamalg #7', 'exportiunivamalg #9', 'scholaramalgamalg #9'))
       OR (i_category IN ('Women', 'Music', 'Men') AND i_class IN ('accessories', 'classical', 'fragrances', 'pants')
        AND i_brand IN ('amalgimporto #1', 'edu packscholar #1', 'exportiimporto #1', 'importoamalg #1')))"""

# ---------------------------------------------------------------------- generated SQL for q66 and q88
_MON3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_WH_COLS = "w_warehouse_name, w_warehouse_sq_ft, w_city, w_county, w_state, w_country"


def _q66_branch(fact, pfx, sales_expr, net_expr):
    sales = ",\n  ".join(f"sum(CASE WHEN d_moy = {i + 1} THEN {sales_expr} ELSE 0 END) AS {m}_sales"
                         for i, m in enumerate(_MON3))
    nets = ",\n  ".join(f"sum(CASE WHEN d_moy = {i + 1} THEN {net_expr} ELSE 0 END) AS {m}_net"
                        for i, m in enumerate(_MON3))
    return (f"SELECT {_WH_COLS}, '{{carriers_label}}' AS ship_carriers, d_year AS year_,\n  {sales},\n  {nets}\n"
            f"FROM {fact}, warehouse, date_dim, time_dim, ship_mode\n"
            f"WHERE {pfx}_warehouse_sk = w_warehouse_sk AND {pfx}_sold_date_sk = d_date_sk AND {pfx}_sold_time_sk = t_time_sk\n"
            f"  AND {pfx}_ship_mode_sk = sm_ship_mode_sk AND d_year = {{year}} AND t_time BETWEEN {{t_lo}} AND {{t_hi}}\n"
            f"  AND sm_carrier IN ({{carriers_sql}})\n"
            f"GROUP BY {_WH_COLS}, d_year")


_Q66_SQL = (
    f"SELECT {_WH_COLS}, ship_carriers, year_,\n  "
    + ",\n  ".join(f"sum({m}_sales) AS {m}_sales" for m in _MON3) + ",\n  "
    + ",\n  ".join(f"sum({m}_sales/w_warehouse_sq_ft) AS {m}_sales_per_sq_foot" for m in _MON3) + ",\n  "
    + ",\n  ".join(f"sum({m}_net) AS {m}_net" for m in _MON3)
    + "\nFROM (\n"
    + _q66_branch("web_sales", "ws", "ws_ext_sales_price * ws_quantity", "ws_net_paid * ws_quantity")
    + "\nUNION ALL\n"
    + _q66_branch("catalog_sales", "cs", "cs_sales_price * cs_quantity", "cs_net_paid_inc_tax * cs_quantity")
    + f"\n) x\nGROUP BY {_WH_COLS}, ship_carriers, year_\nORDER BY w_warehouse_name NULLS FIRST\nLIMIT 100;"
)

_Q88_SLOTS = [("h8_30_to_9", 8, ">= 30"), ("h9_to_9_30", 9, "< 30"), ("h9_30_to_10", 9, ">= 30"),
              ("h10_to_10_30", 10, "< 30"), ("h10_30_to_11", 10, ">= 30"), ("h11_to_11_30", 11, "< 30"),
              ("h11_30_to_12", 11, ">= 30"), ("h12_to_12_30", 12, "< 30")]
_Q88_SQL = "SELECT *\nFROM " + ",\n  ".join(
    f"""(SELECT count(*) {alias} FROM store_sales, household_demographics, time_dim, store
   WHERE ss_sold_time_sk = time_dim.t_time_sk AND ss_hdemo_sk = household_demographics.hd_demo_sk AND ss_store_sk = s_store_sk
     AND time_dim.t_hour = {hour} AND time_dim.t_minute {cond} AND {{hd_cond}} AND store.s_store_name = '{{store_name}}') s{i + 1}"""
    for i, (alias, hour, cond) in enumerate(_Q88_SLOTS)) + ";"


def _q88_cond(p):
    return "(" + " OR ".join(f"(household_demographics.hd_dep_count = {d} AND household_demographics.hd_vehicle_count <= {d}+2)"
                             for d in p["deps"]) + ")"


# q76: the "missing value" column per channel
_SS_NULL = {"ss_store_sk": "store", "ss_customer_sk": "customer", "ss_promo_sk": "promotion",
            "ss_hdemo_sk": "household demographics record", "ss_addr_sk": "customer address"}
_WS_NULL = {"ws_ship_customer_sk": "ship-to customer", "ws_bill_customer_sk": "bill-to customer",
            "ws_promo_sk": "promotion", "ws_web_page_sk": "web page", "ws_ship_addr_sk": "ship-to address"}
_CS_NULL = {"cs_ship_addr_sk": "ship-to address", "cs_bill_customer_sk": "bill-to customer",
            "cs_promo_sk": "promotion", "cs_call_center_sk": "call center", "cs_warehouse_sk": "warehouse"}

_ALL = [
    # ------------------------------------------------------------------ simple
    dict(id="t52", qnum=52, complexity="simple",
         sql="""SELECT dt.d_year, item.i_brand_id brand_id, item.i_brand brand, sum(ss_ext_sales_price) ext_price
FROM date_dim dt, store_sales, item
WHERE dt.d_date_sk = store_sales.ss_sold_date_sk AND store_sales.ss_item_sk = item.i_item_sk
  AND item.i_manager_id = {manager_id} AND dt.d_moy = {moy} AND dt.d_year = {year}
GROUP BY dt.d_year, item.i_brand, item.i_brand_id
ORDER BY dt.d_year, ext_price DESC, brand_id
LIMIT 100;""",
         slots=dict(manager_id=("int", 1, 100), moy=("int", 1, 12), year=("int", *YEARS)), derive=MONTH_NAME,
         phrasings=[
             "What did each brand under manager {manager_id} sell in our stores in {month_name} {year}? Report year, brand id, brand and extended sales, sorted by year, then sales high to low, then brand id; top 100.",
             "store_sales joined to item and date_dim with i_manager_id = {manager_id}, d_moy = {moy}, d_year = {year}: return d_year, i_brand_id, i_brand and sum(ss_ext_sales_price) AS ext_price per brand, ordered by d_year, ext_price desc, brand_id; limit 100.",
             "Store brand revenue, {month_name} {year}, manager {manager_id}: year, brand id, brand, ext price. Highest first, 100 rows.",
             "Could you pull the brands that manager #{manager_id} looks after and tell me how much each one took in at the registers (extended sales price) during {month_name} of {year}? Include the year, brand id and brand name, rank from biggest to smallest with brand id breaking ties, and keep it to the first 100.",
         ]),
    # ------------------------------------------------------------------ medium
    dict(id="t53", qnum=53, complexity="medium",
         sql="""SELECT *
FROM (SELECT i_manufact_id, sum(ss_sales_price) sum_sales,
             avg(sum(ss_sales_price)) OVER (PARTITION BY i_manufact_id) avg_quarterly_sales
      FROM item, store_sales, date_dim, store
      WHERE ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk
        AND d_month_seq BETWEEN {mseq} AND {mseq}+11
        AND """ + _Q53_ITEMS + """
      GROUP BY i_manufact_id, d_qoy) tmp1
WHERE CASE WHEN avg_quarterly_sales > 0 THEN ABS (sum_sales - avg_quarterly_sales)/ avg_quarterly_sales ELSE NULL END > 0.1
ORDER BY avg_quarterly_sales, sum_sales, i_manufact_id
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         notes="item category/class/brand groups fixed as in the official text; only the year varies",
         phrasings=[
             "Which manufacturers had a quarter in {year} where store sales were more than 10% above or below their average quarter? Count only items in group A (categories Books, Children, Electronics; classes personal, portable, reference, self-help; brands scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9, scholaramalgamalg #9) or group B (categories Women, Music, Men; classes accessories, classical, fragrances, pants; brands amalgimporto #1, edu packscholar #1, exportiimporto #1, importoamalg #1). Show manufacturer id, quarterly sales and average quarterly sales, ordered by average, sales, manufacturer id; 100 rows.",
             "Per i_manufact_id and d_qoy over the 12 month_seqs of {year}: sum(ss_sales_price) AS sum_sales and avg of the quarterly sums over the manufacturer AS avg_quarterly_sales. Item filter: (i_category in Books/Children/Electronics, i_class in personal/portable/reference/self-help, i_brand in scholaramalgamalg #14/scholaramalgamalg #7/exportiunivamalg #9/scholaramalgamalg #9) or (i_category in Women/Music/Men, i_class in accessories/classical/fragrances/pants, i_brand in amalgimporto #1/edu packscholar #1/exportiimporto #1/importoamalg #1). Keep abs(sum_sales - avg)/avg > 0.1; output i_manufact_id, sum_sales, avg_quarterly_sales sorted by avg, sum, id; limit 100.",
             "{year} manufacturers with a quarter >10% off their quarterly mean in store sales; items: Books/Children/Electronics x personal/portable/reference/self-help x scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9, scholaramalgamalg #9, or Women/Music/Men x accessories/classical/fragrances/pants x amalgimporto #1, edu packscholar #1, exportiimporto #1, importoamalg #1. Id, quarter sales, average. 100.",
             "I want to find manufacturers whose store business was lumpy from quarter to quarter in {year}. Only two product groups matter: Books, Children or Electronics items in the personal, portable, reference or self-help classes from the brands scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9 or scholaramalgamalg #9; and Women, Music or Men items in accessories, classical, fragrances or pants from amalgimporto #1, edu packscholar #1, exportiimporto #1 or importoamalg #1. Flag any quarter whose sales-price total is more than ten percent away from that manufacturer's quarterly average, and give me the manufacturer id, the quarter total and the average, sorted by average, then total, then manufacturer, max 100 rows.",
         ]),
    dict(id="t63", qnum=63, complexity="medium",
         sql="""SELECT *
FROM (SELECT i_manager_id, sum(ss_sales_price) sum_sales,
             avg(sum(ss_sales_price)) OVER (PARTITION BY i_manager_id) avg_monthly_sales
      FROM item, store_sales, date_dim, store
      WHERE ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk
        AND d_month_seq BETWEEN {mseq} AND {mseq}+11
        AND """ + _Q53_ITEMS + """
      GROUP BY i_manager_id, d_moy) tmp1
WHERE CASE WHEN avg_monthly_sales > 0 THEN ABS (sum_sales - avg_monthly_sales) / avg_monthly_sales ELSE NULL END > 0.1
ORDER BY i_manager_id, avg_monthly_sales, sum_sales
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         notes="item groups fixed as in the official text; only the year varies",
         phrasings=[
             "For each item manager, list the months of {year} in which their store sales deviated by more than 10% from their own monthly average. Items in scope: Books, Children or Electronics in classes personal, portable, reference or self-help with brands scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9 or scholaramalgamalg #9; or Women, Music or Men in classes accessories, classical, fragrances or pants with brands amalgimporto #1, edu packscholar #1, exportiimporto #1 or importoamalg #1. Return manager id, the month's sales and the monthly average, ordered by manager, average, sales; 100 rows.",
             "Group store_sales by i_manager_id and d_moy for d_month_seq in {year}, with sum_sales = sum(ss_sales_price) and avg_monthly_sales = avg(sum_sales) over the manager; item predicate (i_category IN Books, Children, Electronics AND i_class IN personal, portable, reference, self-help AND i_brand IN scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9, scholaramalgamalg #9) OR (i_category IN Women, Music, Men AND i_class IN accessories, classical, fragrances, pants AND i_brand IN amalgimporto #1, edu packscholar #1, exportiimporto #1, importoamalg #1). Rows with relative deviation > 0.1; columns i_manager_id, sum_sales, avg_monthly_sales; order by those three; limit 100.",
             "Managers' off-trend months in {year} (store sales >10% from monthly avg), items limited to the Books/Children/Electronics personal-portable-reference-self-help scholaramalgamalg #14/#7/#9 + exportiunivamalg #9 set and the Women/Music/Men accessories-classical-fragrances-pants amalgimporto #1, edu packscholar #1, exportiimporto #1, importoamalg #1 set. 100 rows.",
             "Here's a monthly consistency check for {year}: for every product manager, total up store sales price per month and compare each month to that manager's average month, keeping only months more than ten percent off. Please restrict to two product groups — Books, Children and Electronics items in the personal, portable, reference and self-help classes from scholaramalgamalg #14, scholaramalgamalg #7, exportiunivamalg #9 and scholaramalgamalg #9, plus Women, Music and Men items in accessories, classical, fragrances and pants from amalgimporto #1, edu packscholar #1, exportiimporto #1 and importoamalg #1. Show the manager id, that month's total and the average, sorted by manager, then average, then total; first 100.",
         ]),
    dict(id="t61", qnum=61, complexity="medium",
         sql="""SELECT promotions, total, cast(promotions AS decimal(15,4))/cast(total AS decimal(15,4))*100
FROM (SELECT sum(ss_ext_sales_price) promotions
      FROM store_sales, store, promotion, date_dim, customer, customer_address, item
      WHERE ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk AND ss_promo_sk = p_promo_sk
        AND ss_customer_sk = c_customer_sk AND ca_address_sk = c_current_addr_sk AND ss_item_sk = i_item_sk
        AND ca_gmt_offset = {gmt_offset} AND i_category = '{category}'
        AND (p_channel_dmail = 'Y' OR p_channel_email = 'Y' OR p_channel_tv = 'Y')
        AND s_gmt_offset = {gmt_offset} AND d_year = {year} AND d_moy = {moy}) promotional_sales,
     (SELECT sum(ss_ext_sales_price) total
      FROM store_sales, store, date_dim, customer, customer_address, item
      WHERE ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk AND ss_customer_sk = c_customer_sk
        AND ca_address_sk = c_current_addr_sk AND ss_item_sk = i_item_sk
        AND ca_gmt_offset = {gmt_offset} AND i_category = '{category}'
        AND s_gmt_offset = {gmt_offset} AND d_year = {year} AND d_moy = {moy}) all_sales
ORDER BY promotions, total
LIMIT 100;""",
         slots=dict(category=("choice", CATEGORIES), year=("int", *YEARS), moy=("int", 1, 12), gmt_offset=DB_STORE_GMT),
         derive=MONTH_NAME,
         phrasings=[
             "What share of {category} store revenue in {month_name} {year} came from promoted sales (promotions run by direct mail, email or TV), considering only stores in GMT offset {gmt_offset} and customers whose current address is in the same offset? Return promotional sales, total sales and the promotional percentage.",
             "promotions = sum(ss_ext_sales_price) with p_channel_dmail = 'Y' or p_channel_email = 'Y' or p_channel_tv = 'Y'; total = the same sum without the promotion join; both filtered to i_category = '{category}', d_year = {year}, d_moy = {moy}, s_gmt_offset = {gmt_offset} and the customer's ca_gmt_offset = {gmt_offset}. Output promotions, total and promotions/total*100.",
             "{category}, {month_name} {year}, GMT {gmt_offset} stores and customers: promo (dmail/email/TV) store sales vs all store sales, plus percent.",
             "How dependent was our in-store {category} business on promotions in {month_name} of {year}? Treat a sale as promotional if its promotion went out via direct mail, email or television. Only look at stores sitting in the {gmt_offset} GMT offset and at shoppers whose home address is in that same offset, and give me three numbers: the promotional dollars, the total dollars, and promotional as a percent of total.",
         ]),
    dict(id="t69", qnum=69, complexity="medium",
         sql="""SELECT cd_gender, cd_marital_status, cd_education_status, count(*) cnt1, cd_purchase_estimate, count(*) cnt2,
       cd_credit_rating, count(*) cnt3
FROM customer c, customer_address ca, customer_demographics
WHERE c.c_current_addr_sk = ca.ca_address_sk AND ca_state IN ({states_sql}) AND cd_demo_sk = c.c_current_cdemo_sk
  AND EXISTS (SELECT * FROM store_sales, date_dim
              WHERE c.c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk AND d_year = {year}
                AND d_moy BETWEEN {moy} AND {moy}+2)
  AND (NOT EXISTS (SELECT * FROM web_sales, date_dim
                   WHERE c.c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk AND d_year = {year}
                     AND d_moy BETWEEN {moy} AND {moy}+2)
       AND NOT EXISTS (SELECT * FROM catalog_sales, date_dim
                       WHERE c.c_customer_sk = cs_ship_customer_sk AND cs_sold_date_sk = d_date_sk AND d_year = {year}
                         AND d_moy BETWEEN {moy} AND {moy}+2))
GROUP BY cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating
ORDER BY cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating
LIMIT 100;""",
         slots=dict(states=("db_sample", DB_CA_STATE, 3), year=("int", *YEARS), moy=("int", 1, 10)),
         derive=dict(states_sql=lambda p: _sql_list(p["states"]), states_nl=lambda p: _nl_list(p["states"], "or"),
                     month_name=lambda p: MONTHS[p["moy"] - 1], end_month_name=lambda p: MONTHS[p["moy"] + 1],
                     moy_end=lambda p: str(p["moy"] + 2)),
         phrasings=[
             "Demographic profile of store-only shoppers: customers living in {states_nl} who bought in stores between {month_name} and {end_month_name} {year} but made no web purchase (as bill-to) and no catalog purchase (as ship-to) in that window. Count them by gender, marital status, education, purchase estimate and credit rating; show each attribute with the count (repeated as cnt1, cnt2, cnt3), ordered by the five attributes; 100 rows.",
             "customer x customer_address x customer_demographics (current cdemo) with ca_state in ({states_sql}), EXISTS a store_sales row in d_year {year}, d_moy {moy}-{moy_end}, and NOT EXISTS web_sales (ws_bill_customer_sk) or catalog_sales (cs_ship_customer_sk) rows in the same months. Group by cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating and return them with count(*) as cnt1/cnt2/cnt3; sort by the group columns; limit 100.",
             "Store-only customers in {states_nl}, {month_name}-{end_month_name} {year}: counts by gender, marital, education, purchase estimate, credit rating.",
             "I'd like to understand who shops with us only in person. Take customers whose current address is in {states_nl} and who made at least one store purchase during the three months {month_name} through {end_month_name} of {year}, yet bought nothing on the web or through the catalog over those same months. Break them down by gender, marital status, education level, purchase estimate and credit rating, giving the head count for each combination (the count appears three times in the output), sorted by those attributes, at most 100 rows.",
         ]),
    dict(id="t89", qnum=89, complexity="medium",
         sql="""SELECT *
FROM (SELECT i_category, i_class, i_brand, s_store_name, s_company_name, d_moy, sum(ss_sales_price) sum_sales,
             avg(sum(ss_sales_price)) OVER (PARTITION BY i_category, i_brand, s_store_name, s_company_name) avg_monthly_sales
      FROM item, store_sales, date_dim, store
      WHERE ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk AND d_year = {year}
        AND ((i_category IN ('Books','Electronics','Sports') AND i_class IN ('computers','stereo','football'))
             OR (i_category IN ('Men','Jewelry','Women') AND i_class IN ('shirts','birdal','dresses')))
      GROUP BY i_category, i_class, i_brand, s_store_name, s_company_name, d_moy) tmp1
WHERE CASE WHEN (avg_monthly_sales <> 0) THEN (abs(sum_sales - avg_monthly_sales) / avg_monthly_sales) ELSE NULL END > 0.1
ORDER BY sum_sales - avg_monthly_sales, s_store_name, 1, 2, 3, 5, 6, 7, 8
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive={},
         notes="category/class lists fixed as in the official text ('birdal' is the official spelling)",
         phrasings=[
             "In {year}, which category/class/brand/store combinations had months where store sales were more than 10% away from their monthly average? Only items in Books, Electronics or Sports with class computers, stereo or football, or in Men, Jewelry or Women with class shirts, birdal or dresses. Show category, class, brand, store name, company name, month, monthly sales and average monthly sales; biggest shortfall versus average first, then store name and the other columns; 100 rows.",
             "For d_year = {year}, group store_sales by i_category, i_class, i_brand, s_store_name, s_company_name, d_moy with sum(ss_sales_price) AS sum_sales and avg(sum_sales) partitioned by category, brand, store name, company name AS avg_monthly_sales; items where (i_category in Books, Electronics, Sports and i_class in computers, stereo, football) or (i_category in Men, Jewelry, Women and i_class in shirts, birdal, dresses); keep |sum - avg| / avg > 0.1. Order by sum_sales - avg_monthly_sales, s_store_name, then remaining columns; limit 100.",
             "{year} store months >10% off average by category, class, brand, store, company — Books/Electronics/Sports computers/stereo/football and Men/Jewelry/Women shirts/birdal/dresses. 100 rows, most below average first.",
             "Can you find the months in {year} where a brand's sales in a particular store went noticeably off-pattern — more than ten percent above or below that brand's average month at that store? I only care about computers, stereo and football items in Books, Electronics or Sports, and shirts, birdal and dresses items in Men, Jewelry or Women. For each hit show category, class, brand, store name, company name, month number, that month's sales and the average, with the months furthest below average at the top (then store name and the rest), first 100.",
         ]),
    dict(id="t92", qnum=92, complexity="medium",
         sql="""SELECT sum(ws_ext_discount_amt) AS "Excess Discount Amount"
FROM web_sales, item, date_dim
WHERE i_manufact_id = {manufact_id} AND i_item_sk = ws_item_sk
  AND d_date BETWEEN '{start}' AND cast('{end}' AS date) AND d_date_sk = ws_sold_date_sk
  AND ws_ext_discount_amt > (SELECT 1.3 * avg(ws_ext_discount_amt) FROM web_sales, date_dim
                             WHERE ws_item_sk = i_item_sk AND d_date BETWEEN '{start}' AND cast('{end}' AS date)
                               AND d_date_sk = ws_sold_date_sk)
ORDER BY sum(ws_ext_discount_amt)
LIMIT 100;""",
         slots=dict(manufact_id=("int", 1, 1000), start=("date", "1998-01-01", "2002-09-30")),
         derive=_window(90),
         phrasings=[
             "How much excess discount did we give on web orders of manufacturer {manufact_id}'s products between {start_nl} and {end_nl}? Count only sales whose extended discount was more than 30% above that item's average web discount over the same 90 days, and return the total.",
             "sum(ws_ext_discount_amt) for web_sales of items with i_manufact_id = {manufact_id}, sold d_date {start} .. {end}, where ws_ext_discount_amt > 1.3 * avg(ws_ext_discount_amt) of the same item in that date range. One value.",
             "Manufacturer {manufact_id}, web, {start} to {end}: total discount on sales discounted above 1.3x item average.",
             "I'm looking at discounting on the website. For products made by manufacturer number {manufact_id}, sold online from {start_nl} up to and including {end_nl}, add up the extended discount amounts — but only on those sales where the discount was greater than 1.3 times what that same item was discounted on average during that window. Just the single total, please.",
         ]),
    dict(id="t94", qnum=94, complexity="medium",
         sql="""SELECT count(DISTINCT ws_order_number) AS "order count", sum(ws_ext_ship_cost) AS "total shipping cost",
       sum(ws_net_profit) AS "total net profit"
FROM web_sales ws1, date_dim, customer_address, web_site
WHERE d_date BETWEEN '{start}' AND cast('{end}' AS date) AND ws1.ws_ship_date_sk = d_date_sk
  AND ws1.ws_ship_addr_sk = ca_address_sk AND ca_state = '{state}' AND ws1.ws_web_site_sk = web_site_sk
  AND web_company_name = '{company}'
  AND EXISTS (SELECT * FROM web_sales ws2 WHERE ws1.ws_order_number = ws2.ws_order_number
                                            AND ws1.ws_warehouse_sk <> ws2.ws_warehouse_sk)
  AND NOT EXISTS (SELECT * FROM web_returns wr1 WHERE ws1.ws_order_number = wr1.wr_order_number)
ORDER BY count(DISTINCT ws_order_number)
LIMIT 100;""",
         slots=dict(start=("date", "1998-01-01", "2002-10-31"), state=("db", DB_CA_STATE), company=DB_WEB_COMPANY),
         derive=_window(60),
         phrasings=[
             "How many web orders shipped to {state} between {start_nl} and {end_nl} through web sites of company '{company}' were fulfilled from more than one warehouse and never returned? Give the order count, total shipping cost and total net profit.",
             "count(DISTINCT ws_order_number), sum(ws_ext_ship_cost), sum(ws_net_profit) for web_sales with ship date {start} .. {end}, ship address ca_state = '{state}', web_company_name = '{company}', where another line of the same order has a different ws_warehouse_sk and no web_returns row exists for the order.",
             "Unreturned multi-warehouse web orders, shipped {start} to {end} to {state}, company '{company}': order count, shipping cost, net profit.",
             "For orders placed on the '{company}' web sites and shipped to customers in {state} sometime from {start_nl} through {end_nl}, I want the split shipments — orders whose lines came out of at least two different warehouses — that nobody sent back. Tell me how many distinct orders that is, what we spent on shipping them, and the net profit they made.",
         ]),
    dict(id="t98", qnum=98, complexity="medium",
         sql="""SELECT i_item_id, i_item_desc, i_category, i_class, i_current_price, sum(ss_ext_sales_price) AS itemrevenue,
       sum(ss_ext_sales_price)*100.0000/sum(sum(ss_ext_sales_price)) OVER (PARTITION BY i_class) AS revenueratio
FROM store_sales, item, date_dim
WHERE ss_item_sk = i_item_sk AND i_category IN ({cats_sql}) AND ss_sold_date_sk = d_date_sk
  AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
GROUP BY i_item_id, i_item_desc, i_category, i_class, i_current_price
ORDER BY i_category NULLS FIRST, i_class NULLS FIRST, i_item_id NULLS FIRST, i_item_desc NULLS FIRST, revenueratio NULLS FIRST;""",
         slots=dict(cats=("sample", CATEGORIES, 3), start=("date", "1998-01-01", "2002-11-30")),
         derive=dict(cats_sql=lambda p: _sql_list(p["cats"]), cats_nl=lambda p: _nl_list(p["cats"]), **_window(30)),
         phrasings=[
             "For in-store sales of {cats_nl} items from {start_nl} to {end_nl}, show each item's id, description, category, class and current price, its revenue (extended sales price) and that revenue as a percent of its class's revenue. Sort by category, class, item id, description and percent, nulls first; all rows.",
             "store_sales x item x date_dim, i_category IN ({cats_sql}), d_date between {start} and {end}: per i_item_id, i_item_desc, i_category, i_class, i_current_price return sum(ss_ext_sales_price) AS itemrevenue and itemrevenue*100 / class total AS revenueratio. ORDER BY category, class, item id, desc, ratio, nulls first; no limit.",
             "Store item revenue and share of class, {cats_nl}, {start} through {end}.",
             "I need a store revenue breakdown for every item in the {cats_nl} categories over the month from {start_nl} to {end_nl}: list item id, description, category, class and current price, how much it brought in (sum of extended sales price), and what percentage of its class's total that represents. Order it by category, class, item id, description and that percentage (nulls first), and give me everything, no row cap.",
         ]),
    dict(id="t88", qnum=88, complexity="medium",
         sql=_Q88_SQL,
         slots=dict(store_name=DB_STORE_NAME, deps=("sample", [0, 1, 2, 3, 4], 3)),
         derive=dict(hd_cond=_q88_cond,
                     dep_a=lambda p: str(p["deps"][0]), dep_a2=lambda p: str(p["deps"][0] + 2),
                     dep_b=lambda p: str(p["deps"][1]), dep_b2=lambda p: str(p["deps"][1] + 2),
                     dep_c=lambda p: str(p["deps"][2]), dep_c2=lambda p: str(p["deps"][2] + 2)),
         notes="three dependent counts drawn from 0-4 (official: 4, 2, 0), each with vehicle count <= deps + 2",
         phrasings=[
             "At stores named '{store_name}', how many sales were made in each half hour from 8:30 to 12:30 (8:30-9:00, 9:00-9:30, 9:30-10:00, 10:00-10:30, 10:30-11:00, 11:00-11:30, 11:30-12:00, 12:00-12:30), counting only households with {dep_a} dependents and at most {dep_a2} vehicles, {dep_b} dependents and at most {dep_b2} vehicles, or {dep_c} dependents and at most {dep_c2} vehicles? Eight counts in one row.",
             "Eight count(*) columns h8_30_to_9 ... h12_to_12_30 over store_sales joined to time_dim, household_demographics and store, one per half-hour (t_hour 8 minute >= 30, hour 9 < 30, hour 9 >= 30, ..., hour 12 < 30), with s_store_name = '{store_name}' and (hd_dep_count = {dep_a} and hd_vehicle_count <= {dep_a2}) or (hd_dep_count = {dep_b} and hd_vehicle_count <= {dep_b2}) or (hd_dep_count = {dep_c} and hd_vehicle_count <= {dep_c2}).",
             "'{store_name}' stores, half-hourly sale counts 8:30-12:30; households dep {dep_a}/veh<={dep_a2}, dep {dep_b}/veh<={dep_b2}, dep {dep_c}/veh<={dep_c2}.",
             "I'm trying to see how morning foot traffic builds up at our '{store_name}' locations. Could you count store transactions in every 30-minute slot starting at 8:30 and ending at 12:30 — that's eight slots — but only for shoppers from households that have {dep_a} dependents with no more than {dep_a2} vehicles, or {dep_b} dependents with no more than {dep_b2} vehicles, or {dep_c} dependents with no more than {dep_c2} vehicles? A single row of eight numbers is perfect.",
         ]),
    # ------------------------------------------------------------------ complex
    dict(id="t51", qnum=51, complexity="complex",
         sql="""WITH web_v1 AS
  (SELECT ws_item_sk item_sk, d_date,
          sum(sum(ws_sales_price)) OVER (PARTITION BY ws_item_sk ORDER BY d_date ROWS BETWEEN unbounded preceding AND CURRENT ROW) cume_sales
   FROM web_sales, date_dim
   WHERE ws_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq}+11 AND ws_item_sk IS NOT NULL
   GROUP BY ws_item_sk, d_date),
     store_v1 AS
  (SELECT ss_item_sk item_sk, d_date,
          sum(sum(ss_sales_price)) OVER (PARTITION BY ss_item_sk ORDER BY d_date ROWS BETWEEN unbounded preceding AND CURRENT ROW) cume_sales
   FROM store_sales, date_dim
   WHERE ss_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq}+11 AND ss_item_sk IS NOT NULL
   GROUP BY ss_item_sk, d_date)
SELECT *
FROM (SELECT item_sk, d_date, web_sales, store_sales,
             max(web_sales) OVER (PARTITION BY item_sk ORDER BY d_date ROWS BETWEEN unbounded preceding AND CURRENT ROW) web_cumulative,
             max(store_sales) OVER (PARTITION BY item_sk ORDER BY d_date ROWS BETWEEN unbounded preceding AND CURRENT ROW) store_cumulative
      FROM (SELECT CASE WHEN web.item_sk IS NOT NULL THEN web.item_sk ELSE store.item_sk END item_sk,
                   CASE WHEN web.d_date IS NOT NULL THEN web.d_date ELSE store.d_date END d_date,
                   web.cume_sales web_sales, store.cume_sales store_sales
            FROM web_v1 web FULL OUTER JOIN store_v1 store ON (web.item_sk = store.item_sk AND web.d_date = store.d_date)) x) y
WHERE web_cumulative > store_cumulative
ORDER BY item_sk NULLS FIRST, d_date NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "For {year}, track each item's year-to-date sales (sales price) day by day on the web and in stores, and show the days on which the item's running web total was ahead of its running store total. Return item key, date, web and store running totals, and the running maximum of each; ordered by item then date; 100 rows.",
             "Compute per item_sk and d_date within the 12 months of {year} cumulative sum(ws_sales_price) and cumulative sum(ss_sales_price), full outer join them on item_sk and d_date, carry each forward with a running max (web_cumulative, store_cumulative), and keep rows where web_cumulative > store_cumulative. Columns item_sk, d_date, web_sales, store_sales, web_cumulative, store_cumulative; order by item_sk, d_date nulls first; limit 100.",
             "{year}: item/day pairs where cumulative web sales beat cumulative store sales. First 100 by item, date.",
             "I'm curious which products were selling better online than in our shops as {year} went on. Treat it as a running total from the start of the year: for each item and each day where the year-to-date web figure is above the year-to-date store figure, list the item key, the date, both running totals and their carried-forward highs. Sort by item, then date, and stop at 100 rows.",
         ]),
    dict(id="t54", qnum=54, complexity="complex",
         sql="""WITH my_customers AS
  (SELECT DISTINCT c_customer_sk, c_current_addr_sk
   FROM (SELECT cs_sold_date_sk sold_date_sk, cs_bill_customer_sk customer_sk, cs_item_sk item_sk FROM catalog_sales
         UNION ALL SELECT ws_sold_date_sk sold_date_sk, ws_bill_customer_sk customer_sk, ws_item_sk item_sk FROM web_sales) cs_or_ws_sales,
        item, date_dim, customer
   WHERE sold_date_sk = d_date_sk AND item_sk = i_item_sk AND i_category = '{category}' AND i_class = '{class_}'
     AND c_customer_sk = cs_or_ws_sales.customer_sk AND d_moy = {moy} AND d_year = {year}),
     my_revenue AS
  (SELECT c_customer_sk, sum(ss_ext_sales_price) AS revenue
   FROM my_customers, store_sales, customer_address, store, date_dim
   WHERE c_current_addr_sk = ca_address_sk AND ca_county = s_county AND ca_state = s_state AND ss_sold_date_sk = d_date_sk
     AND c_customer_sk = ss_customer_sk
     AND d_month_seq BETWEEN (SELECT DISTINCT d_month_seq+1 FROM date_dim WHERE d_year = {year} AND d_moy = {moy})
                         AND (SELECT DISTINCT d_month_seq+3 FROM date_dim WHERE d_year = {year} AND d_moy = {moy})
   GROUP BY c_customer_sk),
     segments AS (SELECT cast(round(revenue/50) AS int) AS SEGMENT FROM my_revenue)
SELECT SEGMENT, count(*) AS num_customers, SEGMENT*50 AS segment_base
FROM segments
GROUP BY SEGMENT
ORDER BY SEGMENT NULLS FIRST, num_customers NULLS FIRST, segment_base
LIMIT 100;""",
         slots=dict(catclass=DB_CATCLASS, year=("int", 1998, 2002), moy=("int", 1, 12)),
         derive=dict(category=lambda p: p["catclass"].split("|")[0], class_=lambda p: p["catclass"].split("|")[1],
                     month_name=lambda p: MONTHS[p["moy"] - 1]),
         notes="category and class drawn together as one existing (category, class) pair",
         phrasings=[
             "Take the customers who bought {class_} items in the {category} category through the catalog or the web in {month_name} {year}. How much did each spend in stores in their own county and state over the next three months? Group them into $50 revenue segments (revenue / 50, rounded) and show segment, number of customers and segment base (segment x 50), ordered by segment and count; 100 rows.",
             "my_customers = distinct customers with a catalog_sales (bill) or web_sales (bill) row in d_year {year}, d_moy {moy} for i_category = '{category}' and i_class = '{class_}'; revenue = their sum(ss_ext_sales_price) in month_seq +1 to +3 after that month at stores whose s_county and s_state equal the customer's current ca_county and ca_state; segment = cast(round(revenue/50) as int). Return segment, count(*) AS num_customers, segment*50 AS segment_base ordered by segment, num_customers, segment_base nulls first; limit 100.",
             "Customers buying {category}/{class_} via catalog or web in {month_name} {year}: distribution of their next-3-month local store spend in $50 segments (segment, customers, base).",
             "Here's what I'm after. Find everyone who picked up something from the {class_} class of {category} either from our catalog or on our website during {month_name} {year}. Then, for the three months right after that, total what each of those people spent at stores located in the same county and state as their current address, divide by 50 and round to get a segment number, and tell me how many customers fall in each segment together with the segment's dollar base (segment times 50). Order by segment, keep the first 100.",
         ]),
    dict(id="t56", qnum=56, complexity="complex",
         sql="""WITH ss AS
  (SELECT i_item_id, sum(ss_ext_sales_price) total_sales
   FROM store_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_color IN ({colors_sql}))
     AND ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND ss_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id),
     cs AS
  (SELECT i_item_id, sum(cs_ext_sales_price) total_sales
   FROM catalog_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_color IN ({colors_sql}))
     AND cs_item_sk = i_item_sk AND cs_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND cs_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id),
     ws AS
  (SELECT i_item_id, sum(ws_ext_sales_price) total_sales
   FROM web_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_color IN ({colors_sql}))
     AND ws_item_sk = i_item_sk AND ws_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND ws_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id)
SELECT i_item_id, sum(total_sales) total_sales
FROM (SELECT * FROM ss UNION ALL SELECT * FROM cs UNION ALL SELECT * FROM ws) tmp1
GROUP BY i_item_id
ORDER BY total_sales NULLS FIRST, i_item_id NULLS FIRST
LIMIT 100;""",
         slots=dict(colors=("db_sample", DB_COLOR, 3), year=("int", *YEARS), moy=("int", 1, 12), gmt_offset=DB_CA_GMT),
         derive=dict(colors_sql=lambda p: _sql_list(p["colors"]), colors_nl=lambda p: _nl_list(p["colors"], "or"),
                     month_name=lambda p: MONTHS[p["moy"] - 1]),
         phrasings=[
             "Combined store, catalog and web sales in {month_name} {year} for items colored {colors_nl}, counting only sales whose customer address (store sale address, or billing address for catalog and web) is in GMT offset {gmt_offset}. Show item id and the combined extended sales, smallest first then item id; 100 rows.",
             "Per i_item_id with i_color in ({colors_sql}): sum(ss_ext_sales_price) + sum(cs_ext_sales_price) + sum(ws_ext_sales_price) for d_year = {year}, d_moy = {moy}, where the address (ss_addr_sk / cs_bill_addr_sk / ws_bill_addr_sk) has ca_gmt_offset = {gmt_offset}. Output i_item_id, total_sales ordered by total_sales, i_item_id nulls first; limit 100.",
             "All-channel revenue per item id for {colors_nl} items, {month_name} {year}, buyers at GMT {gmt_offset}. Lowest totals first, 100.",
             "Can you work out how much each {colors_nl} product made in {month_name} of {year} when you add stores, the catalog and the website together? Only include purchases where the buyer's address (the sale address in stores, the billing address otherwise) lies in the {gmt_offset} GMT offset. List item ids with their combined extended sales, from the smallest total upward with item id as tie-breaker, first 100 please.",
         ]),
    dict(id="t60", qnum=60, complexity="complex",
         sql="""WITH ss AS
  (SELECT i_item_id, sum(ss_ext_sales_price) total_sales
   FROM store_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_category = '{category}')
     AND ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND ss_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id),
     cs AS
  (SELECT i_item_id, sum(cs_ext_sales_price) total_sales
   FROM catalog_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_category = '{category}')
     AND cs_item_sk = i_item_sk AND cs_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND cs_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id),
     ws AS
  (SELECT i_item_id, sum(ws_ext_sales_price) total_sales
   FROM web_sales, date_dim, customer_address, item
   WHERE i_item_id IN (SELECT i_item_id FROM item WHERE i_category = '{category}')
     AND ws_item_sk = i_item_sk AND ws_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
     AND ws_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_item_id)
SELECT i_item_id, sum(total_sales) total_sales
FROM (SELECT * FROM ss UNION ALL SELECT * FROM cs UNION ALL SELECT * FROM ws) tmp1
GROUP BY i_item_id
ORDER BY i_item_id, total_sales
LIMIT 100;""",
         slots=dict(category=("choice", CATEGORIES), year=("int", *YEARS), moy=("int", 1, 12), gmt_offset=DB_CA_GMT),
         derive=MONTH_NAME,
         phrasings=[
             "What did each {category} item sell across all three channels (store, catalog, web) in {month_name} {year}, counting only buyers whose address is in GMT offset {gmt_offset}? Show item id and total extended sales, ordered by item id; 100 rows.",
             "UNION ALL of per-i_item_id sums of ss_ext_sales_price, cs_ext_sales_price and ws_ext_sales_price for i_category = '{category}', d_year {year}, d_moy {moy}, address (ss_addr_sk, cs_bill_addr_sk, ws_bill_addr_sk) with ca_gmt_offset = {gmt_offset}; re-aggregate per item. Columns i_item_id, total_sales; order by i_item_id, total_sales; limit 100.",
             "{category} items, {month_name} {year}, GMT {gmt_offset} customers: store+catalog+web revenue by item id.",
             "For the {category} department, I'd like each item's total takings in {month_name} {year} with stores, catalog orders and web orders all rolled together — but only where the customer's address (sale address for store purchases, billing address for the other two) falls in time zone offset {gmt_offset}. Give me item id and that total, in item id order, first 100 rows.",
         ]),
    dict(id="t57", qnum=57, complexity="complex",
         sql="""WITH v1 AS
  (SELECT i_category, i_brand, cc_name, d_year, d_moy, sum(cs_sales_price) sum_sales,
          avg(sum(cs_sales_price)) OVER (PARTITION BY i_category, i_brand, cc_name, d_year) avg_monthly_sales,
          rank() OVER (PARTITION BY i_category, i_brand, cc_name ORDER BY d_year, d_moy) rn
   FROM item, catalog_sales, date_dim, call_center
   WHERE cs_item_sk = i_item_sk AND cs_sold_date_sk = d_date_sk AND cc_call_center_sk = cs_call_center_sk
     AND (d_year = {year} OR (d_year = {year}-1 AND d_moy = 12) OR (d_year = {year}+1 AND d_moy = 1))
   GROUP BY i_category, i_brand, cc_name, d_year, d_moy),
     v2 AS
  (SELECT v1.i_category, v1.i_brand, v1.cc_name, v1.d_year, v1.d_moy, v1.avg_monthly_sales, v1.sum_sales,
          v1_lag.sum_sales psum, v1_lead.sum_sales nsum
   FROM v1, v1 v1_lag, v1 v1_lead
   WHERE v1.i_category = v1_lag.i_category AND v1.i_category = v1_lead.i_category AND v1.i_brand = v1_lag.i_brand
     AND v1.i_brand = v1_lead.i_brand AND v1.cc_name = v1_lag.cc_name AND v1.cc_name = v1_lead.cc_name
     AND v1.rn = v1_lag.rn + 1 AND v1.rn = v1_lead.rn - 1)
SELECT *
FROM v2
WHERE d_year = {year} AND avg_monthly_sales > 0
  AND CASE WHEN avg_monthly_sales > 0 THEN abs(sum_sales - avg_monthly_sales) / avg_monthly_sales ELSE NULL END > 0.1
ORDER BY sum_sales - avg_monthly_sales NULLS FIRST, 1, 2, 3, 4, 5, 6, 7, 8, 9
LIMIT 100;""",
         slots=dict(year=("int", 1999, 2001)), derive={**PREV_YEAR, **NEXT_YEAR},
         phrasings=[
             "For {year}, find the category/brand/call-center combinations whose monthly catalog sales were more than 10% away from their {year} monthly average, and show each such month next to the previous and following month's sales. Columns: category, brand, call center name, year, month, average monthly sales, the month's sales, previous month's sales, next month's sales; ordered by sales minus average ascending, then by the columns in order; 100 rows.",
             "Group catalog_sales by i_category, i_brand, cc_name, d_year, d_moy for {year} (plus December {prev_year} and January {next_year} as neighbours): sum(cs_sales_price) AS sum_sales, avg of sum_sales over (category, brand, cc_name, year) AS avg_monthly_sales, and rank by year/month to self-join the prior (psum) and next (nsum) month. Keep {year} rows with avg > 0 and abs(sum - avg)/avg > 0.1; select all v2 columns ordered by sum_sales - avg_monthly_sales, then columns 1-9; limit 100.",
             "{year} catalog months more than 10% off the category/brand/call-center monthly average, with prior and next month sales. 100 rows, biggest shortfall first.",
             "I'd like to see where catalog sales through each call center swung noticeably during {year}. For each item category, brand and call center, compare every month's sales-price total with that combination's average month in {year}, and whenever it's off by more than ten percent, show me the category, brand, call center, year, month, the average, that month's total, and the totals for the month before and the month after (December {prev_year} and January {next_year} serve as the neighbours at the edges). Put the biggest shortfalls against the average at the top and limit it to 100.",
         ]),
    dict(id="t58", qnum=58, complexity="complex",
         sql="""WITH ss_items AS
  (SELECT i_item_id item_id, sum(ss_ext_sales_price) ss_item_rev
   FROM store_sales, item, date_dim
   WHERE ss_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq = (SELECT d_week_seq FROM date_dim WHERE d_date = '{date}'))
     AND ss_sold_date_sk = d_date_sk
   GROUP BY i_item_id),
     cs_items AS
  (SELECT i_item_id item_id, sum(cs_ext_sales_price) cs_item_rev
   FROM catalog_sales, item, date_dim
   WHERE cs_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq = (SELECT d_week_seq FROM date_dim WHERE d_date = '{date}'))
     AND cs_sold_date_sk = d_date_sk
   GROUP BY i_item_id),
     ws_items AS
  (SELECT i_item_id item_id, sum(ws_ext_sales_price) ws_item_rev
   FROM web_sales, item, date_dim
   WHERE ws_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq = (SELECT d_week_seq FROM date_dim WHERE d_date = '{date}'))
     AND ws_sold_date_sk = d_date_sk
   GROUP BY i_item_id)
SELECT ss_items.item_id, ss_item_rev, ss_item_rev/((ss_item_rev+cs_item_rev+ws_item_rev)/3) * 100 ss_dev,
       cs_item_rev, cs_item_rev/((ss_item_rev+cs_item_rev+ws_item_rev)/3) * 100 cs_dev,
       ws_item_rev, ws_item_rev/((ss_item_rev+cs_item_rev+ws_item_rev)/3) * 100 ws_dev,
       (ss_item_rev+cs_item_rev+ws_item_rev)/3 average
FROM ss_items, cs_items, ws_items
WHERE ss_items.item_id = cs_items.item_id AND ss_items.item_id = ws_items.item_id
  AND ss_item_rev BETWEEN 0.9 * cs_item_rev AND 1.1 * cs_item_rev AND ss_item_rev BETWEEN 0.9 * ws_item_rev AND 1.1 * ws_item_rev
  AND cs_item_rev BETWEEN 0.9 * ss_item_rev AND 1.1 * ss_item_rev AND cs_item_rev BETWEEN 0.9 * ws_item_rev AND 1.1 * ws_item_rev
  AND ws_item_rev BETWEEN 0.9 * ss_item_rev AND 1.1 * ss_item_rev AND ws_item_rev BETWEEN 0.9 * cs_item_rev AND 1.1 * cs_item_rev
ORDER BY ss_items.item_id NULLS FIRST, ss_item_rev NULLS FIRST
LIMIT 100;""",
         slots=dict(date=("date", "1998-01-08", "2002-12-20")), derive=dict(date_nl=lambda p: _pretty_date(p["date"])),
         phrasings=[
             "In the week containing {date_nl}, which items had roughly equal revenue in stores, catalog and web (each channel within 10% of each of the others)? For each, show item id, store revenue and its percentage of the three-channel average, catalog revenue and percentage, web revenue and percentage, and the average. Order by item id and store revenue; 100 rows.",
             "For the d_week_seq of d_date '{date}', compute per i_item_id ss_item_rev, cs_item_rev, ws_item_rev (sums of ext_sales_price); keep items where every channel's revenue is between 0.9x and 1.1x every other channel's; output item_id, ss_item_rev, ss_dev, cs_item_rev, cs_dev, ws_item_rev, ws_dev, average, with dev = rev / ((ss+cs+ws)/3) * 100. Order by item_id, ss_item_rev nulls first; limit 100.",
             "Items with balanced store/catalog/web revenue (all within ±10%) in the week of {date}: revenues, % of average, average. 100 rows.",
             "Take the week that {date_nl} falls in. I want the items that sold about the same amount whatever the channel — store, catalog and web extended sales each within ten percent of the other two. For those items, list the item id, each channel's revenue alongside that revenue as a percentage of the three-channel average, and the average itself. Sort by item id then store revenue, only the first 100.",
         ]),
    dict(id="t59", qnum=59, complexity="complex",
         sql="""WITH wss AS
  (SELECT d_week_seq, ss_store_sk,
          sum(CASE WHEN (d_day_name='Sunday') THEN ss_sales_price ELSE NULL END) sun_sales,
          sum(CASE WHEN (d_day_name='Monday') THEN ss_sales_price ELSE NULL END) mon_sales,
          sum(CASE WHEN (d_day_name='Tuesday') THEN ss_sales_price ELSE NULL END) tue_sales,
          sum(CASE WHEN (d_day_name='Wednesday') THEN ss_sales_price ELSE NULL END) wed_sales,
          sum(CASE WHEN (d_day_name='Thursday') THEN ss_sales_price ELSE NULL END) thu_sales,
          sum(CASE WHEN (d_day_name='Friday') THEN ss_sales_price ELSE NULL END) fri_sales,
          sum(CASE WHEN (d_day_name='Saturday') THEN ss_sales_price ELSE NULL END) sat_sales
   FROM store_sales, date_dim
   WHERE d_date_sk = ss_sold_date_sk
   GROUP BY d_week_seq, ss_store_sk)
SELECT s_store_name1, s_store_id1, d_week_seq1, sun_sales1/sun_sales2 AS sun_sales_ratio, mon_sales1/mon_sales2 AS mon_sales_ratio,
       tue_sales1/tue_sales2 AS tue_sales_ratio, wed_sales1/wed_sales2 AS wed_sales_ratio, thu_sales1/thu_sales2 AS thu_sales_ratio,
       fri_sales1/fri_sales2 AS fri_sales_ratio, sat_sales1/sat_sales2 AS sat_sales_ratio
FROM (SELECT s_store_name s_store_name1, wss.d_week_seq d_week_seq1, s_store_id s_store_id1, sun_sales sun_sales1,
             mon_sales mon_sales1, tue_sales tue_sales1, wed_sales wed_sales1, thu_sales thu_sales1, fri_sales fri_sales1,
             sat_sales sat_sales1
      FROM wss, store, date_dim d
      WHERE d.d_week_seq = wss.d_week_seq AND ss_store_sk = s_store_sk AND d_month_seq BETWEEN {mseq} AND {mseq} + 11) y,
     (SELECT s_store_name s_store_name2, wss.d_week_seq d_week_seq2, s_store_id s_store_id2, sun_sales sun_sales2,
             mon_sales mon_sales2, tue_sales tue_sales2, wed_sales wed_sales2, thu_sales thu_sales2, fri_sales fri_sales2,
             sat_sales sat_sales2
      FROM wss, store, date_dim d
      WHERE d.d_week_seq = wss.d_week_seq AND ss_store_sk = s_store_sk AND d_month_seq BETWEEN {mseq} + 12 AND {mseq} + 23) x
WHERE s_store_id1 = s_store_id2 AND d_week_seq1 = d_week_seq2-52
ORDER BY s_store_name1 NULLS FIRST, s_store_id1 NULLS FIRST, d_week_seq1 NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2001)), derive=dict(mseq=_mseq, **NEXT_YEAR),
         phrasings=[
             "For each store and each week of {year}, compare sales by day of week with the same week a year later ({next_year}): show store name, store id, week sequence and seven ratios (Sunday through Saturday) of the {year} day's sales to the {next_year} day's sales. Order by store name, store id, week; 100 rows.",
             "wss = per d_week_seq and ss_store_sk, sum(ss_sales_price) for each d_day_name. Join weeks falling in {year} with week_seq + 52 (in {next_year}) for the same s_store_id and return s_store_name1, s_store_id1, d_week_seq1 and sun_sales_ratio ... sat_sales_ratio (first year / second year). ORDER BY name, id, week seq nulls first; limit 100.",
             "Store weekday sales ratios, {year} week vs same week {next_year}, per store name/id/week. 100 rows.",
             "How well did each store's weekday pattern hold up from {year} into {next_year}? For every week in {year}, divide that store's Sunday sales by its Sunday sales in the matching week 52 weeks later, and do the same for Monday through Saturday. I'd like the store name, store id, the week number (week sequence) and those seven ratios, sorted by store name, id and week, first 100 rows.",
         ]),
    dict(id="t64", qnum=64, complexity="complex",
         sql="""WITH cs_ui AS
  (SELECT cs_item_sk, sum(cs_ext_list_price) AS sale, sum(cr_refunded_cash+cr_reversed_charge+cr_store_credit) AS refund
   FROM catalog_sales, catalog_returns
   WHERE cs_item_sk = cr_item_sk AND cs_order_number = cr_order_number
   GROUP BY cs_item_sk
   HAVING sum(cs_ext_list_price) > 2*sum(cr_refunded_cash+cr_reversed_charge+cr_store_credit)),
     cross_sales AS
  (SELECT i_product_name product_name, i_item_sk item_sk, s_store_name store_name, s_zip store_zip,
          ad1.ca_street_number b_street_number, ad1.ca_street_name b_street_name, ad1.ca_city b_city, ad1.ca_zip b_zip,
          ad2.ca_street_number c_street_number, ad2.ca_street_name c_street_name, ad2.ca_city c_city, ad2.ca_zip c_zip,
          d1.d_year AS syear, d2.d_year AS fsyear, d3.d_year s2year, count(*) cnt,
          sum(ss_wholesale_cost) s1, sum(ss_list_price) s2, sum(ss_coupon_amt) s3
   FROM store_sales, store_returns, cs_ui, date_dim d1, date_dim d2, date_dim d3, store, customer,
        customer_demographics cd1, customer_demographics cd2, promotion, household_demographics hd1,
        household_demographics hd2, customer_address ad1, customer_address ad2, income_band ib1, income_band ib2, item
   WHERE ss_store_sk = s_store_sk AND ss_sold_date_sk = d1.d_date_sk AND ss_customer_sk = c_customer_sk
     AND ss_cdemo_sk = cd1.cd_demo_sk AND ss_hdemo_sk = hd1.hd_demo_sk AND ss_addr_sk = ad1.ca_address_sk
     AND ss_item_sk = i_item_sk AND ss_item_sk = sr_item_sk AND ss_ticket_number = sr_ticket_number
     AND ss_item_sk = cs_ui.cs_item_sk AND c_current_cdemo_sk = cd2.cd_demo_sk AND c_current_hdemo_sk = hd2.hd_demo_sk
     AND c_current_addr_sk = ad2.ca_address_sk AND c_first_sales_date_sk = d2.d_date_sk
     AND c_first_shipto_date_sk = d3.d_date_sk AND ss_promo_sk = p_promo_sk
     AND hd1.hd_income_band_sk = ib1.ib_income_band_sk AND hd2.hd_income_band_sk = ib2.ib_income_band_sk
     AND cd1.cd_marital_status <> cd2.cd_marital_status
     AND i_color IN ({colors_sql})
     AND i_current_price BETWEEN {price} AND {price} + 10 AND i_current_price BETWEEN {price} + 1 AND {price} + 15
   GROUP BY i_product_name, i_item_sk, s_store_name, s_zip, ad1.ca_street_number, ad1.ca_street_name, ad1.ca_city,
            ad1.ca_zip, ad2.ca_street_number, ad2.ca_street_name, ad2.ca_city, ad2.ca_zip, d1.d_year, d2.d_year, d3.d_year)
SELECT cs1.product_name, cs1.store_name, cs1.store_zip, cs1.b_street_number, cs1.b_street_name, cs1.b_city, cs1.b_zip,
       cs1.c_street_number, cs1.c_street_name, cs1.c_city, cs1.c_zip, cs1.syear cs1syear, cs1.cnt cs1cnt,
       cs1.s1 AS s11, cs1.s2 AS s21, cs1.s3 AS s31, cs2.s1 AS s12, cs2.s2 AS s22, cs2.s3 AS s32, cs2.syear, cs2.cnt
FROM cross_sales cs1, cross_sales cs2
WHERE cs1.item_sk = cs2.item_sk AND cs1.syear = {year} AND cs2.syear = {year} + 1 AND cs2.cnt <= cs1.cnt
  AND cs1.store_name = cs2.store_name AND cs1.store_zip = cs2.store_zip
ORDER BY cs1.product_name, cs1.store_name, cs2.cnt, cs1.s1, cs2.s1;""",
         slots=dict(colors=("db_sample", DB_COLOR, 6), price=("int", 10, 80), year=("int", 1998, 2001)),
         derive=dict(colors_sql=lambda p: _sql_list(p["colors"]), colors_nl=lambda p: _nl_list(p["colors"], "or"),
                     price_lo=lambda p: str(p["price"] + 1), price_hi=lambda p: str(p["price"] + 10), **NEXT_YEAR),
         notes="price band slot keeps the official double BETWEEN (effective band price+1 .. price+10)",
         phrasings=[
             "For store purchases that were later returned, of items colored {colors_nl} with current price between ${price_lo} and ${price_hi} (and only items whose catalog sales at list price exceed twice their catalog refunds), where the shopper's marital status at purchase differs from their current one: compare {year} with {next_year} per product, store and address pair. Show product name, store name and zip, the purchase address and current address (street number, street name, city, zip), the {year} year, count and sums of wholesale cost, list price and coupon amount, and the same three sums plus year and count for {next_year}, keeping rows where the {next_year} count is not above {year}'s. Order by product name, store name, {next_year} count, and the two wholesale-cost sums.",
             "cs_ui = catalog items with sum(cs_ext_list_price) > 2 * sum(cr_refunded_cash + cr_reversed_charge + cr_store_credit); cross_sales = store_sales joined to store_returns (item, ticket), cs_ui, store, customer, sale and current cdemo/hdemo/address/income band, with cd1.cd_marital_status <> cd2.cd_marital_status, i_color in ({colors_sql}), i_current_price in [{price_lo}, {price_hi}], grouped by product name, item, store name/zip, both addresses and years, with count and sums of ss_wholesale_cost, ss_list_price, ss_coupon_amt. Self-join syear {year} to syear {next_year} on item, store name and zip with cs2.cnt <= cs1.cnt; return product_name, store_name, store_zip, b_/c_ street number, street name, city, zip, cs1syear, cs1cnt, s11, s21, s31, s12, s22, s32, syear, cnt ordered by product_name, store_name, cs2.cnt, cs1.s1, cs2.s1.",
             "Returned store sales of {colors_nl} items priced {price_lo}-{price_hi}, catalog-profitable items only, marital status changed: {year} vs {next_year} counts and wholesale/list/coupon sums per product, store, purchase and current address, where {next_year} count <= {year} count.",
             "This one's a bit involved. I'm looking at items in the colors {colors_nl} whose current price sits between {price_lo} and {price_hi} dollars, and only those items where catalog sales at list price come to more than double what we refunded on catalog returns. Among store purchases of those items that ended up being returned, made by customers whose marital status back then doesn't match their current one, I want to line up {year} against {next_year} for the same product at the same store (same name and zip): product name, store name and zip, the address used for the purchase and the customer's current address (street number, street name, city, zip each), and for each of the two years the year, number of purchases and totals of wholesale cost, list price and coupon amount. Only keep cases where {next_year} had no more purchases than {year}, and sort by product name, store name, the {next_year} count, then the wholesale totals.",
         ]),
    dict(id="t66", qnum=66, complexity="complex",
         sql=_Q66_SQL,
         slots=dict(year=("int", *YEARS), carriers=("db_sample", DB_CARRIER, 2), hour=("int", 0, 15)),
         derive=dict(carriers_sql=lambda p: _sql_list(p["carriers"]), carriers_nl=lambda p: _nl_list(p["carriers"], "or"),
                     carriers_label=lambda p: ",".join(p["carriers"]),
                     t_lo=lambda p: str(p["hour"] * 3600), t_hi=lambda p: str(p["hour"] * 3600 + 28800),
                     hour_end=lambda p: str(p["hour"] + 8)),
         notes="time window is an 8-hour window starting on the hour (official: 30838 = 08:33:58 + 28800 s)",
         phrasings=[
             "Monthly web plus catalog sales by warehouse for {year}, counting only orders shipped by {carriers_nl} and sold between {hour}:00 and {hour_end}:00. For each warehouse give name, square footage, city, county, state, country, the carrier label '{carriers_label}', the year, twelve monthly sales totals (sales price times quantity), the twelve monthly totals per square foot, and twelve monthly net paid totals (times quantity). Order by warehouse name; 100 rows.",
             "UNION ALL of web_sales (ws_ext_sales_price*ws_quantity, ws_net_paid*ws_quantity) and catalog_sales (cs_sales_price*cs_quantity, cs_net_paid_inc_tax*cs_quantity) pivoted into jan..dec columns by d_moy, for d_year {year}, t_time between {t_lo} and {t_hi} seconds, sm_carrier in ({carriers_sql}); grouped by w_warehouse_name, w_warehouse_sq_ft, w_city, w_county, w_state, w_country with ship_carriers = '{carriers_label}' and year_; output the 12 sales sums, the 12 sales/w_warehouse_sq_ft sums and the 12 net sums. Order by w_warehouse_name nulls first; limit 100.",
             "Warehouse month-by-month web+catalog sales, per-sq-ft sales and net paid, {year}, carriers {carriers_nl}, sold {hour}:00-{hour_end}:00. By warehouse name, 100.",
             "I need a warehouse scorecard for {year}. Combine web and catalog orders that were sold in the eight hours from {hour}:00 to {hour_end}:00 and shipped with {carriers_nl}, and for every warehouse show its name, size in square feet, city, county, state and country, a label reading '{carriers_label}', the year, then January through December sales (price times quantity), those same monthly sales divided by the warehouse's square footage, and January through December net paid (times quantity). Sort alphabetically by warehouse name and give me up to 100 rows.",
         ]),
    dict(id="t67", qnum=67, complexity="complex",
         sql="""SELECT *
FROM (SELECT i_category, i_class, i_brand, i_product_name, d_year, d_qoy, d_moy, s_store_id, sumsales,
             rank() OVER (PARTITION BY i_category ORDER BY sumsales DESC) rk
      FROM (SELECT i_category, i_class, i_brand, i_product_name, d_year, d_qoy, d_moy, s_store_id,
                   sum(coalesce(ss_sales_price*ss_quantity,0)) sumsales
            FROM store_sales, date_dim, store, item
            WHERE ss_sold_date_sk = d_date_sk AND ss_item_sk = i_item_sk AND ss_store_sk = s_store_sk
              AND d_month_seq BETWEEN {mseq} AND {mseq}+11
            GROUP BY rollup(i_category, i_class, i_brand, i_product_name, d_year, d_qoy, d_moy, s_store_id)) dw1) dw2
WHERE rk <= 100
ORDER BY i_category NULLS FIRST, i_class NULLS FIRST, i_brand NULLS FIRST, i_product_name NULLS FIRST, d_year NULLS FIRST,
         d_qoy NULLS FIRST, d_moy NULLS FIRST, s_store_id NULLS FIRST, sumsales NULLS FIRST, rk NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "For {year}, compute store sales (sales price times quantity) at every rollup level of category > class > brand > product name > year > quarter > month > store id, rank the rows within each category by sales (highest = 1), and keep the top 100 per category. Show the eight attributes, the sales and the rank, sorted by those columns in order with nulls first; 100 rows.",
             "GROUP BY ROLLUP(i_category, i_class, i_brand, i_product_name, d_year, d_qoy, d_moy, s_store_id) over store_sales in the 12 months of {year}, sumsales = sum(coalesce(ss_sales_price*ss_quantity, 0)); rk = rank() over (partition by i_category order by sumsales desc); keep rk <= 100. Output all columns plus sumsales, rk, ordered by every column nulls first; limit 100.",
             "{year} store sales rollup category→store id, top 100 per category by sales. First 100 rows.",
             "Could you build me a full drill-down of {year} store sales — quantity times sales price — rolling up from store id through month, quarter, year, product name, brand and class to category, including all the subtotal levels? Within each category rank the rows from highest sales downward and keep only ranks 1 to 100. Return category, class, brand, product name, year, quarter, month, store id, sales and rank, sorted on those columns in that order (nulls first), and just the first 100 lines.",
         ]),
    dict(id="t70", qnum=70, complexity="complex",
         sql="""SELECT sum(ss_net_profit) AS total_sum, s_state, s_county, grouping(s_state)+grouping(s_county) AS lochierarchy,
       rank() OVER (PARTITION BY grouping(s_state)+grouping(s_county), CASE WHEN grouping(s_county) = 0 THEN s_state END
                    ORDER BY sum(ss_net_profit) DESC) AS rank_within_parent
FROM store_sales, date_dim d1, store
WHERE d1.d_month_seq BETWEEN {mseq} AND {mseq}+11 AND d1.d_date_sk = ss_sold_date_sk AND s_store_sk = ss_store_sk
  AND s_state IN (SELECT s_state
                  FROM (SELECT s_state AS s_state, rank() OVER (PARTITION BY s_state ORDER BY sum(ss_net_profit) DESC) AS ranking
                        FROM store_sales, store, date_dim
                        WHERE d_month_seq BETWEEN {mseq} AND {mseq}+11 AND d_date_sk = ss_sold_date_sk AND s_store_sk = ss_store_sk
                        GROUP BY s_state) tmp1
                  WHERE ranking <= 5)
GROUP BY rollup(s_state, s_county)
ORDER BY lochierarchy DESC, CASE WHEN grouping(s_state)+grouping(s_county) = 0 THEN s_state END, rank_within_parent
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "Store net profit for {year} by state and county, with state subtotals and a grand total, restricted to the top 5 states by profit. Show total profit, state, county, hierarchy level (0 = county, 1 = state, 2 = total) and rank within parent (most profitable = 1). Order by level descending, then state for county rows, then rank; 100 rows.",
             "sum(ss_net_profit) grouped by ROLLUP(s_state, s_county) for d_month_seq within {year}, with lochierarchy = grouping(s_state)+grouping(s_county) and rank_within_parent = rank by profit desc partitioned by lochierarchy and (for county rows) s_state; s_state limited to states ranking <= 5 by sum(ss_net_profit) in the same period. Output total_sum, s_state, s_county, lochierarchy, rank_within_parent; order by lochierarchy desc, state, rank; limit 100.",
             "{year} store profit rollup state/county for the top-5 states, ranked within parent. 100 rows.",
             "I want to see where our store profit came from in {year}, geographically. Start with the five states that made the most net profit, then show the profit for each county in them, each state's subtotal and the overall total. Tag each row with its level (county 0, state 1, grand total 2) and its rank among siblings by profit, best first. Show the grand total first, then the states, then counties grouped by state, ordered by rank — 100 rows at most.",
         ]),
    dict(id="t71", qnum=71, complexity="complex",
         sql="""SELECT i_brand_id brand_id, i_brand brand, t_hour, t_minute, sum(ext_price) ext_price
FROM item,
  (SELECT ws_ext_sales_price AS ext_price, ws_sold_date_sk AS sold_date_sk, ws_item_sk AS sold_item_sk, ws_sold_time_sk AS time_sk
   FROM web_sales, date_dim WHERE d_date_sk = ws_sold_date_sk AND d_moy = {moy} AND d_year = {year}
   UNION ALL
   SELECT cs_ext_sales_price AS ext_price, cs_sold_date_sk AS sold_date_sk, cs_item_sk AS sold_item_sk, cs_sold_time_sk AS time_sk
   FROM catalog_sales, date_dim WHERE d_date_sk = cs_sold_date_sk AND d_moy = {moy} AND d_year = {year}
   UNION ALL
   SELECT ss_ext_sales_price AS ext_price, ss_sold_date_sk AS sold_date_sk, ss_item_sk AS sold_item_sk, ss_sold_time_sk AS time_sk
   FROM store_sales, date_dim WHERE d_date_sk = ss_sold_date_sk AND d_moy = {moy} AND d_year = {year}) tmp,
  time_dim
WHERE sold_item_sk = i_item_sk AND i_manager_id = {manager_id} AND time_sk = t_time_sk
  AND (t_meal_time = 'breakfast' OR t_meal_time = 'dinner')
GROUP BY i_brand, i_brand_id, t_hour, t_minute
ORDER BY ext_price DESC NULLS FIRST, i_brand_id NULLS FIRST, t_hour NULLS FIRST, t_minute NULLS FIRST;""",
         slots=dict(manager_id=("int", 1, 100), moy=("int", 1, 12), year=("int", *YEARS)), derive=MONTH_NAME,
         phrasings=[
             "Across web, catalog and store, how much did each brand managed by manager {manager_id} sell at each hour and minute of breakfast or dinner time in {month_name} {year}? Show brand id, brand, hour, minute and total extended sales price, largest first, then brand id, hour, minute; all rows.",
             "UNION ALL of ws/cs/ss ext_sales_price with sold date in d_year {year}, d_moy {moy}, joined to item (i_manager_id = {manager_id}) and time_dim with t_meal_time in ('breakfast', 'dinner'); group by i_brand, i_brand_id, t_hour, t_minute; return brand_id, brand, t_hour, t_minute, sum(ext_price) ordered by ext_price desc, brand_id, t_hour, t_minute nulls first.",
             "Manager {manager_id} brands, {month_name} {year}, all channels: ext price by hour/minute at breakfast and dinner times, top sellers first.",
             "When during the day do manager #{manager_id}'s brands sell best around mealtimes? Taking every sale in {month_name} of {year} — website, catalog and stores all together — and only the times classed as breakfast or dinner, give me each brand's id and name with the hour and minute and the total extended sales price at that time. Biggest totals at the top, then by brand id, hour and minute; no limit.",
         ]),
    dict(id="t72", qnum=72, complexity="complex",
         sql="""SELECT i_item_desc, w_warehouse_name, d1.d_week_seq,
       sum(CASE WHEN p_promo_sk IS NULL THEN 1 ELSE 0 END) no_promo,
       sum(CASE WHEN p_promo_sk IS NOT NULL THEN 1 ELSE 0 END) promo, count(*) total_cnt
FROM catalog_sales
JOIN inventory ON (cs_item_sk = inv_item_sk)
JOIN warehouse ON (w_warehouse_sk = inv_warehouse_sk)
JOIN item ON (i_item_sk = cs_item_sk)
JOIN customer_demographics ON (cs_bill_cdemo_sk = cd_demo_sk)
JOIN household_demographics ON (cs_bill_hdemo_sk = hd_demo_sk)
JOIN date_dim d1 ON (cs_sold_date_sk = d1.d_date_sk)
JOIN date_dim d2 ON (inv_date_sk = d2.d_date_sk)
JOIN date_dim d3 ON (cs_ship_date_sk = d3.d_date_sk)
LEFT OUTER JOIN promotion ON (cs_promo_sk = p_promo_sk)
LEFT OUTER JOIN catalog_returns ON (cr_item_sk = cs_item_sk AND cr_order_number = cs_order_number)
WHERE d1.d_week_seq = d2.d_week_seq AND inv_quantity_on_hand < cs_quantity AND d3.d_date > d1.d_date + 5
  AND hd_buy_potential = '{buy_potential}' AND d1.d_year = {year} AND cd_marital_status = '{marital}'
GROUP BY i_item_desc, w_warehouse_name, d1.d_week_seq
ORDER BY total_cnt DESC NULLS FIRST, i_item_desc NULLS FIRST, w_warehouse_name NULLS FIRST, d1.d_week_seq NULLS FIRST
LIMIT 100;""",
         slots=dict(buy_potential=DB_BUY_POT, year=("int", *YEARS), marital=("choice", ["M", "S", "D", "W"])),
         derive=dict(marital_nl=lambda p: MARITAL[p["marital"]]),
         phrasings=[
             "For {year} catalog orders billed to {marital_nl} customers in households with buy potential '{buy_potential}', where a warehouse's inventory that week was below the ordered quantity and the order shipped more than 5 days after it was placed, count orders with and without a promotion per item description, warehouse and week. Show item description, warehouse name, week sequence, no-promo count, promo count and total; highest total first, then description, warehouse, week; 100 rows.",
             "catalog_sales joined to inventory (same item, inv week_seq = sold week_seq, inv_quantity_on_hand < cs_quantity), warehouse, item, bill cdemo (cd_marital_status = '{marital}'), bill hdemo (hd_buy_potential = '{buy_potential}'), sold date d_year = {year}, ship date > sold date + 5, left join promotion and catalog_returns. Group by i_item_desc, w_warehouse_name, d1.d_week_seq; return no_promo, promo, total_cnt counts; order by total_cnt desc, desc, warehouse, week; limit 100.",
             "{year} late-shipped, under-stocked catalog orders, {marital_nl} buyers, buy potential {buy_potential}: promo / no-promo / total counts by item, warehouse, week.",
             "I'm trying to see where stock-outs hurt catalog orders in {year}. Look at orders billed to customers who are {marital_nl} and come from households with a '{buy_potential}' buying potential, where the warehouse had fewer units on hand in the order's week than the customer ordered, and the order didn't ship until more than five days after it was placed. For each item description, warehouse and week, tell me how many such orders had no promotion, how many had one, and the total — busiest combinations first (then item, warehouse, week), top 100.",
         ]),
    dict(id="t74", qnum=74, complexity="complex",
         sql="""WITH year_total AS
  (SELECT c_customer_id customer_id, c_first_name customer_first_name, c_last_name customer_last_name, d_year AS year_,
          sum(ss_net_paid) year_total, 's' sale_type
   FROM customer, store_sales, date_dim
   WHERE c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk AND d_year IN ({year}, {year}+1)
   GROUP BY c_customer_id, c_first_name, c_last_name, d_year
   UNION ALL
   SELECT c_customer_id customer_id, c_first_name customer_first_name, c_last_name customer_last_name, d_year AS year_,
          sum(ws_net_paid) year_total, 'w' sale_type
   FROM customer, web_sales, date_dim
   WHERE c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk AND d_year IN ({year}, {year}+1)
   GROUP BY c_customer_id, c_first_name, c_last_name, d_year)
SELECT t_s_secyear.customer_id, t_s_secyear.customer_first_name, t_s_secyear.customer_last_name
FROM year_total t_s_firstyear, year_total t_s_secyear, year_total t_w_firstyear, year_total t_w_secyear
WHERE t_s_secyear.customer_id = t_s_firstyear.customer_id AND t_s_firstyear.customer_id = t_w_secyear.customer_id
  AND t_s_firstyear.customer_id = t_w_firstyear.customer_id AND t_s_firstyear.sale_type = 's' AND t_w_firstyear.sale_type = 'w'
  AND t_s_secyear.sale_type = 's' AND t_w_secyear.sale_type = 'w' AND t_s_firstyear.year_ = {year}
  AND t_s_secyear.year_ = {year}+1 AND t_w_firstyear.year_ = {year} AND t_w_secyear.year_ = {year}+1
  AND t_s_firstyear.year_total > 0 AND t_w_firstyear.year_total > 0
  AND CASE WHEN t_w_firstyear.year_total > 0 THEN t_w_secyear.year_total / t_w_firstyear.year_total ELSE NULL END
    > CASE WHEN t_s_firstyear.year_total > 0 THEN t_s_secyear.year_total / t_s_firstyear.year_total ELSE NULL END
ORDER BY 1 NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2001)), derive=NEXT_YEAR,
         phrasings=[
             "Which customers grew their web spending faster than their store spending from {year} to {next_year}? Use yearly net paid totals, require positive {year} totals in both channels, and compare the {next_year}/{year} growth ratios. Show customer id, first name and last name, ordered by customer id; 100 rows.",
             "year_total = per c_customer_id, name and d_year, sum(ss_net_paid) as 's' rows and sum(ws_net_paid) (bill customer) as 'w' rows for {year} and {next_year}. Return customer_id, customer_first_name, customer_last_name where the {year} store and web totals are > 0 and web {next_year}/{year} ratio > store {next_year}/{year} ratio; order by customer_id; limit 100.",
             "Customers whose web net-paid growth beat store growth, {year} to {next_year}: id, first, last name. 100.",
             "I want a list of shoppers who are shifting toward buying online. Specifically, people who spent something both in stores and on the web in {year}, and whose web spending (net paid) went up proportionally more than their store spending between {year} and {next_year}. Just their customer id, first name and last name, sorted by id, first 100 names.",
         ]),
    dict(id="t75", qnum=75, complexity="complex",
         sql="""WITH all_sales AS
  (SELECT d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id, SUM(sales_cnt) AS sales_cnt, SUM(sales_amt) AS sales_amt
   FROM (SELECT d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id,
                cs_quantity - COALESCE(cr_return_quantity,0) AS sales_cnt, cs_ext_sales_price - COALESCE(cr_return_amount,0.0) AS sales_amt
         FROM catalog_sales JOIN item ON i_item_sk = cs_item_sk JOIN date_dim ON d_date_sk = cs_sold_date_sk
         LEFT JOIN catalog_returns ON (cs_order_number = cr_order_number AND cs_item_sk = cr_item_sk)
         WHERE i_category = '{category}'
         UNION
         SELECT d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id,
                ss_quantity - COALESCE(sr_return_quantity,0) AS sales_cnt, ss_ext_sales_price - COALESCE(sr_return_amt,0.0) AS sales_amt
         FROM store_sales JOIN item ON i_item_sk = ss_item_sk JOIN date_dim ON d_date_sk = ss_sold_date_sk
         LEFT JOIN store_returns ON (ss_ticket_number = sr_ticket_number AND ss_item_sk = sr_item_sk)
         WHERE i_category = '{category}'
         UNION
         SELECT d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id,
                ws_quantity - COALESCE(wr_return_quantity,0) AS sales_cnt, ws_ext_sales_price - COALESCE(wr_return_amt,0.0) AS sales_amt
         FROM web_sales JOIN item ON i_item_sk = ws_item_sk JOIN date_dim ON d_date_sk = ws_sold_date_sk
         LEFT JOIN web_returns ON (ws_order_number = wr_order_number AND ws_item_sk = wr_item_sk)
         WHERE i_category = '{category}') sales_detail
   GROUP BY d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id)
SELECT prev_yr.d_year AS prev_year, curr_yr.d_year AS year_, curr_yr.i_brand_id, curr_yr.i_class_id, curr_yr.i_category_id,
       curr_yr.i_manufact_id, prev_yr.sales_cnt AS prev_yr_cnt, curr_yr.sales_cnt AS curr_yr_cnt,
       curr_yr.sales_cnt-prev_yr.sales_cnt AS sales_cnt_diff, curr_yr.sales_amt-prev_yr.sales_amt AS sales_amt_diff
FROM all_sales curr_yr, all_sales prev_yr
WHERE curr_yr.i_brand_id = prev_yr.i_brand_id AND curr_yr.i_class_id = prev_yr.i_class_id
  AND curr_yr.i_category_id = prev_yr.i_category_id AND curr_yr.i_manufact_id = prev_yr.i_manufact_id
  AND curr_yr.d_year = {year} AND prev_yr.d_year = {year}-1
  AND CAST(curr_yr.sales_cnt AS DECIMAL(17,2))/CAST(prev_yr.sales_cnt AS DECIMAL(17,2)) < 0.9
ORDER BY sales_cnt_diff, sales_amt_diff
LIMIT 100;""",
         slots=dict(category=("choice", CATEGORIES), year=("int", 1999, 2002)), derive=PREV_YEAR,
         phrasings=[
             "Which {category} product lines (brand, class, category and manufacturer ids) saw net unit sales — after returns, across store, catalog and web — fall below 90% of the prior year's level in {year}? Show previous year, year, brand id, class id, category id, manufacturer id, previous and current net units, unit change and net amount change; ordered by unit change then amount change; 100 rows.",
             "all_sales = UNION of catalog, store and web sales for i_category = '{category}' with sales_cnt = quantity - coalesce(return quantity, 0) and sales_amt = ext_sales_price - coalesce(return amount, 0), summed by d_year, i_brand_id, i_class_id, i_category_id, i_manufact_id. Self-join {year} to {prev_year} on the four ids where curr sales_cnt / prev sales_cnt < 0.9; output prev_year, year_, ids, prev_yr_cnt, curr_yr_cnt, sales_cnt_diff, sales_amt_diff ordered by sales_cnt_diff, sales_amt_diff; limit 100.",
             "{category}: brand/class/manufacturer combos whose net (post-return) all-channel units dropped >10% from {prev_year} to {year}. Counts and diffs, worst first, 100.",
             "I'm worried about shrinking lines in {category}. Combining stores, catalog and web, and netting out returns, find each brand/class/category/manufacturer combination whose units sold in {year} came in under 90 percent of what it sold in {prev_year}. For each, show both years, the four ids, last year's and this year's net units, the change in units and the change in net sales dollars. Largest declines first (by units, then dollars), up to 100 rows.",
         ]),
    dict(id="t76", qnum=76, complexity="complex",
         sql="""SELECT channel, col_name, d_year, d_qoy, i_category, COUNT(*) sales_cnt, SUM(ext_sales_price) sales_amt
FROM (SELECT 'store' AS channel, '{ss_col}' col_name, d_year, d_qoy, i_category, ss_ext_sales_price ext_sales_price
      FROM store_sales, item, date_dim
      WHERE {ss_col} IS NULL AND ss_sold_date_sk = d_date_sk AND ss_item_sk = i_item_sk
      UNION ALL
      SELECT 'web' AS channel, '{ws_col}' col_name, d_year, d_qoy, i_category, ws_ext_sales_price ext_sales_price
      FROM web_sales, item, date_dim
      WHERE {ws_col} IS NULL AND ws_sold_date_sk = d_date_sk AND ws_item_sk = i_item_sk
      UNION ALL
      SELECT 'catalog' AS channel, '{cs_col}' col_name, d_year, d_qoy, i_category, cs_ext_sales_price ext_sales_price
      FROM catalog_sales, item, date_dim
      WHERE {cs_col} IS NULL AND cs_sold_date_sk = d_date_sk AND cs_item_sk = i_item_sk) foo
GROUP BY channel, col_name, d_year, d_qoy, i_category
ORDER BY channel NULLS FIRST, col_name NULLS FIRST, d_year NULLS FIRST, d_qoy NULLS FIRST, i_category NULLS FIRST
LIMIT 100;""",
         slots=dict(ss_col=("choice", list(_SS_NULL)), ws_col=("choice", list(_WS_NULL)), cs_col=("choice", list(_CS_NULL))),
         derive=dict(ss_nl=lambda p: _SS_NULL[p["ss_col"]], ws_nl=lambda p: _WS_NULL[p["ws_col"]],
                     cs_nl=lambda p: _CS_NULL[p["cs_col"]]),
         notes="the per-channel null column is the substitution parameter (official: ss_store_sk, ws_ship_customer_sk, cs_ship_addr_sk)",
         phrasings=[
             "How many sales, and how much extended sales revenue, are missing a key reference in each channel: store sales with no {ss_nl}, web sales with no {ws_nl}, and catalog sales with no {cs_nl}? Break down by channel, the missing column's name, year, quarter and item category; show channel, column name, year, quarter, category, count and amount, ordered by those five columns; 100 rows.",
             "UNION ALL of store_sales rows with {ss_col} IS NULL (channel 'store', col_name '{ss_col}'), web_sales rows with {ws_col} IS NULL ('web', '{ws_col}') and catalog_sales rows with {cs_col} IS NULL ('catalog', '{cs_col}'), joined to item and date_dim; group by channel, col_name, d_year, d_qoy, i_category with count(*) sales_cnt and sum(ext_sales_price) sales_amt; order by the five group columns nulls first; limit 100.",
             "Sales with null {ss_col} (store), {ws_col} (web), {cs_col} (catalog): count and amount by channel, column, year, quarter, category.",
             "We have some incomplete transaction records and I'd like to size the problem. In stores, look at sales that have no {ss_nl} recorded; on the web, sales with no {ws_nl}; in the catalog, sales with no {cs_nl}. For each channel, along with the name of the column that's empty, the year, the quarter and the item category, tell me how many such sales there were and their total extended sales price. Sort by channel, column, year, quarter and category, and 100 rows is enough.",
         ]),
    dict(id="t77", qnum=77, complexity="complex",
         sql="""WITH ss AS
  (SELECT s_store_sk, sum(ss_ext_sales_price) AS sales, sum(ss_net_profit) AS profit
   FROM store_sales, date_dim, store
   WHERE ss_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND ss_store_sk = s_store_sk
   GROUP BY s_store_sk),
     sr AS
  (SELECT s_store_sk, sum(sr_return_amt) AS returns_, sum(sr_net_loss) AS profit_loss
   FROM store_returns, date_dim, store
   WHERE sr_returned_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND sr_store_sk = s_store_sk
   GROUP BY s_store_sk),
     cs AS
  (SELECT cs_call_center_sk, sum(cs_ext_sales_price) AS sales, sum(cs_net_profit) AS profit
   FROM catalog_sales, date_dim
   WHERE cs_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
   GROUP BY cs_call_center_sk),
     cr AS
  (SELECT cr_call_center_sk, sum(cr_return_amount) AS returns_, sum(cr_net_loss) AS profit_loss
   FROM catalog_returns, date_dim
   WHERE cr_returned_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
   GROUP BY cr_call_center_sk),
     ws AS
  (SELECT wp_web_page_sk, sum(ws_ext_sales_price) AS sales, sum(ws_net_profit) AS profit
   FROM web_sales, date_dim, web_page
   WHERE ws_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND ws_web_page_sk = wp_web_page_sk
   GROUP BY wp_web_page_sk),
     wr AS
  (SELECT wp_web_page_sk, sum(wr_return_amt) AS returns_, sum(wr_net_loss) AS profit_loss
   FROM web_returns, date_dim, web_page
   WHERE wr_returned_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND wr_web_page_sk = wp_web_page_sk
   GROUP BY wp_web_page_sk)
SELECT channel, id, sum(sales) AS sales, sum(returns_) AS returns_, sum(profit) AS profit
FROM (SELECT 'store channel' AS channel, ss.s_store_sk AS id, sales, coalesce(returns_, 0) AS returns_,
             (profit - coalesce(profit_loss,0)) AS profit
      FROM ss LEFT JOIN sr ON ss.s_store_sk = sr.s_store_sk
      UNION ALL
      SELECT 'catalog channel' AS channel, cs_call_center_sk AS id, sales, returns_, (profit - profit_loss) AS profit
      FROM cs, cr
      UNION ALL
      SELECT 'web channel' AS channel, ws.wp_web_page_sk AS id, sales, coalesce(returns_, 0) returns_,
             (profit - coalesce(profit_loss,0)) AS profit
      FROM ws LEFT JOIN wr ON ws.wp_web_page_sk = wr.wp_web_page_sk) x
GROUP BY ROLLUP (channel, id)
ORDER BY channel NULLS FIRST, id NULLS FIRST, returns_ DESC
LIMIT 100;""",
         slots=dict(start=("date", "1998-01-01", "2002-11-30")), derive=_window(30),
         phrasings=[
             "Sales, returns and profit net of return losses for {start_nl} through {end_nl}, by channel: per store for the store channel, per call center for the catalog channel, and per web page for the web channel, with channel subtotals and a grand total. Show channel, id, sales, returns and profit, ordered by channel, id, returns descending; 100 rows.",
             "For d_date between {start} and {end}: ss/sr aggregated by s_store_sk, cs/cr by call center sk (cross-joined, as in the original), ws/wr by wp_web_page_sk; sales = sum ext_sales_price, returns_ = sum return amount, profit = net_profit - net_loss. UNION ALL as 'store channel', 'catalog channel', 'web channel' and GROUP BY ROLLUP(channel, id) summing sales, returns_, profit. Order by channel, id nulls first, returns_ desc; limit 100.",
             "Channel P&L {start} to {end}: sales, returns, net profit by store / call center / web page with rollup totals.",
             "Could you put together a 30-day channel report for {start_nl} to {end_nl}? For stores break it out by store, for the catalog by call center, and for the web by web page; for each give me total sales, total returns, and profit after subtracting return losses. Add a subtotal for each channel and an overall total line, sort by channel and id (with the larger returns first among ties), and cap it at 100 lines.",
         ]),
    dict(id="t78", qnum=78, complexity="complex",
         sql="""WITH ws AS
  (SELECT d_year AS ws_sold_year, ws_item_sk, ws_bill_customer_sk ws_customer_sk, sum(ws_quantity) ws_qty,
          sum(ws_wholesale_cost) ws_wc, sum(ws_sales_price) ws_sp
   FROM web_sales LEFT JOIN web_returns ON wr_order_number = ws_order_number AND ws_item_sk = wr_item_sk
   JOIN date_dim ON ws_sold_date_sk = d_date_sk
   WHERE wr_order_number IS NULL
   GROUP BY d_year, ws_item_sk, ws_bill_customer_sk),
     cs AS
  (SELECT d_year AS cs_sold_year, cs_item_sk, cs_bill_customer_sk cs_customer_sk, sum(cs_quantity) cs_qty,
          sum(cs_wholesale_cost) cs_wc, sum(cs_sales_price) cs_sp
   FROM catalog_sales LEFT JOIN catalog_returns ON cr_order_number = cs_order_number AND cs_item_sk = cr_item_sk
   JOIN date_dim ON cs_sold_date_sk = d_date_sk
   WHERE cr_order_number IS NULL
   GROUP BY d_year, cs_item_sk, cs_bill_customer_sk),
     ss AS
  (SELECT d_year AS ss_sold_year, ss_item_sk, ss_customer_sk, sum(ss_quantity) ss_qty, sum(ss_wholesale_cost) ss_wc,
          sum(ss_sales_price) ss_sp
   FROM store_sales LEFT JOIN store_returns ON sr_ticket_number = ss_ticket_number AND ss_item_sk = sr_item_sk
   JOIN date_dim ON ss_sold_date_sk = d_date_sk
   WHERE sr_ticket_number IS NULL
   GROUP BY d_year, ss_item_sk, ss_customer_sk)
SELECT ss_sold_year, ss_item_sk, ss_customer_sk, round((ss_qty*1.00)/(coalesce(ws_qty,0)+coalesce(cs_qty,0)),2) ratio,
       ss_qty store_qty, ss_wc store_wholesale_cost, ss_sp store_sales_price,
       coalesce(ws_qty,0)+coalesce(cs_qty,0) other_chan_qty, coalesce(ws_wc,0)+coalesce(cs_wc,0) other_chan_wholesale_cost,
       coalesce(ws_sp,0)+coalesce(cs_sp,0) other_chan_sales_price
FROM ss
LEFT JOIN ws ON (ws_sold_year = ss_sold_year AND ws_item_sk = ss_item_sk AND ws_customer_sk = ss_customer_sk)
LEFT JOIN cs ON (cs_sold_year = ss_sold_year AND cs_item_sk = ss_item_sk AND cs_customer_sk = ss_customer_sk)
WHERE (coalesce(ws_qty,0) > 0 OR coalesce(cs_qty, 0) > 0) AND ss_sold_year = {year}
ORDER BY ss_sold_year, ss_item_sk, ss_customer_sk, ss_qty DESC, ss_wc DESC, ss_sp DESC, other_chan_qty,
         other_chan_wholesale_cost, other_chan_sales_price, ratio
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "For {year}, compare each customer's unreturned store purchases of an item with their unreturned web and catalog purchases of the same item in the same year. For customer-item pairs that also bought through web or catalog, show year, item key, customer key, ratio of store quantity to other-channel quantity (2 decimals), store quantity, wholesale cost and sales price, and the other channels' combined quantity, wholesale cost and sales price. Order by year, item, customer, then store quantity, cost and price descending, then the other-channel figures and the ratio; 100 rows.",
             "Per (d_year, item_sk, customer_sk) sum quantity, wholesale_cost, sales_price for store_sales, web_sales (bill customer) and catalog_sales (bill customer), each excluding rows that have a matching return. Left join web and catalog onto store for ss_sold_year = {year}, keep rows with ws_qty > 0 or cs_qty > 0, and output ss_sold_year, ss_item_sk, ss_customer_sk, ratio = round(ss_qty / (ws_qty + cs_qty), 2), store_qty, store_wholesale_cost, store_sales_price, other_chan_qty, other_chan_wholesale_cost, other_chan_sales_price. Sort by year, item, customer, store qty/wc/sp desc, other-channel columns, ratio; limit 100.",
             "{year} customer-item pairs bought (not returned) in store and also via web/catalog: store vs other-channel qty, cost, price, qty ratio. 100 rows.",
             "I'd like to see customers who buy the same product through more than one channel. For {year}, considering only purchases that were never returned, take each customer and item they bought in a store and line it up against what that same customer bought of that item on the web and through the catalog that year — keep only cases with some web or catalog quantity. Show the year, item key, customer key, store quantity divided by other-channel quantity (rounded to two places), the store quantity, wholesale cost and sales price, and the combined web-plus-catalog quantity, wholesale cost and sales price. Sort by year, item, customer, then the store numbers descending, then the other-channel numbers and the ratio, 100 rows.",
         ]),
    dict(id="t80", qnum=80, complexity="complex",
         sql="""WITH ssr AS
  (SELECT s_store_id AS store_id, sum(ss_ext_sales_price) AS sales, sum(coalesce(sr_return_amt, 0)) AS returns_,
          sum(ss_net_profit - coalesce(sr_net_loss, 0)) AS profit
   FROM store_sales LEFT OUTER JOIN store_returns ON (ss_item_sk = sr_item_sk AND ss_ticket_number = sr_ticket_number),
        date_dim, store, item, promotion
   WHERE ss_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
     AND ss_store_sk = s_store_sk AND ss_item_sk = i_item_sk AND i_current_price > 50 AND ss_promo_sk = p_promo_sk
     AND p_channel_tv = 'N'
   GROUP BY s_store_id),
     csr AS
  (SELECT cp_catalog_page_id AS catalog_page_id, sum(cs_ext_sales_price) AS sales, sum(coalesce(cr_return_amount, 0)) AS returns_,
          sum(cs_net_profit - coalesce(cr_net_loss, 0)) AS profit
   FROM catalog_sales LEFT OUTER JOIN catalog_returns ON (cs_item_sk = cr_item_sk AND cs_order_number = cr_order_number),
        date_dim, catalog_page, item, promotion
   WHERE cs_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
     AND cs_catalog_page_sk = cp_catalog_page_sk AND cs_item_sk = i_item_sk AND i_current_price > 50
     AND cs_promo_sk = p_promo_sk AND p_channel_tv = 'N'
   GROUP BY cp_catalog_page_id),
     wsr AS
  (SELECT web_site_id, sum(ws_ext_sales_price) AS sales, sum(coalesce(wr_return_amt, 0)) AS returns_,
          sum(ws_net_profit - coalesce(wr_net_loss, 0)) AS profit
   FROM web_sales LEFT OUTER JOIN web_returns ON (ws_item_sk = wr_item_sk AND ws_order_number = wr_order_number),
        date_dim, web_site, item, promotion
   WHERE ws_sold_date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
     AND ws_web_site_sk = web_site_sk AND ws_item_sk = i_item_sk AND i_current_price > 50
     AND ws_promo_sk = p_promo_sk AND p_channel_tv = 'N'
   GROUP BY web_site_id)
SELECT channel, id, sum(sales) AS sales, sum(returns_) AS returns_, sum(profit) AS profit
FROM (SELECT 'store channel' AS channel, concat('store', store_id) AS id, sales, returns_, profit FROM ssr
      UNION ALL
      SELECT 'catalog channel' AS channel, concat('catalog_page', catalog_page_id) AS id, sales, returns_, profit FROM csr
      UNION ALL
      SELECT 'web channel' AS channel, concat('web_site', web_site_id) AS id, sales, returns_, profit FROM wsr) x
GROUP BY ROLLUP (channel, id)
ORDER BY channel NULLS FIRST, id NULLS FIRST
LIMIT 100;""",
         slots=dict(start=("date", "1998-01-01", "2002-11-30")), derive=_window(30),
         phrasings=[
             "For items priced over $50 sold on non-TV promotions between {start_nl} and {end_nl}, report sales, returns and profit net of return losses per store, per catalog page and per web site, with channel subtotals and a grand total. Show channel, id (prefixed 'store', 'catalog_page' or 'web_site'), sales, returns, profit; ordered by channel then id; 100 rows.",
             "ssr / csr / wsr = per s_store_id / cp_catalog_page_id / web_site_id: sum(ext_sales_price), sum(coalesce(return amount, 0)), sum(net_profit - coalesce(net_loss, 0)), sales left-joined to their returns, d_date {start} .. {end}, i_current_price > 50, promotion with p_channel_tv = 'N'. UNION ALL with channel labels and ids concat('store'|'catalog_page'|'web_site', id), GROUP BY ROLLUP(channel, id). Order by channel, id nulls first; limit 100.",
             "{start} to {end}, items > $50, non-TV promos: sales/returns/profit by store, catalog page, web site, with rollups.",
             "I'd like the channel numbers for our pricier merchandise — anything with a current price above fifty dollars — sold on promotions that weren't advertised on TV, between {start_nl} and {end_nl}. Show sales, returns and profit after return losses for each store, each catalog page and each web site (label the ids with 'store', 'catalog_page' or 'web_site' in front), plus a subtotal per channel and an overall total. Order by channel and id, up to 100 rows.",
         ]),
    dict(id="t81", qnum=81, complexity="complex",
         sql="""WITH customer_total_return AS
  (SELECT cr_returning_customer_sk AS ctr_customer_sk, ca_state AS ctr_state, sum(cr_return_amt_inc_tax) AS ctr_total_return
   FROM catalog_returns, date_dim, customer_address
   WHERE cr_returned_date_sk = d_date_sk AND d_year = {year} AND cr_returning_addr_sk = ca_address_sk
   GROUP BY cr_returning_customer_sk, ca_state)
SELECT c_customer_id, c_salutation, c_first_name, c_last_name, ca_street_number, ca_street_name, ca_street_type, ca_suite_number,
       ca_city, ca_county, ca_state, ca_zip, ca_country, ca_gmt_offset, ca_location_type, ctr_total_return
FROM customer_total_return ctr1, customer_address, customer
WHERE ctr1.ctr_total_return > (SELECT avg(ctr_total_return)*1.2 FROM customer_total_return ctr2 WHERE ctr1.ctr_state = ctr2.ctr_state)
  AND ca_address_sk = c_current_addr_sk AND ca_state = '{state}' AND ctr1.ctr_customer_sk = c_customer_sk
ORDER BY c_customer_id, c_salutation, c_first_name, c_last_name, ca_street_number, ca_street_name, ca_street_type,
         ca_suite_number, ca_city, ca_county, ca_state, ca_zip, ca_country, ca_gmt_offset, ca_location_type, ctr_total_return
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), state=("db", DB_CA_STATE)), derive={},
         phrasings=[
             "Which customers currently living in {state} returned an unusually large amount through the catalog in {year} — more than 1.2 times the average return total of customers returning from the same state? Show customer id, salutation, first and last name, full current address (street number, street name, street type, suite, city, county, state, zip, country, GMT offset, location type) and their total return amount including tax; ordered by all of those columns; 100 rows.",
             "customer_total_return = sum(cr_return_amt_inc_tax) per cr_returning_customer_sk and returning-address ca_state for d_year {year}. Return c_customer_id, c_salutation, c_first_name, c_last_name, ca_street_number, ca_street_name, ca_street_type, ca_suite_number, ca_city, ca_county, ca_state, ca_zip, ca_country, ca_gmt_offset, ca_location_type, ctr_total_return for customers whose current ca_state = '{state}' and whose total > 1.2 x the state's average total; order by all columns; limit 100.",
             "{state} customers with {year} catalog returns (incl. tax) over 1.2x their state's average: id, name, full address, return total.",
             "I'm looking for heavy catalog returners. For {year}, add up each customer's catalog return amounts including tax, by the state they returned from, and flag anyone whose total is more than 20 percent above the average for that state. Of those, show me the ones whose current address is in {state}: customer id, salutation, first and last name, every part of their current address (street number, name and type, suite, city, county, state, zip, country, GMT offset, location type) and the return total. Sort on all of those fields in that order, first 100.",
         ]),
    dict(id="t83", qnum=83, complexity="complex",
         sql="""WITH sr_items AS
  (SELECT i_item_id item_id, sum(sr_return_quantity) sr_item_qty
   FROM store_returns, item, date_dim
   WHERE sr_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq IN
                     (SELECT d_week_seq FROM date_dim WHERE d_date IN ('{d1}', '{d2}', '{d3}')))
     AND sr_returned_date_sk = d_date_sk
   GROUP BY i_item_id),
     cr_items AS
  (SELECT i_item_id item_id, sum(cr_return_quantity) cr_item_qty
   FROM catalog_returns, item, date_dim
   WHERE cr_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq IN
                     (SELECT d_week_seq FROM date_dim WHERE d_date IN ('{d1}', '{d2}', '{d3}')))
     AND cr_returned_date_sk = d_date_sk
   GROUP BY i_item_id),
     wr_items AS
  (SELECT i_item_id item_id, sum(wr_return_quantity) wr_item_qty
   FROM web_returns, item, date_dim
   WHERE wr_item_sk = i_item_sk
     AND d_date IN (SELECT d_date FROM date_dim WHERE d_week_seq IN
                     (SELECT d_week_seq FROM date_dim WHERE d_date IN ('{d1}', '{d2}', '{d3}')))
     AND wr_returned_date_sk = d_date_sk
   GROUP BY i_item_id)
SELECT sr_items.item_id, sr_item_qty, (sr_item_qty*1.0000)/(sr_item_qty+cr_item_qty+wr_item_qty)/3.0000 * 100 sr_dev,
       cr_item_qty, (cr_item_qty*1.0000)/(sr_item_qty+cr_item_qty+wr_item_qty)/3.0000 * 100 cr_dev,
       wr_item_qty, (wr_item_qty*1.0000)/(sr_item_qty+cr_item_qty+wr_item_qty)/3.0000 * 100 wr_dev,
       (sr_item_qty+cr_item_qty+wr_item_qty)/3.0 average
FROM sr_items, cr_items, wr_items
WHERE sr_items.item_id = cr_items.item_id AND sr_items.item_id = wr_items.item_id
ORDER BY sr_items.item_id NULLS FIRST, sr_item_qty NULLS FIRST
LIMIT 100;""",
         slots=dict(d1=("date", "1998-01-01", "2002-12-24"), d2=("date", "1998-01-01", "2002-12-24"),
                    d3=("date", "1998-01-01", "2002-12-24")),
         derive=dict(d1_nl=lambda p: _pretty_date(p["d1"]), d2_nl=lambda p: _pretty_date(p["d2"]),
                     d3_nl=lambda p: _pretty_date(p["d3"])),
         phrasings=[
             "For returns made during the three weeks that contain {d1_nl}, {d2_nl} and {d3_nl}, compare how many units of each item came back through stores, the catalog and the web. For items returned in all three channels, show item id, store return quantity and its deviation figure (quantity / total / 3 x 100), catalog quantity and deviation, web quantity and deviation, and the average quantity per channel; ordered by item id and store quantity; 100 rows.",
             "Weeks = d_week_seq of d_date in ('{d1}', '{d2}', '{d3}'). Per i_item_id: sr_item_qty = sum(sr_return_quantity), cr_item_qty = sum(cr_return_quantity), wr_item_qty = sum(wr_return_quantity) for returns dated in those weeks; inner-join the three; output item_id, sr_item_qty, sr_dev, cr_item_qty, cr_dev, wr_item_qty, wr_dev, average with dev = qty / (sr+cr+wr) / 3 * 100 and average = (sr+cr+wr)/3. Order by item_id, sr_item_qty nulls first; limit 100.",
             "Return quantities by item across store/catalog/web for the weeks of {d1}, {d2}, {d3}, with per-channel deviation and average. 100 rows.",
             "Here's a returns comparison I'd like. Pick out the weeks that {d1_nl}, {d2_nl} and {d3_nl} fall in, and for every item that was returned in stores, via catalog and via the web during those weeks, give me the item id, the quantity returned in each channel, a deviation number for each channel (that channel's quantity divided by the three-channel total, divided by three, times 100), and the average quantity across the three channels. Sort by item id and then the store quantity, first 100.",
         ]),
    dict(id="t85", qnum=85, complexity="complex",
         sql="""SELECT SUBSTRING(r_reason_desc,1,20), avg(ws_quantity) avg1, avg(wr_refunded_cash) avg2, avg(wr_fee)
FROM web_sales, web_returns, web_page, customer_demographics cd1, customer_demographics cd2, customer_address, date_dim, reason
WHERE ws_web_page_sk = wp_web_page_sk AND ws_item_sk = wr_item_sk AND ws_order_number = wr_order_number
  AND ws_sold_date_sk = d_date_sk AND d_year = {year} AND cd1.cd_demo_sk = wr_refunded_cdemo_sk
  AND cd2.cd_demo_sk = wr_returning_cdemo_sk AND ca_address_sk = wr_refunded_addr_sk AND r_reason_sk = wr_reason_sk
  AND ((cd1.cd_marital_status = 'M' AND cd1.cd_marital_status = cd2.cd_marital_status AND cd1.cd_education_status = 'Advanced Degree'
        AND cd1.cd_education_status = cd2.cd_education_status AND ws_sales_price BETWEEN 100.00 AND 150.00)
       OR (cd1.cd_marital_status = 'S' AND cd1.cd_marital_status = cd2.cd_marital_status AND cd1.cd_education_status = 'College'
        AND cd1.cd_education_status = cd2.cd_education_status AND ws_sales_price BETWEEN 50.00 AND 100.00)
       OR (cd1.cd_marital_status = 'W' AND cd1.cd_marital_status = cd2.cd_marital_status AND cd1.cd_education_status = '2 yr Degree'
        AND cd1.cd_education_status = cd2.cd_education_status AND ws_sales_price BETWEEN 150.00 AND 200.00))
  AND ((ca_country = 'United States' AND ca_state IN ({states1_sql}) AND ws_net_profit BETWEEN 100 AND 200)
       OR (ca_country = 'United States' AND ca_state IN ('WI', 'CT', 'KY') AND ws_net_profit BETWEEN 150 AND 300)
       OR (ca_country = 'United States' AND ca_state IN ('LA', 'IA', 'AR') AND ws_net_profit BETWEEN 50 AND 250))
GROUP BY r_reason_desc
ORDER BY SUBSTRING(r_reason_desc,1,20), avg(ws_quantity), avg(wr_refunded_cash), avg(wr_fee)
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), states1=("db_sample", DB_CA_STATE, 3)),
         derive=dict(states1_sql=lambda p: _sql_list(p["states1"]), states1_nl=lambda p: _nl_list(p["states1"], "or"),
                     states1_sl=lambda p: "/".join(p["states1"])),
         notes="year and the first state group vary (official first group: IN, OH, NJ); demographic bands and the other two state groups fixed",
         phrasings=[
             "For returned web sales from {year}, give the average quantity sold, average refunded cash and average return fee per return reason (first 20 characters of the reason), where the refunded and returning customers have the same demographics and either: married with an Advanced Degree and sales price 100-150, single College graduates with price 50-100, or widowed with a 2 yr Degree and price 150-200; and the refund address is in the United States with either state {states1_nl} and net profit 100-200, state WI, CT or KY and profit 150-300, or state LA, IA or AR and profit 50-250. Ordered by reason and the three averages; 100 rows.",
             "web_sales joined to web_returns (item, order), web_page, refunded cdemo cd1, returning cdemo cd2, refunded address, reason; d_year = {year}; cd1 and cd2 share marital and education status with (M, 'Advanced Degree', ws_sales_price 100-150) or (S, 'College', 50-100) or (W, '2 yr Degree', 150-200); ca_country = 'United States' with (ca_state in ({states1_sql}), ws_net_profit 100-200) or (WI/CT/KY, 150-300) or (LA/IA/AR, 50-250). Group by r_reason_desc; output substring(reason, 1, 20), avg(ws_quantity), avg(wr_refunded_cash), avg(wr_fee) in that order; limit 100.",
             "{year} web returns by reason: avg quantity, refunded cash, fee — matching demographics M/Advanced Degree/$100-150, S/College/$50-100, W/2 yr Degree/$150-200; US refund address in {states1_sl} (profit 100-200), WI/CT/KY (150-300) or LA/IA/AR (50-250).",
             "Could you summarize web returns by reason for sales made in {year}? I want the reason text cut to 20 characters plus the average quantity originally bought, the average cash refunded and the average return fee. Only count returns where the person refunded and the person returning have the same profile, and that profile is one of: married with an advanced degree buying at 100 to 150 dollars, single and college-educated buying at 50 to 100, or widowed with a two-year degree buying at 150 to 200. On top of that the refund address must be in the US, and either in {states1_nl} with a net profit between 100 and 200, in Wisconsin, Connecticut or Kentucky with profit 150 to 300, or in Louisiana, Iowa or Arkansas with profit 50 to 250. Sort by reason and then the averages, 100 rows max.",
         ]),
    dict(id="t86", qnum=86, complexity="complex",
         sql="""SELECT sum(ws_net_paid) AS total_sum, i_category, i_class, grouping(i_category)+grouping(i_class) AS lochierarchy,
       rank() OVER (PARTITION BY grouping(i_category)+grouping(i_class), CASE WHEN grouping(i_class) = 0 THEN i_category END
                    ORDER BY sum(ws_net_paid) DESC) AS rank_within_parent
FROM web_sales, date_dim d1, item
WHERE d1.d_month_seq BETWEEN {mseq} AND {mseq}+11 AND d1.d_date_sk = ws_sold_date_sk AND i_item_sk = ws_item_sk
GROUP BY rollup(i_category, i_class)
ORDER BY lochierarchy DESC NULLS FIRST, CASE WHEN grouping(i_category)+grouping(i_class) = 0 THEN i_category END NULLS FIRST,
         rank_within_parent NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "Web net paid revenue for {year} by item category and class, with category subtotals and a grand total, ranked within each parent level (highest = 1). Show total, category, class, hierarchy level (0 class, 1 category, 2 total) and rank; ordered by level descending, then category for class rows, then rank; 100 rows.",
             "sum(ws_net_paid) over web_sales in the 12 month_seqs of {year}, GROUP BY ROLLUP(i_category, i_class), lochierarchy = grouping(i_category)+grouping(i_class), rank_within_parent = rank() by sum desc partitioned by lochierarchy and (for leaf rows) i_category. Columns total_sum, i_category, i_class, lochierarchy, rank_within_parent; order by lochierarchy desc, category for leaf rows, rank, nulls first; limit 100.",
             "{year} web net paid by category/class rollup, ranked within parent. 100 rows.",
             "How did online revenue split across our merchandise hierarchy in {year}? Using net paid on web sales, give me the grand total, each category's total and each category-class total, with a level marker (2 for the grand total, 1 for categories, 0 for classes) and a rank showing where each sits among its siblings, biggest first. Grand total first, then categories, then classes grouped under their category in rank order — 100 lines max.",
         ]),
    dict(id="t87", qnum=87, complexity="complex",
         sql="""SELECT count(*)
FROM ((SELECT DISTINCT c_last_name, c_first_name, d_date
       FROM store_sales, date_dim, customer
       WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_customer_sk = customer.c_customer_sk
         AND d_month_seq BETWEEN {mseq} AND {mseq}+11)
      EXCEPT
      (SELECT DISTINCT c_last_name, c_first_name, d_date
       FROM catalog_sales, date_dim, customer
       WHERE catalog_sales.cs_sold_date_sk = date_dim.d_date_sk AND catalog_sales.cs_bill_customer_sk = customer.c_customer_sk
         AND d_month_seq BETWEEN {mseq} AND {mseq}+11)
      EXCEPT
      (SELECT DISTINCT c_last_name, c_first_name, d_date
       FROM web_sales, date_dim, customer
       WHERE web_sales.ws_sold_date_sk = date_dim.d_date_sk AND web_sales.ws_bill_customer_sk = customer.c_customer_sk
         AND d_month_seq BETWEEN {mseq} AND {mseq}+11)) cool_cust;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "In {year}, how many distinct (customer last name, first name, date) combinations bought in a store on a day when that same-named customer did not buy from the catalog or the web? One count.",
             "count(*) of (SELECT DISTINCT c_last_name, c_first_name, d_date from store_sales in {year}) EXCEPT the same triple from catalog_sales (bill customer) EXCEPT the same from web_sales (bill customer), all limited to the 12 month_seqs of {year}.",
             "{year}: number of distinct name+date store shopping days with no catalog or web purchase by that name on that date.",
             "I'd like a single number for {year}: take every distinct combination of a customer's last name, first name and the date they shopped in one of our stores, then throw out any combination where someone with that same name also placed a catalog order or a web order on that same date. How many combinations are left?",
         ]),
    dict(id="t95", qnum=95, complexity="complex",
         sql="""WITH ws_wh AS
  (SELECT ws1.ws_order_number, ws1.ws_warehouse_sk wh1, ws2.ws_warehouse_sk wh2
   FROM web_sales ws1, web_sales ws2
   WHERE ws1.ws_order_number = ws2.ws_order_number AND ws1.ws_warehouse_sk <> ws2.ws_warehouse_sk)
SELECT count(DISTINCT ws_order_number) AS "order count", sum(ws_ext_ship_cost) AS "total shipping cost",
       sum(ws_net_profit) AS "total net profit"
FROM web_sales ws1, date_dim, customer_address, web_site
WHERE d_date BETWEEN '{start}' AND cast('{end}' AS date) AND ws1.ws_ship_date_sk = d_date_sk
  AND ws1.ws_ship_addr_sk = ca_address_sk AND ca_state = '{state}' AND ws1.ws_web_site_sk = web_site_sk
  AND web_company_name = '{company}'
  AND ws1.ws_order_number IN (SELECT ws_order_number FROM ws_wh)
  AND ws1.ws_order_number IN (SELECT wr_order_number FROM web_returns, ws_wh WHERE wr_order_number = ws_wh.ws_order_number)
ORDER BY count(DISTINCT ws_order_number)
LIMIT 100;""",
         slots=dict(start=("date", "1998-01-01", "2002-10-31"), state=("db", DB_CA_STATE), company=DB_WEB_COMPANY),
         derive=_window(60),
         phrasings=[
             "Among web orders shipped to {state} between {start_nl} and {end_nl} through '{company}' web sites, how many were split across more than one warehouse and later had a return? Give the number of distinct orders, total shipping cost and total net profit.",
             "ws_wh = order numbers whose web_sales lines use at least two different ws_warehouse_sk. Return count(DISTINCT ws_order_number), sum(ws_ext_ship_cost), sum(ws_net_profit) over web_sales with ship date {start} .. {end}, ship-to ca_state = '{state}', web_company_name = '{company}', order number in ws_wh and also present in web_returns.",
             "Returned multi-warehouse web orders shipped {start}–{end} to {state}, company '{company}': orders, ship cost, net profit.",
             "I'm looking at split shipments that came back. Consider web orders from the '{company}' sites that were shipped to addresses in {state} sometime between {start_nl} and {end_nl}, where the order's items were sent from two or more different warehouses and at least part of the order was returned afterwards. How many distinct orders is that, and what were their total shipping cost and total net profit?",
         ]),
]

for _t in _ALL:
    _t["bench"] = "tpcds"

TEMPLATES = sorted(_ALL, key=lambda t: t["qnum"])
BY_ID = {t["id"]: t for t in TEMPLATES}
