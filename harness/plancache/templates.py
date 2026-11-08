"""Workload W templates (PLAN §2h): 30 TPC-DS (33 written, 3 excluded below) queries from DuckDB's `tpcds_queries()` with 1-3 variable literals
and 4 natural-language phrasings each.

Each template is a dict:
  id          "tNN" (NN = TPC-DS query number)
  qnum        TPC-DS query number (source: SELECT query FROM tpcds_queries() WHERE query_nr = qnum)
  complexity  "simple" (<= 3 tables, flat), "medium" (4-7 tables or a subquery/window), "complex" (CTEs / rollups /
              self-joins / multi-fact)
  sql         DuckDB SQL with {slot} placeholders (the official query text with only the listed literals made variable)
  slots       {name: spec}; spec kinds:
                ("int", lo, hi)              uniform integer in [lo, hi]
                ("choice", [v, ...])         one value
                ("sample", [v, ...], k)      k distinct values (a list), in drawn order
                ("date", "YYYY-MM-DD", "YYYY-MM-DD")  uniform day in [lo, hi] (ISO string)
                ("db", sql)                  one value from the tenant (sql returns one column of candidates)
                ("db_sample", sql, k)        min(k, n) distinct values from the tenant (a list)
  derive      {name: f(params) -> str}: SQL fragments and NL renderings computed from the drawn slots
  phrasings   4 analyst-style questions with {slot}/{derived} placeholders; each asks for exactly the columns,
              order and limit the SQL returns
  notes       deviations from the official literal structure, if any

Draws are tenant-specific only for "db"/"db_sample" slots (store names, states, cities, counties, reasons, GMT offsets
exist per tenant); everything else is a fixed range valid for every SF (sales years 1998-2002, d_month_seq 1200 =
Jan 2000, manager ids 1-100, manufacturer ids 1-1000, 10 item categories, ...).
"""
import datetime as _dt

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]  # d_dow 0 = Sunday
CATEGORIES = ["Books", "Children", "Electronics", "Home", "Jewelry", "Men", "Music", "Shoes", "Sports", "Women"]
EDUCATION = ["Primary", "Secondary", "College", "2 yr Degree", "4 yr Degree", "Advanced Degree", "Unknown"]
MARITAL = {"M": "married", "S": "single", "D": "divorced", "W": "widowed", "U": "unknown marital status"}
GENDER = {"M": "male", "F": "female"}
YEARS = (1998, 2002)


def _plus_days(iso, n):
    return (_dt.date.fromisoformat(iso) + _dt.timedelta(days=n)).isoformat()


def _sql_list(vals):
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)


def _nl_list(vals, conj="and"):
    vals = [str(v) for v in vals]
    return vals[0] if len(vals) == 1 else ", ".join(vals[:-1]) + f" {conj} " + vals[-1]


def _pretty_date(iso):
    d = _dt.date.fromisoformat(iso)
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def _mseq(p):
    return str((p["year"] - 1900) * 12)


MONTH_NAME = {"month_name": lambda p: MONTHS[p["moy"] - 1]}

