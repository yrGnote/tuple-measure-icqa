import os
import duckdb
import argparse

DEFAULT_DATA_DIR = "/Users/Desktop/tpchdata/data/sf0.05"
DEFAULT_DB_PATH  = "/Users/Desktop/tpchdata/data/sf0.05/tpch_sf0p05.duckdb"

def ensure_db(data_dir, db_path, rebuild):
    # ensure_db / build_duckdb_from_tbl 
    if rebuild or (not os.path.exists(db_path)):
        raise RuntimeError("DB not found or rebuild requested, please rebuild using your build function.")
    print(f"[OK] Reusing existing DuckDB database: {db_path}")

def count_violations(con, sql):
    return con.execute(sql).fetchone()[0]

def main():
    parser = argparse.ArgumentParser(add_help=True)

    parser.add_argument("--data_dir", type=str, default=DEFAULT_DATA_DIR)
    parser.add_argument("--db_path",  type=str, default=DEFAULT_DB_PATH)
    parser.add_argument("--rebuild", action="store_true")

    args = parser.parse_args()

    data_dir = args.data_dir
    db_path  = args.db_path

    print(f"DATA_DIR = {data_dir}")
    print(f"DB_PATH  = {db_path}")

    ensure_db(data_dir, db_path, args.rebuild)

    con = duckdb.connect(db_path)
    try:
        dcs = [
            ("DC1_receipt_before_ship",
             "SELECT COUNT(*) FROM lineitem WHERE l_receiptdate < l_shipdate;"),
            ("DC2_commit_before_orderdate",
             """SELECT COUNT(*) FROM orders o JOIN lineitem l
                ON l.l_orderkey=o.o_orderkey
                WHERE l.l_commitdate < o.o_orderdate;"""),
            ("DC3_order_F_but_line_not_F",
             """SELECT COUNT(*) FROM orders o JOIN lineitem l
                ON l.l_orderkey=o.o_orderkey
                WHERE o.o_orderstatus='F' AND l.l_linestatus<>'F';"""),
            ("DC4_customer_region_chain_invalid",
             """SELECT COUNT(*) FROM customer c
                JOIN nation n ON c.c_nationkey=n.n_nationkey
                JOIN region r ON n.n_regionkey=r.r_regionkey
                WHERE r.r_regionkey < 0;"""),
            ("DC5_negative_partsupp_availqty",
             """SELECT COUNT(*) FROM lineitem l
                JOIN partsupp ps
                  ON l.l_partkey=ps.ps_partkey AND l.l_suppkey=ps.ps_suppkey
                WHERE ps.ps_availqty < 0;"""),
        ]

        all_ok = True
        for name, sql in dcs:
            vio = count_violations(con, sql)
            print(f"{name}: {'OK' if vio==0 else 'VIOLATED'} ({vio})")
            if vio != 0:
                all_ok = False

        print()
        print("All DCs satisfied on current SF." if all_ok else "Some DCs are violated.")
    finally:
        con.close()

if __name__ == "__main__":
    main()
