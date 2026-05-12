#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extract SUPPORT SETS (with answer value, pk, support_id) for TPC-H Q1–Q5
from all DuckDB databases under `VIOLATIONS_BASE`.

For each DB file and each query, we generate one parquet file:

   <Q>_support.parquet

schema (per-DB file):

    scale       STRING  -- e.g., 'sf0.1'
    subset      STRING  -- 'subsetA' / 'subsetB'
    ratio       STRING  -- '0p01pct' / '0p05pct' / '0p1pct'
    seed        STRING  -- 'seed01'..'seed10'
    qname       STRING  -- 'Q1'..'Q5'
    answer_id   BIGINT
    support_id  BIGINT
    answervalue VARCHAR
    rel         VARCHAR
    key1..key4  BIGINT (some NULL)
    pk          VARCHAR -- primary key string used in tuple_measures

Directory example:

violations/sf0.1/subsetB/0p01pct/seed09/tpch_subsetB_0p01pct_seed09.duckdb
 → support_sets/sf0.1/subsetB/0p01pct/seed09/Q5_support.parquet

Additionally, we build a merged file:

    support_sets/all_support_sets.parquet

which is simply the union (via DuckDB) of all per-DB files above.
"""

from __future__ import annotations

import duckdb
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VIOLATIONS_BASE = Path("/Users/Desktop/tpchdata/violations")
SUPPORT_BASE    = Path("/Users/Desktop/tpchdata/support_sets")
MERGED_OUT      = SUPPORT_BASE / "all_support_sets.parquet"

QUERIES = ["Q1", "Q2", "Q3", "Q4", "Q5"]

TPCH_SUPPORT_SQL: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Q1–Q5 SQL (without meta，meta wraps a layer outside)
# ---------------------------------------------------------------------------

TPCH_SUPPORT_SQL["Q1"] = r"""
WITH base AS (
    SELECT
        o_orderkey,
        o_orderpriority
    FROM orders
    WHERE o_orderpriority IN ('1-URGENT', '2-HIGH', '3-MEDIUM')
      AND o_orderdate >= DATE '1995-03-01'
      AND o_orderdate <  DATE '1995-03-11'
      AND o_totalprice > 70000
),
answers AS (
    SELECT DISTINCT
        o_orderpriority AS answervalue
    FROM base
),
ranked AS (
    SELECT
        answervalue,
        ROW_NUMBER() OVER (ORDER BY answervalue) AS answer_id
    FROM answers
),
witnesses AS (
    SELECT
        r.answer_id,
        r.answervalue,
        ROW_NUMBER() OVER (
            PARTITION BY r.answer_id
            ORDER BY b.o_orderkey
        ) AS support_id,
        b.o_orderkey
    FROM ranked r
    JOIN base   b ON b.o_orderpriority = r.answervalue
),
orders_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'orders' AS rel,
        o_orderkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
support_flat AS (
    SELECT * FROM orders_support
)
SELECT
    'Q1' AS qname,
    answer_id,
    support_id,
    answervalue::VARCHAR AS answervalue,
    rel,
    key1,
    key2,
    key3,
    key4,
    CAST(key1 AS VARCHAR) AS pk
FROM support_flat
ORDER BY answer_id, support_id, rel, key1, key2;
"""

TPCH_SUPPORT_SQL["Q2"] = r"""
WITH base AS (
    SELECT
        o.o_orderkey,
        l.l_orderkey,
        l.l_linenumber,
        l.l_shipmode
    FROM orders   AS o
    JOIN lineitem AS l
      ON l.l_orderkey = o.o_orderkey
    WHERE l.l_shipmode IN ('AIR', 'SHIP', 'TRUCK', 'MAIL')
      AND o.o_orderdate >= DATE '1995-03-15'
      AND o.o_orderdate <  DATE '1995-03-18'
      AND l.l_quantity > 30
      AND l.l_discount BETWEEN 0.04 AND 0.08
      AND l.l_shipinstruct IN ('DELIVER IN PERSON', 'COLLECT COD')
),
answers AS (
    SELECT DISTINCT
        l_shipmode AS answervalue
    FROM base
),
ranked AS (
    SELECT
        answervalue,
        ROW_NUMBER() OVER (ORDER BY answervalue) AS answer_id
    FROM answers
),
witnesses AS (
    SELECT
        r.answer_id,
        r.answervalue,
        ROW_NUMBER() OVER (
            PARTITION BY r.answer_id
            ORDER BY b.o_orderkey, b.l_orderkey, b.l_linenumber
        ) AS support_id,
        b.o_orderkey,
        b.l_orderkey,
        b.l_linenumber
    FROM ranked r
    JOIN base   b ON b.l_shipmode = r.answervalue
),
orders_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'orders' AS rel,
        o_orderkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