_ALL = [
    # ------------------------------------------------------------------ simple
    dict(id="t03", qnum=3, complexity="simple",
         sql="""SELECT dt.d_year, item.i_brand_id brand_id, item.i_brand brand, sum(ss_ext_sales_price) sum_agg
FROM date_dim dt, store_sales, item
WHERE dt.d_date_sk = store_sales.ss_sold_date_sk AND store_sales.ss_item_sk = item.i_item_sk
  AND item.i_manufact_id = {manufact_id} AND dt.d_moy = {moy}
GROUP BY dt.d_year, item.i_brand, item.i_brand_id
ORDER BY dt.d_year, sum_agg DESC, brand_id
LIMIT 100;""",
         slots=dict(manufact_id=("int", 1, 1000), moy=("int", 1, 12)), derive=MONTH_NAME,
         phrasings=[
             "For items made by manufacturer {manufact_id}, what were the store sales (sum of extended sales price) in {month_name} of each year, broken down by brand? Show the year, brand id, brand name and total, sorted by year, then total descending, then brand id; top 100 rows.",
             "Show yearly {month_name} in-store revenue (extended sales price) per brand for manufacturer id {manufact_id}: year, brand id, brand, and the summed revenue. Order by year ascending, revenue descending, brand id; limit 100.",
             "I need a breakdown by year and brand of store extended sales price for products from manufacturer #{manufact_id}, counting only sales made in {month_name}. Columns: year, brand id, brand, total. Sort by year, highest total first within a year, then brand id, and keep the first 100.",
             "Which brands of manufacturer {manufact_id} sold the most in stores during {month_name}, year by year? List year, brand id, brand and the sum of ext sales price, ordered by year, then that sum descending, then brand id (max 100 rows).",
         ]),
    dict(id="t42", qnum=42, complexity="simple",
         sql="""SELECT dt.d_year, item.i_category_id, item.i_category, sum(ss_ext_sales_price)
FROM date_dim dt, store_sales, item
WHERE dt.d_date_sk = store_sales.ss_sold_date_sk AND store_sales.ss_item_sk = item.i_item_sk
  AND item.i_manager_id = {manager_id} AND dt.d_moy = {moy} AND dt.d_year = {year}
GROUP BY dt.d_year, item.i_category_id, item.i_category
ORDER BY sum(ss_ext_sales_price) DESC, dt.d_year, item.i_category_id, item.i_category
LIMIT 100;""",
         slots=dict(manager_id=("int", 1, 100), moy=("int", 1, 12), year=("int", *YEARS)), derive=MONTH_NAME,
         phrasings=[
             "What were store sales (extended sales price) by item category in {month_name} {year} for items managed by manager {manager_id}? Give the year, category id, category and total, largest total first (ties by year, category id, category), up to 100 rows.",
             "For manager id {manager_id}'s items, total the in-store extended sales price per category for {month_name} {year}. Return year, category id, category name and the sum, ordered by the sum descending, then year, category id and category; limit 100.",
             "Break down {month_name} {year} store revenue by category for products whose manager is {manager_id}: year, i_category_id, i_category, sum of ext sales price, sorted from highest revenue down (then by year, category id, category), 100 rows max.",
             "In {year}, during {month_name}, how much did each category sell in stores, counting only items with manager id {manager_id}? Show year, category id, category and summed extended sales price, highest first, tie-break on year, category id, category; first 100.",
         ]),
    dict(id="t55", qnum=55, complexity="simple",
         sql="""SELECT i_brand_id brand_id, i_brand brand, sum(ss_ext_sales_price) ext_price
FROM date_dim, store_sales, item
WHERE d_date_sk = ss_sold_date_sk AND ss_item_sk = i_item_sk
  AND i_manager_id = {manager_id} AND d_moy = {moy} AND d_year = {year}
GROUP BY i_brand, i_brand_id
ORDER BY ext_price DESC, i_brand_id
LIMIT 100;""",
         slots=dict(manager_id=("int", 1, 100), moy=("int", 1, 12), year=("int", *YEARS)), derive=MONTH_NAME,
         phrasings=[
             "Which brands brought in the most store revenue in {month_name} {year} among items with manager {manager_id}? List brand id, brand and the sum of extended sales price, highest first, then by brand id; top 100.",
             "For manager id {manager_id}, give each brand's total in-store extended sales price for {month_name} {year}: brand id, brand name, total. Sort by total descending and brand id; limit 100.",
             "Total store ext sales price per brand in {month_name} of {year}, only items managed by manager {manager_id}. Columns brand_id, brand, ext_price; order ext_price desc then brand_id; 100 rows max.",
             "I'd like brand-level store sales for {month_name} {year} for products under manager #{manager_id}: show brand id, brand and summed extended price, ranked from largest down (ties by brand id), first 100 only.",
         ]),
    dict(id="t96", qnum=96, complexity="simple",
         sql="""SELECT count(*)
FROM store_sales, household_demographics, time_dim, store
WHERE ss_sold_time_sk = time_dim.t_time_sk AND ss_hdemo_sk = household_demographics.hd_demo_sk
  AND ss_store_sk = s_store_sk AND time_dim.t_hour = {hour} AND time_dim.t_minute >= 30
  AND household_demographics.hd_dep_count = {dep_count} AND store.s_store_name = '{store_name}'
ORDER BY count(*)
LIMIT 100;""",
         slots=dict(hour=("int", 8, 20), dep_count=("int", 0, 9),
                    store_name=("db", "SELECT DISTINCT s_store_name FROM store WHERE s_store_name IS NOT NULL")),
         derive=dict(hour_end=lambda p: str(p["hour"] + 1)),
         phrasings=[
             "How many store sales happened between {hour}:30 and {hour_end}:00 (sold-time hour {hour}, minute 30 or later) at stores named '{store_name}' for households with {dep_count} dependents? Just the count.",
             "Count the store_sales rows sold in the second half of hour {hour} (minute >= 30) at store name '{store_name}' where the household has dep_count = {dep_count}.",
             "Give me the number of in-store sales at '{store_name}' stores to households with {dep_count} dependents, sold during {hour}:30-{hour}:59.",
             "For households with a dependent count of {dep_count}, what is the count of sales at the store(s) called '{store_name}' made at hour {hour} with minute at least 30?",
         ]),
    dict(id="t43", qnum=43, complexity="simple",
         sql="""SELECT s_store_name, s_store_id,
  sum(CASE WHEN (d_day_name='Sunday') THEN ss_sales_price ELSE NULL END) sun_sales,
  sum(CASE WHEN (d_day_name='Monday') THEN ss_sales_price ELSE NULL END) mon_sales,
  sum(CASE WHEN (d_day_name='Tuesday') THEN ss_sales_price ELSE NULL END) tue_sales,
  sum(CASE WHEN (d_day_name='Wednesday') THEN ss_sales_price ELSE NULL END) wed_sales,
  sum(CASE WHEN (d_day_name='Thursday') THEN ss_sales_price ELSE NULL END) thu_sales,
  sum(CASE WHEN (d_day_name='Friday') THEN ss_sales_price ELSE NULL END) fri_sales,
  sum(CASE WHEN (d_day_name='Saturday') THEN ss_sales_price ELSE NULL END) sat_sales
FROM date_dim, store_sales, store
WHERE d_date_sk = ss_sold_date_sk AND s_store_sk = ss_store_sk AND s_gmt_offset = {gmt_offset} AND d_year = {year}
GROUP BY s_store_name, s_store_id
ORDER BY s_store_name, s_store_id, sun_sales, mon_sales, tue_sales, wed_sales, thu_sales, fri_sales, sat_sales
LIMIT 100;""",
         slots=dict(year=("int", *YEARS),
                    gmt_offset=("db", "SELECT DISTINCT CAST(s_gmt_offset AS INTEGER) FROM store WHERE s_gmt_offset IS NOT NULL")),
         derive={},
         phrasings=[
             "For stores in GMT offset {gmt_offset}, show each store's name and id with its total sales price for every day of the week (Sunday through Saturday as seven columns) in {year}. Order by store name, store id, then the day totals Sunday to Saturday; limit 100.",
             "Weekday breakdown of {year} store sales (ss_sales_price) per store with gmt offset {gmt_offset}: store name, store id, sun, mon, tue, wed, thu, fri, sat sales. Sort by name, id and then the seven totals in order; at most 100 rows.",
             "In {year}, how much did each store in time zone offset {gmt_offset} sell on Sundays, Mondays, ..., Saturdays? I want store name, store id and seven day-of-week sums of sales price, ordered by store name, id, then Sunday..Saturday sums. 100 rows max.",
             "List stores (name, id) located at GMT offset {gmt_offset} with their {year} sales price totals split into Sunday, Monday, Tuesday, Wednesday, Thursday, Friday and Saturday columns, sorted by name, id and the day columns in that order, first 100.",
         ]),
    dict(id="t93", qnum=93, complexity="simple",
         sql="""SELECT ss_customer_sk, sum(act_sales) sumsales
FROM (SELECT ss_item_sk, ss_ticket_number, ss_customer_sk,
        CASE WHEN sr_return_quantity IS NOT NULL THEN (ss_quantity-sr_return_quantity)*ss_sales_price
             ELSE (ss_quantity*ss_sales_price) END act_sales
      FROM store_sales LEFT OUTER JOIN store_returns ON (sr_item_sk = ss_item_sk AND sr_ticket_number = ss_ticket_number), reason
      WHERE sr_reason_sk = r_reason_sk AND r_reason_desc = '{reason}') t
GROUP BY ss_customer_sk
ORDER BY sumsales NULLS FIRST, ss_customer_sk NULLS FIRST
LIMIT 100;""",
         slots=dict(reason=("db", "SELECT DISTINCT r_reason_desc FROM reason WHERE r_reason_desc IS NOT NULL")), derive={},
         phrasings=[
             "For store sales that were returned with reason '{reason}', compute each customer's actual sales: (quantity minus returned quantity) times sales price. Show customer sk and the total, smallest totals first, then by customer sk (nulls first); 100 rows.",
             "Per customer (ss_customer_sk), sum the net sales amount after returns — (ss_quantity - sr_return_quantity) * ss_sales_price — over store sales returned for the reason '{reason}'. Order by that sum ascending then customer sk, nulls first, limit 100.",
             "Which customers have the lowest net store sales on items returned because of '{reason}'? Net = (quantity sold - quantity returned) x sales price, summed per customer sk. Return customer sk and the sum, ascending, tie-break on customer sk, first 100.",
             "Looking only at store returns with reason description '{reason}', give the customer surrogate key and total actual sales (sold minus returned quantity, times sales price) for each customer, sorted by total then customer key ascending with nulls first, top 100.",
         ]),
    dict(id="t32", qnum=32, complexity="medium",
         sql="""SELECT sum(cs_ext_discount_amt) AS "excess discount amount"
FROM catalog_sales, item, date_dim
WHERE i_manufact_id = {manufact_id} AND i_item_sk = cs_item_sk
  AND d_date BETWEEN '{start}' AND cast('{end}' AS date) AND d_date_sk = cs_sold_date_sk
  AND cs_ext_discount_amt > (SELECT 1.3 * avg(cs_ext_discount_amt) FROM catalog_sales, date_dim
                             WHERE cs_item_sk = i_item_sk AND d_date BETWEEN '{start}' AND cast('{end}' AS date)
                               AND d_date_sk = cs_sold_date_sk)
LIMIT 100;""",
         slots=dict(manufact_id=("int", 1, 1000), start=("date", "1998-01-01", "2002-09-30")),
         derive=dict(end=lambda p: _plus_days(p["start"], 90), start_nl=lambda p: _pretty_date(p["start"]),
                     end_nl=lambda p: _pretty_date(_plus_days(p["start"], 90))),
         phrasings=[
             "What is the total excess discount amount on catalog sales of manufacturer {manufact_id}'s items between {start} and {end}, where excess means the sale's extended discount is more than 1.3 times that item's average extended discount over the same period? One number.",
             "Sum cs_ext_discount_amt for catalog sales from {start_nl} to {end_nl} of items with manufacturer id {manufact_id}, counting only sales whose discount exceeds 130% of the average discount for the same item in that window.",
             "For manufacturer #{manufact_id}, add up the extended discount amounts of catalog sales sold {start} through {end} (inclusive) whose discount is above 1.3x the item's mean ext discount in that date range.",
             "Between {start_nl} and {end_nl}, how much catalog extended discount was given on manufacturer {manufact_id} products in sales where the discount was over 1.3 times the per-item average for those dates? Return the single sum.",
         ]),
    dict(id="t97", qnum=97, complexity="complex",
         sql="""WITH ssci AS (SELECT ss_customer_sk customer_sk, ss_item_sk item_sk FROM store_sales, date_dim
                WHERE ss_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq} + 11
                GROUP BY ss_customer_sk, ss_item_sk),
     csci AS (SELECT cs_bill_customer_sk customer_sk, cs_item_sk item_sk FROM catalog_sales, date_dim
                WHERE cs_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq} + 11
                GROUP BY cs_bill_customer_sk, cs_item_sk)
SELECT sum(CASE WHEN ssci.customer_sk IS NOT NULL AND csci.customer_sk IS NULL THEN 1 ELSE 0 END) store_only,
       sum(CASE WHEN ssci.customer_sk IS NULL AND csci.customer_sk IS NOT NULL THEN 1 ELSE 0 END) catalog_only,
       sum(CASE WHEN ssci.customer_sk IS NOT NULL AND csci.customer_sk IS NOT NULL THEN 1 ELSE 0 END) store_and_catalog
FROM ssci FULL OUTER JOIN csci ON (ssci.customer_sk = csci.customer_sk AND ssci.item_sk = csci.item_sk)
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "In {year}, how many distinct (customer, item) pairs were bought only in stores, only through the catalog, and through both? Return the three counts: store_only, catalog_only, store_and_catalog.",
             "Taking all customer-item combinations purchased during {year} (store sales vs catalog sales by bill customer), count those that appear only in store sales, only in catalog sales, and in both. Three columns.",
             "Compare channels for {year}: count customer/item pairs that were store-only, catalog-only, or bought via both store and catalog.",
             "For the 12 months of {year}, give me the number of unique customer-and-item pairs seen only in store_sales, only in catalog_sales, and in both, as store_only, catalog_only and store_and_catalog.",
         ]),
    dict(id="t12", qnum=12, complexity="medium",
         sql="""SELECT i_item_id, i_item_desc, i_category, i_class, i_current_price, sum(ws_ext_sales_price) AS itemrevenue,
       sum(ws_ext_sales_price)*100.0000/sum(sum(ws_ext_sales_price)) OVER (PARTITION BY i_class) AS revenueratio
FROM web_sales, item, date_dim
WHERE ws_item_sk = i_item_sk AND i_category IN ({cats_sql}) AND ws_sold_date_sk = d_date_sk
  AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
GROUP BY i_item_id, i_item_desc, i_category, i_class, i_current_price
ORDER BY i_category, i_class, i_item_id, i_item_desc, revenueratio
LIMIT 100;""",
         slots=dict(cats=("sample", CATEGORIES, 3), start=("date", "1998-01-01", "2002-11-30")),
         derive=dict(cats_sql=lambda p: _sql_list(p["cats"]), cats_nl=lambda p: _nl_list(p["cats"]),
                     end=lambda p: _plus_days(p["start"], 30), start_nl=lambda p: _pretty_date(p["start"]),
                     end_nl=lambda p: _pretty_date(_plus_days(p["start"], 30))),
         phrasings=[
             "For web sales of {cats_nl} items between {start} and {end}, show item id, description, category, class, current price, the item's revenue (sum of extended sales price), and its revenue as a percentage of its class's total. Sort by category, class, item id, description, ratio; first 100.",
             "Web revenue report, {start_nl} to {end_nl}, categories {cats_nl}: per item give i_item_id, i_item_desc, i_category, i_class, i_current_price, itemrevenue and revenueratio (item revenue x 100 / class revenue). Order by category, class, item id, desc, revenueratio, limit 100.",
             "What share of its class's web sales revenue did each item in {cats_nl} earn from {start} through {end}? Include the item id, description, category, class, current price and total ext sales price too; order by category, class, item id, description and the share; 100 rows.",
             "List items in the {cats_nl} categories with their online (web) ext sales revenue over {start_nl}-{end_nl} and the percent of class revenue they represent, along with item id, description, category, class and current price. Ordered by category, class, item id, description, percent; limit 100.",
         ]),
    dict(id="t20", qnum=20, complexity="medium",
         sql="""SELECT i_item_id, i_item_desc, i_category, i_class, i_current_price, sum(cs_ext_sales_price) AS itemrevenue,
       sum(cs_ext_sales_price)*100.0000/sum(sum(cs_ext_sales_price)) OVER (PARTITION BY i_class) AS revenueratio
FROM catalog_sales, item, date_dim
WHERE cs_item_sk = i_item_sk AND i_category IN ({cats_sql}) AND cs_sold_date_sk = d_date_sk
  AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
GROUP BY i_item_id, i_item_desc, i_category, i_class, i_current_price
ORDER BY i_category NULLS FIRST, i_class NULLS FIRST, i_item_id NULLS FIRST, i_item_desc NULLS FIRST, revenueratio NULLS FIRST
LIMIT 100;""",
         slots=dict(cats=("sample", CATEGORIES, 3), start=("date", "1998-01-01", "2002-11-30")),
         derive=dict(cats_sql=lambda p: _sql_list(p["cats"]), cats_nl=lambda p: _nl_list(p["cats"]),
                     end=lambda p: _plus_days(p["start"], 30), start_nl=lambda p: _pretty_date(p["start"]),
                     end_nl=lambda p: _pretty_date(_plus_days(p["start"], 30))),
         phrasings=[
             "For catalog sales of {cats_nl} items from {start} to {end}, give item id, description, category, class, current price, total extended sales price, and that total as a percent of the item's class total. Order by category, class, item id, description, percent (nulls first); 100 rows.",
             "Catalog revenue by item, {start_nl} through {end_nl}, restricted to categories {cats_nl}: i_item_id, i_item_desc, i_category, i_class, i_current_price, itemrevenue, revenueratio (100 x item revenue / class revenue). Sort by category, class, item id, desc, ratio, nulls first, limit 100.",
             "How much catalog revenue did each {cats_nl} item make between {start} and {end}, and what percentage of its class's catalog revenue is that? Show id, description, category, class, current price, revenue and percentage, sorted by category, class, id, description, percentage; first 100.",
             "Show me catalog-channel item revenue (sum of cs_ext_sales_price) for the {cats_nl} categories over {start_nl}-{end_nl} with each item's share of its class, plus item id, description, category, class and current price, ordered category, class, item id, description, share; limit 100.",
         ]),
    # ------------------------------------------------------------------ medium
    dict(id="t07", qnum=7, complexity="medium",
         sql="""SELECT i_item_id, avg(ss_quantity) agg1, avg(ss_list_price) agg2, avg(ss_coupon_amt) agg3, avg(ss_sales_price) agg4
FROM store_sales, customer_demographics, date_dim, item, promotion
WHERE ss_sold_date_sk = d_date_sk AND ss_item_sk = i_item_sk AND ss_cdemo_sk = cd_demo_sk AND ss_promo_sk = p_promo_sk
  AND cd_gender = '{gender}' AND cd_marital_status = '{marital}' AND cd_education_status = 'College'
  AND (p_channel_email = 'N' OR p_channel_event = 'N') AND d_year = {year}
GROUP BY i_item_id
ORDER BY i_item_id
LIMIT 100;""",
         slots=dict(gender=("choice", ["M", "F"]), marital=("choice", list(MARITAL)), year=("int", *YEARS)),
         derive=dict(gender_nl=lambda p: GENDER[p["gender"]], marital_nl=lambda p: MARITAL[p["marital"]]),
         phrasings=[
             "For store sales in {year} to {marital_nl} {gender_nl} customers with College education, using promotions that were not email or not event promotions, give each item id with the average quantity, list price, coupon amount and sales price. Order by item id, first 100.",
             "Per item id: avg ss_quantity, avg list price, avg coupon amt, avg sales price over {year} store sales where the customer demographic is gender {gender}, marital status {marital}, education 'College', and the promo has channel_email = 'N' or channel_event = 'N'. Sort by item id, limit 100.",
             "What were the average quantity, list price, coupon amount and sales price per item in stores during {year}, for College-educated {gender_nl} customers who are {marital_nl}, on promotions without email or without event channel? Item id plus the four averages, by item id, 100 rows.",
             "Show item id and four averages (quantity, list price, coupon amount, sales price) of {year} in-store purchases by {gender_nl}, {marital_nl}, college-educated shoppers, counting only promotions where email is 'N' or event is 'N'; ordered by item id, top 100.",
         ]),
    dict(id="t26", qnum=26, complexity="medium",
         sql="""SELECT i_item_id, avg(cs_quantity) agg1, avg(cs_list_price) agg2, avg(cs_coupon_amt) agg3, avg(cs_sales_price) agg4
FROM catalog_sales, customer_demographics, date_dim, item, promotion
WHERE cs_sold_date_sk = d_date_sk AND cs_item_sk = i_item_sk AND cs_bill_cdemo_sk = cd_demo_sk AND cs_promo_sk = p_promo_sk
  AND cd_gender = '{gender}' AND cd_marital_status = 'S' AND cd_education_status = '{education}'
  AND (p_channel_email = 'N' OR p_channel_event = 'N') AND d_year = {year}
GROUP BY i_item_id
ORDER BY i_item_id
LIMIT 100;""",
         slots=dict(gender=("choice", ["M", "F"]), education=("choice", EDUCATION), year=("int", *YEARS)),
         derive=dict(gender_nl=lambda p: GENDER[p["gender"]]),
         phrasings=[
             "For catalog sales in {year} billed to single {gender_nl} customers with education '{education}', on promotions that were not email or not event promotions, show each item id with average quantity, list price, coupon amount and sales price, ordered by item id, first 100.",
             "Per item id, average cs_quantity, cs_list_price, cs_coupon_amt and cs_sales_price for {year} catalog orders whose bill-to demographic is gender {gender}, marital status S, education status '{education}', with promotion channel_email = 'N' or channel_event = 'N'. Order by item id; limit 100.",
             "What did single {gender_nl} catalog shoppers with '{education}' education buy in {year}? Give item id and the averages of quantity, list price, coupon amount and sales price, only for promotions lacking email or lacking event channel, sorted by item id, 100 rows.",
             "Catalog channel, year {year}: item id plus avg quantity / list price / coupon amount / sales price for purchases by unmarried (single) {gender_nl} customers whose education is {education}, where the promo is not email or not event. By item id, top 100.",
         ]),
    dict(id="t15", qnum=15, complexity="medium",
         sql="""SELECT ca_zip, sum(cs_sales_price)
FROM catalog_sales, customer, customer_address, date_dim
WHERE cs_bill_customer_sk = c_customer_sk AND c_current_addr_sk = ca_address_sk
  AND (SUBSTRING(ca_zip, 1, 5) IN ('85669', '86197', '88274', '83405', '86475', '85392', '85460', '80348', '81792')
       OR ca_state IN ('CA', 'WA', 'GA') OR cs_sales_price > 500)
  AND cs_sold_date_sk = d_date_sk AND d_qoy = {qoy} AND d_year = {year}
GROUP BY ca_zip
ORDER BY ca_zip NULLS FIRST
LIMIT 100;""",
         slots=dict(qoy=("int", 1, 4), year=("int", *YEARS)), derive={},
         phrasings=[
             "Total catalog sales price by customer zip code for Q{qoy} {year}, counting sales where the bill-to customer's current zip starts with 85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348 or 81792, or the customer lives in CA, WA or GA, or the sale price is over 500. Show zip and total, ordered by zip (nulls first), 100 rows.",
             "For quarter {qoy} of {year}, sum cs_sales_price per ca_zip of the billing customer's current address, including a sale if the 5-digit zip is in (85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348, 81792) or state in (CA, WA, GA) or cs_sales_price > 500. Sort by zip, limit 100.",
             "Which zip codes generated catalog sales in {year} Q{qoy}, and how much (sum of sales price)? Only count sales from customers in CA, WA or GA, or with zip prefix 85669/86197/88274/83405/86475/85392/85460/80348/81792, or any sale above 500. Zip ascending, nulls first, first 100.",
             "Catalog sales price totals grouped by customer zip for the {qoy} quarter of {year}; a sale counts if its price exceeds 500, or the customer's state is CA, WA or GA, or the first five zip digits are one of 85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348, 81792. Order by zip; 100 rows max.",
         ]),
    dict(id="t19", qnum=19, complexity="medium",
         sql="""SELECT i_brand_id brand_id, i_brand brand, i_manufact_id, i_manufact, sum(ss_ext_sales_price) ext_price
FROM date_dim, store_sales, item, customer, customer_address, store
WHERE d_date_sk = ss_sold_date_sk AND ss_item_sk = i_item_sk AND i_manager_id = {manager_id}
  AND d_moy = {moy} AND d_year = {year} AND ss_customer_sk = c_customer_sk AND c_current_addr_sk = ca_address_sk
  AND SUBSTRING(ca_zip, 1, 5) <> SUBSTRING(s_zip, 1, 5) AND ss_store_sk = s_store_sk
GROUP BY i_brand, i_brand_id, i_manufact_id, i_manufact
ORDER BY ext_price DESC, i_brand, i_brand_id, i_manufact_id, i_manufact
LIMIT 100;""",
         slots=dict(manager_id=("int", 1, 100), moy=("int", 1, 12), year=("int", *YEARS)), derive=MONTH_NAME,
         phrasings=[
             "For items with manager {manager_id}, what were store sales (extended sales price) in {month_name} {year} by brand and manufacturer, counting only purchases where the customer's current zip (first 5 digits) differs from the store's zip? Show brand id, brand, manufacturer id, manufacturer, total; highest total first, then brand, brand id, manufacturer id, manufacturer; 100 rows.",
             "Sum ss_ext_sales_price per (brand id, brand, manufact id, manufact) for {month_name} {year} store sales of manager-{manager_id} items bought by customers whose home zip5 is not the store's zip5. Order by the sum desc, then brand, brand id, manufact id, manufact. Limit 100.",
             "Which brand/manufacturer combinations sold best in {month_name} {year} to out-of-area customers (current address zip prefix different from the store zip prefix), for items managed by {manager_id}? Give brand id, brand, manufacturer id, manufacturer and ext sales price total, sorted descending by total with ties by brand, brand id, manufacturer id, manufacturer; top 100.",
             "In {year}, month {moy} ({month_name}), restricted to manager id {manager_id}'s items and customers living in a different 5-digit zip than the store they bought from: brand_id, brand, i_manufact_id, i_manufact and summed extended price, biggest first (then brand, brand_id, manufact id, manufact), 100 max.",
         ]),
    dict(id="t82", qnum=82, complexity="medium",
         sql="""SELECT i_item_id, i_item_desc, i_current_price
FROM item, inventory, date_dim, store_sales
WHERE i_current_price BETWEEN {price} AND {price}+30 AND inv_item_sk = i_item_sk AND d_date_sk = inv_date_sk
  AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
  AND i_manufact_id IN ({manus_sql}) AND inv_quantity_on_hand BETWEEN 100 AND 500 AND ss_item_sk = i_item_sk
GROUP BY i_item_id, i_item_desc, i_current_price
ORDER BY i_item_id
LIMIT 100;""",
         slots=dict(price=("int", 10, 70), manus=("sample", list(range(1, 1001)), 4),
                    start=("date", "1998-01-01", "2002-10-15")),
         derive=dict(manus_sql=lambda p: ", ".join(map(str, p["manus"])), manus_nl=lambda p: _nl_list(p["manus"], "or"),
                     end=lambda p: _plus_days(p["start"], 60), price_hi=lambda p: str(p["price"] + 30)),
         notes="manufacturer list is 4 random ids (a 4-value slot); empty results are common and recorded",
         phrasings=[
             "Which items from manufacturers {manus_nl}, priced between {price} and {price_hi}, had between 100 and 500 units on hand in inventory at some point from {start} to {end} and have been sold in stores? Return item id, description and current price, ordered by item id, up to 100.",
             "List i_item_id, i_item_desc, i_current_price for items with current price in [{price}, {price_hi}], manufacturer id in ({manus_sql}), an inventory record dated {start}..{end} with quantity on hand 100-500, and at least one store sale. Distinct items, sorted by item id, limit 100.",
             "Show me distinct items (id, description, current price) made by manufacturer {manus_nl} costing {price} to {price_hi} dollars that had an inventory count between 100 and 500 sometime between {start} and {end}, and that appear in store sales. Order by item id; 100 rows.",
             "I'm looking for store-sold items whose current price is {price}-{price_hi}, whose manufacturer id is one of {manus_nl}, and whose inventory on hand was 100 to 500 on some date in {start} through {end}. Item id, description, price, by item id, first 100.",
         ]),
    dict(id="t62", qnum=62, complexity="medium",
         sql="""SELECT w_substr, sm_type, web_name,
  sum(CASE WHEN (ws_ship_date_sk - ws_sold_date_sk <= 30) THEN 1 ELSE 0 END) AS "30 days",
  sum(CASE WHEN (ws_ship_date_sk - ws_sold_date_sk > 30) AND (ws_ship_date_sk - ws_sold_date_sk <= 60) THEN 1 ELSE 0 END) AS "31-60 days",
  sum(CASE WHEN (ws_ship_date_sk - ws_sold_date_sk > 60) AND (ws_ship_date_sk - ws_sold_date_sk <= 90) THEN 1 ELSE 0 END) AS "61-90 days",
  sum(CASE WHEN (ws_ship_date_sk - ws_sold_date_sk > 90) AND (ws_ship_date_sk - ws_sold_date_sk <= 120) THEN 1 ELSE 0 END) AS "91-120 days",
  sum(CASE WHEN (ws_ship_date_sk - ws_sold_date_sk > 120) THEN 1 ELSE 0 END) AS ">120 days"
FROM web_sales, (SELECT SUBSTRING(w_warehouse_name,1,20) w_substr, * FROM warehouse) sq1, ship_mode, web_site, date_dim
WHERE d_month_seq BETWEEN {mseq} AND {mseq} + 11 AND ws_ship_date_sk = d_date_sk AND ws_warehouse_sk = w_warehouse_sk
  AND ws_ship_mode_sk = sm_ship_mode_sk AND ws_web_site_sk = web_site_sk
GROUP BY w_substr, sm_type, web_name
ORDER BY 1 NULLS FIRST, 2 NULLS FIRST, 3 NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "For web orders shipped in {year}, count orders by shipping delay (ship date minus sold date: up to 30 days, 31-60, 61-90, 91-120, over 120) for each warehouse (first 20 characters of its name), ship mode type and web site name. Sort by those three columns, nulls first; 100 rows.",
             "Web shipping lag report for {year} (by ship date): per first-20-chars warehouse name, sm_type and web_name, the number of web_sales lines shipped within 30 days, 31-60, 61-90, 91-120 and more than 120 days after sale. Order by warehouse, ship mode type, site name; limit 100.",
             "How long did web orders shipped during {year} take to ship? Group by warehouse name (truncated to 20 chars), ship mode type and web site name, and give five counts: <=30 days, 31-60, 61-90, 91-120, >120 days. Ordered by the three group columns, 100 rows max.",
             "Break down {year}-shipped web sales by warehouse (substring of name, 20 chars), shipping mode type and website name, with counts in delay buckets 30 days, 31-60 days, 61-90 days, 91-120 days and >120 days. Sorted by warehouse, mode type, site; first 100.",
         ]),
    dict(id="t99", qnum=99, complexity="medium",
         sql="""SELECT w_substr, sm_type, cc_name,
  sum(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk <= 30) THEN 1 ELSE 0 END) AS "30 days",
  sum(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 30) AND (cs_ship_date_sk - cs_sold_date_sk <= 60) THEN 1 ELSE 0 END) AS "31-60 days",
  sum(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 60) AND (cs_ship_date_sk - cs_sold_date_sk <= 90) THEN 1 ELSE 0 END) AS "61-90 days",
  sum(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 90) AND (cs_ship_date_sk - cs_sold_date_sk <= 120) THEN 1 ELSE 0 END) AS "91-120 days",
  sum(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 120) THEN 1 ELSE 0 END) AS ">120 days"
FROM catalog_sales, (SELECT SUBSTRING(w_warehouse_name,1,20) w_substr, * FROM warehouse) AS sq1, ship_mode, call_center, date_dim
WHERE d_month_seq BETWEEN {mseq} AND {mseq} + 11 AND cs_ship_date_sk = d_date_sk AND cs_warehouse_sk = w_warehouse_sk
  AND cs_ship_mode_sk = sm_ship_mode_sk AND cs_call_center_sk = cc_call_center_sk
GROUP BY w_substr, sm_type, cc_name
ORDER BY w_substr NULLS FIRST, sm_type NULLS FIRST, cc_name NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "For catalog orders shipped in {year}, count orders per warehouse (first 20 characters of the name), ship mode type and call center name by shipping delay: within 30 days, 31-60, 61-90, 91-120, and more than 120 days. Order by warehouse, ship mode type, call center, nulls first; 100 rows.",
             "Catalog shipping delay buckets for {year} ship dates: per 20-char warehouse name, sm_type and cc_name, how many catalog_sales lines took <=30, 31-60, 61-90, 91-120, >120 days from sale to shipment. Sort by the three grouping columns; limit 100.",
             "How quickly were catalog orders shipped in {year}? By warehouse (name truncated to 20 chars), ship mode type and call center name, give five counts of ship-minus-sold days: 30 or less, 31-60, 61-90, 91-120, over 120. Sorted by those three columns, first 100.",
             "Group {year}-shipped catalog sales by warehouse substring (20 chars), shipping mode type and call center name, and count lines in the delay ranges 30 days, 31-60 days, 61-90 days, 91-120 days and >120 days; ordered warehouse, mode, call center; 100 max.",
         ]),
    dict(id="t50", qnum=50, complexity="medium",
         sql="""SELECT s_store_name, s_company_id, s_street_number, s_street_name, s_street_type, s_suite_number, s_city, s_county, s_state, s_zip,
  sum(CASE WHEN (sr_returned_date_sk - ss_sold_date_sk <= 30) THEN 1 ELSE 0 END) AS "30 days",
  sum(CASE WHEN (sr_returned_date_sk - ss_sold_date_sk > 30) AND (sr_returned_date_sk - ss_sold_date_sk <= 60) THEN 1 ELSE 0 END) AS "31-60 days",
  sum(CASE WHEN (sr_returned_date_sk - ss_sold_date_sk > 60) AND (sr_returned_date_sk - ss_sold_date_sk <= 90) THEN 1 ELSE 0 END) AS "61-90 days",
  sum(CASE WHEN (sr_returned_date_sk - ss_sold_date_sk > 90) AND (sr_returned_date_sk - ss_sold_date_sk <= 120) THEN 1 ELSE 0 END) AS "91-120 days",
  sum(CASE WHEN (sr_returned_date_sk - ss_sold_date_sk > 120) THEN 1 ELSE 0 END) AS ">120 days"
FROM store_sales, store_returns, store, date_dim d1, date_dim d2
WHERE d2.d_year = {year} AND d2.d_moy = {moy} AND ss_ticket_number = sr_ticket_number AND ss_item_sk = sr_item_sk
  AND ss_sold_date_sk = d1.d_date_sk AND sr_returned_date_sk = d2.d_date_sk AND ss_customer_sk = sr_customer_sk
  AND ss_store_sk = s_store_sk
GROUP BY s_store_name, s_company_id, s_street_number, s_street_name, s_street_type, s_suite_number, s_city, s_county, s_state, s_zip
ORDER BY s_store_name, s_company_id, s_street_number, s_street_name, s_street_type, s_suite_number, s_city, s_county, s_state, s_zip
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 12)), derive=MONTH_NAME,
         phrasings=[
             "For store returns made in {month_name} {year}, matched to their original sale (same ticket, item and customer), count returns per store by days between sale and return: 30 or fewer, 31-60, 61-90, 91-120, over 120. Show store name, company id, street number, street name, street type, suite number, city, county, state, zip and the five counts, ordered by those store columns; 100 rows.",
             "Return lag by store for returns in {month_name} {year}: group by s_store_name, s_company_id, s_street_number, s_street_name, s_street_type, s_suite_number, s_city, s_county, s_state, s_zip and count returns (joined to store_sales on ticket, item, customer) within 30 days, 31-60, 61-90, 91-120, >120 days of the sale. Sort by the ten store columns; limit 100.",
             "How long after purchase did customers return items to each store in {month_name} {year}? Give each store's name, company id, full address (street number, name, type, suite, city, county, state, zip) and counts of returns at <=30, 31-60, 61-90, 91-120 and >120 days, ordered by name then the address fields, first 100.",
             "Per store (name, company id, street number, street name, street type, suite, city, county, state, zip), bucket the returns processed in {year} month {moy} by how many days after the sale they came back: 30 days, 31-60, 61-90, 91-120, more than 120. Same ticket/item/customer on sale and return. Order by the store columns as listed, 100 max.",
         ]),
    dict(id="t40", qnum=40, complexity="medium",
         sql="""SELECT w_state, i_item_id,
  sum(CASE WHEN (cast(d_date AS date) < CAST ('{pivot}' AS date)) THEN cs_sales_price - coalesce(cr_refunded_cash,0) ELSE 0 END) AS sales_before,
  sum(CASE WHEN (cast(d_date AS date) >= CAST ('{pivot}' AS date)) THEN cs_sales_price - coalesce(cr_refunded_cash,0) ELSE 0 END) AS sales_after
FROM catalog_sales LEFT OUTER JOIN catalog_returns ON (cs_order_number = cr_order_number AND cs_item_sk = cr_item_sk),
     warehouse, item, date_dim
WHERE i_current_price BETWEEN 0.99 AND 1.49 AND i_item_sk = cs_item_sk AND cs_warehouse_sk = w_warehouse_sk
  AND cs_sold_date_sk = d_date_sk AND d_date BETWEEN CAST ('{lo}' AS date) AND CAST ('{hi}' AS date)
GROUP BY w_state, i_item_id
ORDER BY w_state, i_item_id
LIMIT 100;""",
         slots=dict(pivot=("date", "1998-02-01", "2002-11-30")),
         derive=dict(lo=lambda p: _plus_days(p["pivot"], -30), hi=lambda p: _plus_days(p["pivot"], 30),
                     pivot_nl=lambda p: _pretty_date(p["pivot"])),
         phrasings=[
             "For catalog sales of items priced $0.99-$1.49, sold between {lo} and {hi}, show per warehouse state and item id the net sales (sales price minus any refunded cash from returns) before {pivot} and on/after {pivot}. Order by state and item id; 100 rows.",
             "Net catalog sales around {pivot_nl}: for items with current price 0.99 to 1.49, sum cs_sales_price - coalesce(cr_refunded_cash, 0) (left-joining catalog_returns on order number and item) for sold dates in the 30 days before vs. from {pivot} through 30 days after. Columns w_state, i_item_id, sales_before, sales_after; sort by w_state, i_item_id; limit 100.",
             "How did cheap items (current price between 0.99 and 1.49) do in the catalog channel before versus after {pivot}? Within {lo}..{hi}, per warehouse state and item id, give sales price net of refunded cash before and after that date, ordered by state then item, first 100.",
             "Compare catalog sales net of refunds in the month before {pivot_nl} (from {lo}) against {pivot} to {hi}, for items priced 0.99-1.49, grouped by warehouse state and item id: w_state, item id, sales_before, sales_after. By state, item id; 100 max.",
         ]),
    dict(id="t21", qnum=21, complexity="medium",
         sql="""SELECT *
FROM (SELECT w_warehouse_name, i_item_id,
        sum(CASE WHEN (cast(d_date AS date) < CAST ('{pivot}' AS date)) THEN inv_quantity_on_hand ELSE 0 END) AS inv_before,
        sum(CASE WHEN (cast(d_date AS date) >= CAST ('{pivot}' AS date)) THEN inv_quantity_on_hand ELSE 0 END) AS inv_after
      FROM inventory, warehouse, item, date_dim
      WHERE i_current_price BETWEEN 0.99 AND 1.49 AND i_item_sk = inv_item_sk AND inv_warehouse_sk = w_warehouse_sk
        AND inv_date_sk = d_date_sk AND d_date BETWEEN CAST ('{lo}' AS date) AND CAST ('{hi}' AS date)
      GROUP BY w_warehouse_name, i_item_id) x
WHERE (CASE WHEN inv_before > 0 THEN (inv_after*1.000) / inv_before ELSE NULL END) BETWEEN 2.000/3.000 AND 3.000/2.000
ORDER BY w_warehouse_name NULLS FIRST, i_item_id NULLS FIRST
LIMIT 100;""",
         slots=dict(pivot=("date", "1998-02-01", "2002-11-25")),
         derive=dict(lo=lambda p: _plus_days(p["pivot"], -30), hi=lambda p: _plus_days(p["pivot"], 30),
                     pivot_nl=lambda p: _pretty_date(p["pivot"])),
         phrasings=[
             "For items priced between $0.99 and $1.49, total inventory on hand per warehouse name and item id in the 30 days before {pivot} and from {pivot} to 30 days after ({lo} to {hi}). Keep only rows where the after/before ratio is between 2/3 and 3/2. Show warehouse name, item id, inv_before, inv_after, ordered by warehouse then item (nulls first); 100 rows.",
             "Inventory stability around {pivot_nl}: per w_warehouse_name and i_item_id for items with current price 0.99-1.49, sum inv_quantity_on_hand for dates {lo} up to (not including) {pivot}, and for {pivot} through {hi}; return those with inv_before > 0 and inv_after/inv_before within [2/3, 3/2]. Sort by warehouse, item; limit 100.",
             "Which cheap items (price 0.99 to 1.49) had roughly steady inventory in each warehouse across {pivot}, meaning on-hand totals after vs before the date differ by at most a factor of 1.5? Use a 30-day window on each side. Warehouse name, item id, before total, after total, by warehouse and item, first 100.",
             "Show warehouse name, item id and summed inventory quantity before and on/after {pivot} (window {lo} to {hi}) for items whose current price is 0.99-1.49, filtered to after/before ratios between 0.667 and 1.5. Ordered by warehouse name, item id with nulls first; 100 max.",
         ]),
    dict(id="t45", qnum=45, complexity="medium",
         sql="""SELECT ca_zip, ca_city, sum(ws_sales_price)
FROM web_sales, customer, customer_address, date_dim, item
WHERE ws_bill_customer_sk = c_customer_sk AND c_current_addr_sk = ca_address_sk AND ws_item_sk = i_item_sk
  AND (SUBSTRING(ca_zip,1,5) IN ('85669', '86197', '88274', '83405', '86475', '85392', '85460', '80348', '81792')
       OR i_item_id IN (SELECT i_item_id FROM item WHERE i_item_sk IN (2, 3, 5, 7, 11, 13, 17, 19, 23, 29)))
  AND ws_sold_date_sk = d_date_sk AND d_qoy = {qoy} AND d_year = {year}
GROUP BY ca_zip, ca_city
ORDER BY ca_zip, ca_city
LIMIT 100;""",
         slots=dict(qoy=("int", 1, 4), year=("int", *YEARS)), derive={},
         phrasings=[
             "Total web sales price by customer zip and city for Q{qoy} {year}, counting a sale if the bill-to customer's current zip starts with 85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348 or 81792, or the item has the same item id as one of the items with surrogate key 2, 3, 5, 7, 11, 13, 17, 19, 23 or 29. Zip, city, total, ordered by zip and city; 100 rows.",
             "For web sales in quarter {qoy} of {year}: sum ws_sales_price grouped by ca_zip, ca_city of the billing customer's current address, where zip5 is in (85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348, 81792) or i_item_id is among the item ids of i_item_sk 2, 3, 5, 7, 11, 13, 17, 19, 23, 29. Sort by zip, city, limit 100.",
             "Which zip/city pairs bought online in {year} Q{qoy}, and how much (sum of sales price)? Include only customers whose zip prefix is 85669/86197/88274/83405/86475/85392/85460/80348/81792, or purchases of items sharing an item id with item_sk 2,3,5,7,11,13,17,19,23,29. Order by zip then city, first 100.",
             "Web sales price totals per customer zip code and city for the {qoy} quarter of {year}; a sale qualifies when the 5-digit zip is one of 85669, 86197, 88274, 83405, 86475, 85392, 85460, 80348, 81792 or when its item id matches an item with sk in {{2,3,5,7,11,13,17,19,23,29}}. By zip, city; 100 max.",
         ]),
    dict(id="t84", qnum=84, complexity="medium",
         sql="""SELECT c_customer_id AS customer_id, concat(concat(coalesce(c_last_name, ''), ', '), coalesce(c_first_name, '')) AS customername
FROM customer, customer_address, customer_demographics, household_demographics, income_band, store_returns
WHERE ca_city = '{city}' AND c_current_addr_sk = ca_address_sk AND ib_lower_bound >= {income}
  AND ib_upper_bound <= {income} + 50000 AND ib_income_band_sk = hd_income_band_sk AND cd_demo_sk = c_current_cdemo_sk
  AND hd_demo_sk = c_current_hdemo_sk AND sr_cdemo_sk = cd_demo_sk
ORDER BY c_customer_id NULLS FIRST
LIMIT 100;""",
         slots=dict(city=("db", "SELECT ca_city FROM customer_address WHERE ca_city IS NOT NULL GROUP BY ca_city HAVING count(*) >= 200"),
                    income=("choice", [0, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000, 100000])),
         derive=dict(income_hi=lambda p: str(p["income"] + 50000)),
         notes="city drawn from tenant cities with >= 200 addresses",
         phrasings=[
             "List customers living in {city} whose household income band lies within ${income}-${income_hi} (band lower bound at least {income}, upper bound at most {income_hi}) and whose current demographic profile appears on a store return. Show customer id and name formatted 'Last, First', ordered by customer id, first 100 (one row per matching return).",
             "customer_id and customername (last name, comma, space, first name; missing parts as empty) for customers whose current address city is {city}, whose household income band has ib_lower_bound >= {income} and ib_upper_bound <= {income_hi}, joined to store_returns on sr_cdemo_sk = the customer's current cdemo. Order by customer id, limit 100.",
             "Which {city} residents with household income band between {income} and {income_hi} have store returns tied to their current demographics? Return customer id and 'Last, First' name for each matching return row, sorted by customer id, 100 rows.",
             "Find customers from the city of {city} in income bands bounded by {income} and {income_hi} whose current customer demographic sk shows up in store_returns; give customer id and name as 'last, first', by customer id, top 100.",
         ]),
    dict(id="t90", qnum=90, complexity="medium",
         sql="""SELECT case when pmc=0 then null else cast(amc AS decimal(15,4))/cast(pmc AS decimal(15,4)) end am_pm_ratio
FROM (SELECT count(*) amc FROM web_sales, household_demographics, time_dim, web_page
      WHERE ws_sold_time_sk = time_dim.t_time_sk AND ws_ship_hdemo_sk = household_demographics.hd_demo_sk
        AND ws_web_page_sk = web_page.wp_web_page_sk AND time_dim.t_hour BETWEEN {am} AND {am}+1
        AND household_demographics.hd_dep_count = 6 AND web_page.wp_char_count BETWEEN {char_lo} AND {char_lo}+200) at_,
     (SELECT count(*) pmc FROM web_sales, household_demographics, time_dim, web_page
      WHERE ws_sold_time_sk = time_dim.t_time_sk AND ws_ship_hdemo_sk = household_demographics.hd_demo_sk
        AND ws_web_page_sk = web_page.wp_web_page_sk AND time_dim.t_hour BETWEEN {pm} AND {pm}+1
        AND household_demographics.hd_dep_count = 6 AND web_page.wp_char_count BETWEEN {char_lo} AND {char_lo}+200) pt
ORDER BY am_pm_ratio
LIMIT 100;""",
         slots=dict(am=("int", 6, 11), pm=("int", 13, 21),
                    char_lo=("db", "SELECT DISTINCT CAST(wp_char_count // 100 * 100 AS INTEGER) FROM web_page WHERE wp_char_count IS NOT NULL")),
         derive=dict(am_end=lambda p: str(p["am"] + 1), pm_end=lambda p: str(p["pm"] + 1), char_hi=lambda p: str(p["char_lo"] + 200)),
         notes="char-count band lower bound drawn from the tenant's web pages (5000-5200 has no page at sf0.5); dep count fixed at 6 as in the official query",
         phrasings=[
             "What is the ratio of morning to evening web sales: the count of web sales sold in hours {am}-{am_end} divided by the count sold in hours {pm}-{pm_end}, for ship-to households with 6 dependents and web pages with {char_lo}-{char_hi} characters? Return the ratio (null if the evening count is 0).",
             "Compute am_pm_ratio = (# web_sales with sold-time hour between {am} and {am_end}) / (# with hour between {pm} and {pm_end}), counting only sales whose ship household has dep_count = 6 and whose web page char count is {char_lo} to {char_hi}.",
             "For web pages between {char_lo} and {char_hi} characters and shipping households with 6 dependents, how many times more web sales happened at hours {am}-{am_end} than at hours {pm}-{pm_end}? Give the single ratio as a decimal.",
             "Divide the number of web sales made from hour {am} through hour {am_end} by the number made from hour {pm} through {pm_end}, restricted to ship-hdemo dependent count 6 and wp_char_count in [{char_lo}, {char_hi}]. One value, am_pm_ratio.",
         ]),
    dict(id="t06", qnum=6, complexity="medium",
         sql="""SELECT a.ca_state state, count(*) cnt
FROM customer_address a, customer c, store_sales s, date_dim d, item i
WHERE a.ca_address_sk = c.c_current_addr_sk AND c.c_customer_sk = s.ss_customer_sk AND s.ss_sold_date_sk = d.d_date_sk
  AND s.ss_item_sk = i.i_item_sk
  AND d.d_month_seq = (SELECT DISTINCT (d_month_seq) FROM date_dim WHERE d_year = {year} AND d_moy = {moy})
  AND i.i_current_price > 1.2 * (SELECT avg(j.i_current_price) FROM item j WHERE j.i_category = i.i_category)
GROUP BY a.ca_state
HAVING count(*) >= 10
ORDER BY cnt NULLS FIRST, a.ca_state NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 12)), derive=MONTH_NAME,
         phrasings=[
             "By customer state, how many store sales in {month_name} {year} were of items priced more than 20% above the average price of their category? Only states with at least 10 such sales; show state and count, smallest count first, then state; 100 rows.",
             "Count store_sales rows per customer's current-address state for {month_name} {year} where the item's current price exceeds 1.2 x the average current price of items in the same category. Keep states with count >= 10, order by count then state (nulls first), limit 100.",
             "Which states had customers buy premium-priced items (current price over 1.2 times their category's average) in stores during {month_name} {year}? Return state and number of such sales, for states with 10 or more, ascending by count and state, first 100.",
             "For {year}, month {moy}: number of in-store purchases of above-category-average-by-20% priced items, grouped by the buyer's current state, having at least 10; columns state, cnt; sorted by cnt, state; 100 max.",
         ]),
    dict(id="t68", qnum=68, complexity="complex",
         sql="""SELECT c_last_name, c_first_name, ca_city, bought_city, ss_ticket_number, extended_price, extended_tax, list_price
FROM (SELECT ss_ticket_number, ss_customer_sk, ca_city bought_city, sum(ss_ext_sales_price) extended_price,
             sum(ss_ext_list_price) list_price, sum(ss_ext_tax) extended_tax
      FROM store_sales, date_dim, store, household_demographics, customer_address
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_store_sk = store.s_store_sk
        AND store_sales.ss_hdemo_sk = household_demographics.hd_demo_sk AND store_sales.ss_addr_sk = customer_address.ca_address_sk
        AND date_dim.d_dom BETWEEN 1 AND 2
        AND (household_demographics.hd_dep_count = {dep_count} OR household_demographics.hd_vehicle_count = 3)
        AND date_dim.d_year IN ({year}, {year}+1, {year}+2) AND store.s_city IN ({cities_sql})
      GROUP BY ss_ticket_number, ss_customer_sk, ss_addr_sk, ca_city) dn,
     customer, customer_address current_addr
WHERE ss_customer_sk = c_customer_sk AND customer.c_current_addr_sk = current_addr.ca_address_sk
  AND current_addr.ca_city <> bought_city
ORDER BY c_last_name NULLS FIRST, ss_ticket_number NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2000), dep_count=("int", 0, 9),
                    cities=("db_sample", "SELECT DISTINCT s_city FROM store WHERE s_city IS NOT NULL", 2)),
         derive=dict(cities_sql=lambda p: _sql_list(p["cities"]), cities_nl=lambda p: _nl_list(p["cities"], "or"),
                     year2=lambda p: str(p["year"] + 2)),
         phrasings=[
             "Find store tickets from the 1st or 2nd day of any month in {year}-{year2}, at stores in {cities_nl}, by households with {dep_count} dependents or 3 vehicles, where the customer's current city differs from the city of the purchase address. Show last name, first name, current city, purchase city, ticket number, and the ticket's total extended sales price, extended tax and extended list price; order by last name then ticket, 100 rows.",
             "Per ticket (ss_ticket_number, customer, ss_addr) for sales on day-of-month 1-2 in years {year} to {year2} at stores whose city is {cities_nl}, with hd_dep_count = {dep_count} or hd_vehicle_count = 3: sum ext sales price, ext list price, ext tax. Join to the customer and their current address, keep rows where current city <> the sale address city, and return c_last_name, c_first_name, ca_city, bought_city, ss_ticket_number, extended_price, extended_tax, list_price sorted by last name, ticket; limit 100.",
             "Which customers shopped away from home? Look at purchases made on the first two days of a month during {year}, {year}+1 or {year2} in {cities_nl} stores, by households having {dep_count} dependents or three vehicles, and list customer last/first name, their current city, the city they bought in, ticket number and the ticket totals of extended price, extended tax and list price, by last name and ticket, first 100.",
             "List c_last_name, c_first_name, current city, bought city, ticket number, extended price, extended tax and list price totals for store tickets on day 1 or 2 of the month between {year} and {year2} at stores located in {cities_nl}, household dep count {dep_count} or vehicle count 3, where the customer now lives in a different city from where the sale address was. Ordered by last name, ticket number; 100 max.",
         ]),
    dict(id="t73", qnum=73, complexity="complex",
         sql="""SELECT c_last_name, c_first_name, c_salutation, c_preferred_cust_flag, ss_ticket_number, cnt
FROM (SELECT ss_ticket_number, ss_customer_sk, count(*) cnt
      FROM store_sales, date_dim, store, household_demographics
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_store_sk = store.s_store_sk
        AND store_sales.ss_hdemo_sk = household_demographics.hd_demo_sk AND date_dim.d_dom BETWEEN 1 AND 2
        AND (household_demographics.hd_buy_potential = 'Unknown' OR household_demographics.hd_buy_potential = '>10000')
        AND household_demographics.hd_vehicle_count > 0
        AND CASE WHEN household_demographics.hd_vehicle_count > 0
                 THEN (household_demographics.hd_dep_count*1.000)/ household_demographics.hd_vehicle_count ELSE NULL END > 1
        AND date_dim.d_year IN ({year}, {year}+1, {year}+2) AND store.s_county IN ({counties_sql})
      GROUP BY ss_ticket_number, ss_customer_sk) dj,
     customer
WHERE ss_customer_sk = c_customer_sk AND cnt BETWEEN 1 AND 5
ORDER BY cnt DESC, c_last_name ASC, ss_ticket_number ASC, ss_customer_sk ASC;""",
         slots=dict(year=("int", 1998, 2000),
                    counties=("db_sample", "SELECT DISTINCT s_county FROM store WHERE s_county IS NOT NULL", 4)),
         derive=dict(counties_sql=lambda p: _sql_list(p["counties"]), counties_nl=lambda p: _nl_list(p["counties"], "or"),
                     year2=lambda p: str(p["year"] + 2)),
         phrasings=[
             "Find store tickets with 1 to 5 line items bought on the 1st or 2nd of a month in {year}-{year2} at stores in {counties_nl}, by households with buy potential 'Unknown' or '>10000' that have at least one vehicle and more dependents than vehicles. Show customer last name, first name, salutation, preferred flag, ticket number and item count, ordered by count descending, last name, ticket, customer sk.",
             "Per (ticket, customer) count store_sales rows on d_dom 1-2 in {year}, {year}+1, {year2} at stores with s_county in ({counties_sql}), where hd_buy_potential is 'Unknown' or '>10000', vehicle count > 0 and dep_count/vehicle_count > 1; keep counts 1-5 and return c_last_name, c_first_name, c_salutation, c_preferred_cust_flag, ss_ticket_number, cnt, sorted by cnt desc, last name, ticket number, customer sk. All rows.",
             "Which customers made small purchases (1-5 items on one ticket) on the first two days of any month between {year} and {year2} in stores located in {counties_nl}, coming from households of unknown or >10000 buying potential with more dependents than (nonzero) vehicles? Give last/first name, salutation, preferred-customer flag, ticket number and number of items; biggest count first, then last name, ticket, customer key.",
             "List c_last_name, c_first_name, salutation, preferred flag, ticket number and line count for tickets of 1 to 5 lines from day 1 or 2 of the month, years {year} through {year2}, store county {counties_nl}, household buy potential Unknown or >10000, vehicles > 0 and dependents per vehicle > 1. Sort by count descending, last name, ticket number, customer sk; no limit.",
         ]),
    dict(id="t79", qnum=79, complexity="complex",
         sql="""SELECT c_last_name, c_first_name, SUBSTRING(s_city,1,30), ss_ticket_number, amt, profit
FROM (SELECT ss_ticket_number, ss_customer_sk, store.s_city, sum(ss_coupon_amt) amt, sum(ss_net_profit) profit
      FROM store_sales, date_dim, store, household_demographics
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_store_sk = store.s_store_sk
        AND store_sales.ss_hdemo_sk = household_demographics.hd_demo_sk
        AND (household_demographics.hd_dep_count = {dep_count} OR household_demographics.hd_vehicle_count > 2)
        AND date_dim.d_dow = {dow} AND date_dim.d_year IN ({year}, {year}+1, {year}+2)
        AND store.s_number_employees BETWEEN 200 AND 295
      GROUP BY ss_ticket_number, ss_customer_sk, ss_addr_sk, store.s_city) ms,
     customer
WHERE ss_customer_sk = c_customer_sk
ORDER BY c_last_name NULLS FIRST, c_first_name NULLS FIRST, SUBSTRING(s_city,1,30) NULLS FIRST, profit NULLS FIRST, ss_ticket_number
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2000), dow=("int", 0, 6), dep_count=("int", 0, 9)),
         derive=dict(dow_name=lambda p: DOW[p["dow"]], year2=lambda p: str(p["year"] + 2)),
         phrasings=[
             "For store tickets bought on {dow_name}s in {year}-{year2} at stores with 200 to 295 employees, by households with {dep_count} dependents or more than 2 vehicles, show customer last name, first name, store city (first 30 characters), ticket number, total coupon amount and total net profit per ticket. Order by last name, first name, city, profit, ticket; 100 rows.",
             "Per ticket (ticket number, customer, sale address, store city) for store sales with d_dow = {dow} ({dow_name}) in years {year}, {year}+1, {year2}, s_number_employees between 200 and 295, and hd_dep_count = {dep_count} or hd_vehicle_count > 2: sum ss_coupon_amt and ss_net_profit; return c_last_name, c_first_name, substring(s_city,1,30), ss_ticket_number, amt, profit, sorted by last name, first name, city, profit, ticket (nulls first); limit 100.",
             "Which customers' {dow_name} shopping trips between {year} and {year2} at mid-size stores (200-295 employees) earned what profit? Only households with {dep_count} dependents or over two vehicles. Give last name, first name, store city truncated to 30 chars, ticket number, coupon amount sum and net profit sum; ordered last, first, city, profit, ticket; first 100.",
             "List customer last/first name, store city (30-char substring), ticket number, summed coupon amount and summed net profit for tickets sold on {dow_name} during {year} through {year2}, at stores employing 200-295 people, from households with dependent count {dep_count} or vehicle count above 2. Sort by last name, first name, city, profit, ticket number; 100 max.",
         ]),
    # ------------------------------------------------------------------ complex
    dict(id="t01", qnum=1, complexity="complex",
         sql="""WITH customer_total_return AS
  (SELECT sr_customer_sk AS ctr_customer_sk, sr_store_sk AS ctr_store_sk, sum(sr_return_amt) AS ctr_total_return
   FROM store_returns, date_dim
   WHERE sr_returned_date_sk = d_date_sk AND d_year = {year}
   GROUP BY sr_customer_sk, sr_store_sk)
SELECT c_customer_id
FROM customer_total_return ctr1, store, customer
WHERE ctr1.ctr_total_return > (SELECT avg(ctr_total_return)*1.2 FROM customer_total_return ctr2
                               WHERE ctr1.ctr_store_sk = ctr2.ctr_store_sk)
  AND s_store_sk = ctr1.ctr_store_sk AND s_state = '{state}' AND ctr1.ctr_customer_sk = c_customer_sk
ORDER BY c_customer_id
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), state=("db", "SELECT DISTINCT s_state FROM store WHERE s_state IS NOT NULL")),
         derive={},
         phrasings=[
             "Which customers returned unusually much to a store in {year}: their total store return amount at that store exceeded 1.2 times the average customer total for the same store? Only stores in {state}. Give customer ids, sorted, first 100.",
             "For {year} store returns, compute each customer's total sr_return_amt per store; list c_customer_id for customer/store pairs where that total is more than 20% above the store's average customer total, restricted to stores in state {state}. Order by customer id, limit 100.",
             "List the ids of customers whose {year} returns at a {state} store totaled over 1.2x the average per-customer return total at that store. Sorted by customer id, 100 rows max.",
             "In {state} stores, find customers with above-normal return totals in {year} (customer's sum of return amount at a store > 1.2 x that store's mean customer sum). Return c_customer_id ascending, top 100.",
         ]),
    dict(id="t27", qnum=27, complexity="complex",
         sql="""WITH results AS
  (SELECT i_item_id, s_state, 0 AS g_state, ss_quantity agg1, ss_list_price agg2, ss_coupon_amt agg3, ss_sales_price agg4
   FROM store_sales, customer_demographics, date_dim, store, item
   WHERE ss_sold_date_sk = d_date_sk AND ss_item_sk = i_item_sk AND ss_store_sk = s_store_sk AND ss_cdemo_sk = cd_demo_sk
     AND cd_gender = 'M' AND cd_marital_status = 'S' AND cd_education_status = '{education}'
     AND d_year = {year} AND s_state = '{state}')
SELECT i_item_id, s_state, g_state, agg1, agg2, agg3, agg4
FROM (SELECT i_item_id, s_state, 0 AS g_state, avg(agg1) agg1, avg(agg2) agg2, avg(agg3) agg3, avg(agg4) agg4
      FROM results GROUP BY i_item_id, s_state
      UNION ALL
      SELECT i_item_id, NULL AS s_state, 1 AS g_state, avg(agg1) agg1, avg(agg2) agg2, avg(agg3) agg3, avg(agg4) agg4
      FROM results GROUP BY i_item_id
      UNION ALL
      SELECT NULL AS i_item_id, NULL AS s_state, 1 AS g_state, avg(agg1) agg1, avg(agg2) agg2, avg(agg3) agg3, avg(agg4) agg4
      FROM results) foo
ORDER BY i_item_id NULLS FIRST, s_state NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), education=("choice", EDUCATION),
                    state=("db", "SELECT DISTINCT s_state FROM store WHERE s_state IS NOT NULL")),
         derive={},
         phrasings=[
             "For {year} store sales in {state} to single male customers with education '{education}', give average quantity, list price, coupon amount and sales price per item and state, plus a subtotal row per item (state null) and a grand total row (item and state null), with a flag g_state = 0 for item+state rows and 1 for the rollup rows. Columns: item id, state, g_state, four averages; order by item id then state, nulls first; 100 rows.",
             "Rollup of average ss_quantity, ss_list_price, ss_coupon_amt, ss_sales_price by (i_item_id, s_state), (i_item_id), and overall, for {year} sales at stores in state {state} where the customer demographic is M / S / '{education}'. Output i_item_id, s_state, g_state (0 detail, 1 rollup), agg1..agg4; sorted by item id, state, nulls first; limit 100.",
             "I want item-level averages (quantity, list price, coupon, sales price) for single men educated '{education}' buying in {state} stores in {year}: one row per item and state with g_state 0, one per item with null state and g_state 1, and an all-items row with nulls and g_state 1. Order by item id and state, nulls first, first 100.",
             "Show i_item_id, s_state, g_state and the averages of quantity, list price, coupon amount and sales price for store purchases in {year} in {state} by unmarried male shoppers with '{education}' education, including per-item rollups and a grand total (g_state = 1 on those). Nulls first, sorted by item then state; 100 max.",
         ]),
    dict(id="t36", qnum=36, complexity="complex",
         sql="""WITH results AS
  (SELECT sum(ss_net_profit) AS ss_net_profit, sum(ss_ext_sales_price) AS ss_ext_sales_price,
          (sum(ss_net_profit)*1.0000)/sum(ss_ext_sales_price) AS gross_margin, i_category, i_class, 0 AS g_category, 0 AS g_class
   FROM store_sales, date_dim d1, item, store
   WHERE d1.d_year = {year} AND d1.d_date_sk = ss_sold_date_sk AND i_item_sk = ss_item_sk AND s_store_sk = ss_store_sk
     AND s_state = '{state}'
   GROUP BY i_category, i_class),
     results_rollup AS
  (SELECT gross_margin, i_category, i_class, 0 AS t_category, 0 AS t_class, 0 AS lochierarchy FROM results
   UNION
   SELECT (sum(ss_net_profit)*1.0000)/sum(ss_ext_sales_price) AS gross_margin, i_category, NULL AS i_class,
          0 AS t_category, 1 AS t_class, 1 AS lochierarchy FROM results GROUP BY i_category
   UNION
   SELECT (sum(ss_net_profit)*1.0000)/sum(ss_ext_sales_price) AS gross_margin, NULL AS i_category, NULL AS i_class,
          1 AS t_category, 1 AS t_class, 2 AS lochierarchy FROM results)
SELECT gross_margin, i_category, i_class, lochierarchy,
       rank() OVER (PARTITION BY lochierarchy, CASE WHEN t_class = 0 THEN i_category END ORDER BY gross_margin ASC) AS rank_within_parent
FROM results_rollup
ORDER BY lochierarchy DESC NULLS FIRST, CASE WHEN lochierarchy = 0 THEN i_category END NULLS FIRST, rank_within_parent NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), state=("db", "SELECT DISTINCT s_state FROM store WHERE s_state IS NOT NULL")),
         derive={},
         phrasings=[
             "Gross margin (net profit / extended sales price) of {year} store sales in {state}, at three levels: per category and class (lochierarchy 0), per category (1), and overall (2). Rank margins ascending within each parent (classes within their category; categories among themselves). Show gross_margin, category, class, lochierarchy, rank; order by lochierarchy descending, then category for class rows, then rank; 100 rows.",
             "For stores in state {state} in {year}, compute sum(ss_net_profit)/sum(ss_ext_sales_price) by (i_category, i_class), by i_category, and in total, with lochierarchy 0/1/2, and rank_within_parent = rank by gross margin ascending partitioned by lochierarchy and (for class rows) category. Output gross_margin, i_category, i_class, lochierarchy, rank_within_parent sorted by lochierarchy desc, category (class level only), rank, nulls first; limit 100.",
             "How profitable was each item category and class in {state} stores during {year}? Give the gross margin hierarchy — overall, per category, per category/class — with a level indicator (2, 1, 0) and the rank of each margin (lowest = 1) among its siblings. Columns margin, category, class, level, rank; top level first, classes grouped by category, by rank; first 100.",
             "Rank {year} store gross margins for {state}: total, category and category+class rollup levels (lochierarchy 2/1/0), margin = net profit over ext sales price, rank ascending within parent. Return gross_margin, i_category, i_class, lochierarchy, rank_within_parent ordered by lochierarchy descending, category for leaf rows, rank; 100 max.",
         ]),
    dict(id="t65", qnum=65, complexity="complex",
         sql="""SELECT s_store_name, i_item_desc, sc.revenue, i_current_price, i_wholesale_cost, i_brand
FROM store, item,
  (SELECT ss_store_sk, avg(revenue) AS ave
   FROM (SELECT ss_store_sk, ss_item_sk, sum(ss_sales_price) AS revenue FROM store_sales, date_dim
         WHERE ss_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq}+11
         GROUP BY ss_store_sk, ss_item_sk) sa
   GROUP BY ss_store_sk) sb,
  (SELECT ss_store_sk, ss_item_sk, sum(ss_sales_price) AS revenue FROM store_sales, date_dim
   WHERE ss_sold_date_sk = d_date_sk AND d_month_seq BETWEEN {mseq} AND {mseq}+11
   GROUP BY ss_store_sk, ss_item_sk) sc
WHERE sb.ss_store_sk = sc.ss_store_sk AND sc.revenue <= 0.1 * sb.ave AND s_store_sk = sc.ss_store_sk
  AND i_item_sk = sc.ss_item_sk
ORDER BY s_store_name NULLS FIRST, i_item_desc NULLS FIRST, s_store_sk NULLS FIRST, i_item_sk NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "Which store/item pairs had {year} revenue (sum of sales price) at or below 10% of that store's average item revenue? Show store name, item description, revenue, current price, wholesale cost and brand, ordered by store name, item description (then store and item keys); 100 rows.",
             "For {year} (12 months), per store and item sum ss_sales_price; list s_store_name, i_item_desc, revenue, i_current_price, i_wholesale_cost, i_brand where the item's revenue <= 0.1 x the average item revenue of the same store. Sort by store name, item desc, store sk, item sk; limit 100.",
             "Find the weakest sellers in each store during {year}: items whose total sales price there was no more than a tenth of the store's average per-item revenue. Give store name, item description, revenue, current price, wholesale cost, brand; by store name and item description, first 100.",
             "List store name, item description, store-item revenue, current price, wholesale cost and brand for items that in {year} earned at most 10 percent of the mean item revenue of their store. Ordered by store name, description, store key, item key; 100 max.",
         ]),
    dict(id="t25", qnum=25, complexity="complex",
         sql="""SELECT i_item_id, i_item_desc, s_store_id, s_store_name, sum(ss_net_profit) AS store_sales_profit,
       sum(sr_net_loss) AS store_returns_loss, sum(cs_net_profit) AS catalog_sales_profit
FROM store_sales, store_returns, catalog_sales, date_dim d1, date_dim d2, date_dim d3, store, item
WHERE d1.d_moy = {moy} AND d1.d_year = {year} AND d1.d_date_sk = ss_sold_date_sk AND i_item_sk = ss_item_sk
  AND s_store_sk = ss_store_sk AND ss_customer_sk = sr_customer_sk AND ss_item_sk = sr_item_sk
  AND ss_ticket_number = sr_ticket_number AND sr_returned_date_sk = d2.d_date_sk AND d2.d_moy BETWEEN {moy} AND {moy_end}
  AND d2.d_year = {year} AND sr_customer_sk = cs_bill_customer_sk AND sr_item_sk = cs_item_sk
  AND cs_sold_date_sk = d3.d_date_sk AND d3.d_moy BETWEEN {moy} AND {moy_end} AND d3.d_year = {year}
GROUP BY i_item_id, i_item_desc, s_store_id, s_store_name
ORDER BY i_item_id, i_item_desc, s_store_id, s_store_name
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 6)),
         derive=dict(moy_end=lambda p: str(p["moy"] + 6), month_name=lambda p: MONTHS[p["moy"] - 1],
                     end_month_name=lambda p: MONTHS[p["moy"] + 5]),
         phrasings=[
             "For items bought in a store in {month_name} {year}, returned by the same customer between {month_name} and {end_month_name} {year}, and then bought by that customer through the catalog in the same {month_name}-{end_month_name} window: per item and store give item id, item description, store id, store name, total store net profit, total return net loss and total catalog net profit. Order by item id, description, store id, store name; 100 rows.",
             "Join store_sales (sold in month {moy} of {year}) to store_returns (same customer, item, ticket; returned in months {moy}-{moy_end} of {year}) to catalog_sales (bill customer and item match the return; sold in months {moy}-{moy_end} of {year}). Group by i_item_id, i_item_desc, s_store_id, s_store_name and sum ss_net_profit, sr_net_loss, cs_net_profit. Sort by the four group columns, limit 100.",
             "Which items did customers buy in store in {month_name} {year}, return by {end_month_name}, and re-purchase from the catalog in that period? Show item id, description, store id, store name, store sales profit, store returns loss and catalog sales profit, ordered by item id, description, store id, store name, first 100.",
             "Per item and store: summed store net profit, return net loss, and catalog net profit, for store purchases in {month_name} {year} that were returned (same ticket) during {month_name}-{end_month_name} {year} and followed by a catalog purchase of the same item by the same customer in that span. Columns item id, item desc, store id, store name and the three sums; by item id, desc, store id, name; 100 max.",
         ]),
    dict(id="t91", qnum=91, complexity="complex",
         sql="""SELECT cc_call_center_id Call_Center, cc_name Call_Center_Name, cc_manager Manager, sum(cr_net_loss) Returns_Loss
FROM call_center, catalog_returns, date_dim, customer, customer_address, customer_demographics, household_demographics
WHERE cr_call_center_sk = cc_call_center_sk AND cr_returned_date_sk = d_date_sk AND cr_returning_customer_sk = c_customer_sk
  AND cd_demo_sk = c_current_cdemo_sk AND hd_demo_sk = c_current_hdemo_sk AND ca_address_sk = c_current_addr_sk
  AND d_year = {year} AND d_moy = {moy}
  AND ((cd_marital_status = 'M' AND cd_education_status = 'Unknown') OR (cd_marital_status = 'W' AND cd_education_status = 'Advanced Degree'))
  AND hd_buy_potential LIKE 'Unknown%' AND ca_gmt_offset = -7
GROUP BY cc_call_center_id, cc_name, cc_manager, cd_marital_status, cd_education_status
ORDER BY sum(cr_net_loss) DESC;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 12)), derive=MONTH_NAME,
         phrasings=[
             "Catalog returns loss by call center for {month_name} {year}: for returning customers whose current demographics are married with unknown education or widowed with an advanced degree, household buy potential starting with 'Unknown', and address GMT offset -7, show call center id, name, manager and total net loss, one row per call center and demographic group, largest loss first.",
             "Sum cr_net_loss grouped by cc_call_center_id, cc_name, cc_manager, cd_marital_status, cd_education_status (output only the first three and the sum) for catalog returns in {year} month {moy} by customers with (marital M and education 'Unknown') or (marital W and education 'Advanced Degree'), hd_buy_potential LIKE 'Unknown%', ca_gmt_offset = -7. Order by the sum descending.",
             "Which call centers lost the most on catalog returns in {month_name} {year} from customers in GMT -7 with unknown buying potential who are either married with unknown education or widowed with advanced degrees? Call center id, name, manager, returns loss, split by those two demographic groups, highest loss first.",
             "For {month_name} of {year}, report Call_Center, Call_Center_Name, Manager and Returns_Loss (sum of catalog return net loss) for returning customers at gmt offset -7, buy potential beginning 'Unknown', and demographics married/Unknown-education or widowed/Advanced Degree; grouped also by marital and education status; sorted by loss descending. All rows.",
         ]),
]

# Dropped after the template check (harness/plancache/check_templates.py, 12 draws x 4 tenants, Nov 7):
EXCLUDED = {"t82": "empty for 67% / 42% / 25% of draws on sf0.5 / sf1 / sf2 (random manufacturer list x price band)",
            "t25": "empty for 25-92% of draws on every tenant (store purchase -> return -> catalog re-purchase chain)",
            "t91": "empty for 58% / 33% of draws on sf0.5 / sf1 (narrow demographic x GMT -7 filter)"}
TEMPLATES = [t for t in _ALL if t["id"] not in EXCLUDED]
BY_ID = {t["id"]: t for t in TEMPLATES}


# ---------------------------------------------------------------------- sampling
_DB_CACHE = {}


def db_values(con, key, sql):
    """Candidate values for a db slot on one tenant (cached by tenant key + sql)."""
    k = (key, sql)
    if k not in _DB_CACHE:
        _DB_CACHE[k] = sorted(r[0] for r in con.execute(sql).fetchall())
    return _DB_CACHE[k]


def draw_params(tpl, rng, con=None, tenant_key=None):
    """Draw slot values (random.Random rng). con/tenant_key needed for db slots."""
    p = {}
    for name, spec in tpl["slots"].items():
        kind = spec[0]
        if kind == "int":
            p[name] = rng.randint(spec[1], spec[2])
        elif kind == "choice":
            p[name] = rng.choice(spec[1])
        elif kind == "sample":
            p[name] = rng.sample(spec[1], spec[2])
        elif kind == "date":
            lo, hi = _dt.date.fromisoformat(spec[1]), _dt.date.fromisoformat(spec[2])
            p[name] = (lo + _dt.timedelta(days=rng.randint(0, (hi - lo).days))).isoformat()
        elif kind == "db":
            p[name] = rng.choice(db_values(con, tenant_key, spec[1]))
        elif kind == "db_sample":
            vals = db_values(con, tenant_key, spec[1])
            p[name] = rng.sample(vals, min(spec[2], len(vals)))
        else:
            raise ValueError(kind)
    return p


def render(tpl, params, phrasing_id):
    """(question, gold_sql) for drawn params."""
    derived = {name: f(params) for name, f in tpl.get("derive", {}).items()}  # SQL fragments, already quoted
    full = {**params, **derived}
    fmt = {**{k: (v.replace("'", "''") if isinstance(v, str) else v) for k, v in params.items()}, **derived}
    sql = tpl["sql"].format(**fmt)
    nl = tpl["phrasings"][phrasing_id].format(**full)
    return nl, sql
