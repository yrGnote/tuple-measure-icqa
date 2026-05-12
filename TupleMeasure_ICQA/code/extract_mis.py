#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_mis.py

Purpose
-------
Extract all Minimal Inconsistent Sets (MIS) per Denial Constraint (DC)
from a violated TPC-H DuckDB database.

Supported DCs
-------------
DC1, DC2, DC3, DC4 (as defined in the paper / discussion)

Output
------
For each DC, a JSON file containing a list of MIS.
Each MIS is represented as a mapping from relation name to primary keys.

Example MIS entry:
{
  "dc": "DC2",
  "tuples": {
    "orders": [123],
    "lineitem": [456]
  }
}
"""

import os
import json
import argparse
import duckdb

# =========================
# DC SQL DEFINITIONS
# =========================

DC_QUERIES = {
    "DC1": {
        "sql": """
        SELECT
            l.l_orderkey AS orderkey,
            l.l_linenumber AS linenumber
        FROM lineitem l
        WHERE l.l_receiptdate < l.l_shipdate
        """,
        "builder": lambda r: {
            "lineitem": [(r[0], r[1])]
        }
    },

    "DC2": {
        "sql": """
        SELECT
            o.o_orderkey,
            l.l_orderkey,
            l.l_linenumber
        FROM orders o
        JOIN lineitem l
          ON l.l_orderkey = o.o_orderkey
        WHERE l.l_commitdate < o.o_orderdate
        """,
        "builder": lambda r: {
            "orders": [r[0]],
            "lineitem": [(r[1], r[2])]
        }
    },

    "DC3": {
        "sql": """
        SELECT
            o.o_orderkey,
            l.l_orderkey,
            l.l_linenumber
        FROM orders o
        JOIN lineitem l
          ON l.l_orderkey = o.o_orderkey
        WHERE o.o_orderstatus = 'F'
          AND l.l_linestatus <> 'F'
        """,
        "builder": lambda r: {
            "orders": [r[0]],
            "lineitem": [(r[1], r[2])]
        }
    },

    "DC4": {
        "sql": """
        SELECT
            l.l_orderkey,
            l.l_linenumber,
            ps.ps_partkey,
            ps.ps_suppkey,
            p.p_partkey
        FROM lineitem l
        JOIN partsupp ps
          ON l.l_partkey = ps.ps_partkey
         AND l.l_suppkey = ps.ps_suppkey
        JOIN part p
          ON ps.ps_partkey = p.p_partkey
        WHERE ps.ps_availqty < 0
        """,
        "builder": lambda r: {
            "lineitem": [(r[0], r[1])],
            "partsupp": [(r[2], r[3])],
            "part": [r[4]]
        }
    }
}


# =========================
# EXTRACTION LOGIC
# =========================

def extract_mis(con, dc_name, dc_def, out_dir):
    """Extract all MIS for a single DC and write to JSON."""

    print(f"[INFO] Extracting MIS for {dc_name} ...")

    rows = con.execute(dc_def["sql"]).fetchall()

    mis_list = []
    for r in rows:
        mis = {
            "dc": dc_name,
            "tuples": dc_def["builder"](r)
        }
        mis_list.append(mis)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{dc_name}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mis_list, f, indent=2)

    print(f"[OK] {dc_name}: {len(mis_list)} MIS written to {out_path}")


# =========================
# MAIN
# =========================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to violated DuckDB database")
    parser.add_argument("--out", required=True, help="Output directory for MIS JSON files")
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=True)

    for dc_name, dc_def in DC_QUERIES.items():
        extract_mis(con, dc_name, dc_def, args.out)

    con.close()
    print("[DONE] MIS extraction completed.")


if __name__ == "__main__":
    main()
