#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compute answer-level ICQA using exact minimal hitting-set responsibility.

For each answer (scale,subset,ratio,seed,qname,answer_id):

  - Let S = { Gamma_1, ..., Gamma_k } be its family of minimal supports
    (each Gamma_i is a set of tuples t identified by (rel, pk)).

  - For each tuple t in union S:
        S^-t = { Gamma in S | t not in Gamma }
        h*_t = min |H|, H hitting set for S^-t
        rho(t) = 1 / (1 + h*_t)

  - Then, for each tuple-level measure im_m:
        ICQA_resp^m(q, alpha) = sum_t rho(t) * im_m(t)

input：
  - support set :
      /Users/Desktop/tpchdata/support_sets/all_support_sets.parquet
  - tuple-level inconsistency measures:
      /Users/Desktop/tpchdata/outputs/scores/tuple_measures.parquet

output：
  - /Users/Desktop/tpchdata/outputs/icqa/icqa_resp.parquet
"""

from pathlib import Path
import time
from typing import List, Set, Dict, Any

import duckdb
import pandas as pd

from pysat.solvers import Glucose4
from pysat.card import CardEnc

BASE = Path("/Users/Desktop/tpchdata")

SUPPORT_ALL_FILE = BASE / "support_sets" / "all_support_sets.parquet"
TUPLE_MEASURES_FILE = BASE / "outputs" / "scores" / "tuple_measures.parquet"

OUT_DIR  = BASE / "outputs" / "icqa"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "icqa_resp.parquet"

QUERIES  = ["Q1", "Q2", "Q3", "Q4", "Q5"]
MEASURES = ["CBM", "CIM", "PIM", "RIM"]


def min_hitting_set_size_for_t(
    support_sets: List[Set[int]],
    universe_size: int,
    t_idx: int,
) -> int:
    """
    For support_sets on Universe = {0..n-1} 
    For fixed tuple index t_idx, compute the size of S^-t minimal hitting set:

        S^-t = { S in support_sets | t_idx not in S }

    if S^-t empty, return 0。
    PySAT + Glucose4
    """
    sets_minus_t = [S for S in support_sets if t_idx not in S]
    if not sets_minus_t:
        return 0

    n = universe_size

    def var(i: int) -> int:
        # PySAT from 1
        return i + 1

    for k in range(0, n + 1):
        with Glucose4(bootstrap_with=[]) as solver:
            # each S in S^-t: OR_{i in S} x_i
            for S in sets_minus_t:
                if not S:
                    # EEmpty set must be hit, return 0 directly
                    return 0
                solver.add_clause([var(i) for i in S])

            # sum x_i <= k
            card = CardEnc.atmost(
                lits=[var(i) for i in range(n)],
                bound=k,
            )
            for cl in card.clauses:
                solver.add_clause(cl)

            if solver.solve():
                return k

    return n


def compute_resp_for_query(
    scale: str,
    subset: str,
    ratio: str,
    seed: str,
    qname: str,
    support_q: pd.DataFrame,
    tm_db: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """
    for all answers of one (scale,subset,ratio,seed,qname) pair，
    compute exact responsibility-based ICQA。
    """
    if "support_id" not in support_q.columns:
        raise ValueError("support_q miss 'support_id' ")

    df = support_q.copy()
    df["relation"] = df["rel"].astype(str)
    df["pk"]       = df["pk"].astype(str)

    out_rows: List[Dict[str, Any]] = []

    answers = df[["answer_id", "answervalue"]].drop_duplicates().reset_index(drop=True)
    n_ans   = len(answers)
    print(f"      [RESP] answers = {n_ans}")

    for idx_ans, row_ans in answers.iterrows():
        answer_id = row_ans["answer_id"]
        ans_val   = row_ans["answervalue"]

        sup_ans = df[df["answer_id"] == answer_id].copy()
        sup_ans["tuple_id"] = sup_ans["relation"] + "#" + sup_ans["pk"]

        uniq_tuples = sup_ans["tuple_id"].drop_duplicates().tolist()
        tid2idx = {tid: i for i, tid in enumerate(uniq_tuples)}
        n = len(uniq_tuples)

        support_sets: List[Set[int]] = []
        for _, g in sup_ans.groupby("support_id"):
            S = {tid2idx[tid] for tid in g["tuple_id"]}
            if S:
                support_sets.append(S)

        if n == 0 or not support_sets:
            out_rows.append({
                "scale":  scale,
                "subset": subset,
                "ratio":  ratio,
                "seed":   seed,
                "qname":  qname,
                "answer_id":   int(answer_id),
                "answervalue": ans_val,
                "icqa_resp_cbm": 0.0,
                "icqa_resp_cim": 0.0,
                "icqa_resp_pim": 0.0,
                "icqa_resp_rim": 0.0,
            })
            continue

        tuple_meta = sup_ans[["relation", "pk", "tuple_id"]].drop_duplicates()
        tm_ans = tm_db.merge(tuple_meta, on=["relation", "pk"], how="inner")
        if tm_ans.empty:
            out_rows.append({
                "scale":  scale,
                "subset": subset,
                "ratio":  ratio,
                "seed":   seed,
                "qname":  qname,
                "answer_id":   int(answer_id),
                "answervalue": ans_val,
                "icqa_resp_cbm": 0.0,
                "icqa_resp_cim": 0.0,
                "icqa_resp_pim": 0.0,
                "icqa_resp_rim": 0.0,
            })
            continue

        if (idx_ans % 5) == 0:
            print(f"         [RESP] answer {idx_ans+1}/{n_ans}, tuples={n}, supports={len(support_sets)}")

        rho: Dict[str, float] = {}
        for tid, idx_t in tid2idx.items():
            h_star = min_hitting_set_size_for_t(support_sets, n, idx_t)
            rho[tid] = 1.0 / (1 + h_star) if h_star is not None else 0.0

        icqa = {m: 0.0 for m in MEASURES}
        for _, r in tm_ans.iterrows():
            tid = r["tuple_id"]
            m   = str(r["measure"]).upper()
            if m not in icqa:
                continue
            v = float(r["value"])
            w = rho.get(tid, 0.0)
            icqa[m] += w * v

        out_rows.append({
            "scale":  scale,
            "subset": subset,
            "ratio":  ratio,
            "seed":   seed,
            "qname":  qname,
            "answer_id":   int(answer_id),
            "answervalue": ans_val,
            "icqa_resp_cbm": icqa["CBM"],
            "icqa_resp_cim": icqa["CIM"],
            "icqa_resp_pim": icqa["PIM"],
            "icqa_resp_rim": icqa["RIM"],
        })

    return out_rows


def main():
    print("[INFO] Aggregator = resp (exact responsibility)")
    print(f"[INFO] support_all      : {SUPPORT_ALL_FILE}")
    print(f"[INFO] tuple_measures   : {TUPLE_MEASURES_FILE}")
    print(f"[INFO] output parquet   : {OUT_FILE}")

    con = duckdb.connect()

    db_list = con.execute(f"""
        SELECT DISTINCT
            scale,
            subset,
            ratio,
            seed
        FROM read_parquet('{SUPPORT_ALL_FILE.as_posix()}')
        ORDER BY scale, subset, ratio, seed
    """).df()

    all_rows: List[Dict[str, Any]] = []

    for _, db_row in db_list.iterrows():
        scale = str(db_row["scale"])
        subset = str(db_row["subset"])
        ratio  = str(db_row["ratio"])
        seed   = str(db_row["seed"])

        print(f"\n== DB: scale={scale}, subset={subset}, ratio={ratio}, seed={seed} ==")

        support_db = con.execute(f"""
            SELECT *
            FROM read_parquet('{SUPPORT_ALL_FILE.as_posix()}')
            WHERE scale = ? AND subset = ? AND ratio = ? AND seed = ?
        """, [scale, subset, ratio, seed]).df()

        if support_db.empty:
            print("   [WARN] no support rows for this DB, skip.")
            continue

        tm_db = con.execute(f"""
            SELECT
                scale,
                subset,
                ratio,
                seed,
                relation,
                pk,
                UPPER(measure) AS measure,
                value
            FROM read_parquet('{TUPLE_MEASURES_FILE.as_posix()}')
            WHERE scale = ? AND subset = ? AND ratio = ? AND seed = ?
        """, [scale, subset, ratio, seed]).df()

        if tm_db.empty:
            print("   [WARN] no tuple_measures rows for this DB, skip.")
            continue

        support_db["rel"] = support_db["rel"].astype(str)
        support_db["pk"]  = support_db["pk"].astype(str)
        tm_db["relation"] = tm_db["relation"].astype(str)
        tm_db["pk"]       = tm_db["pk"].astype(str)

        for qname in QUERIES:
            support_q = support_db[support_db["qname"] == qname].copy()
            if support_q.empty:
                print(f"   [Q={qname}] no support rows, skip.")
                continue

            print(f"   [Q={qname}] support rows = {len(support_q)}")

            resp_rows = compute_resp_for_query(scale, subset, ratio, seed, qname, support_q, tm_db)
            all_rows.extend(resp_rows)

    if not all_rows:
        print("[WARN] No ICQA rows produced; nothing to write.")
        return

    out_df = pd.DataFrame(all_rows)
    front_cols = ["scale", "subset", "ratio", "seed", "qname", "answer_id", "answervalue"]
    other_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + other_cols]

    print(f"\n[INFO] Writing {len(out_df)} rows to: {OUT_FILE}")
    out_df.to_parquet(OUT_FILE, index=False)
    con.close()


if __name__ == "__main__":
    t0 = time.time()
    main()
    t1 = time.time()
    print(f"[RUNTIME] Total = {t1 - t0:.2f} seconds")
