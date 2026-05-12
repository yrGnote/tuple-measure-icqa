#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""inject_violations.py

Inject controlled violations into a clean TPC-H DuckDB database and then export
ALL MIS (witness sets) per DC as JSONL.

Two DC sets:
  - subsetA: {DC1, DC2}
  - subsetB: {DC1, DC2, DC3, DC4}

Ratios (of a base table size) supported:
  - 0.0001 (0.01%)
  - 0.0005 (0.05%)
  - 0.001  (0.1%)

Design choices (important):
  - To reduce cross-DC interference, DC1/DC2/DC3 injections only UPDATE lineitem.
    DC4 injections UPDATE partsupp.
  - Deterministic selection uses Python's random.Random(seed) on candidate keys.
  - After injection, we export MIS by enumerating ALL violating witnesses for each DC.

JSONL format (one MIS per line):
  {"dc":"DC2","tuples":[{"table":"orders","pk":{...}}, {"table":"lineitem","pk":{...}}]}

Run example:
  python inject_violations.py \
    --clean_db /Users/Desktop/tpchdata/data/sf0.05/tpch_sf0p05.duckdb \
    --out_root /Users/Desktop/tpchdata/violations/sf0.05 \
    --seeds 1 2 3 4 5 6 7 8 9 10

"""

from __future__ import annotations

print("### RUNNING inject_violations.py FROM:", __file__)

import argparse
import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Tuple

import duckdb


# -------------------------
# DC definitions (SQL)
# -------------------------
# NOTE: These queries return the witness tuples that satisfy the body of the DC,
# i.e., violations. Each returned row is converted to one MIS.

SQL_DC1_MIS = """
SELECT
  l_orderkey::BIGINT AS l_orderkey,
  l_linenumber::BIGINT AS l_linenumber
FROM lineitem
WHERE CAST(l_receiptdate AS DATE) < CAST(l_shipdate AS DATE)
"""

SQL_DC2_MIS = """
SELECT
  o.o_orderkey::BIGINT AS o_orderkey,
  l.l_orderkey::BIGINT AS l_orderkey,
  l.l_linenumber::BIGINT AS l_linenumber
FROM orders o
JOIN lineitem l
  ON l.l_orderkey = o.o_orderkey
WHERE CAST(l.l_commitdate AS DATE) < CAST(o.o_orderdate AS DATE)
"""

SQL_DC3_MIS = """
SELECT
  o.o_orderkey::BIGINT AS o_orderkey,
  l.l_orderkey::BIGINT AS l_orderkey,
  l.l_linenumber::BIGINT AS l_linenumber
FROM orders o
JOIN lineitem l
  ON l.l_orderkey = o.o_orderkey
WHERE o.o_orderstatus = 'F'
  AND l.l_linestatus <> 'F'
"""

# New DC4 (3 relations): lineitem(l) ∧ partsupp(ps) ∧ part(p)
#  ∧ l.partkey=ps.partkey ∧ l.suppkey=ps.suppkey ∧ ps.partkey=p.partkey ∧ ps.availqty < 0
SQL_DC4_MIS = """
SELECT
  l.l_orderkey::BIGINT AS l_orderkey,
  l.l_linenumber::BIGINT AS l_linenumber,
  ps.ps_partkey::BIGINT AS ps_partkey,
  ps.ps_suppkey::BIGINT AS ps_suppkey,
  p.p_partkey::BIGINT AS p_partkey
FROM lineitem l
JOIN partsupp ps
  ON l.l_partkey = ps.ps_partkey
 AND l.l_suppkey = ps.ps_suppkey
JOIN part p
  ON ps.ps_partkey = p.p_partkey
