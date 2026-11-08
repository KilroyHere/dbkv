"""Workload W2 templates, TPC-DS part A: the queries numbered 1-50 that are not already in templates.py (31 templates).

Same format as templates.py (see its docstring for the dict keys and slot kinds); every entry also carries
"bench": "tpcds". draw_params / render from templates.py work unchanged on these dicts. Source SQL is DuckDB's
`tpcds_queries()` text, compacted, with the user-facing qualification literals made into {slot}s.

Phrasing convention (4 per template, written as different people would ask):
  0  business-analyst wording, no column names
  1  schema-ish wording (table / column names)
  2  terse request
  3  verbose / conversational
"""
try:
    from .templates import (MONTHS, CATEGORIES, EDUCATION, GENDER, YEARS, _plus_days, _sql_list, _nl_list,
                            _pretty_date, _mseq, MONTH_NAME)
except ImportError:  # imported as a top-level module (sys.path contains harness/plancache)
    from templates import (MONTHS, CATEGORIES, EDUCATION, GENDER, YEARS, _plus_days, _sql_list, _nl_list,
                           _pretty_date, _mseq, MONTH_NAME)

QOY_ORD = {1: "first", 2: "second", 3: "third", 4: "fourth"}
_CA_STATE = "SELECT DISTINCT ca_state FROM customer_address WHERE ca_state IS NOT NULL"
_CA_COUNTY = "SELECT DISTINCT ca_county FROM customer_address WHERE ca_county IS NOT NULL"
_CA_GMT = "SELECT DISTINCT CAST(ca_gmt_offset AS INTEGER) FROM customer_address WHERE ca_gmt_offset IS NOT NULL"
_S_COUNTY = "SELECT DISTINCT s_county FROM store WHERE s_county IS NOT NULL"
_S_CITY = "SELECT DISTINCT s_city FROM store WHERE s_city IS NOT NULL"

# q8's official 400-zip target list (kept fixed; too long to put in a question, so phrasings call it the target list)
_Q8_ZIPS = ("'24128', '76232', '65084', '87816', '83926', '77556', '20548', '26231', '43848', '15126', '91137', "
            "'61265', '98294', '25782', '17920', '18426', '98235', '40081', '84093', '28577', '55565', '17183', "
            "'54601', '67897', '22752', '86284', '18376', '38607', '45200', '21756', '29741', '96765', '23932', "
            "'89360', '29839', '25989', '28898', '91068', '72550', '10390', '18845', '47770', '82636', '41367', "
            "'76638', '86198', '81312', '37126', '39192', '88424', '72175', '81426', '53672', '10445', '42666', "
            "'66864', '66708', '41248', '48583', '82276', '18842', '78890', '49448', '14089', '38122', '34425', "
            "'79077', '19849', '43285', '39861', '66162', '77610', '13695', '99543', '83444', '83041', '12305', "
            "'57665', '68341', '25003', '57834', '62878', '49130', '81096', '18840', '27700', '23470', '50412', "
            "'21195', '16021', '76107', '71954', '68309', '18119', '98359', '64544', '10336', '86379', '27068', "
            "'39736', '98569', '28915', '24206', '56529', '57647', '54917', '42961', '91110', '63981', '14922', "
            "'36420', '23006', '67467', '32754', '30903', '20260', '31671', '51798', '72325', '85816', '68621', "
            "'13955', '36446', '41766', '68806', '16725', '15146', '22744', '35850', '88086', '51649', '18270', "
            "'52867', '39972', '96976', '63792', '11376', '94898', '13595', '10516', '90225', '58943', '39371', "
            "'94945', '28587', '96576', '57855', '28488', '26105', '83933', '25858', '34322', '44438', '73171', "
            "'30122', '34102', '22685', '71256', '78451', '54364', '13354', '45375', '40558', '56458', '28286', "
            "'45266', '47305', '69399', '83921', '26233', '11101', '15371', '69913', '35942', '15882', '25631', "
            "'24610', '44165', '99076', '33786', '70738', '26653', '14328', '72305', '62496', '22152', '10144', "
            "'64147', '48425', '14663', '21076', '18799', '30450', '63089', '81019', '68893', '24996', '51200', "
            "'51211', '45692', '92712', '70466', '79994', '22437', '25280', '38935', '71791', '73134', '56571', "
            "'14060', '19505', '72425', '56575', '74351', '68786', '51650', '20004', '18383', '76614', '11634', "
            "'18906', '15765', '41368', '73241', '76698', '78567', '97189', '28545', '76231', '75691', '22246', "
            "'51061', '90578', '56691', '68014', '51103', '94167', '57047', '14867', '73520', '15734', '63435', "
            "'25733', '35474', '24676', '94627', '53535', '17879', '15559', '53268', '59166', '11928', '59402', "
            "'33282', '45721', '43933', '68101', '33515', '36634', '71286', '19736', '58058', '55253', '67473', "
            "'41918', '19515', '36495', '19430', '22351', '77191', '91393', '49156', '50298', '87501', '18652', "
            "'53179', '18767', '63193', '23968', '65164', '68880', '21286', '72823', '58470', '67301', '13394', "
            "'31016', '70372', '67030', '40604', '24317', '45748', '39127', '26065', '77721', '31029', '31880', "
            "'60576', '24671', '45549', '13376', '50016', '33123', '19769', '22927', '97789', '46081', '72151', "
            "'15723', '46136', '51949', '68100', '96888', '64528', '14171', '79777', '28709', '11489', '25103', "
            "'32213', '78668', '22245', '15798', '27156', '37930', '62971', '21337', '51622', '67853', '10567', "
            "'38415', '15455', '58263', '42029', '60279', '37125', '56240', '88190', '50308', '26859', '64457', "
            "'89091', '82136', '62377', '36233', '63837', '58078', '17043', '30010', '60099', '28810', '98025', "
            "'29178', '87343', '73273', '30469', '64034', '39516', '86057', '21309', '90257', '67875', '40162', "
            "'11356', '73650', '61810', '72013', '30431', '22461', '19512', '13375', '55307', '30625', '83849', "
            "'68908', '26689', '96451', '38193', '46820', '88885', '84935', '69035', '83144', '47537', '56616', "
            "'94983', '48033', '69952', '25486', '61547', '27385', '61860', '58048', '56910', '16807', '17871', "
            "'35258', '31387', '35458', '35576'")