lineitem_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'lineitem' AS rel,
        l_orderkey::BIGINT   AS key1,
        l_linenumber::BIGINT AS key2,
        NULL::BIGINT         AS key3,
        NULL::BIGINT         AS key4
    FROM witnesses
),
support_flat AS (
    SELECT * FROM orders_support
    UNION ALL
    SELECT * FROM lineitem_support
)
SELECT
    'Q2' AS qname,
    answer_id,
    support_id,
    answervalue::VARCHAR AS answervalue,
    rel,
    key1,
    key2,
    key3,
    key4,
    CASE
        WHEN rel = 'lineitem' THEN
            CAST(key1 AS VARCHAR) || ',' || CAST(key2 AS VARCHAR)
        ELSE
            CAST(key1 AS VARCHAR)
    END AS pk
FROM support_flat
ORDER BY answer_id, support_id, rel, key1, key2;
"""

TPCH_SUPPORT_SQL["Q3"] = r"""
WITH base AS (
    SELECT
        c.c_custkey,
        o.o_orderkey,
        n.n_nationkey,
        n.n_name
    FROM customer AS c
    JOIN orders   AS o ON o.o_custkey   = c.c_custkey
    JOIN nation   AS n ON n.n_nationkey = c.c_nationkey
    WHERE n.n_name IN ('FRANCE', 'GERMANY', 'BRAZIL', 'CANADA')
      AND c.c_mktsegment IN ('AUTOMOBILE', 'MACHINERY')
      AND o.o_orderdate >= DATE '1995-01-01'
      AND o.o_orderdate <  DATE '1995-01-11'
),
answers AS (
    SELECT DISTINCT
        n_name AS answervalue
    FROM base
),
ranked AS (
    SELECT
        answervalue,
        ROW_NUMBER() OVER (ORDER BY answervalue) AS answer_id
    FROM answers
),
witnesses AS (
    SELECT
        r.answer_id,
        r.answervalue,
        ROW_NUMBER() OVER (
            PARTITION BY r.answer_id
            ORDER BY b.c_custkey, b.o_orderkey, b.n_nationkey
        ) AS support_id,
        b.c_custkey,
        b.o_orderkey,
        b.n_nationkey
    FROM ranked r
    JOIN base   b ON b.n_name = r.answervalue
),
customer_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'customer' AS rel,
        c_custkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
orders_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'orders' AS rel,
        o_orderkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
nation_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'nation' AS rel,
        n_nationkey::BIGINT AS key1,
        NULL::BIGINT       AS key2,
        NULL::BIGINT       AS key3,
        NULL::BIGINT       AS key4
    FROM witnesses
),
support_flat AS (
    SELECT * FROM customer_support
    UNION ALL
    SELECT * FROM orders_support
    UNION ALL
    SELECT * FROM nation_support
)
SELECT
    'Q3' AS qname,
    answer_id,
    support_id,
    answervalue::VARCHAR AS answervalue,
    rel,
    key1,
    key2,
    key3,
    key4,
    CAST(key1 AS VARCHAR) AS pk
FROM support_flat
ORDER BY answer_id, support_id, rel, key1, key2;
"""

TPCH_SUPPORT_SQL["Q4"] = r"""
WITH base AS (
    SELECT
        o.o_orderkey,
        l.l_orderkey,
        l.l_linenumber,
        s.s_suppkey,
        n.n_nationkey,
        n.n_name
    FROM orders   AS o
    JOIN lineitem AS l ON l.l_orderkey  = o.o_orderkey
    JOIN supplier AS s ON s.s_suppkey   = l.l_suppkey
    JOIN nation   AS n ON n.n_nationkey = s.s_nationkey
    WHERE n.n_name IN ('FRANCE', 'GERMANY', 'BRAZIL')
      AND o.o_orderdate >= DATE '1995-02-01'
      AND o.o_orderdate <  DATE '1995-02-06'
      AND l.l_quantity BETWEEN 25 AND 80
      AND l.l_shipdate < DATE '1995-03-15'
      AND s.s_acctbal >= -500
),
answers AS (
    SELECT DISTINCT
        n_name AS answervalue
    FROM base
),
ranked AS (
    SELECT
        answervalue,
        ROW_NUMBER() OVER (ORDER BY answervalue) AS answer_id
    FROM answers
),
witnesses AS (
    SELECT
        r.answer_id,
        r.answervalue,
        ROW_NUMBER() OVER (
            PARTITION BY r.answer_id
            ORDER BY b.o_orderkey, b.l_orderkey, b.l_linenumber, b.s_suppkey, b.n_nationkey
        ) AS support_id,
        b.o_orderkey,
        b.l_orderkey,
        b.l_linenumber,
        b.s_suppkey,
        b.n_nationkey
    FROM ranked r
    JOIN base   b ON b.n_name = r.answervalue
),
orders_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'orders' AS rel,
        o_orderkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