WHERE ps.ps_availqty < 0
"""


# -------------------------
# Utilities
# -------------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def jsonl_write(path: str, records: Iterable[dict]) -> int:
    """Write records as JSONL. Returns number of lines written."""
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def count_rows(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def fetchall(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence | None = None) -> List[tuple]:
    if params is None:
        return con.execute(sql).fetchall()
    return con.execute(sql, params).fetchall()


def sample_keys(keys: List[tuple], n: int, seed: int) -> List[tuple]:
    import random

    if n <= 0 or not keys:
        return []
    n = min(n, len(keys))
    rng = random.Random(seed)
    # random.sample preserves no order; we keep it deterministic by sorting afterwards.
    picked = rng.sample(keys, n)
    return picked


def safe_ratio_count(base: int, ratio: float) -> int:
    return max(1, int(math.floor(base * ratio))) if base > 0 and ratio > 0 else 0


# -------------------------
# Injection logic
# -------------------------

@dataclass
class InjectResult:
    dc: str
    requested: int
    applied: int


def inject_dc1(con: duckdb.DuckDBPyConnection, n: int, seed: int) -> InjectResult:
    """DC1: Lineitem receiptdate must not be earlier than shipdate.

    Inject by setting receiptdate = shipdate - 1 day for selected lineitems.
    """
    candidates = fetchall(
        con,
        """
        SELECT l_orderkey::BIGINT, l_linenumber::BIGINT
        FROM lineitem
        WHERE CAST(l_receiptdate AS DATE) >= CAST(l_shipdate AS DATE)
        """,
    )
    picked = sample_keys(candidates, n, seed)
    applied = 0
    for (ok, ln) in picked:
        con.execute(
            """
            UPDATE lineitem
            SET l_receiptdate = CAST(l_shipdate AS DATE) - INTERVAL 1 DAY
            WHERE l_orderkey = ? AND l_linenumber = ?
            """,
            [ok, ln],
        )
        applied += 1
    return InjectResult("DC1", n, applied)


def inject_dc2(con: duckdb.DuckDBPyConnection, n: int, seed: int) -> InjectResult:
    """DC2: No commitment date earlier than order date (join orders-lineitem).

    Inject by setting lineitem.commitdate = orders.orderdate - 1 day for selected lineitems.
    This avoids touching orders and reduces ripple effects.
    """
    candidates = fetchall(
        con,
        """
        SELECT l.l_orderkey::BIGINT, l.l_linenumber::BIGINT
        FROM lineitem l
        JOIN orders o ON l.l_orderkey = o.o_orderkey
        WHERE CAST(l.l_commitdate AS DATE) >= CAST(o.o_orderdate AS DATE)
        """,
    )
    picked = sample_keys(candidates, n, seed)
    applied = 0
    for (ok, ln) in picked:
        con.execute(
            """
            UPDATE lineitem
            SET l_commitdate = (
                SELECT CAST(o.o_orderdate AS DATE) - INTERVAL 1 DAY
                FROM orders o
                WHERE o.o_orderkey = lineitem.l_orderkey
            )
            WHERE l_orderkey = ? AND l_linenumber = ?
            """,
            [ok, ln],
        )
        applied += 1
    return InjectResult("DC2", n, applied)


def inject_dc3(con: duckdb.DuckDBPyConnection, n: int, seed: int) -> InjectResult:
    """DC3: If an order is fulfilled (F), all its lineitems must be fulfilled (linestatus='F').

    Inject by picking lineitems whose order is already 'F' and whose linestatus is 'F',
    then flipping linestatus to 'O'.
    """
    candidates = fetchall(
        con,
        """
        SELECT l.l_orderkey::BIGINT, l.l_linenumber::BIGINT
        FROM lineitem l
        JOIN orders o ON l.l_orderkey = o.o_orderkey
        WHERE o.o_orderstatus = 'F'
          AND l.l_linestatus = 'F'
        """,
    )
    picked = sample_keys(candidates, n, seed)
    applied = 0
    for (ok, ln) in picked:
        con.execute(
            """
            UPDATE lineitem
            SET l_linestatus = 'O'
            WHERE l_orderkey = ? AND l_linenumber = ?
            """,
            [ok, ln],
        )
        applied += 1
    return InjectResult("DC3", n, applied)


def inject_DC4(con: duckdb.DuckDBPyConnection, n: int, seed: int) -> InjectResult:
    """DC4 (3 relations): lineitem(l) ∧ partsupp(ps) ∧ part(p) ∧ joins ∧ ps_availqty < 0.

    Inject by selecting partsupp tuples that are referenced by at least one lineitem and have
    non-negative availqty, then making them negative.

    This tends to create many MIS because one (ps_partkey, ps_suppkey) can be referenced by
    multiple lineitems.
    """
    candidates = fetchall(
        con,
        """
        SELECT DISTINCT ps.ps_partkey::BIGINT, ps.ps_suppkey::BIGINT
        FROM partsupp ps
        JOIN lineitem l
          ON l.l_partkey = ps.ps_partkey
         AND l.l_suppkey = ps.ps_suppkey
        JOIN part p
          ON p.p_partkey = ps.ps_partkey
        WHERE ps.ps_availqty >= 0
        """,
    )
    picked = sample_keys(candidates, n, seed)
    applied = 0
    for (pk, sk) in picked:
        con.execute(
            """
            UPDATE partsupp
            SET ps_availqty = -ABS(CAST(ps_availqty AS BIGINT)) - 1
            WHERE ps_partkey = ? AND ps_suppkey = ?
            """,
            [pk, sk],
        )
        applied += 1
    return InjectResult("DC4", n, applied)


# -------------------------
# MIS export
# -------------------------

def export_mis(con: duckdb.DuckDBPyConnection, out_dir: str, dcs: Sequence[str]) -> Dict[str, int]:
    """Export all MIS per DC into JSONL files. Returns {dc: count}."""
    ensure_dir(out_dir)

    counts: Dict[str, int] = {}

    if "DC1" in dcs:
        rows = fetchall(con, SQL_DC1_MIS)
        path = os.path.join(out_dir, "mis_DC1.jsonl")
        counts["DC1"] = jsonl_write(
            path,
            (
                {
                    "dc": "DC1",
                    "tuples": [
                        {"table": "lineitem", "pk": {"l_orderkey": int(ok), "l_linenumber": int(ln)}}
                    ],
                }
                for (ok, ln) in rows
            ),
        )

    if "DC2" in dcs:
        rows = fetchall(con, SQL_DC2_MIS)
        path = os.path.join(out_dir, "mis_DC2.jsonl")
        counts["DC2"] = jsonl_write(
            path,
            (
                {
                    "dc": "DC2",
                    "tuples": [
                        {"table": "orders", "pk": {"o_orderkey": int(o_ok)}},
                        {"table": "lineitem", "pk": {"l_orderkey": int(l_ok), "l_linenumber": int(l_ln)}},
                    ],
                }
                for (o_ok, l_ok, l_ln) in rows
            ),
        )

    if "DC3" in dcs:
        rows = fetchall(con, SQL_DC3_MIS)
        path = os.path.join(out_dir, "mis_DC3.jsonl")
        counts["DC3"] = jsonl_write(
            path,
            (
                {
                    "dc": "DC3",
                    "tuples": [
                        {"table": "orders", "pk": {"o_orderkey": int(o_ok)}},
                        {"table": "lineitem", "pk": {"l_orderkey": int(l_ok), "l_linenumber": int(l_ln)}},
                    ],
                }
                for (o_ok, l_ok, l_ln) in rows
            ),
        )

    if "DC4" in dcs:
        rows = fetchall(con, SQL_DC4_MIS)
        path = os.path.join(out_dir, "mis_DC4.jsonl")
        counts["DC4"] = jsonl_write(
            path,
            (
                {
                    "dc": "DC4",
                    "tuples": [
                        {"table": "lineitem", "pk": {"l_orderkey": int(l_ok), "l_linenumber": int(l_ln)}},
                        {"table": "partsupp", "pk": {"ps_partkey": int(ps_pk), "ps_suppkey": int(ps_sk)}},
                        {"table": "part", "pk": {"p_partkey": int(p_pk)}},
                    ],
                }
                for (l_ok, l_ln, ps_pk, ps_sk, p_pk) in rows
            ),
        )

    return counts


# -------------------------
# Orchestration
# -------------------------

RATIOS_DEFAULT = [0.0001, 0.0005, 0.001]
SUBSETS = {
    "subsetA": ["DC1", "DC2"],
    "subsetB": ["DC1", "DC2", "DC3", "DC4"],
}


def run_one(clean_db: str, out_db: str, out_dir: str, dcs: Sequence[str], ratio: float, seed: int) -> dict:
    """Copy clean DB, inject violations, export MIS, return metadata."""
    ensure_dir(os.path.dirname(out_db))
    shutil.copyfile(clean_db, out_db)

    con = duckdb.connect(out_db)

    base_lineitem = count_rows(con, "lineitem")
    base_partsupp = count_rows(con, "partsupp")

    # We use lineitem as the base size for DC1/DC2/DC3 (their witnesses contain lineitem).
    n_lineitem = safe_ratio_count(base_lineitem, ratio)
    # For DC4, we use partsupp base size (more stable), but keep the same ratio.
    n_partsupp = safe_ratio_count(base_partsupp, ratio)

    # Derive per-DC seeds deterministically from the run seed.
    # (Avoids correlated picks between DCs.)
    dc_seed = {
        "DC1": seed * 1000 + 1,
        "DC2": seed * 1000 + 2,
        "DC3": seed * 1000 + 3,
        "DC4": seed * 1000 + 4,
    }

    inject_log: List[InjectResult] = []

    if "DC1" in dcs:
        inject_log.append(inject_dc1(con, n_lineitem, dc_seed["DC1"]))
    if "DC2" in dcs:
        inject_log.append(inject_dc2(con, n_lineitem, dc_seed["DC2"]))
    if "DC3" in dcs:
        inject_log.append(inject_dc3(con, n_lineitem, dc_seed["DC3"]))
    if "DC4" in dcs:
        inject_log.append(inject_DC4(con, n_partsupp, dc_seed["DC4"]))

    # Export all MIS after injection (ground truth).
    mis_dir = os.path.join(out_dir, "mis")
    mis_counts = export_mis(con, mis_dir, dcs)

    con.close()

    meta = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "clean_db": clean_db,
        "out_db": out_db,
        "subset": list(dcs),
        "ratio": ratio,
        "seed": seed,
        "base_counts": {"lineitem": base_lineitem, "partsupp": base_partsupp},
        "requested": {
            "lineitem_based": n_lineitem,
            "partsupp_based": n_partsupp,
        },
        "injection": [{"dc": r.dc, "requested": r.requested, "applied": r.applied} for r in inject_log],
        "mis_counts": mis_counts,
        "paths": {
            "mis_dir": mis_dir,
        },
    }

    ensure_dir(out_dir)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--clean_db", required=True, help="Path to clean DuckDB file (input).")
    p.add_argument("--out_root", required=True, help="Output root directory.")
    p.add_argument("--seeds", nargs="+", type=int, required=True, help="Seeds, e.g., 1 2 ... 10")
    p.add_argument(
        "--ratios",
        nargs="+",
        type=float,
        default=RATIOS_DEFAULT,
        help="Injection ratios as floats, e.g., 0.0001 0.0005 0.001",
    )
    p.add_argument(
        "--subsets",
        nargs="+",
        default=["subsetA", "subsetB"],
        choices=list(SUBSETS.keys()),
        help="Which DC subsets to generate.",
    )
    return p.parse_args()


def ratio_tag(r: float) -> str:
    # 0.0001 -> 0p01pct, 0.0005 -> 0p05pct, 0.001 -> 0p1pct
    pct = r * 100
    if pct < 1:
        # keep two decimals if needed
        s = f"{pct:.2f}".rstrip("0").rstrip(".")
    else:
        s = f"{pct:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", "p") + "pct"


def main() -> None:
    args = parse_args()

    clean_db = os.path.abspath(args.clean_db)
    out_root = os.path.abspath(args.out_root)

    if not os.path.exists(clean_db):
        raise FileNotFoundError(f"clean_db not found: {clean_db}")

    ensure_dir(out_root)

    all_meta = []

    for subset_name in args.subsets:
        dcs = SUBSETS[subset_name]

        for r in args.ratios:
            rtag = ratio_tag(r)

            for seed in args.seeds:
                run_dir = os.path.join(out_root, subset_name, rtag, f"seed{seed:02d}")
                ensure_dir(run_dir)

                out_db = os.path.join(run_dir, f"tpch_{subset_name}_{rtag}_seed{seed:02d}.duckdb")

                meta = run_one(
                    clean_db=clean_db,
                    out_db=out_db,
                    out_dir=run_dir,
                    dcs=dcs,
                    ratio=r,
                    seed=seed,
                )

                print(
                    f"[OK] {subset_name} {rtag} seed={seed:02d}: "
                    + ", ".join([f"{k}={v}" for k, v in meta["mis_counts"].items()])
                )

                all_meta.append({"subset": subset_name, "ratio": r, "seed": seed, "run_dir": run_dir})

    with open(os.path.join(out_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