_ALL = [
    # ------------------------------------------------------------------ medium
    dict(id="t08", qnum=8, complexity="medium", bench="tpcds",
         sql="""SELECT s_store_name, sum(ss_net_profit)
FROM store_sales, date_dim, store,
  (SELECT ca_zip FROM
     (SELECT SUBSTRING(ca_zip, 1, 5) ca_zip FROM customer_address
      WHERE SUBSTRING(ca_zip, 1, 5) IN (""" + _Q8_ZIPS + """)
      INTERSECT
      SELECT ca_zip FROM (SELECT SUBSTRING(ca_zip, 1, 5) ca_zip, count(*) cnt FROM customer_address, customer
                          WHERE ca_address_sk = c_current_addr_sk AND c_preferred_cust_flag='Y'
                          GROUP BY ca_zip HAVING count(*) > 10) A1) A2) V1
WHERE ss_store_sk = s_store_sk AND ss_sold_date_sk = d_date_sk AND d_qoy = {qoy} AND d_year = {year}
  AND (SUBSTRING(s_zip, 1, 2) = SUBSTRING(V1.ca_zip, 1, 2))
GROUP BY s_store_name
ORDER BY s_store_name
LIMIT 100;""",
         slots=dict(qoy=("int", 1, 4), year=("int", *YEARS)),
         derive=dict(qoy_ord=lambda p: QOY_ORD[p["qoy"]]),
         notes="the official 400-zip target list stays fixed in the SQL; phrasings refer to it as the target zip list",
         phrasings=[
             "Which stores earned what net profit in Q{qoy} {year} in regions with lots of preferred customers? Only count stores whose zip code shares its first two digits with a zip that is on the standard 400-zip target list and also has more than 10 preferred customers living there. Show store name and total net profit, alphabetical, up to 100 stores.",
             "s_store_name, sum(ss_net_profit) for store_sales with d_qoy = {qoy} and d_year = {year}, where substr(s_zip,1,2) matches substr(V1.ca_zip,1,2) and V1 = (5-digit ca_zip values in the hard-coded target zip list) INTERSECT (5-digit zips of current addresses with more than 10 customers where c_preferred_cust_flag = 'Y'). GROUP BY / ORDER BY s_store_name, LIMIT 100.",
             "Store net profit, {year} Q{qoy}, stores in 2-digit zip areas of target-list zips having >10 preferred customers. Name + profit, by name, 100.",
             "I'd like to know how profitable each store was during the {qoy_ord} quarter of {year}, but only for stores sitting in the same two-digit zip region as one of our target zip codes — meaning a zip from the usual target list that also has more than ten preferred customers on file. Could you list the store name with its summed net profit, sorted by store name, maximum 100?",
         ]),
    dict(id="t09", qnum=9, complexity="medium", bench="tpcds",
         sql="""SELECT CASE WHEN (SELECT count(*) FROM store_sales WHERE ss_quantity BETWEEN 1 AND 20) > {thresh}
            THEN (SELECT avg(ss_ext_discount_amt) FROM store_sales WHERE ss_quantity BETWEEN 1 AND 20)
            ELSE (SELECT avg(ss_net_paid) FROM store_sales WHERE ss_quantity BETWEEN 1 AND 20) END bucket1,
       CASE WHEN (SELECT count(*) FROM store_sales WHERE ss_quantity BETWEEN 21 AND 40) > {thresh}
            THEN (SELECT avg(ss_ext_discount_amt) FROM store_sales WHERE ss_quantity BETWEEN 21 AND 40)
            ELSE (SELECT avg(ss_net_paid) FROM store_sales WHERE ss_quantity BETWEEN 21 AND 40) END bucket2,
       CASE WHEN (SELECT count(*) FROM store_sales WHERE ss_quantity BETWEEN 41 AND 60) > {thresh}
            THEN (SELECT avg(ss_ext_discount_amt) FROM store_sales WHERE ss_quantity BETWEEN 41 AND 60)
            ELSE (SELECT avg(ss_net_paid) FROM store_sales WHERE ss_quantity BETWEEN 41 AND 60) END bucket3,
       CASE WHEN (SELECT count(*) FROM store_sales WHERE ss_quantity BETWEEN 61 AND 80) > {thresh}
            THEN (SELECT avg(ss_ext_discount_amt) FROM store_sales WHERE ss_quantity BETWEEN 61 AND 80)
            ELSE (SELECT avg(ss_net_paid) FROM store_sales WHERE ss_quantity BETWEEN 61 AND 80) END bucket4,
       CASE WHEN (SELECT count(*) FROM store_sales WHERE ss_quantity BETWEEN 81 AND 100) > {thresh}
            THEN (SELECT avg(ss_ext_discount_amt) FROM store_sales WHERE ss_quantity BETWEEN 81 AND 100)
            ELSE (SELECT avg(ss_net_paid) FROM store_sales WHERE ss_quantity BETWEEN 81 AND 100) END bucket5
FROM reason
WHERE r_reason_sk = 1;""",
         slots=dict(thresh=("choice", [10000, 25000, 50000, 75000, 100000, 150000, 250000, 400000, 600000, 800000])),
         derive=dict(thresh_c=lambda p: f"{p['thresh']:,}"),
         notes="official query has five different count thresholds; here one shared threshold slot",
         phrasings=[
             "Split in-store sales into quantity bands of 1-20, 21-40, 41-60, 61-80 and 81-100. For each band, if it contains more than {thresh_c} sales, report the average extended discount; otherwise report the average net paid. Give the five results side by side as bucket1 to bucket5.",
             "For ss_quantity ranges [1,20], [21,40], [41,60], [61,80], [81,100] in store_sales: CASE WHEN count(*) in the range > {thresh} THEN avg(ss_ext_discount_amt) ELSE avg(ss_net_paid) END, returned as columns bucket1..bucket5 (one row, selected from reason where r_reason_sk = 1).",
             "Store sales, 5 quantity buckets of 20 units (1-100): avg ext discount if the bucket has over {thresh} rows, else avg net paid. One row.",
             "Here's a quick one on store sales: group the line items by quantity into five 20-unit bands, starting at 1 and going up to 100. Whenever a band has more than {thresh_c} rows I want the mean extended discount amount for it, and when it doesn't, the mean net paid instead. Just one row back please, with the five numbers labeled bucket1 through bucket5.",
         ]),
    dict(id="t10", qnum=10, complexity="medium", bench="tpcds",
         sql="""SELECT cd_gender, cd_marital_status, cd_education_status, count(*) cnt1, cd_purchase_estimate, count(*) cnt2,
       cd_credit_rating, count(*) cnt3, cd_dep_count, count(*) cnt4, cd_dep_employed_count, count(*) cnt5,
       cd_dep_college_count, count(*) cnt6
FROM customer c, customer_address ca, customer_demographics
WHERE c.c_current_addr_sk = ca.ca_address_sk AND ca_county IN ({counties_sql}) AND cd_demo_sk = c.c_current_cdemo_sk
  AND EXISTS (SELECT * FROM store_sales, date_dim WHERE c.c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk
              AND d_year = {year} AND d_moy BETWEEN {moy} AND {moy}+3)
  AND (EXISTS (SELECT * FROM web_sales, date_dim WHERE c.c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk
               AND d_year = {year} AND d_moy BETWEEN {moy} AND {moy}+3)
       OR EXISTS (SELECT * FROM catalog_sales, date_dim WHERE c.c_customer_sk = cs_ship_customer_sk AND cs_sold_date_sk = d_date_sk
                  AND d_year = {year} AND d_moy BETWEEN {moy} AND {moy}+3))
GROUP BY cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating, cd_dep_count,
         cd_dep_employed_count, cd_dep_college_count
ORDER BY cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating, cd_dep_count,
         cd_dep_employed_count, cd_dep_college_count
LIMIT 100;""",
         slots=dict(counties=("db_sample", _CA_COUNTY, 5), year=("int", *YEARS), moy=("int", 1, 9)),
         derive=dict(counties_sql=lambda p: _sql_list(p["counties"]), counties_nl=lambda p: _nl_list(p["counties"], "or"),
                     moy_end=lambda p: str(p["moy"] + 3), month_name=lambda p: MONTHS[p["moy"] - 1],
                     end_month_name=lambda p: MONTHS[p["moy"] + 2]),
         phrasings=[
             "Profile customers living in {counties_nl} who bought in a store between {month_name} and {end_month_name} {year} and, in the same months, also bought online or had a catalog order shipped to them. Count them by gender, marital status, education, purchase estimate, credit rating, number of dependents, employed dependents and dependents in college, with the count repeated after education and after each of the next five attributes. Sort by the eight attributes; 100 rows.",
             "Group customers (current ca_county in {counties_nl}) by cd_gender, cd_marital_status, cd_education_status, cd_purchase_estimate, cd_credit_rating, cd_dep_count, cd_dep_employed_count, cd_dep_college_count of c_current_cdemo_sk, keeping those with a store_sales row in d_year {year}, d_moy {moy}..{moy_end} AND (a web_sales row as ws_bill_customer or a catalog_sales row as cs_ship_customer in that window). Output the columns interleaved with count(*) as cnt1..cnt6; ORDER BY the eight cd_ columns; LIMIT 100.",
             "Demographic counts (gender, marital, education, purchase estimate, credit, dep / employed / college counts) for {counties_nl} residents who shopped in store plus web-or-catalog, months {moy}-{moy_end} of {year}. Sorted, 100.",
             "I want to understand who our cross-channel shoppers are in a few counties: {counties_nl}. Take customers whose current address is in one of those, who made at least one store purchase from {month_name} through {end_month_name} {year}, and who in that same stretch either bought on the web or received a catalog shipment. Then bucket them by their demographic profile — gender, marital status, education, purchase estimate, credit rating, dependents, employed dependents, college dependents — and show the head count next to each of the last six fields. Order by the profile fields and give me the first 100.",
         ]),
    dict(id="t13", qnum=13, complexity="medium", bench="tpcds",
         sql="""SELECT avg(ss_quantity) avg1, avg(ss_ext_sales_price) avg2, avg(ss_ext_wholesale_cost) avg3, sum(ss_ext_wholesale_cost)
FROM store_sales, store, customer_demographics, household_demographics, customer_address, date_dim
WHERE s_store_sk = ss_store_sk AND ss_sold_date_sk = d_date_sk AND d_year = {year}
  AND ((ss_hdemo_sk=hd_demo_sk AND cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'M' AND cd_education_status = 'Advanced Degree'
        AND ss_sales_price BETWEEN 100.00 AND 150.00 AND hd_dep_count = 3)
    OR (ss_hdemo_sk=hd_demo_sk AND cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'S' AND cd_education_status = 'College'
        AND ss_sales_price BETWEEN 50.00 AND 100.00 AND hd_dep_count = 1)
    OR (ss_hdemo_sk=hd_demo_sk AND cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'W' AND cd_education_status = '2 yr Degree'
        AND ss_sales_price BETWEEN 150.00 AND 200.00 AND hd_dep_count = 1))
  AND ((ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('TX', 'OH', 'TX') AND ss_net_profit BETWEEN 100 AND 200)
    OR (ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('OR', 'NM', 'KY') AND ss_net_profit BETWEEN 150 AND 300)
    OR (ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('VA', 'TX', 'MS') AND ss_net_profit BETWEEN 50 AND 250));""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "For {year} store sales, what were the average quantity, average extended sales price, average extended wholesale cost and total extended wholesale cost? Count a sale only if the shopper fits one of three profiles — married, advanced degree, 3 dependents, unit price $100-150; single, college, 1 dependent, $50-100; widowed, 2-year degree, 1 dependent, $150-200 — and the US sale address and profit fit one of: Texas or Ohio with net profit 100-200; Oregon, New Mexico or Kentucky with 150-300; Virginia, Texas or Mississippi with 50-250. One row.",
             "avg(ss_quantity), avg(ss_ext_sales_price), avg(ss_ext_wholesale_cost), sum(ss_ext_wholesale_cost) over store_sales with d_year = {year}, where (cd_marital_status, cd_education_status, ss_sales_price range, hd_dep_count) is ('M', 'Advanced Degree', 100-150, 3) or ('S', 'College', 50-100, 1) or ('W', '2 yr Degree', 150-200, 1), and the ss_addr_sk address has ca_country = 'United States' with (ca_state IN (TX, OH) and ss_net_profit 100-200) or (IN (OR, NM, KY) and 150-300) or (IN (VA, TX, MS) and 50-250).",
             "{year} store sales: avg qty, avg ext sales price, avg ext wholesale cost, sum ext wholesale cost. Demo groups M/Advanced Degree/3 deps/$100-150 | S/College/1 dep/$50-100 | W/2 yr Degree/1 dep/$150-200; US states TX,OH profit 100-200 | OR,NM,KY 150-300 | VA,TX,MS 50-250.",
             "Could you work out four numbers for in-store sales during {year}: the average quantity, the average extended sales price, the average extended wholesale cost, and the summed extended wholesale cost? A sale should count only when the buyer is either married with an advanced degree and three dependents paying 100 to 150 per unit, or single with a college education and one dependent paying 50 to 100, or widowed with a 2 yr degree and one dependent paying 150 to 200 — and, on top of that, the sale's address is in the United States and is either in TX/OH with profit between 100 and 200, in OR/NM/KY with profit between 150 and 300, or in VA/TX/MS with profit between 50 and 250.",
         ]),
    dict(id="t16", qnum=16, complexity="medium", bench="tpcds",
         sql="""SELECT count(DISTINCT cs_order_number) AS "order count", sum(cs_ext_ship_cost) AS "total shipping cost",
       sum(cs_net_profit) AS "total net profit"
FROM catalog_sales cs1, date_dim, customer_address, call_center
WHERE d_date BETWEEN '{start}' AND cast('{end}' AS date) AND cs1.cs_ship_date_sk = d_date_sk
  AND cs1.cs_ship_addr_sk = ca_address_sk AND ca_state = '{state}' AND cs1.cs_call_center_sk = cc_call_center_sk
  AND cc_county = '{county}'
  AND EXISTS (SELECT * FROM catalog_sales cs2 WHERE cs1.cs_order_number = cs2.cs_order_number AND cs1.cs_warehouse_sk <> cs2.cs_warehouse_sk)
  AND NOT EXISTS (SELECT * FROM catalog_returns cr1 WHERE cs1.cs_order_number = cr1.cr_order_number)
ORDER BY count(DISTINCT cs_order_number)
LIMIT 100;""",
         slots=dict(start=("date", "1999-02-01", "2002-10-31"), state=("db", _CA_STATE),
                    county=("db", "SELECT DISTINCT cc_county FROM call_center WHERE cc_county IS NOT NULL")),
         derive=dict(end=lambda p: _plus_days(p["start"], 60), start_nl=lambda p: _pretty_date(p["start"]),
                     end_nl=lambda p: _pretty_date(_plus_days(p["start"], 60))),
         phrasings=[
             "How many catalog orders shipped between {start} and {end} to customers in {state}, through call centers in {county}, were fulfilled from more than one warehouse and never returned? Give the number of distinct orders, their total shipping cost and total net profit.",
             "count(DISTINCT cs_order_number), sum(cs_ext_ship_cost), sum(cs_net_profit) from catalog_sales where the ship date is in {start}..{end}, ship-to ca_state = '{state}', call_center.cc_county = '{county}', some other row of the same order has a different cs_warehouse_sk, and the order has no catalog_returns rows.",
             "Unreturned multi-warehouse catalog orders shipped {start_nl}-{end_nl} to {state}, call center county {county}: order count, total ship cost, total net profit.",
             "I'm digging into split shipments. Take catalog orders that shipped from {start_nl} to {end_nl} to an address in {state}, handled by a call center in {county}. I only care about orders where the items came out of at least two different warehouses and where nothing on the order was ever returned. For those, can you tell me how many distinct orders there are, the total extended shipping cost, and the total net profit?",
         ]),
    dict(id="t28", qnum=28, complexity="medium", bench="tpcds",
         sql="""SELECT *
FROM (SELECT avg(ss_list_price) B1_LP, count(ss_list_price) B1_CNT, count(DISTINCT ss_list_price) B1_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 0 AND 5 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B1,
     (SELECT avg(ss_list_price) B2_LP, count(ss_list_price) B2_CNT, count(DISTINCT ss_list_price) B2_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 6 AND 10 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B2,
     (SELECT avg(ss_list_price) B3_LP, count(ss_list_price) B3_CNT, count(DISTINCT ss_list_price) B3_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 11 AND 15 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B3,
     (SELECT avg(ss_list_price) B4_LP, count(ss_list_price) B4_CNT, count(DISTINCT ss_list_price) B4_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 16 AND 20 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B4,
     (SELECT avg(ss_list_price) B5_LP, count(ss_list_price) B5_CNT, count(DISTINCT ss_list_price) B5_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 21 AND 25 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B5,
     (SELECT avg(ss_list_price) B6_LP, count(ss_list_price) B6_CNT, count(DISTINCT ss_list_price) B6_CNTD FROM store_sales
      WHERE ss_quantity BETWEEN 26 AND 30 AND (ss_list_price BETWEEN {lp} AND {lp}+10 OR ss_coupon_amt BETWEEN {cp} AND {cp}+1000 OR ss_wholesale_cost BETWEEN {wc} AND {wc}+20)) B6
LIMIT 100;""",
         slots=dict(lp=("int", 0, 190), cp=("int", 0, 17000), wc=("int", 0, 80)),
         derive=dict(lp_hi=lambda p: str(p["lp"] + 10), cp_hi=lambda p: str(p["cp"] + 1000), wc_hi=lambda p: str(p["wc"] + 20)),
         notes="official query has separate list-price/coupon/wholesale bounds per bucket; here one shared set of 3 slots",
         phrasings=[
             "Across six store-sale quantity bands (0-5, 6-10, 11-15, 16-20, 21-25, 26-30), considering only sales with a list price of {lp}-{lp_hi}, or a coupon of {cp}-{cp_hi}, or a wholesale cost of {wc}-{wc_hi}: what is each band's average list price, number of list prices and number of distinct list prices? Return all 18 figures in one row (B1_LP, B1_CNT, B1_CNTD, ... B6_CNTD).",
             "For store_sales rows with (ss_list_price BETWEEN {lp} AND {lp_hi} OR ss_coupon_amt BETWEEN {cp} AND {cp_hi} OR ss_wholesale_cost BETWEEN {wc} AND {wc_hi}), compute avg(ss_list_price), count(ss_list_price), count(DISTINCT ss_list_price) for ss_quantity in 0-5, 6-10, 11-15, 16-20, 21-25, 26-30, as one row B1_LP, B1_CNT, B1_CNTD through B6_LP, B6_CNT, B6_CNTD.",
             "Store list price avg / count / distinct count per quantity band 0-5, 6-10, ..., 26-30; filter list price {lp}-{lp_hi} or coupon {cp}-{cp_hi} or wholesale {wc}-{wc_hi}. Single row.",
             "I'm trying to understand list-price spread by basket size in stores. Please look at sales where the list price is between {lp} and {lp_hi}, or the coupon amount is between {cp} and {cp_hi}, or the wholesale cost is between {wc} and {wc_hi}. Split them into six quantity bands — 0 to 5, 6 to 10, 11 to 15, 16 to 20, 21 to 25 and 26 to 30 — and for each band give me the average list price, how many list prices there are, and how many distinct ones, all laid out in a single row.",
         ]),
    dict(id="t35", qnum=35, complexity="medium", bench="tpcds",
         sql="""SELECT ca_state, cd_gender, cd_marital_status, cd_dep_count, count(*) cnt1, min(cd_dep_count) min1, max(cd_dep_count) max1,
       avg(cd_dep_count) avg1, cd_dep_employed_count, count(*) cnt2, min(cd_dep_employed_count) min2,
       max(cd_dep_employed_count) max2, avg(cd_dep_employed_count) avg2, cd_dep_college_count, count(*) cnt3,
       min(cd_dep_college_count), max(cd_dep_college_count), avg(cd_dep_college_count)
FROM customer c, customer_address ca, customer_demographics
WHERE c.c_current_addr_sk = ca.ca_address_sk AND cd_demo_sk = c.c_current_cdemo_sk
  AND EXISTS (SELECT * FROM store_sales, date_dim WHERE c.c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk
              AND d_year = {year} AND d_qoy < 4)
  AND (EXISTS (SELECT * FROM web_sales, date_dim WHERE c.c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk
               AND d_year = {year} AND d_qoy < 4)
       OR EXISTS (SELECT * FROM catalog_sales, date_dim WHERE c.c_customer_sk = cs_ship_customer_sk AND cs_sold_date_sk = d_date_sk
                  AND d_year = {year} AND d_qoy < 4))
GROUP BY ca_state, cd_gender, cd_marital_status, cd_dep_count, cd_dep_employed_count, cd_dep_college_count
ORDER BY ca_state NULLS FIRST, cd_gender NULLS FIRST, cd_marital_status NULLS FIRST, cd_dep_count NULLS FIRST,
         cd_dep_employed_count NULLS FIRST, cd_dep_college_count NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "For customers who bought in a store during the first three quarters of {year} and also bought on the web or through a catalog shipment in that period, group by home state, gender, marital status, dependents, employed dependents and college dependents. For each of the three dependent measures show the value, the group count, and its min, max and average. Order by state, gender, marital status and the three dependent counts; 100 rows.",
             "Customers with a store_sales row in d_year {year} with d_qoy < 4, and a web_sales (ws_bill_customer_sk) or catalog_sales (cs_ship_customer_sk) row under the same date condition: GROUP BY ca_state, cd_gender, cd_marital_status, cd_dep_count, cd_dep_employed_count, cd_dep_college_count; select each dependent column followed by count(*), min, max, avg of it. ORDER BY the six group columns nulls first; LIMIT 100.",
             "Q1-Q3 {year} store + (web or catalog) customers: count and min/max/avg of dep, employed-dep and college-dep counts by state, gender, marital status and those counts. Sorted, 100.",
             "I want a demographic summary of multi-channel customers for {year}, looking only at January through September. A customer qualifies if they made a store purchase in that window and either a web purchase or a catalog order shipped to them in it too. Break them out by current state, gender, marital status, and their dependent, employed-dependent and college-dependent counts; next to each of those three counts show how many customers there are plus the min, max and mean. Sort by state, gender, marital status, then the three counts, and keep the first 100 rows.",
         ]),
    dict(id="t37", qnum=37, complexity="medium", bench="tpcds",
         sql="""SELECT i_item_id, i_item_desc, i_current_price
FROM item, inventory, date_dim, catalog_sales
WHERE i_current_price BETWEEN {price} AND {price} + 30 AND inv_item_sk = i_item_sk AND d_date_sk=inv_date_sk
  AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date)
  AND i_manufact_id IN ({manus_sql}) AND inv_quantity_on_hand BETWEEN 100 AND 500 AND cs_item_sk = i_item_sk
GROUP BY i_item_id, i_item_desc, i_current_price
ORDER BY i_item_id
LIMIT 100;""",
         slots=dict(price=("int", 10, 70), manus=("sample", list(range(1, 1001)), 4),
                    start=("date", "1998-01-01", "2002-10-15")),
         derive=dict(manus_sql=lambda p: ", ".join(map(str, p["manus"])), manus_nl=lambda p: _nl_list(p["manus"], "or"),
                     end=lambda p: _plus_days(p["start"], 60), price_hi=lambda p: str(p["price"] + 30),
                     start_nl=lambda p: _pretty_date(p["start"]), end_nl=lambda p: _pretty_date(_plus_days(p["start"], 60))),
         notes="same shape as t82 (catalog instead of store); 4 random manufacturer ids, empty results likely common",
         phrasings=[
             "Which catalog-sold items from manufacturers {manus_nl}, currently priced between ${price} and ${price_hi}, had between 100 and 500 units on hand in inventory at some point from {start_nl} to {end_nl}? List item id, description and current price, by item id, up to 100.",
             "Distinct i_item_id, i_item_desc, i_current_price for items with i_current_price BETWEEN {price} AND {price_hi}, i_manufact_id IN ({manus_sql}), an inventory row with d_date in [{start}, {end}] and inv_quantity_on_hand BETWEEN 100 AND 500, and at least one catalog_sales row. ORDER BY i_item_id LIMIT 100.",
             "Items (id, desc, price) priced {price}-{price_hi}, manufacturer {manus_nl}, inventory 100-500 sometime {start}..{end}, sold via catalog. By id, 100.",
             "I'm hunting for mid-stock catalog items. Could you find items made by manufacturer {manus_nl} whose current price falls between {price} and {price_hi}, that had somewhere between 100 and 500 units in inventory on at least one day between {start} and {end}, and that have shown up in catalog sales? Just give me each item's id, description and current price once, sorted by item id, first 100.",
         ]),
    dict(id="t41", qnum=41, complexity="medium", bench="tpcds",
         sql="""SELECT distinct(i_product_name)
FROM item i1
WHERE i_manufact_id BETWEEN {manufact_lo} AND {manufact_lo}+40
  AND (SELECT count(*) AS item_cnt FROM item
       WHERE (i_manufact = i1.i_manufact
              AND ((i_category = 'Women' AND (i_color = 'powder' OR i_color = 'khaki') AND (i_units = 'Ounce' OR i_units = 'Oz') AND (i_size = 'medium' OR i_size = 'extra large'))
                OR (i_category = 'Women' AND (i_color = 'brown' OR i_color = 'honeydew') AND (i_units = 'Bunch' OR i_units = 'Ton') AND (i_size = 'N/A' OR i_size = 'small'))
                OR (i_category = 'Men' AND (i_color = 'floral' OR i_color = 'deep') AND (i_units = 'N/A' OR i_units = 'Dozen') AND (i_size = 'petite' OR i_size = 'large'))
                OR (i_category = 'Men' AND (i_color = 'light' OR i_color = 'cornflower') AND (i_units = 'Box' OR i_units = 'Pound') AND (i_size = 'medium' OR i_size = 'extra large'))))
          OR (i_manufact = i1.i_manufact
              AND ((i_category = 'Women' AND (i_color = 'midnight' OR i_color = 'snow') AND (i_units = 'Pallet' OR i_units = 'Gross') AND (i_size = 'medium' OR i_size = 'extra large'))
                OR (i_category = 'Women' AND (i_color = 'cyan' OR i_color = 'papaya') AND (i_units = 'Cup' OR i_units = 'Dram') AND (i_size = 'N/A' OR i_size = 'small'))
                OR (i_category = 'Men' AND (i_color = 'orange' OR i_color = 'frosted') AND (i_units = 'Each' OR i_units = 'Tbl') AND (i_size = 'petite' OR i_size = 'large'))
                OR (i_category = 'Men' AND (i_color = 'forest' OR i_color = 'ghost') AND (i_units = 'Lb' OR i_units = 'Bundle') AND (i_size = 'medium' OR i_size = 'extra large'))))) > 0
ORDER BY i_product_name
LIMIT 100;""",
         slots=dict(manufact_lo=("int", 1, 960)), derive=dict(manufact_hi=lambda p: str(p["manufact_lo"] + 40)),
         notes="the eight color/units/size profiles are fixed (official literals); only the manufacturer-id window varies",
         phrasings=[
             "List the distinct product names of items with manufacturer id between {manufact_lo} and {manufact_hi} whose manufacturer also makes at least one item in any of these profiles: Women's powder or khaki in Ounce/Oz, medium or extra large; Women's brown or honeydew in Bunch/Ton, N/A or small; Men's floral or deep in N/A/Dozen, petite or large; Men's light or cornflower in Box/Pound, medium or extra large; Women's midnight or snow in Pallet/Gross, medium or extra large; Women's cyan or papaya in Cup/Dram, N/A or small; Men's orange or frosted in Each/Tbl, petite or large; Men's forest or ghost in Lb/Bundle, medium or extra large. Alphabetical, 100 max.",
             "SELECT DISTINCT i_product_name from item i1 where i_manufact_id BETWEEN {manufact_lo} AND {manufact_hi} and some item with the same i_manufact matches one of (i_category, i_color set, i_units set, i_size set): (Women, powder|khaki, Ounce|Oz, medium|extra large), (Women, brown|honeydew, Bunch|Ton, N/A|small), (Men, floral|deep, N/A|Dozen, petite|large), (Men, light|cornflower, Box|Pound, medium|extra large), (Women, midnight|snow, Pallet|Gross, medium|extra large), (Women, cyan|papaya, Cup|Dram, N/A|small), (Men, orange|frosted, Each|Tbl, petite|large), (Men, forest|ghost, Lb|Bundle, medium|extra large). ORDER BY i_product_name LIMIT 100.",
             "Product names, manufact id {manufact_lo}-{manufact_hi}, where the same manufacturer has an item matching: W powder/khaki Ounce/Oz med/XL; W brown/honeydew Bunch/Ton N/A/small; M floral/deep N/A/Dozen petite/large; M light/cornflower Box/Pound med/XL; W midnight/snow Pallet/Gross med/XL; W cyan/papaya Cup/Dram N/A/small; M orange/frosted Each/Tbl petite/large; M forest/ghost Lb/Bundle med/XL. Distinct, sorted, 100.",
             "This one's a bit fiddly. I need the unique product names for items whose manufacturer id is in the {manufact_lo} to {manufact_hi} range, but only if that item's manufacturer (by manufacturer name) also produces something matching one of eight specs. In Women's: powder or khaki colored, sold by the Ounce or Oz, size medium or extra large; brown or honeydew, Bunch or Ton, size N/A or small; midnight or snow, Pallet or Gross, medium or extra large; cyan or papaya, Cup or Dram, N/A or small. In Men's: floral or deep, N/A or Dozen units, petite or large; light or cornflower, Box or Pound, medium or extra large; orange or frosted, Each or Tbl, petite or large; forest or ghost, Lb or Bundle, medium or extra large. Sort the names alphabetically and stop at 100.",
         ]),
    dict(id="t48", qnum=48, complexity="medium", bench="tpcds",
         sql="""SELECT SUM (ss_quantity)
FROM store_sales, store, customer_demographics, customer_address, date_dim
WHERE s_store_sk = ss_store_sk AND ss_sold_date_sk = d_date_sk AND d_year = {year}
  AND ((cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'M' AND cd_education_status = '4 yr Degree' AND ss_sales_price BETWEEN 100.00 AND 150.00)
    OR (cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'D' AND cd_education_status = '2 yr Degree' AND ss_sales_price BETWEEN 50.00 AND 100.00)
    OR (cd_demo_sk = ss_cdemo_sk AND cd_marital_status = 'S' AND cd_education_status = 'College' AND ss_sales_price BETWEEN 150.00 AND 200.00))
  AND ((ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('CO', 'OH', 'TX') AND ss_net_profit BETWEEN 0 AND 2000)
    OR (ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('OR', 'MN', 'KY') AND ss_net_profit BETWEEN 150 AND 3000)
    OR (ss_addr_sk = ca_address_sk AND ca_country = 'United States' AND ca_state IN ('VA', 'CA', 'MS') AND ss_net_profit BETWEEN 50 AND 25000));""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "How many units were sold in stores in {year} to three customer groups — married with a 4-year degree paying $100-150 per unit, divorced with a 2-year degree paying $50-100, single with college paying $150-200 — where the sale address is in the US and is in Colorado, Ohio or Texas with net profit 0-2000, Oregon, Minnesota or Kentucky with 150-3000, or Virginia, California or Mississippi with 50-25000? Total quantity only.",
             "SUM(ss_quantity) for store_sales in d_year {year} where (cd_marital_status, cd_education_status, ss_sales_price) is in ('M', '4 yr Degree', 100-150), ('D', '2 yr Degree', 50-100) or ('S', 'College', 150-200), and the sale's ca_country = 'United States' with ca_state IN (CO, OH, TX) and ss_net_profit 0-2000, or IN (OR, MN, KY) and 150-3000, or IN (VA, CA, MS) and 50-25000.",
             "Total store quantity {year}: M/4 yr Degree $100-150, D/2 yr Degree $50-100, S/College $150-200; US CO,OH,TX profit 0-2000 | OR,MN,KY 150-3000 | VA,CA,MS 50-25000.",
             "Can you give me the total number of units sold in our stores during {year}, but only for sales that meet two tests? First, the buyer is married with a 4 yr degree and paid between 100 and 150, divorced with a 2 yr degree and paid 50 to 100, or single with a college education and paid 150 to 200. Second, the sale's address is in the United States and either in CO, OH or TX with a net profit from 0 to 2000, in OR, MN or KY with profit from 150 to 3000, or in VA, CA or MS with profit from 50 to 25000.",
         ]),
    # ------------------------------------------------------------------ complex
    dict(id="t02", qnum=2, complexity="complex", bench="tpcds",
         sql="""WITH wscs AS
  (SELECT sold_date_sk, sales_price
   FROM (SELECT ws_sold_date_sk sold_date_sk, ws_ext_sales_price sales_price FROM web_sales
         UNION ALL
         SELECT cs_sold_date_sk sold_date_sk, cs_ext_sales_price sales_price FROM catalog_sales) sq1),
     wswscs AS
  (SELECT d_week_seq,
          sum(CASE WHEN (d_day_name='Sunday') THEN sales_price ELSE NULL END) sun_sales,
          sum(CASE WHEN (d_day_name='Monday') THEN sales_price ELSE NULL END) mon_sales,
          sum(CASE WHEN (d_day_name='Tuesday') THEN sales_price ELSE NULL END) tue_sales,
          sum(CASE WHEN (d_day_name='Wednesday') THEN sales_price ELSE NULL END) wed_sales,
          sum(CASE WHEN (d_day_name='Thursday') THEN sales_price ELSE NULL END) thu_sales,
          sum(CASE WHEN (d_day_name='Friday') THEN sales_price ELSE NULL END) fri_sales,
          sum(CASE WHEN (d_day_name='Saturday') THEN sales_price ELSE NULL END) sat_sales
   FROM wscs, date_dim
   WHERE d_date_sk = sold_date_sk
   GROUP BY d_week_seq)
SELECT d_week_seq1, round(sun_sales1/sun_sales2, 2) r1, round(mon_sales1/mon_sales2, 2) r2, round(tue_sales1/tue_sales2, 2) r3,
       round(wed_sales1/wed_sales2, 2) r4, round(thu_sales1/thu_sales2, 2) r5, round(fri_sales1/fri_sales2, 2) r6,
       round(sat_sales1/sat_sales2, 2)
FROM (SELECT wswscs.d_week_seq d_week_seq1, sun_sales sun_sales1, mon_sales mon_sales1, tue_sales tue_sales1, wed_sales wed_sales1,
             thu_sales thu_sales1, fri_sales fri_sales1, sat_sales sat_sales1
      FROM wswscs, date_dim WHERE date_dim.d_week_seq = wswscs.d_week_seq AND d_year = {year}) y,
     (SELECT wswscs.d_week_seq d_week_seq2, sun_sales sun_sales2, mon_sales mon_sales2, tue_sales tue_sales2, wed_sales wed_sales2,
             thu_sales thu_sales2, fri_sales fri_sales2, sat_sales sat_sales2
      FROM wswscs, date_dim WHERE date_dim.d_week_seq = wswscs.d_week_seq AND d_year = {year}+1) z
WHERE d_week_seq1 = d_week_seq2-53
ORDER BY d_week_seq1 NULLS FIRST;""",
         slots=dict(year=("int", 1998, 2001)), derive=dict(year2=lambda p: str(p["year"] + 1)),
         phrasings=[
             "How did web-plus-catalog revenue for each day of the week compare between {year} and the following year? For every week of {year}, divide that week's Sunday, Monday, ... Saturday sales (extended sales price) by the sales on the same weekday 53 weeks later in {year2}, rounded to two decimals. One row per week: week sequence and the seven ratios, ordered by week.",
             "Union ws_ext_sales_price and cs_ext_sales_price, sum per d_week_seq split by d_day_name (Sunday..Saturday). Join weeks belonging to d_year {year} to d_week_seq + 53 in d_year {year2} and output d_week_seq1 plus round(day_{year} / day_{year2}, 2) for the seven weekdays (r1..r7), ORDER BY d_week_seq1 NULLS FIRST.",
             "Weekly web+catalog sales ratio {year} vs {year2} (week+53), per weekday Sun-Sat, 2 dp, by week seq.",
             "I'm curious how each weekday held up from {year} to {year2} for our non-store channels. Could you combine web and catalog extended sales, total them by week and by day of week, and then for each week in {year} divide each day's total by the same day in the week 53 weeks later? I'd like the week sequence number and the seven rounded ratios, Sunday first, sorted by week.",
         ]),
    dict(id="t04", qnum=4, complexity="complex", bench="tpcds",
         sql="""WITH year_total AS
  (SELECT c_customer_id customer_id, c_first_name customer_first_name, c_last_name customer_last_name,
          c_preferred_cust_flag customer_preferred_cust_flag, c_birth_country customer_birth_country, c_login customer_login,
          c_email_address customer_email_address, d_year dyear,
          sum(((ss_ext_list_price-ss_ext_wholesale_cost-ss_ext_discount_amt)+ss_ext_sales_price)/2) year_total, 's' sale_type
   FROM customer, store_sales, date_dim
   WHERE c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk
   GROUP BY c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year
   UNION ALL
   SELECT c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year,
          sum((((cs_ext_list_price-cs_ext_wholesale_cost-cs_ext_discount_amt)+cs_ext_sales_price)/2)), 'c'
   FROM customer, catalog_sales, date_dim
   WHERE c_customer_sk = cs_bill_customer_sk AND cs_sold_date_sk = d_date_sk
   GROUP BY c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year
   UNION ALL
   SELECT c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year,
          sum((((ws_ext_list_price-ws_ext_wholesale_cost-ws_ext_discount_amt)+ws_ext_sales_price)/2)), 'w'
   FROM customer, web_sales, date_dim
   WHERE c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk
   GROUP BY c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year)
SELECT t_s_secyear.customer_id, t_s_secyear.customer_first_name, t_s_secyear.customer_last_name, t_s_secyear.customer_preferred_cust_flag
FROM year_total t_s_firstyear, year_total t_s_secyear, year_total t_c_firstyear, year_total t_c_secyear,
     year_total t_w_firstyear, year_total t_w_secyear
WHERE t_s_secyear.customer_id = t_s_firstyear.customer_id AND t_s_firstyear.customer_id = t_c_secyear.customer_id
  AND t_s_firstyear.customer_id = t_c_firstyear.customer_id AND t_s_firstyear.customer_id = t_w_firstyear.customer_id
  AND t_s_firstyear.customer_id = t_w_secyear.customer_id
  AND t_s_firstyear.sale_type = 's' AND t_c_firstyear.sale_type = 'c' AND t_w_firstyear.sale_type = 'w'
  AND t_s_secyear.sale_type = 's' AND t_c_secyear.sale_type = 'c' AND t_w_secyear.sale_type = 'w'
  AND t_s_firstyear.dyear = {year} AND t_s_secyear.dyear = {year}+1 AND t_c_firstyear.dyear = {year}
  AND t_c_secyear.dyear = {year}+1 AND t_w_firstyear.dyear = {year} AND t_w_secyear.dyear = {year}+1
  AND t_s_firstyear.year_total > 0 AND t_c_firstyear.year_total > 0 AND t_w_firstyear.year_total > 0
  AND CASE WHEN t_c_firstyear.year_total > 0 THEN t_c_secyear.year_total / t_c_firstyear.year_total ELSE NULL END
    > CASE WHEN t_s_firstyear.year_total > 0 THEN t_s_secyear.year_total / t_s_firstyear.year_total ELSE NULL END
  AND CASE WHEN t_c_firstyear.year_total > 0 THEN t_c_secyear.year_total / t_c_firstyear.year_total ELSE NULL END
    > CASE WHEN t_w_firstyear.year_total > 0 THEN t_w_secyear.year_total / t_w_firstyear.year_total ELSE NULL END
ORDER BY t_s_secyear.customer_id NULLS FIRST, t_s_secyear.customer_first_name NULLS FIRST,
         t_s_secyear.customer_last_name NULLS FIRST, t_s_secyear.customer_preferred_cust_flag NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2001)), derive=dict(year2=lambda p: str(p["year"] + 1)),
         phrasings=[
             "Which customers grew their catalog business faster than both their store and web business from {year} to {year2}? Measure each channel's yearly amount as half of (extended list price minus wholesale cost minus discount, plus extended sales price), require a positive {year} amount in all three channels, and list customer id, first name, last name and preferred-customer flag, sorted by those; first 100.",
             "year_total per c_customer_id, d_year and channel (store_sales/ss_customer_sk, catalog_sales/cs_bill_customer_sk, web_sales/ws_bill_customer_sk) = sum(((ext_list_price - ext_wholesale_cost - ext_discount_amt) + ext_sales_price) / 2). Keep customers with all three {year} totals > 0 where catalog {year2}/{year} > store {year2}/{year} and catalog ratio > web ratio; return customer_id, customer_first_name, customer_last_name, customer_preferred_cust_flag ORDER BY those four, LIMIT 100.",
             "Customers whose catalog growth {year}->{year2} beat store and web growth (yearly value = ((list - wholesale - discount) + sales price)/2): id, first, last, preferred flag. Sorted, 100.",
             "I'm looking for customers who shifted toward the catalog between {year} and {year2}. For each customer, channel (store, catalog, web) and year, take the sum of ((extended list price - extended wholesale cost - extended discount) + extended sales price) / 2. Ignore anyone who didn't have a positive {year} figure in every channel, then show the people whose catalog year-over-year ratio is bigger than both their store ratio and their web ratio — customer id, first name, last name and preferred flag, ordered by those columns, top 100 please.",
         ]),
    dict(id="t05", qnum=5, complexity="complex", bench="tpcds",
         sql="""WITH ssr AS
  (SELECT s_store_id, sum(sales_price) AS sales, sum(profit) AS profit, sum(return_amt) AS returns_, sum(net_loss) AS profit_loss
   FROM (SELECT ss_store_sk AS store_sk, ss_sold_date_sk AS date_sk, ss_ext_sales_price AS sales_price, ss_net_profit AS profit,
                cast(0 AS decimal(7,2)) AS return_amt, cast(0 AS decimal(7,2)) AS net_loss FROM store_sales
         UNION ALL
         SELECT sr_store_sk AS store_sk, sr_returned_date_sk AS date_sk, cast(0 AS decimal(7,2)) AS sales_price,
                cast(0 AS decimal(7,2)) AS profit, sr_return_amt AS return_amt, sr_net_loss AS net_loss FROM store_returns) salesreturns,
        date_dim, store
   WHERE date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND store_sk = s_store_sk
   GROUP BY s_store_id),
     csr AS
  (SELECT cp_catalog_page_id, sum(sales_price) AS sales, sum(profit) AS profit, sum(return_amt) AS returns_, sum(net_loss) AS profit_loss
   FROM (SELECT cs_catalog_page_sk AS page_sk, cs_sold_date_sk AS date_sk, cs_ext_sales_price AS sales_price, cs_net_profit AS profit,
                cast(0 AS decimal(7,2)) AS return_amt, cast(0 AS decimal(7,2)) AS net_loss FROM catalog_sales
         UNION ALL
         SELECT cr_catalog_page_sk AS page_sk, cr_returned_date_sk AS date_sk, cast(0 AS decimal(7,2)) AS sales_price,
                cast(0 AS decimal(7,2)) AS profit, cr_return_amount AS return_amt, cr_net_loss AS net_loss FROM catalog_returns) salesreturns,
        date_dim, catalog_page
   WHERE date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND page_sk = cp_catalog_page_sk
   GROUP BY cp_catalog_page_id),
     wsr AS
  (SELECT web_site_id, sum(sales_price) AS sales, sum(profit) AS profit, sum(return_amt) AS returns_, sum(net_loss) AS profit_loss
   FROM (SELECT ws_web_site_sk AS wsr_web_site_sk, ws_sold_date_sk AS date_sk, ws_ext_sales_price AS sales_price, ws_net_profit AS profit,
                cast(0 AS decimal(7,2)) AS return_amt, cast(0 AS decimal(7,2)) AS net_loss FROM web_sales
         UNION ALL
         SELECT ws_web_site_sk AS wsr_web_site_sk, wr_returned_date_sk AS date_sk, cast(0 AS decimal(7,2)) AS sales_price,
                cast(0 AS decimal(7,2)) AS profit, wr_return_amt AS return_amt, wr_net_loss AS net_loss
         FROM web_returns LEFT OUTER JOIN web_sales ON (wr_item_sk = ws_item_sk AND wr_order_number = ws_order_number)) salesreturns,
        date_dim, web_site
   WHERE date_sk = d_date_sk AND d_date BETWEEN cast('{start}' AS date) AND cast('{end}' AS date) AND wsr_web_site_sk = web_site_sk
   GROUP BY web_site_id)
SELECT channel, id, sum(sales) AS sales, sum(returns_) AS returns_, sum(profit) AS profit
FROM (SELECT 'store channel' AS channel, concat('store', s_store_id) AS id, sales, returns_, (profit - profit_loss) AS profit FROM ssr
      UNION ALL
      SELECT 'catalog channel' AS channel, concat('catalog_page', cp_catalog_page_id) AS id, sales, returns_, (profit - profit_loss) AS profit FROM csr
      UNION ALL
      SELECT 'web channel' AS channel, concat('web_site', web_site_id) AS id, sales, returns_, (profit - profit_loss) AS profit FROM wsr) x
GROUP BY ROLLUP (channel, id)
ORDER BY channel NULLS FIRST, id NULLS FIRST
LIMIT 100;""",
         slots=dict(start=("date", "1998-01-01", "2002-12-15")),
         derive=dict(end=lambda p: _plus_days(p["start"], 14), start_nl=lambda p: _pretty_date(p["start"]),
                     end_nl=lambda p: _pretty_date(_plus_days(p["start"], 14))),
         phrasings=[
             "Give me a sales and returns report for the two weeks {start} to {end} across all channels: each store (by store id), each catalog page (by page id) and each web site (by site id), showing total sales, total returns and profit after return losses. Include a subtotal per channel and a grand total; sort by channel then id, 100 rows.",
             "For d_date between {start} and {end}: per s_store_id sum ss_ext_sales_price, ss_net_profit, sr_return_amt, sr_net_loss; per cp_catalog_page_id the catalog_sales/catalog_returns equivalents; per web_site_id the web_sales/web_returns ones (returns mapped to a site via their web_sales row). Output channel ('store channel' / 'catalog channel' / 'web channel'), id (prefix 'store' / 'catalog_page' / 'web_site' + id), sales, returns_, profit = net profit - net loss, GROUP BY ROLLUP(channel, id), ORDER BY channel, id NULLS FIRST, LIMIT 100.",
             "{start_nl} - {end_nl}: sales, returns and profit net of return loss per store, catalog page and web site, rolled up by channel and overall. By channel, id; 100.",
             "Could you put together a two-week channel summary covering {start_nl} through {end_nl}? I'd like every store, every catalog page and every web site on its own line, tagged with its channel, showing how much it sold, how much came back in returns, and the profit once return losses are subtracted. Please add a subtotal line for each channel and one overall total, order by channel and then id, and cap it at 100 lines.",
         ]),
    dict(id="t11", qnum=11, complexity="complex", bench="tpcds",
         sql="""WITH year_total AS
  (SELECT c_customer_id customer_id, c_first_name customer_first_name, c_last_name customer_last_name,
          c_preferred_cust_flag customer_preferred_cust_flag, c_birth_country customer_birth_country, c_login customer_login,
          c_email_address customer_email_address, d_year dyear, sum(ss_ext_list_price-ss_ext_discount_amt) year_total, 's' sale_type
   FROM customer, store_sales, date_dim
   WHERE c_customer_sk = ss_customer_sk AND ss_sold_date_sk = d_date_sk
   GROUP BY c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year
   UNION ALL
   SELECT c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year,
          sum(ws_ext_list_price-ws_ext_discount_amt), 'w'
   FROM customer, web_sales, date_dim
   WHERE c_customer_sk = ws_bill_customer_sk AND ws_sold_date_sk = d_date_sk
   GROUP BY c_customer_id, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_country, c_login, c_email_address, d_year)
SELECT t_s_secyear.customer_id, t_s_secyear.customer_first_name, t_s_secyear.customer_last_name, t_s_secyear.customer_preferred_cust_flag
FROM year_total t_s_firstyear, year_total t_s_secyear, year_total t_w_firstyear, year_total t_w_secyear
WHERE t_s_secyear.customer_id = t_s_firstyear.customer_id AND t_s_firstyear.customer_id = t_w_secyear.customer_id
  AND t_s_firstyear.customer_id = t_w_firstyear.customer_id
  AND t_s_firstyear.sale_type = 's' AND t_w_firstyear.sale_type = 'w' AND t_s_secyear.sale_type = 's' AND t_w_secyear.sale_type = 'w'
  AND t_s_firstyear.dyear = {year} AND t_s_secyear.dyear = {year}+1 AND t_w_firstyear.dyear = {year} AND t_w_secyear.dyear = {year}+1
  AND t_s_firstyear.year_total > 0 AND t_w_firstyear.year_total > 0
  AND CASE WHEN t_w_firstyear.year_total > 0 THEN (t_w_secyear.year_total*1.0000) / t_w_firstyear.year_total ELSE 0.0 END
    > CASE WHEN t_s_firstyear.year_total > 0 THEN (t_s_secyear.year_total*1.0000) / t_s_firstyear.year_total ELSE 0.0 END
ORDER BY t_s_secyear.customer_id NULLS FIRST, t_s_secyear.customer_first_name NULLS FIRST,
         t_s_secyear.customer_last_name NULLS FIRST, t_s_secyear.customer_preferred_cust_flag NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2001)), derive=dict(year2=lambda p: str(p["year"] + 1)),
         phrasings=[
             "Which customers' web spending grew faster than their store spending from {year} to {year2}? Count spending as extended list price minus extended discount, and only consider customers with positive {year} spending in both channels. Show customer id, first name, last name and preferred-customer flag, sorted by those fields; top 100.",
             "year_total = sum(ext_list_price - ext_discount_amt) by c_customer_id, d_year and channel ('s' from store_sales via ss_customer_sk, 'w' from web_sales via ws_bill_customer_sk). Return customer_id, customer_first_name, customer_last_name, customer_preferred_cust_flag where both {year} totals > 0 and web {year2}/{year} > store {year2}/{year}; ORDER BY the four columns NULLS FIRST, LIMIT 100.",
             "Customers with bigger web than store growth {year}->{year2} (list price less discount): id, names, preferred flag; sorted; 100.",
             "I want to find customers who are moving their spending online. For {year} and {year2}, add up each customer's extended list price minus extended discount, once for store purchases and once for web purchases. Among people who spent something in both channels in {year}, list the ones whose web total grew by a larger factor than their store total — I just need their customer id, first and last name and preferred flag, ordered by those, first 100.",
         ]),
    dict(id="t14", qnum=14, complexity="complex", bench="tpcds",
         # q14 has two parts in the spec; DuckDB's tpcds_queries() ships part 1 only, which is what is phrased here.
         sql="""WITH cross_items AS
  (SELECT i_item_sk ss_item_sk
   FROM item,
     (SELECT iss.i_brand_id brand_id, iss.i_class_id class_id, iss.i_category_id category_id
      FROM store_sales, item iss, date_dim d1
      WHERE ss_item_sk = iss.i_item_sk AND ss_sold_date_sk = d1.d_date_sk AND d1.d_year BETWEEN {year} AND {year} + 2
      INTERSECT
      SELECT ics.i_brand_id, ics.i_class_id, ics.i_category_id
      FROM catalog_sales, item ics, date_dim d2
      WHERE cs_item_sk = ics.i_item_sk AND cs_sold_date_sk = d2.d_date_sk AND d2.d_year BETWEEN {year} AND {year} + 2
      INTERSECT
      SELECT iws.i_brand_id, iws.i_class_id, iws.i_category_id
      FROM web_sales, item iws, date_dim d3
      WHERE ws_item_sk = iws.i_item_sk AND ws_sold_date_sk = d3.d_date_sk AND d3.d_year BETWEEN {year} AND {year} + 2) sq1
   WHERE i_brand_id = brand_id AND i_class_id = class_id AND i_category_id = category_id),
     avg_sales AS
  (SELECT avg(quantity*list_price) average_sales
   FROM (SELECT ss_quantity quantity, ss_list_price list_price FROM store_sales, date_dim
         WHERE ss_sold_date_sk = d_date_sk AND d_year BETWEEN {year} AND {year} + 2
         UNION ALL
         SELECT cs_quantity quantity, cs_list_price list_price FROM catalog_sales, date_dim
         WHERE cs_sold_date_sk = d_date_sk AND d_year BETWEEN {year} AND {year} + 2
         UNION ALL
         SELECT ws_quantity quantity, ws_list_price list_price FROM web_sales, date_dim
         WHERE ws_sold_date_sk = d_date_sk AND d_year BETWEEN {year} AND {year} + 2) sq2)
SELECT channel, i_brand_id, i_class_id, i_category_id, sum(sales) AS sum_sales, sum(number_sales) AS sum_number_sales
FROM (SELECT 'store' channel, i_brand_id, i_class_id, i_category_id, sum(ss_quantity*ss_list_price) sales, count(*) number_sales
      FROM store_sales, item, date_dim
      WHERE ss_item_sk IN (SELECT ss_item_sk FROM cross_items) AND ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk
        AND d_year = {year}+2 AND d_moy = {moy}
      GROUP BY i_brand_id, i_class_id, i_category_id
      HAVING sum(ss_quantity*ss_list_price) > (SELECT average_sales FROM avg_sales)
      UNION ALL
      SELECT 'catalog' channel, i_brand_id, i_class_id, i_category_id, sum(cs_quantity*cs_list_price) sales, count(*) number_sales
      FROM catalog_sales, item, date_dim
      WHERE cs_item_sk IN (SELECT ss_item_sk FROM cross_items) AND cs_item_sk = i_item_sk AND cs_sold_date_sk = d_date_sk
        AND d_year = {year}+2 AND d_moy = {moy}
      GROUP BY i_brand_id, i_class_id, i_category_id
      HAVING sum(cs_quantity*cs_list_price) > (SELECT average_sales FROM avg_sales)
      UNION ALL
      SELECT 'web' channel, i_brand_id, i_class_id, i_category_id, sum(ws_quantity*ws_list_price) sales, count(*) number_sales
      FROM web_sales, item, date_dim
      WHERE ws_item_sk IN (SELECT ss_item_sk FROM cross_items) AND ws_item_sk = i_item_sk AND ws_sold_date_sk = d_date_sk
        AND d_year = {year}+2 AND d_moy = {moy}
      GROUP BY i_brand_id, i_class_id, i_category_id
      HAVING sum(ws_quantity*ws_list_price) > (SELECT average_sales FROM avg_sales)) y
GROUP BY ROLLUP (channel, i_brand_id, i_class_id, i_category_id)
ORDER BY channel NULLS FIRST, i_brand_id NULLS FIRST, i_class_id NULLS FIRST, i_category_id NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2000), moy=("int", 1, 12)),
         derive=dict(year2=lambda p: str(p["year"] + 2), month_name=lambda p: MONTHS[p["moy"] - 1]),
         notes="two-part query in the spec; part 1 only (as shipped by DuckDB)",
         phrasings=[
             "For product lines (brand, class, category) that sold in stores, the catalog and the web during {year}-{year2}, how did each channel do in {month_name} {year2}? Per channel and brand/class/category give sales (quantity x list price) and number of sales, keeping only groups whose sales exceed the average quantity x list price of all sales in all channels over {year}-{year2}. Roll up by channel, brand, class and category, ordered by those; 100 rows.",
             "cross_items = items whose (i_brand_id, i_class_id, i_category_id) occurs in store_sales, catalog_sales and web_sales with d_year BETWEEN {year} AND {year2}; average_sales = avg(quantity*list_price) over the three channels for those years. For d_year = {year2} and d_moy = {moy}, per channel and i_brand_id, i_class_id, i_category_id, compute sum(quantity*list_price) and count(*) on cross items HAVING the sum > average_sales; then ROLLUP(channel, i_brand_id, i_class_id, i_category_id) of sum_sales and sum_number_sales, ORDER BY the four keys NULLS FIRST, LIMIT 100.",
             "{month_name} {year2} sales (qty x list price) and counts by channel/brand/class/category, items whose brand-class-category sold in all 3 channels {year}-{year2}, above the {year}-{year2} average; rollup; 100.",
             "I'd like to see how our cross-channel product lines performed in {month_name} {year2}. First, find every brand/class/category combination that had sales in stores, in the catalog and on the web at some point from {year} to {year2}. Then, for {month_name} {year2}, give each channel and combination its total of quantity times list price and its number of sales — but only where that total beats the average quantity-times-list-price of every sale across all three channels in those three years. Roll it up by channel, brand id, class id and category id, sort by those, and stop at 100 rows.",
         ]),
    dict(id="t17", qnum=17, complexity="complex", bench="tpcds",
         sql="""SELECT i_item_id, i_item_desc, s_state,
       count(ss_quantity) AS store_sales_quantitycount, avg(ss_quantity) AS store_sales_quantityave,
       stddev_samp(ss_quantity) AS store_sales_quantitystdev, stddev_samp(ss_quantity)/avg(ss_quantity) AS store_sales_quantitycov,
       count(sr_return_quantity) AS store_returns_quantitycount, avg(sr_return_quantity) AS store_returns_quantityave,
       stddev_samp(sr_return_quantity) AS store_returns_quantitystdev,
       stddev_samp(sr_return_quantity)/avg(sr_return_quantity) AS store_returns_quantitycov,
       count(cs_quantity) AS catalog_sales_quantitycount, avg(cs_quantity) AS catalog_sales_quantityave,
       stddev_samp(cs_quantity) AS catalog_sales_quantitystdev, stddev_samp(cs_quantity)/avg(cs_quantity) AS catalog_sales_quantitycov
FROM store_sales, store_returns, catalog_sales, date_dim d1, date_dim d2, date_dim d3, store, item
WHERE d1.d_quarter_name = '{year}Q1' AND d1.d_date_sk = ss_sold_date_sk AND i_item_sk = ss_item_sk AND s_store_sk = ss_store_sk
  AND ss_customer_sk = sr_customer_sk AND ss_item_sk = sr_item_sk AND ss_ticket_number = sr_ticket_number
  AND sr_returned_date_sk = d2.d_date_sk AND d2.d_quarter_name IN ('{year}Q1', '{year}Q2', '{year}Q3')
  AND sr_customer_sk = cs_bill_customer_sk AND sr_item_sk = cs_item_sk AND cs_sold_date_sk = d3.d_date_sk
  AND d3.d_quarter_name IN ('{year}Q1', '{year}Q2', '{year}Q3')
GROUP BY i_item_id, i_item_desc, s_state
ORDER BY i_item_id NULLS FIRST, i_item_desc NULLS FIRST, s_state NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "For items bought in a store in Q1 {year}, returned by the same customer during Q1-Q3 {year}, and then bought by that customer from the catalog in Q1-Q3 {year}: per item and store state, show item id, description, state, and for store quantity, returned quantity and catalog quantity the count, average, sample standard deviation and coefficient of variation. Ordered by item id, description, state; 100 rows.",
             "Join store_sales (d_quarter_name '{year}Q1') to store_returns on customer, item and ticket (returned in '{year}Q1', '{year}Q2' or '{year}Q3') and to catalog_sales on cs_bill_customer_sk = sr_customer_sk and item (sold in those same quarters). GROUP BY i_item_id, i_item_desc, s_state; for each of ss_quantity, sr_return_quantity, cs_quantity output count, avg, stddev_samp and stddev_samp/avg. ORDER BY item id, item desc, s_state NULLS FIRST; LIMIT 100.",
             "Qty stats (count, mean, stdev, cov) for store buys {year}Q1 -> store returns {year}Q1-Q3 -> catalog rebuys {year}Q1-Q3, by item id/desc and store state. Sorted, 100.",
             "There's a buy-return-rebuy pattern I want to quantify for {year}. A customer buys something in a store during the first quarter, brings it back to the store sometime in the first three quarters, and buys the same item from the catalog within those same three quarters. Grouping by item and the store's state, can you show the item id, description, state, and for each of the three quantities (bought, returned, re-bought from the catalog) the count, mean, sample standard deviation and stdev divided by mean? Sort by item id, description and state, and keep 100 rows.",
         ]),
    dict(id="t18", qnum=18, complexity="complex", bench="tpcds",
         sql="""SELECT i_item_id, ca_country, ca_state, ca_county,
       avg(cast(cs_quantity AS decimal(12, 2))) agg1, avg(cast(cs_list_price AS decimal(12, 2))) agg2,
       avg(cast(cs_coupon_amt AS decimal(12, 2))) agg3, avg(cast(cs_sales_price AS decimal(12, 2))) agg4,
       avg(cast(cs_net_profit AS decimal(12, 2))) agg5, avg(cast(c_birth_year AS decimal(12, 2))) agg6,
       avg(cast(cd1.cd_dep_count AS decimal(12, 2))) agg7
FROM catalog_sales, customer_demographics cd1, customer_demographics cd2, customer, customer_address, date_dim, item
WHERE cs_sold_date_sk = d_date_sk AND cs_item_sk = i_item_sk AND cs_bill_cdemo_sk = cd1.cd_demo_sk
  AND cs_bill_customer_sk = c_customer_sk AND cd1.cd_gender = '{gender}' AND cd1.cd_education_status = '{education}'
  AND c_current_cdemo_sk = cd2.cd_demo_sk AND c_current_addr_sk = ca_address_sk AND c_birth_month IN (1, 6, 8, 9, 12, 2)
  AND d_year = {year} AND ca_state IN ({states_sql})
GROUP BY ROLLUP (i_item_id, ca_country, ca_state, ca_county)
ORDER BY ca_country NULLS FIRST, ca_state NULLS FIRST, ca_county NULLS FIRST, i_item_id NULLS FIRST,
         grouping (ca_country) NULLS FIRST, grouping (ca_state) NULLS FIRST, grouping (ca_county) NULLS FIRST
LIMIT 100;""",
         slots=dict(gender=("choice", ["M", "F"]), education=("choice", EDUCATION), year=("int", *YEARS),
                    states=("db_sample", _CA_STATE, 7)),
         derive=dict(gender_nl=lambda p: GENDER[p["gender"]], states_sql=lambda p: _sql_list(p["states"]),
                     states_nl=lambda p: _nl_list(p["states"])),
         phrasings=[
             "For {year} catalog orders billed to {gender_nl} customers with '{education}' education, born in January, February, June, August, September or December, and currently living in {states_nl}: average quantity, list price, coupon amount, sales price, net profit, customer birth year and dependents, by item, country, state and county with subtotals at every level. Order by country, state, county, item; 100 rows.",
             "GROUP BY ROLLUP(i_item_id, ca_country, ca_state, ca_county): avg of cs_quantity, cs_list_price, cs_coupon_amt, cs_sales_price, cs_net_profit, c_birth_year, cd1.cd_dep_count (agg1..agg7, as decimal(12,2)) over catalog_sales with d_year = {year}, bill cdemo cd_gender = '{gender}' and cd_education_status = '{education}', c_birth_month IN (1, 2, 6, 8, 9, 12), current address ca_state IN ({states_sql}). ORDER BY ca_country, ca_state, ca_county, i_item_id, then grouping() flags, NULLS FIRST; LIMIT 100.",
             "{year} catalog averages (qty, list, coupon, sales price, profit, birth year, deps) for {gender_nl} '{education}' buyers born Jan/Feb/Jun/Aug/Sep/Dec in {states_nl}; rollup item > country > state > county; 100.",
             "For the catalog channel in {year}, I'd like the averages of quantity, list price, coupon amount, sales price, net profit, the buyer's birth year and the buyer's dependent count. Please restrict it to {gender_nl} bill-to customers whose education is '{education}', whose birthday falls in January, February, June, August, September or December, and whose current address is in one of these states: {states_nl}. Break it down by item, country, state and county, with roll-up subtotal rows, sorted by country, state, county and item, first 100 lines.",
         ]),
    dict(id="t22", qnum=22, complexity="complex", bench="tpcds",
         sql="""SELECT i_product_name, i_brand, i_class, i_category, avg(inv_quantity_on_hand) qoh
FROM inventory, date_dim, item
WHERE inv_date_sk=d_date_sk AND inv_item_sk=i_item_sk AND d_month_seq BETWEEN {mseq} AND {mseq} + 11
GROUP BY rollup(i_product_name, i_brand, i_class, i_category)
ORDER BY qoh NULLS FIRST, i_product_name NULLS FIRST, i_brand NULLS FIRST, i_class NULLS FIRST, i_category NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)),
         derive=dict(mseq=_mseq, mseq_end=lambda p: str((p["year"] - 1900) * 12 + 11)),
         phrasings=[
             "What was the average inventory on hand during {year} by product name, brand, class and category, including subtotals as each level rolls up? Show product name, brand, class, category and average quantity on hand, lowest average first, then by the four names; 100 rows.",
             "avg(inv_quantity_on_hand) AS qoh over inventory x item for d_month_seq {mseq} through {mseq_end} (calendar {year}), GROUP BY ROLLUP(i_product_name, i_brand, i_class, i_category); ORDER BY qoh, i_product_name, i_brand, i_class, i_category NULLS FIRST; LIMIT 100.",
             "{year} avg qty on hand, rollup product > brand > class > category, ascending; 100.",
             "I want to find what we kept the least stock of in {year}. Could you average the quantity on hand across the twelve months of that year by product name, brand, class and category — with subtotal rows as you roll up each level — and show me the 100 smallest averages, breaking ties by product name, brand, class, then category?",
         ]),
    dict(id="t23", qnum=23, complexity="complex", bench="tpcds",
         # q23 has two parts in the spec; DuckDB's tpcds_queries() ships one statement (customer-level output), phrased here.
         sql="""WITH frequent_ss_items AS
  (SELECT itemdesc, i_item_sk item_sk, d_date solddate, count(*) cnt
   FROM store_sales, date_dim, (SELECT SUBSTRING(i_item_desc, 1, 30) itemdesc, * FROM item) sq1
   WHERE ss_sold_date_sk = d_date_sk AND ss_item_sk = i_item_sk AND d_year IN ({year}, {year}+1, {year}+2, {year}+3)
   GROUP BY itemdesc, i_item_sk, d_date
   HAVING count(*) > 4),
     max_store_sales AS
  (SELECT max(csales) tpcds_cmax
   FROM (SELECT c_customer_sk, sum(ss_quantity*ss_sales_price) csales FROM store_sales, customer, date_dim
         WHERE ss_customer_sk = c_customer_sk AND ss_sold_date_sk = d_date_sk AND d_year IN ({year}, {year}+1, {year}+2, {year}+3)
         GROUP BY c_customer_sk) sq2),
     best_ss_customer AS
  (SELECT c_customer_sk, sum(ss_quantity*ss_sales_price) ssales
   FROM store_sales, customer, max_store_sales
   WHERE ss_customer_sk = c_customer_sk
   GROUP BY c_customer_sk
   HAVING sum(ss_quantity*ss_sales_price) > (50/100.0) * max(tpcds_cmax))
SELECT c_last_name, c_first_name, sales
FROM (SELECT c_last_name, c_first_name, sum(cs_quantity*cs_list_price) sales
      FROM catalog_sales, customer, date_dim, best_ss_customer
      WHERE d_year = {year} AND d_moy = {moy} AND cs_sold_date_sk = d_date_sk AND cs_bill_customer_sk = best_ss_customer.c_customer_sk
        AND cs_bill_customer_sk = customer.c_customer_sk AND cs_item_sk IN (SELECT item_sk FROM frequent_ss_items)
      GROUP BY c_last_name, c_first_name
      UNION ALL
      SELECT c_last_name, c_first_name, sum(ws_quantity*ws_list_price) sales
      FROM web_sales, customer, date_dim, best_ss_customer
      WHERE d_year = {year} AND d_moy = {moy} AND ws_sold_date_sk = d_date_sk AND ws_bill_customer_sk = best_ss_customer.c_customer_sk
        AND ws_bill_customer_sk = customer.c_customer_sk AND ws_item_sk IN (SELECT item_sk FROM frequent_ss_items)
      GROUP BY c_last_name, c_first_name) sq3
ORDER BY c_last_name NULLS FIRST, c_first_name NULLS FIRST, sales NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", 1998, 1999), moy=("int", 1, 12)),
         derive=dict(year3=lambda p: str(p["year"] + 3), month_name=lambda p: MONTHS[p["moy"] - 1]),
         notes="two-part query in the spec; the single DuckDB statement only",
         phrasings=[
             "How much did our best store customers spend through the catalog and the web in {month_name} {year} on frequently bought items? Best customers are those whose total store spend (quantity x sales price) is over half of the top customer's store spend in {year}-{year3}; frequent items are items sold in stores more than 4 times on the same day in {year}-{year3}. Show last name, first name and sales (quantity x list price), one row per customer per channel, sorted by last name, first name, sales; 100 rows.",
             "frequent_ss_items: i_item_sk with count(*) > 4 store_sales rows per (30-char item desc, item, d_date) in d_year {year}..{year3}. best_ss_customer: c_customer_sk whose sum(ss_quantity*ss_sales_price) > 0.5 * max per-customer sum over {year}..{year3}. Union catalog_sales (cs_bill_customer_sk, sum cs_quantity*cs_list_price) and web_sales (ws_bill_customer_sk, sum ws_quantity*ws_list_price) for d_year {year}, d_moy {moy}, restricted to those items and customers, grouped by c_last_name, c_first_name; ORDER BY last name, first name, sales NULLS FIRST; LIMIT 100.",
             "{month_name} {year} catalog and web spend (qty x list price) of top store customers (>50% of max store spend {year}-{year3}) on items sold >4 times a day in store {year}-{year3}: last, first, sales. Sorted, 100.",
             "Here's what I'm after: our very best in-store shoppers — anyone whose store spending, quantity times sales price, is more than half of what the single biggest store customer spent over {year} to {year3} — and what they bought from us through the catalog and online in {month_name} {year}. Only count items that are store hot-sellers, meaning they sold more than four times on a single day at some point between {year} and {year3}. For each customer give the last name, first name and the quantity-times-list-price total, separately for catalog and web, sorted by last name, first name and amount, first 100 rows.",
         ]),
    dict(id="t24", qnum=24, complexity="complex", bench="tpcds",
         # q24 has two parts in the spec (two colors); DuckDB's tpcds_queries() ships part 1 only, phrased here.
         sql="""WITH ssales AS
  (SELECT c_last_name, c_first_name, s_store_name, ca_state, s_state, i_color, i_current_price, i_manager_id, i_units, i_size,
          sum(ss_net_paid) netpaid
   FROM store_sales, store_returns, store, item, customer, customer_address
   WHERE ss_ticket_number = sr_ticket_number AND ss_item_sk = sr_item_sk AND ss_customer_sk = c_customer_sk
     AND ss_item_sk = i_item_sk AND ss_store_sk = s_store_sk AND c_current_addr_sk = ca_address_sk
     AND c_birth_country <> upper(ca_country) AND s_zip = ca_zip AND s_market_id = {market_id}
   GROUP BY c_last_name, c_first_name, s_store_name, ca_state, s_state, i_color, i_current_price, i_manager_id, i_units, i_size)
SELECT c_last_name, c_first_name, s_store_name, sum(netpaid) paid
FROM ssales
WHERE i_color = '{color}'
GROUP BY c_last_name, c_first_name, s_store_name
HAVING sum(netpaid) > (SELECT 0.05*avg(netpaid) FROM ssales)
ORDER BY c_last_name, c_first_name, s_store_name;""",
         slots=dict(market_id=("db", "SELECT DISTINCT s_market_id FROM store WHERE s_market_id IS NOT NULL"),
                    color=("db", "SELECT DISTINCT i_color FROM item WHERE i_color IS NOT NULL")),
         derive={},
         notes="two-part query in the spec; part 1 only (as shipped by DuckDB)",
         phrasings=[
             "Among returned store purchases at market {market_id} stores, made by customers who live in the store's zip code but were born in a different country from the one they live in, who spent the most on {color} items? Show last name, first name, store name and net paid, keeping customer/store pairs whose total exceeds 5% of the average net paid across all such purchase groups (by customer, store, states and item attributes). Sort by last name, first name, store; all rows.",
             "ssales = sum(ss_net_paid) of store_sales joined to store_returns (ticket + item), grouped by c_last_name, c_first_name, s_store_name, ca_state, s_state, i_color, i_current_price, i_manager_id, i_units, i_size, where s_market_id = {market_id}, s_zip = ca_zip of the customer's current address and c_birth_country <> upper(ca_country). Return c_last_name, c_first_name, s_store_name, sum(netpaid) for i_color = '{color}' HAVING it > 0.05 * avg(netpaid) over ssales; ORDER BY last name, first name, store name.",
             "Net paid on returned {color} store items, market {market_id}, customers living in the store's zip and born abroad; per customer and store, above 5% of the avg group net paid; last, first, store, paid; sorted.",
             "I'm curious about a specific group of shoppers: people who live in the same zip code as a market-{market_id} store, whose birth country isn't the country they live in now, and whose purchases at that store were later returned. Summing net paid by customer, store, the two states and the item's color, price, manager, units and size, could you show — for {color} items only — each customer's last and first name, the store name and their total net paid, as long as it's more than 5% of the average across all those groups? Sort by last name, first name and store, no limit.",
         ]),
    dict(id="t29", qnum=29, complexity="complex", bench="tpcds",
         sql="""SELECT i_item_id, i_item_desc, s_store_id, s_store_name, sum(ss_quantity) AS store_sales_quantity,
       sum(sr_return_quantity) AS store_returns_quantity, sum(cs_quantity) AS catalog_sales_quantity
FROM store_sales, store_returns, catalog_sales, date_dim d1, date_dim d2, date_dim d3, store, item
WHERE d1.d_moy = {moy} AND d1.d_year = {year} AND d1.d_date_sk = ss_sold_date_sk AND i_item_sk = ss_item_sk
  AND s_store_sk = ss_store_sk AND ss_customer_sk = sr_customer_sk AND ss_item_sk = sr_item_sk
  AND ss_ticket_number = sr_ticket_number AND sr_returned_date_sk = d2.d_date_sk AND d2.d_moy BETWEEN {moy} AND {moy} + 3
  AND d2.d_year = {year} AND sr_customer_sk = cs_bill_customer_sk AND sr_item_sk = cs_item_sk AND cs_sold_date_sk = d3.d_date_sk
  AND d3.d_year IN ({year}, {year}+1, {year}+2)
GROUP BY i_item_id, i_item_desc, s_store_id, s_store_name
ORDER BY i_item_id, i_item_desc, s_store_id, s_store_name
LIMIT 100;""",
         slots=dict(year=("int", 1998, 2000), moy=("int", 1, 9)),
         derive=dict(moy_end=lambda p: str(p["moy"] + 3), year2=lambda p: str(p["year"] + 2),
                     month_name=lambda p: MONTHS[p["moy"] - 1], end_month_name=lambda p: MONTHS[p["moy"] + 2]),
         phrasings=[
             "For items bought in a store in {month_name} {year}, returned to the store by {end_month_name} {year}, and bought again by the same customer through the catalog sometime in {year}-{year2}: per item and store, how many units were sold in store, returned, and bought via catalog? Show item id, description, store id, store name and the three quantities, ordered by item id, description, store id, store name; 100 rows.",
             "store_sales (d_moy = {moy}, d_year = {year}) joined to store_returns on customer, item, ticket (returned d_moy {moy}..{moy_end} of {year}) and to catalog_sales on cs_bill_customer_sk = sr_customer_sk and cs_item_sk = sr_item_sk (d_year IN ({year}, {year}+1, {year2})). GROUP BY i_item_id, i_item_desc, s_store_id, s_store_name; sum ss_quantity, sr_return_quantity, cs_quantity; ORDER BY the group columns; LIMIT 100.",
             "Store qty / return qty / catalog qty per item and store: bought {month_name} {year}, returned by {end_month_name} {year}, catalog rebuy {year}-{year2}. Sorted, 100.",
             "I want to follow a chain of events: someone buys an item in one of our stores in {month_name} {year}, returns it to the store within the next few months (by the end of {end_month_name} {year}), and then orders that same item from the catalog at any point in {year} through {year2}. For each item and store involved, can you tell me the item id and description, the store id and name, and the total quantities sold in store, returned, and ordered from the catalog? Sort by item id, description, store id and store name; 100 rows is enough.",
         ]),
    dict(id="t30", qnum=30, complexity="complex", bench="tpcds",
         sql="""WITH customer_total_return AS
  (SELECT wr_returning_customer_sk AS ctr_customer_sk, ca_state AS ctr_state, sum(wr_return_amt) AS ctr_total_return
   FROM web_returns, date_dim, customer_address
   WHERE wr_returned_date_sk = d_date_sk AND d_year = {year} AND wr_returning_addr_sk = ca_address_sk
   GROUP BY wr_returning_customer_sk, ca_state)
SELECT c_customer_id, c_salutation, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_day, c_birth_month, c_birth_year,
       c_birth_country, c_login, c_email_address, c_last_review_date_sk, ctr_total_return
FROM customer_total_return ctr1, customer_address, customer
WHERE ctr1.ctr_total_return > (SELECT avg(ctr_total_return)*1.2 FROM customer_total_return ctr2 WHERE ctr1.ctr_state = ctr2.ctr_state)
  AND ca_address_sk = c_current_addr_sk AND ca_state = '{state}' AND ctr1.ctr_customer_sk = c_customer_sk
ORDER BY c_customer_id NULLS FIRST, c_salutation NULLS FIRST, c_first_name NULLS FIRST, c_last_name NULLS FIRST,
         c_preferred_cust_flag NULLS FIRST, c_birth_day NULLS FIRST, c_birth_month NULLS FIRST, c_birth_year NULLS FIRST,
         c_birth_country NULLS FIRST, c_login NULLS FIRST, c_email_address NULLS FIRST, c_last_review_date_sk NULLS FIRST,
         ctr_total_return NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), state=("db", _CA_STATE)), derive={},
         phrasings=[
             "Which customers currently living in {state} returned an unusually large amount on the web in {year} — more than 1.2 times the average web return total of customers returning from the same state? Show their customer id, salutation, first and last name, preferred flag, birth day, month, year and country, login, email, last review date key and return total, sorted by all of those in order; 100 rows.",
             "customer_total_return = sum(wr_return_amt) per wr_returning_customer_sk and returning-address ca_state for d_year {year}. Select c_customer_id, c_salutation, c_first_name, c_last_name, c_preferred_cust_flag, c_birth_day, c_birth_month, c_birth_year, c_birth_country, c_login, c_email_address, c_last_review_date_sk, ctr_total_return where ctr_total_return > 1.2 * avg for the same ctr_state and the customer's current ca_state = '{state}'. ORDER BY every output column NULLS FIRST, LIMIT 100.",
             "{state} customers whose {year} web returns exceed 1.2x their state's average per-customer return total: full customer profile + return total, sorted, 100.",
             "I'd like to flag heavy web returners for {year}. For each customer, total up their web return amounts by the state of the address they returned from, and compare that with 1.2 times the average customer total for that state. Show me the customers who exceed it and who currently live in {state}: customer id, salutation, first name, last name, preferred flag, birth day, birth month, birth year, birth country, login, email address, last review date key and their return total, sorted in that column order, top 100.",
         ]),
    dict(id="t31", qnum=31, complexity="complex", bench="tpcds",
         sql="""WITH ss AS
  (SELECT ca_county, d_qoy, d_year, sum(ss_ext_sales_price) AS store_sales
   FROM store_sales, date_dim, customer_address
   WHERE ss_sold_date_sk = d_date_sk AND ss_addr_sk=ca_address_sk
   GROUP BY ca_county, d_qoy, d_year),
     ws AS
  (SELECT ca_county, d_qoy, d_year, sum(ws_ext_sales_price) AS web_sales
   FROM web_sales, date_dim, customer_address
   WHERE ws_sold_date_sk = d_date_sk AND ws_bill_addr_sk=ca_address_sk
   GROUP BY ca_county, d_qoy, d_year)
SELECT ss1.ca_county, ss1.d_year, (ws2.web_sales*1.0000)/ws1.web_sales web_q1_q2_increase,
       (ss2.store_sales*1.0000)/ss1.store_sales store_q1_q2_increase, (ws3.web_sales*1.0000)/ws2.web_sales web_q2_q3_increase,
       (ss3.store_sales*1.0000)/ss2.store_sales store_q2_q3_increase
FROM ss ss1, ss ss2, ss ss3, ws ws1, ws ws2, ws ws3
WHERE ss1.d_qoy = 1 AND ss1.d_year = {year} AND ss1.ca_county = ss2.ca_county AND ss2.d_qoy = 2 AND ss2.d_year = {year}
  AND ss2.ca_county = ss3.ca_county AND ss3.d_qoy = 3 AND ss3.d_year = {year} AND ss1.ca_county = ws1.ca_county
  AND ws1.d_qoy = 1 AND ws1.d_year = {year} AND ws1.ca_county = ws2.ca_county AND ws2.d_qoy = 2 AND ws2.d_year = {year}
  AND ws1.ca_county = ws3.ca_county AND ws3.d_qoy = 3 AND ws3.d_year = {year}
  AND CASE WHEN ws1.web_sales > 0 THEN (ws2.web_sales*1.0000)/ws1.web_sales ELSE NULL END
    > CASE WHEN ss1.store_sales > 0 THEN (ss2.store_sales*1.0000)/ss1.store_sales ELSE NULL END
  AND CASE WHEN ws2.web_sales > 0 THEN (ws3.web_sales*1.0000)/ws2.web_sales ELSE NULL END
    > CASE WHEN ss2.store_sales > 0 THEN (ss3.store_sales*1.0000)/ss2.store_sales ELSE NULL END
ORDER BY ss1.ca_county;""",
         slots=dict(year=("int", *YEARS)), derive={},
         phrasings=[
             "In which counties did web sales grow faster than store sales both from Q1 to Q2 and from Q2 to Q3 of {year}? Use extended sales price, assign store sales by the sale address county and web sales by the billing address county. Show county, year, and the web and store growth ratios for Q1->Q2 and Q2->Q3, ordered by county.",
             "ss = sum(ss_ext_sales_price) by ca_county (ss_addr_sk), d_qoy, d_year; ws = sum(ws_ext_sales_price) by ca_county (ws_bill_addr_sk), d_qoy, d_year. For d_year {year}, return ca_county, d_year, web_q1_q2_increase = ws Q2/Q1, store_q1_q2_increase = ss Q2/Q1, web_q2_q3_increase, store_q2_q3_increase, keeping counties where the web ratio exceeds the store ratio for both quarter pairs. ORDER BY ca_county.",
             "Counties where {year} web growth beat store growth Q1->Q2 and Q2->Q3: county, year, 4 ratios. By county.",
             "I'm trying to see where online is outpacing physical stores. For {year}, take each county's quarterly extended sales — store sales by the county of the sale address, web sales by the county of the billing address — and work out the quarter-over-quarter ratios for Q1 to Q2 and Q2 to Q3 in each channel. List every county where the web ratio is higher than the store ratio for both steps, with the county, the year and all four ratios, alphabetically by county.",
         ]),
    dict(id="t33", qnum=33, complexity="complex", bench="tpcds",
         sql="""WITH ss AS
  (SELECT i_manufact_id, sum(ss_ext_sales_price) total_sales
   FROM store_sales, date_dim, customer_address, item
   WHERE i_manufact_id IN (SELECT i_manufact_id FROM item WHERE i_category IN ('{category}')) AND ss_item_sk = i_item_sk
     AND ss_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy} AND ss_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_manufact_id),
     cs AS
  (SELECT i_manufact_id, sum(cs_ext_sales_price) total_sales
   FROM catalog_sales, date_dim, customer_address, item
   WHERE i_manufact_id IN (SELECT i_manufact_id FROM item WHERE i_category IN ('{category}')) AND cs_item_sk = i_item_sk
     AND cs_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy} AND cs_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_manufact_id),
     ws AS
  (SELECT i_manufact_id, sum(ws_ext_sales_price) total_sales
   FROM web_sales, date_dim, customer_address, item
   WHERE i_manufact_id IN (SELECT i_manufact_id FROM item WHERE i_category IN ('{category}')) AND ws_item_sk = i_item_sk
     AND ws_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy} AND ws_bill_addr_sk = ca_address_sk AND ca_gmt_offset = {gmt_offset}
   GROUP BY i_manufact_id)
SELECT i_manufact_id, sum(total_sales) total_sales
FROM (SELECT * FROM ss UNION ALL SELECT * FROM cs UNION ALL SELECT * FROM ws) tmp1
GROUP BY i_manufact_id
ORDER BY total_sales
LIMIT 100;""",
         slots=dict(category=("choice", CATEGORIES), year=("int", *YEARS), moy=("int", 1, 12), gmt_offset=("db", _CA_GMT)),
         derive=MONTH_NAME,
         phrasings=[
             "For manufacturers that make {category} products, what were total sales across stores, catalog and web in {month_name} {year} to customers in GMT offset {gmt_offset}? Count all items from those manufacturers, using extended sales price. Show manufacturer id and total, smallest first, up to 100.",
             "Sum ss_ext_sales_price + cs_ext_sales_price + ws_ext_sales_price per i_manufact_id for d_year = {year}, d_moy = {moy}, where the item's manufacturer has at least one item with i_category = '{category}' and the sale/bill address has ca_gmt_offset = {gmt_offset} (store via ss_addr_sk, catalog via cs_bill_addr_sk, web via ws_bill_addr_sk). Columns i_manufact_id, total_sales; ORDER BY total_sales; LIMIT 100.",
             "All-channel ext sales by manufacturer id, {month_name} {year}, GMT {gmt_offset} addresses, manufacturers active in {category}. Ascending total, 100.",
             "Could you add up what manufacturers who are in the {category} category sold across all three channels — store, catalog and web — in {month_name} {year}? Only count sales where the customer's address (the sale address for stores, the billing address otherwise) is in time zone offset {gmt_offset}, and include every item those manufacturers make, not just the {category} ones. I need the manufacturer id and the combined extended sales, lowest total first, no more than 100 rows.",
         ]),
    dict(id="t34", qnum=34, complexity="complex", bench="tpcds",
         sql="""SELECT c_last_name, c_first_name, c_salutation, c_preferred_cust_flag, ss_ticket_number, cnt
FROM (SELECT ss_ticket_number, ss_customer_sk, count(*) cnt
      FROM store_sales, date_dim, store, household_demographics
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_store_sk = store.s_store_sk
        AND store_sales.ss_hdemo_sk = household_demographics.hd_demo_sk
        AND (date_dim.d_dom BETWEEN 1 AND 3 OR date_dim.d_dom BETWEEN 25 AND 28)
        AND (household_demographics.hd_buy_potential = '>10000' OR household_demographics.hd_buy_potential = 'Unknown')
        AND household_demographics.hd_vehicle_count > 0
        AND (CASE WHEN household_demographics.hd_vehicle_count > 0
                  THEN (household_demographics.hd_dep_count*1.000)/ household_demographics.hd_vehicle_count ELSE NULL END) > 1.2
        AND date_dim.d_year IN ({year}, {year}+1, {year}+2) AND store.s_county = '{county}'
      GROUP BY ss_ticket_number, ss_customer_sk) dn,
     customer
WHERE ss_customer_sk = c_customer_sk AND cnt BETWEEN 15 AND 20
ORDER BY c_last_name NULLS FIRST, c_first_name NULLS FIRST, c_salutation NULLS FIRST, c_preferred_cust_flag DESC NULLS FIRST,
         ss_ticket_number NULLS FIRST;""",
         slots=dict(year=("int", 1998, 2000), county=("db", _S_COUNTY)), derive=dict(year2=lambda p: str(p["year"] + 2)),
         phrasings=[
             "Which customers had large store baskets (15 to 20 line items on one ticket) bought on the 1st-3rd or 25th-28th of a month in {year}-{year2} at stores in {county}, from households with buying potential '>10000' or 'Unknown' and more than 1.2 dependents per vehicle (at least one vehicle)? Show last name, first name, salutation, preferred flag, ticket number and line count, sorted by last name, first name, salutation, preferred flag descending, ticket; all rows.",
             "Per (ss_ticket_number, ss_customer_sk) count store_sales rows with d_dom in 1-3 or 25-28, d_year IN ({year}, {year}+1, {year2}), s_county = '{county}', hd_buy_potential IN ('>10000', 'Unknown'), hd_vehicle_count > 0 and hd_dep_count / hd_vehicle_count > 1.2; keep cnt BETWEEN 15 AND 20 and return c_last_name, c_first_name, c_salutation, c_preferred_cust_flag, ss_ticket_number, cnt, ORDER BY last, first, salutation, preferred flag DESC, ticket, NULLS FIRST.",
             "Tickets with 15-20 lines, days 1-3/25-28, {year}-{year2}, {county} stores, buy potential >10000/Unknown, deps per vehicle >1.2: customer name, salutation, preferred flag, ticket, count. Sorted.",
             "I'm looking for big shopping trips at our {county} stores. Specifically, tickets with between 15 and 20 items, rung up at the very start (days 1-3) or near the end (days 25-28) of a month, sometime in {year} through {year2}, by households whose buying potential is either over 10000 or unknown, that own at least one vehicle and have more than 1.2 dependents per vehicle. For each such ticket show me the customer's last name, first name, salutation and preferred flag, the ticket number and how many items it had — sorted by last name, first name, salutation, preferred flag (Y before N) and ticket.",
         ]),
    dict(id="t38", qnum=38, complexity="complex", bench="tpcds",
         sql="""SELECT count(*)
FROM (SELECT DISTINCT c_last_name, c_first_name, d_date FROM store_sales, date_dim, customer
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_customer_sk = customer.c_customer_sk
        AND d_month_seq BETWEEN {mseq} AND {mseq} + 11
      INTERSECT
      SELECT DISTINCT c_last_name, c_first_name, d_date FROM catalog_sales, date_dim, customer
      WHERE catalog_sales.cs_sold_date_sk = date_dim.d_date_sk AND catalog_sales.cs_bill_customer_sk = customer.c_customer_sk
        AND d_month_seq BETWEEN {mseq} AND {mseq} + 11
      INTERSECT
      SELECT DISTINCT c_last_name, c_first_name, d_date FROM web_sales, date_dim, customer
      WHERE web_sales.ws_sold_date_sk = date_dim.d_date_sk AND web_sales.ws_bill_customer_sk = customer.c_customer_sk
        AND d_month_seq BETWEEN {mseq} AND {mseq} + 11) hot_cust
LIMIT 100;""",
         slots=dict(year=("int", *YEARS)), derive=dict(mseq=_mseq),
         phrasings=[
             "How many times in {year} did the same customer (by first and last name) buy in a store, from the catalog and on the web all on the same day? Count distinct name-and-date combinations that appear in all three channels.",
             "count(*) of (c_last_name, c_first_name, d_date) tuples present in store_sales (ss_customer_sk) INTERSECT catalog_sales (cs_bill_customer_sk) INTERSECT web_sales (ws_bill_customer_sk), each restricted to the 12 d_month_seq values of {year}.",
             "{year}: number of distinct (last name, first name, date) seen in store, catalog and web sales alike.",
             "Something I've wondered about: during {year}, how often did one person shop with us through every channel on a single day? Treat a customer as their first plus last name, and count the distinct name/date pairs where that name has a store purchase, a catalog purchase and a web purchase on that date. Just the count, please.",
         ]),
    dict(id="t39", qnum=39, complexity="complex", bench="tpcds",
         # q39 has two parts in the spec (b adds cov > 1.5); DuckDB's tpcds_queries() ships part 1 only, phrased here.
         sql="""WITH inv AS
  (SELECT w_warehouse_name, w_warehouse_sk, i_item_sk, d_moy, stdev, mean, CASE mean WHEN 0 THEN NULL ELSE stdev/mean END cov
   FROM (SELECT w_warehouse_name, w_warehouse_sk, i_item_sk, d_moy, stddev_samp(inv_quantity_on_hand)*1.000 stdev,
                avg(inv_quantity_on_hand) mean
         FROM inventory, item, warehouse, date_dim
         WHERE inv_item_sk = i_item_sk AND inv_warehouse_sk = w_warehouse_sk AND inv_date_sk = d_date_sk AND d_year = {year}
         GROUP BY w_warehouse_name, w_warehouse_sk, i_item_sk, d_moy) foo
   WHERE CASE mean WHEN 0 THEN 0 ELSE stdev/mean END > 1)
SELECT inv1.w_warehouse_sk wsk1, inv1.i_item_sk isk1, inv1.d_moy dmoy1, inv1.mean mean1, inv1.cov cov1,
       inv2.w_warehouse_sk, inv2.i_item_sk, inv2.d_moy, inv2.mean, inv2.cov
FROM inv inv1, inv inv2
WHERE inv1.i_item_sk = inv2.i_item_sk AND inv1.w_warehouse_sk = inv2.w_warehouse_sk AND inv1.d_moy={moy} AND inv2.d_moy={moy}+1
ORDER BY inv1.w_warehouse_sk NULLS FIRST, inv1.i_item_sk NULLS FIRST, inv1.d_moy NULLS FIRST, inv1.mean NULLS FIRST,
         inv1.cov NULLS FIRST, inv2.d_moy NULLS FIRST, inv2.mean NULLS FIRST, inv2.cov NULLS FIRST;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 11)),
         derive=dict(moy2=lambda p: str(p["moy"] + 1), month_name=lambda p: MONTHS[p["moy"] - 1],
                     month2_name=lambda p: MONTHS[p["moy"]]),
         notes="two-part query in the spec; part 1 only (as shipped by DuckDB)",
         phrasings=[
             "Which warehouse/item combinations had highly volatile inventory (standard deviation of quantity on hand more than its mean) in both {month_name} and {month2_name} of {year}? For each, show warehouse key, item key, month, mean and coefficient of variation for {month_name}, then the same five fields for {month2_name}. Sort by warehouse, item, then the {month_name} month, mean and cov, then the {month2_name} month, mean and cov; all rows.",
             "inv = per w_warehouse_sk, i_item_sk, d_moy in d_year {year}: mean = avg(inv_quantity_on_hand), stdev = stddev_samp, cov = stdev/mean, keeping cov > 1. Self-join inv1 (d_moy = {moy}) with inv2 (d_moy = {moy2}) on warehouse and item; output wsk1, isk1, dmoy1, mean1, cov1, inv2.w_warehouse_sk, inv2.i_item_sk, inv2.d_moy, inv2.mean, inv2.cov ordered by inv1 warehouse, item, d_moy, mean, cov then inv2 d_moy, mean, cov NULLS FIRST.",
             "Warehouse-item pairs with inventory cov > 1 in month {moy} and month {moy2} of {year}: keys, month, mean, cov for each month. Sorted by warehouse, item.",
             "I want to spot erratic stock levels in {year}. For every warehouse, item and month, work out the mean and sample standard deviation of quantity on hand and their ratio (the coefficient of variation), and keep only cases where that ratio is above 1. Then match up the {month_name} rows with the {month2_name} rows for the same warehouse and item, and show the warehouse key, item key, month number, mean and cov from each of the two months side by side. Order by warehouse, item, then the first month's fields, then the second's.",
         ]),
    dict(id="t44", qnum=44, complexity="complex", bench="tpcds",
         sql="""SELECT asceding.rnk, i1.i_product_name best_performing, i2.i_product_name worst_performing
FROM (SELECT * FROM (SELECT item_sk, rank() OVER (ORDER BY rank_col ASC) rnk
                     FROM (SELECT ss_item_sk item_sk, avg(ss_net_profit) rank_col FROM store_sales ss1
                           WHERE ss_store_sk = {store_sk} GROUP BY ss_item_sk
                           HAVING avg(ss_net_profit) > 0.9* (SELECT avg(ss_net_profit) rank_col FROM store_sales
                                                             WHERE ss_store_sk = {store_sk} AND ss_addr_sk IS NULL
                                                             GROUP BY ss_store_sk)) V1) V11
      WHERE rnk < 11) asceding,
     (SELECT * FROM (SELECT item_sk, rank() OVER (ORDER BY rank_col DESC) rnk
                     FROM (SELECT ss_item_sk item_sk, avg(ss_net_profit) rank_col FROM store_sales ss1
                           WHERE ss_store_sk = {store_sk} GROUP BY ss_item_sk
                           HAVING avg(ss_net_profit) > 0.9* (SELECT avg(ss_net_profit) rank_col FROM store_sales
                                                             WHERE ss_store_sk = {store_sk} AND ss_addr_sk IS NULL
                                                             GROUP BY ss_store_sk)) V2) V21
      WHERE rnk < 11) descending,
     item i1, item i2
WHERE asceding.rnk = descending.rnk AND i1.i_item_sk=asceding.item_sk AND i2.i_item_sk=descending.item_sk
ORDER BY asceding.rnk, i1.i_product_name DESC, i2.i_product_name DESC
LIMIT 100;""",
         slots=dict(store_sk=("db", "SELECT DISTINCT s_store_sk FROM store WHERE s_store_sk IS NOT NULL")), derive={},
         phrasings=[
             "At store {store_sk}, rank items by average net profit, considering only items whose average profit is above 90% of the store's average profit on sales with no customer address. Pair positions 1-10 from the lowest-profit end (labelled best_performing) with positions 1-10 from the highest-profit end (worst_performing): rank, product name from the ascending list, product name from the descending list, ordered by rank then both names descending.",
             "For ss_store_sk = {store_sk}: per ss_item_sk avg(ss_net_profit) HAVING > 0.9 * avg(ss_net_profit) of that store's rows with ss_addr_sk IS NULL. rank() ascending and descending on that average, keep rnk < 11 in each, join on equal rnk and to item for i_product_name; output rnk, best_performing (ascending side), worst_performing (descending side), ORDER BY rnk, the two product names DESC, LIMIT 100.",
             "Store {store_sk}: top-10 by ascending vs descending avg net profit (items above 0.9x the store's no-address avg profit), side by side by rank with product names.",
             "For store number {store_sk}, could you build a two-sided top-ten list of items by average net profit? Only include items whose average profit beats 90% of the store's average profit on sales that have no address recorded. Rank them both from lowest to highest and from highest to lowest, take ranks 1 through 10 from each, and line them up by rank number: the rank, the product name from the low-to-high ranking (call it best_performing) and the product name from the high-to-low ranking (worst_performing). Sort by rank, then each name in reverse alphabetical order.",
         ]),
    dict(id="t46", qnum=46, complexity="complex", bench="tpcds",
         sql="""SELECT c_last_name, c_first_name, ca_city, bought_city, ss_ticket_number, amt, profit
FROM (SELECT ss_ticket_number, ss_customer_sk, ca_city bought_city, sum(ss_coupon_amt) amt, sum(ss_net_profit) profit
      FROM store_sales, date_dim, store, household_demographics, customer_address
      WHERE store_sales.ss_sold_date_sk = date_dim.d_date_sk AND store_sales.ss_store_sk = store.s_store_sk
        AND store_sales.ss_hdemo_sk = household_demographics.hd_demo_sk AND store_sales.ss_addr_sk = customer_address.ca_address_sk
        AND (household_demographics.hd_dep_count = {dep_count} OR household_demographics.hd_vehicle_count= {vehicle_count})
        AND date_dim.d_dow IN (6, 0) AND date_dim.d_year IN ({year}, {year}+1, {year}+2) AND store.s_city IN ({cities_sql})
      GROUP BY ss_ticket_number, ss_customer_sk, ss_addr_sk, ca_city) dn,
     customer, customer_address current_addr
WHERE ss_customer_sk = c_customer_sk AND customer.c_current_addr_sk = current_addr.ca_address_sk
  AND current_addr.ca_city <> bought_city
ORDER BY c_last_name NULLS FIRST, c_first_name NULLS FIRST, ca_city NULLS FIRST, bought_city NULLS FIRST, ss_ticket_number NULLS FIRST
LIMIT 100;""",
         slots=dict(dep_count=("int", 0, 9), vehicle_count=("int", 0, 4), year=("int", 1998, 2000),
                    cities=("db_sample", _S_CITY, 2)),
         derive=dict(cities_sql=lambda p: _sql_list(p["cities"]), cities_nl=lambda p: _nl_list(p["cities"], "or"),
                     year2=lambda p: str(p["year"] + 2)),
         phrasings=[
             "Find weekend store tickets (Saturday or Sunday) from {year}-{year2} at stores in {cities_nl}, bought by households with {dep_count} dependents or {vehicle_count} vehicles, where the customer now lives in a different city than the purchase address. Show last name, first name, current city, purchase city, ticket number, total coupon amount and total net profit, sorted by last name, first name, current city, purchase city, ticket; 100 rows.",
             "Per (ss_ticket_number, ss_customer_sk, ss_addr_sk, ca_city as bought_city) sum ss_coupon_amt and ss_net_profit for d_dow IN (6, 0), d_year IN ({year}, {year}+1, {year2}), s_city IN ({cities_sql}) and (hd_dep_count = {dep_count} OR hd_vehicle_count = {vehicle_count}); join customer and current address, keep ca_city <> bought_city, output c_last_name, c_first_name, ca_city, bought_city, ss_ticket_number, amt, profit ORDER BY those five sort keys NULLS FIRST, LIMIT 100.",
             "Weekend tickets {year}-{year2}, {cities_nl} stores, {dep_count} deps or {vehicle_count} cars, buyer living elsewhere now: names, current/bought city, ticket, coupon sum, profit. Sorted, 100.",
             "I want to see weekend shoppers who were away from home. Look at store tickets rung up on Saturdays or Sundays between {year} and {year2} at our stores in {cities_nl}, where the household had {dep_count} dependents or owned {vehicle_count} vehicles. For each ticket, total the coupon amounts and net profit, and keep it only if the customer's current home city differs from the city on the sale's address. Show their last and first name, current city, the city they bought in, ticket number, coupon total and profit, sorted by last name, first name, current city, bought city and ticket, up to 100 rows.",
         ]),
    dict(id="t47", qnum=47, complexity="complex", bench="tpcds",
         sql="""WITH v1 AS
  (SELECT i_category, i_brand, s_store_name, s_company_name, d_year, d_moy, sum(ss_sales_price) sum_sales,
          avg(sum(ss_sales_price)) OVER (PARTITION BY i_category, i_brand, s_store_name, s_company_name, d_year) avg_monthly_sales,
          rank() OVER (PARTITION BY i_category, i_brand, s_store_name, s_company_name ORDER BY d_year, d_moy) rn
   FROM item, store_sales, date_dim, store
   WHERE ss_item_sk = i_item_sk AND ss_sold_date_sk = d_date_sk AND ss_store_sk = s_store_sk
     AND (d_year = {year} OR (d_year = {year}-1 AND d_moy =12) OR (d_year = {year}+1 AND d_moy =1))
   GROUP BY i_category, i_brand, s_store_name, s_company_name, d_year, d_moy),
     v2 AS
  (SELECT v1.i_category, v1.i_brand, v1.s_store_name, v1.s_company_name, v1.d_year, v1.d_moy, v1.avg_monthly_sales, v1.sum_sales,
          v1_lag.sum_sales psum, v1_lead.sum_sales nsum
   FROM v1, v1 v1_lag, v1 v1_lead
   WHERE v1.i_category = v1_lag.i_category AND v1.i_category = v1_lead.i_category AND v1.i_brand = v1_lag.i_brand
     AND v1.i_brand = v1_lead.i_brand AND v1.s_store_name = v1_lag.s_store_name AND v1.s_store_name = v1_lead.s_store_name
     AND v1.s_company_name = v1_lag.s_company_name AND v1.s_company_name = v1_lead.s_company_name
     AND v1.rn = v1_lag.rn + 1 AND v1.rn = v1_lead.rn - 1)
SELECT *
FROM v2
WHERE d_year = {year} AND avg_monthly_sales > 0
  AND CASE WHEN avg_monthly_sales > 0 THEN abs(sum_sales - avg_monthly_sales) / avg_monthly_sales ELSE NULL END > 0.1
ORDER BY sum_sales - avg_monthly_sales, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
LIMIT 100;""",
         slots=dict(year=("int", 1999, 2001)),
         derive=dict(prev=lambda p: str(p["year"] - 1), next=lambda p: str(p["year"] + 1)),
         phrasings=[
             "In {year}, which months stood out for a category/brand at a given store — monthly store sales more than 10% away from that combination's average monthly sales for the year? Show category, brand, store name, company name, year, month, average monthly sales, that month's sales, and the previous and next month's sales (using December {prev} and January {next} at the edges). Order by how far below average the month was (sales minus average, ascending), then by the other columns; 100 rows.",
             "v1: sum(ss_sales_price) by i_category, i_brand, s_store_name, s_company_name, d_year, d_moy for d_year {year} plus {prev}-12 and {next}-01, with avg over the year's months (partition by the four keys and d_year) and rank() by (d_year, d_moy). Self-join on rn - 1 / rn + 1 to get psum and nsum. Return i_category, i_brand, s_store_name, s_company_name, d_year, d_moy, avg_monthly_sales, sum_sales, psum, nsum for d_year {year} where |sum_sales - avg_monthly_sales| / avg_monthly_sales > 0.1; ORDER BY sum_sales - avg_monthly_sales, then columns 1-10; LIMIT 100.",
             "{year} months where category/brand/store monthly sales deviate >10% from the yearly monthly average, with prior/next month sales; ordered by deviation ascending; 100.",
             "I'd like to find unusual months in {year}. For each item category, brand, store and company, total the store sales price per month and compare it with that group's average month in {year}; flag any month that's off by more than ten percent either way. For the flagged months show category, brand, store name, company name, year, month, the yearly monthly average, the month's sales, and the sales of the month before and the month after — December {prev} and January {next} count as neighbours at the ends. Put the biggest shortfalls first (sales minus average, smallest first), break ties by the remaining columns, and limit it to 100.",
         ]),
    dict(id="t49", qnum=49, complexity="complex", bench="tpcds",
         sql="""SELECT channel, item, return_ratio, return_rank, currency_rank
FROM (SELECT 'web' AS channel, web.item, web.return_ratio, web.return_rank, web.currency_rank
      FROM (SELECT item, return_ratio, currency_ratio, rank() OVER (ORDER BY return_ratio) AS return_rank,
                   rank() OVER (ORDER BY currency_ratio) AS currency_rank
            FROM (SELECT ws.ws_item_sk AS item,
                         (cast(sum(coalesce(wr.wr_return_quantity,0)) AS decimal(15,4))/ cast(sum(coalesce(ws.ws_quantity,0)) AS decimal(15,4))) AS return_ratio,
                         (cast(sum(coalesce(wr.wr_return_amt,0)) AS decimal(15,4))/ cast(sum(coalesce(ws.ws_net_paid,0)) AS decimal(15,4))) AS currency_ratio
                  FROM web_sales ws LEFT OUTER JOIN web_returns wr ON (ws.ws_order_number = wr.wr_order_number AND ws.ws_item_sk = wr.wr_item_sk), date_dim
                  WHERE wr.wr_return_amt > 10000 AND ws.ws_net_profit > 1 AND ws.ws_net_paid > 0 AND ws.ws_quantity > 0
                    AND ws_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
                  GROUP BY ws.ws_item_sk) in_web) web
      WHERE (web.return_rank <= 10 OR web.currency_rank <= 10)
      UNION
      SELECT 'catalog' AS channel, catalog.item, catalog.return_ratio, catalog.return_rank, catalog.currency_rank
      FROM (SELECT item, return_ratio, currency_ratio, rank() OVER (ORDER BY return_ratio) AS return_rank,
                   rank() OVER (ORDER BY currency_ratio) AS currency_rank
            FROM (SELECT cs.cs_item_sk AS item,
                         (cast(sum(coalesce(cr.cr_return_quantity,0)) AS decimal(15,4))/ cast(sum(coalesce(cs.cs_quantity,0)) AS decimal(15,4))) AS return_ratio,
                         (cast(sum(coalesce(cr.cr_return_amount,0)) AS decimal(15,4))/ cast(sum(coalesce(cs.cs_net_paid,0)) AS decimal(15,4))) AS currency_ratio
                  FROM catalog_sales cs LEFT OUTER JOIN catalog_returns cr ON (cs.cs_order_number = cr.cr_order_number AND cs.cs_item_sk = cr.cr_item_sk), date_dim
                  WHERE cr.cr_return_amount > 10000 AND cs.cs_net_profit > 1 AND cs.cs_net_paid > 0 AND cs.cs_quantity > 0
                    AND cs_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
                  GROUP BY cs.cs_item_sk) in_cat) CATALOG
      WHERE (catalog.return_rank <= 10 OR catalog.currency_rank <=10)
      UNION
      SELECT 'store' AS channel, store.item, store.return_ratio, store.return_rank, store.currency_rank
      FROM (SELECT item, return_ratio, currency_ratio, rank() OVER (ORDER BY return_ratio) AS return_rank,
                   rank() OVER (ORDER BY currency_ratio) AS currency_rank
            FROM (SELECT sts.ss_item_sk AS item,
                         (cast(sum(coalesce(sr.sr_return_quantity,0)) AS decimal(15,4))/cast(sum(coalesce(sts.ss_quantity,0)) AS decimal(15,4))) AS return_ratio,
                         (cast(sum(coalesce(sr.sr_return_amt,0)) AS decimal(15,4))/cast(sum(coalesce(sts.ss_net_paid,0)) AS decimal(15,4))) AS currency_ratio
                  FROM store_sales sts LEFT OUTER JOIN store_returns sr ON (sts.ss_ticket_number = sr.sr_ticket_number AND sts.ss_item_sk = sr.sr_item_sk), date_dim
                  WHERE sr.sr_return_amt > 10000 AND sts.ss_net_profit > 1 AND sts.ss_net_paid > 0 AND sts.ss_quantity > 0
                    AND ss_sold_date_sk = d_date_sk AND d_year = {year} AND d_moy = {moy}
                  GROUP BY sts.ss_item_sk) in_store) store
      WHERE (store.return_rank <= 10 OR store.currency_rank <= 10)) sq1
ORDER BY 1 NULLS FIRST, 4 NULLS FIRST, 5 NULLS FIRST, 2 NULLS FIRST
LIMIT 100;""",
         slots=dict(year=("int", *YEARS), moy=("int", 1, 12)), derive=MONTH_NAME,
         phrasings=[
             "For each channel (web, catalog, store), looking at profitable sales in {month_name} {year} that had a return worth more than $10,000, rank items by return ratio (units returned / units sold) and by currency ratio (amount returned / net paid), lowest first. List items in the top 10 on either ranking: channel, item, return ratio, return rank and currency rank, ordered by channel, return rank, currency rank, item; 100 rows.",
             "Per channel, for sales with d_year = {year}, d_moy = {moy}, net_profit > 1, net_paid > 0, quantity > 0 and a matching return row with return amount > 10000: per item return_ratio = sum(return_quantity)/sum(quantity), currency_ratio = sum(return_amt)/sum(net_paid); rank() each ascending; keep return_rank <= 10 OR currency_rank <= 10. UNION the three channels as channel, item, return_ratio, return_rank, currency_rank; ORDER BY 1, 4, 5, 2 NULLS FIRST; LIMIT 100.",
             "{month_name} {year}, web/catalog/store: items in top 10 by return-qty ratio or return-amount ratio (sales with >10000 returns, profit > 1). Channel, item, ratio, both ranks; sorted; 100.",
             "I'd like a returns leaderboard for {month_name} {year}, one per channel — web, catalog and store. Only consider sales that made more than 1 in profit, had positive net paid and quantity, and came back with a return over 10,000. For each item work out the share of units returned and the share of money returned relative to net paid, rank items on each of those from smallest up, and keep anything that lands in the top ten on either list. Show the channel, item, return ratio, its return rank and its currency rank, sorted by channel, return rank, currency rank and item, max 100 rows.",
         ]),
]

TEMPLATES = sorted(_ALL, key=lambda t: t["qnum"])
BY_ID = {t["id"]: t for t in TEMPLATES}