lineitem_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'lineitem' AS rel,
        l_orderkey::BIGINT   AS key1,
        l_linenumber::BIGINT AS key2,
        NULL::BIGINT         AS key3,
        NULL::BIGINT         AS key4
    FROM witnesses
),
supplier_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'supplier' AS rel,
        s_suppkey::BIGINT AS key1,
        NULL::BIGINT     AS key2,
        NULL::BIGINT     AS key3,
        NULL::BIGINT     AS key4
    FROM witnesses
),
nation_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'nation' AS rel,
        n_nationkey::BIGINT AS key1,
        NULL::BIGINT       AS key2,
        NULL::BIGINT       AS key3,
        NULL::BIGINT       AS key4
    FROM witnesses
),
support_flat AS (
    SELECT * FROM orders_support
    UNION ALL
    SELECT * FROM lineitem_support
    UNION ALL
    SELECT * FROM supplier_support
    UNION ALL
    SELECT * FROM nation_support
)
SELECT
    'Q4' AS qname,
    answer_id,
    support_id,
    answervalue::VARCHAR AS answervalue,
    rel,
    key1,
    key2,
    key3,
    key4,
    CASE
        WHEN rel = 'lineitem' THEN
            CAST(key1 AS VARCHAR) || ',' || CAST(key2 AS VARCHAR)
        ELSE
            CAST(key1 AS VARCHAR)
    END AS pk
FROM support_flat
ORDER BY answer_id, support_id, rel, key1, key2;
"""

TPCH_SUPPORT_SQL["Q5"] = r"""
WITH base AS (
    SELECT
        o.o_orderkey,
        l.l_orderkey,
        l.l_linenumber,
        s.s_suppkey,
        n.n_nationkey,
        r.r_regionkey,
        r.r_name
    FROM orders   AS o
    JOIN lineitem AS l ON l.l_orderkey  = o.o_orderkey
    JOIN supplier AS s ON s.s_suppkey   = l.l_suppkey
    JOIN nation   AS n ON n.n_nationkey = s.s_nationkey
    JOIN region   AS r ON r.r_regionkey = n.n_regionkey
    WHERE r.r_name IN ('EUROPE', 'ASIA', 'AMERICA', 'AFRICA')
      AND o.o_orderdate >= DATE '1995-04-01'
      AND o.o_orderdate <  DATE '1995-04-06'
      AND l.l_quantity > 25
      AND l.l_discount BETWEEN 0.02 AND 0.08
      AND l.l_shipmode IN ('AIR', 'TRUCK', 'SHIP')
),
answers AS (
    SELECT DISTINCT
        r_name AS answervalue
    FROM base
),
ranked AS (
    SELECT
        answervalue,
        ROW_NUMBER() OVER (ORDER BY answervalue) AS answer_id
    FROM answers
),
witnesses AS (
    SELECT
        r.answer_id,
        r.answervalue,
        ROW_NUMBER() OVER (
            PARTITION BY r.answer_id
            ORDER BY b.o_orderkey, b.l_orderkey, b.l_linenumber,
                     b.s_suppkey, b.n_nationkey, b.r_regionkey
        ) AS support_id,
        b.o_orderkey,
        b.l_orderkey,
        b.l_linenumber,
        b.s_suppkey,
        b.n_nationkey,
        b.r_regionkey
    FROM ranked r
    JOIN base   b ON b.r_name = r.answervalue
),
orders_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'orders' AS rel,
        o_orderkey::BIGINT AS key1,
        NULL::BIGINT      AS key2,
        NULL::BIGINT      AS key3,
        NULL::BIGINT      AS key4
    FROM witnesses
),
lineitem_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'lineitem' AS rel,
        l_orderkey::BIGINT   AS key1,
        l_linenumber::BIGINT AS key2,
        NULL::BIGINT         AS key3,
        NULL::BIGINT         AS key4
    FROM witnesses
),
supplier_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'supplier' AS rel,
        s_suppkey::BIGINT AS key1,
        NULL::BIGINT     AS key2,
        NULL::BIGINT     AS key3,
        NULL::BIGINT     AS key4
    FROM witnesses
),
nation_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'nation' AS rel,
        n_nationkey::BIGINT AS key1,
        NULL::BIGINT       AS key2,
        NULL::BIGINT       AS key3,
        NULL::BIGINT       AS key4
    FROM witnesses
),
region_support AS (
    SELECT DISTINCT
        answer_id,
        support_id,
        answervalue,
        'region' AS rel,
        r_regionkey::BIGINT AS key1,
        NULL::BIGINT       AS key2,
        NULL::BIGINT       AS key3,
        NULL::BIGINT       AS key4
    FROM witnesses
),
support_flat AS (
    SELECT * FROM orders_support
    UNION ALL
    SELECT * FROM lineitem_support
    UNION ALL
    SELECT * FROM supplier_support
    UNION ALL
    SELECT * FROM nation_support
    UNION ALL
    SELECT * FROM region_support
)
SELECT
    'Q5' AS qname,
    answer_id,
    support_id,
    answervalue::VARCHAR AS answervalue,
    rel,
    key1,
    key2,
    key3,
    key4,
    CASE
        WHEN rel = 'lineitem' THEN
            CAST(key1 AS VARCHAR) || ',' || CAST(key2 AS VARCHAR)
        ELSE
            CAST(key1 AS VARCHAR)
    END AS pk
