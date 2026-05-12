#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import duckdb

def build_one(con: duckdb.DuckDBPyConnection, data_dir: str, table: str, create_sql: str):
    path = os.path.join(data_dir, f"{table}.tbl")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing file: {path}")
    con.execute(create_sql, {"path": path})

def build_tpch_duckdb(data_dir: str, db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # overwrite existing DB
    if os.path.exists(db_path):
        os.remove(db_path)

    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=4;")

    # -----------------------
    # region (3 + dummy)
    # -----------------------
    build_one(con, data_dir, "region", r"""
        CREATE TABLE region AS
        SELECT
            CAST(c1 AS BIGINT)  AS r_regionkey,
            c2                  AS r_name,
            c3                  AS r_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR'}
        );
    """)

    # -----------------------
    # nation (4 + dummy)
    # -----------------------
    build_one(con, data_dir, "nation", r"""
        CREATE TABLE nation AS
        SELECT
            CAST(c1 AS BIGINT)  AS n_nationkey,
            c2                  AS n_name,
            CAST(c3 AS BIGINT)  AS n_regionkey,
            c4                  AS n_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR'}
        );
    """)

    # -----------------------
    # supplier (7 + dummy)
    # -----------------------
    build_one(con, data_dir, "supplier", r"""
        CREATE TABLE supplier AS
        SELECT
            CAST(c1 AS BIGINT)  AS s_suppkey,
            c2                  AS s_name,
            c3                  AS s_address,
            CAST(c4 AS BIGINT)  AS s_nationkey,
            c5                  AS s_phone,
            CAST(c6 AS DOUBLE)  AS s_acctbal,
            c7                  AS s_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR','c6':'VARCHAR','c7':'VARCHAR','c8':'VARCHAR'}
        );
    """)

    # -----------------------
    # customer (8 + dummy)
    # -----------------------
    build_one(con, data_dir, "customer", r"""
        CREATE TABLE customer AS
        SELECT
            CAST(c1 AS BIGINT)  AS c_custkey,
            c2                  AS c_name,
            c3                  AS c_address,
            CAST(c4 AS BIGINT)  AS c_nationkey,
            c5                  AS c_phone,
            CAST(c6 AS DOUBLE)  AS c_acctbal,
            c7                  AS c_mktsegment,
            c8                  AS c_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR','c6':'VARCHAR','c7':'VARCHAR','c8':'VARCHAR','c9':'VARCHAR'}
        );
    """)

    # -----------------------
    # part (9 + dummy)
    # -----------------------
    build_one(con, data_dir, "part", r"""
        CREATE TABLE part AS
        SELECT
            CAST(c1 AS BIGINT)  AS p_partkey,
            c2                  AS p_name,
            c3                  AS p_mfgr,
            c4                  AS p_brand,
            c5                  AS p_type,
            CAST(c6 AS BIGINT)  AS p_size,
            c7                  AS p_container,
            CAST(c8 AS DOUBLE)  AS p_retailprice,
            c9                  AS p_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR','c6':'VARCHAR','c7':'VARCHAR','c8':'VARCHAR','c9':'VARCHAR','c10':'VARCHAR'}
        );
    """)

    # -----------------------
    # partsupp (5 + dummy)
    # -----------------------
    build_one(con, data_dir, "partsupp", r"""
        CREATE TABLE partsupp AS
        SELECT
            CAST(c1 AS BIGINT)  AS ps_partkey,
            CAST(c2 AS BIGINT)  AS ps_suppkey,
            CAST(c3 AS BIGINT)  AS ps_availqty,
            CAST(c4 AS DOUBLE)  AS ps_supplycost,
            c5                  AS ps_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR','c6':'VARCHAR'}
        );
    """)

    # -----------------------
    # orders (9 + dummy)
    # -----------------------
    build_one(con, data_dir, "orders", r"""
        CREATE TABLE orders AS
        SELECT
            CAST(c1 AS BIGINT)  AS o_orderkey,
            CAST(c2 AS BIGINT)  AS o_custkey,
            c3                  AS o_orderstatus,
            CAST(c4 AS DOUBLE)  AS o_totalprice,
            CAST(c5 AS DATE)    AS o_orderdate,
            c6                  AS o_orderpriority,
            c7                  AS o_clerk,
            CAST(c8 AS BIGINT)  AS o_shippriority,
            c9                  AS o_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR','c5':'VARCHAR','c6':'VARCHAR','c7':'VARCHAR','c8':'VARCHAR','c9':'VARCHAR','c10':'VARCHAR'}
        );
    """)

    # -----------------------
    # lineitem (16 + dummy)
    # -----------------------
    build_one(con, data_dir, "lineitem", r"""
        CREATE TABLE lineitem AS
        SELECT
            CAST(c1 AS BIGINT)   AS l_orderkey,
            CAST(c2 AS BIGINT)   AS l_partkey,
            CAST(c3 AS BIGINT)   AS l_suppkey,
            CAST(c4 AS BIGINT)   AS l_linenumber,
            CAST(c5 AS DOUBLE)   AS l_quantity,
            CAST(c6 AS DOUBLE)   AS l_extendedprice,
            CAST(c7 AS DOUBLE)   AS l_discount,
            CAST(c8 AS DOUBLE)   AS l_tax,
            c9                   AS l_returnflag,
            c10                  AS l_linestatus,
            CAST(c11 AS DATE)    AS l_shipdate,
            CAST(c12 AS DATE)    AS l_commitdate,
            CAST(c13 AS DATE)    AS l_receiptdate,
            c14                  AS l_shipinstruct,
            c15                  AS l_shipmode,
            c16                  AS l_comment
        FROM read_csv($path,
            delim='|', header=false,
            columns={
              'c1':'VARCHAR','c2':'VARCHAR','c3':'VARCHAR','c4':'VARCHAR',
              'c5':'VARCHAR','c6':'VARCHAR','c7':'VARCHAR','c8':'VARCHAR',
              'c9':'VARCHAR','c10':'VARCHAR','c11':'VARCHAR','c12':'VARCHAR',
              'c13':'VARCHAR','c14':'VARCHAR','c15':'VARCHAR','c16':'VARCHAR','c17':'VARCHAR'
            }
        );
    """)

    # Helpful indexes (optional, but speeds up joins)
    con.execute("CREATE INDEX idx_orders_orderkey ON orders(o_orderkey);")
    con.execute("CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey);")
    con.execute("CREATE INDEX idx_customer_custkey ON customer(c_custkey);")
    con.execute("CREATE INDEX idx_nation_nationkey ON nation(n_nationkey);")
    con.execute("CREATE INDEX idx_region_regionkey ON region(r_regionkey);")
    con.execute("CREATE INDEX idx_partsupp_pair ON partsupp(ps_partkey, ps_suppkey);")

    con.close()
    print(f"[OK] Built DuckDB database: {db_path}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--db_path", required=True)
    args = ap.parse_args()
    build_tpch_duckdb(args.data_dir, args.db_path)

if __name__ == "__main__":
    main()