FROM support_flat
ORDER BY answer_id, support_id, rel, key1, key2;
"""






# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iter_duckdb_files(base: Path):
    return base.rglob("*.duckdb")


def derive_output_path_and_meta(db_path: Path):
    """
    violations/sf0.1/subsetB/0p01pct/seed09/tpch_...duckdb
      -> support_sets/sf0.1/subsetB/0p01pct/seed09/
    """
    rel = db_path.relative_to(VIOLATIONS_BASE)
    if len(rel.parts) < 5:
        raise ValueError(f"Unexpected DB path: {db_path}")
    sf, subset, ratio, seed_dir = rel.parts[:4]
    out_dir = SUPPORT_BASE / sf / subset / ratio / seed_dir
    meta = {
        "scale": sf,
        "subset": subset,
        "ratio": ratio,
        "seed": seed_dir,
    }
    return out_dir, meta


def extract_for_db(db_path: Path):
    out_dir, meta = derive_output_path_and_meta(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"== DB: {db_path} -> {out_dir}")
    con = duckdb.connect(str(db_path))

    for qname in QUERIES:
        sql_inner = TPCH_SUPPORT_SQL[qname].strip().rstrip(";")

        # Add meta outside SQL
        sql_with_meta = f"""
        SELECT
            '{meta['scale']}'  AS scale,
            '{meta['subset']}' AS subset,
            '{meta['ratio']}'  AS ratio,
            '{meta['seed']}'   AS seed,
            s.*
        FROM ({sql_inner}) AS s
        """

        out_file = out_dir / f"{qname}_support.parquet"
        print(f"  [RUN ] {qname} -> {out_file.name}")

        copy_sql = f"COPY ({sql_with_meta}) TO '{out_file.as_posix()}' (FORMAT PARQUET);"
        con.execute(copy_sql)

    con.close()


def build_merged():
    """
    Use DuckDB union per-DB parquet
    """
    pattern = (SUPPORT_BASE / "sf*/subset*/0p*pct/seed*/Q*_support.parquet").as_posix()
    print(f"[MERGE] reading from pattern: {pattern}")
    con = duckdb.connect()
    merge_sql = f"""
    COPY (
        SELECT *
        FROM read_parquet('{pattern}')
    ) TO '{MERGED_OUT.as_posix()}' (FORMAT PARQUET);
    """
    con.execute(merge_sql)
    con.close()
    print(f"[MERGE] written merged file: {MERGED_OUT}")


def main():
    SUPPORT_BASE.mkdir(parents=True, exist_ok=True)

    db_files = sorted(iter_duckdb_files(VIOLATIONS_BASE))
    if not db_files:
        print(f"No DuckDB files under {VIOLATIONS_BASE}")
        return

    print(f"Found {len(db_files)} DuckDB files.")
    for db_path in db_files:
        extract_for_db(db_path)

    # merge
    build_merged()


if __name__ == "__main__":
    main()
