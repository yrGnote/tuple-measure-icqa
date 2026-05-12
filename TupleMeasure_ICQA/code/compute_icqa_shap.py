#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Compute ICQA_shap (Shapley-based aggregation) for selected answers.

Inputs:
  - /Users/Desktop/tpchdata/outputs/icqa/icqa_prov.parquet
      -> use rows with non-null icqa_prov_cbm to know which answers to compute
  - /Users/Desktop/tpchdata/support_sets/all_support_sets.parquet
      (support sets for all DBs)
  - /Users/Desktop/tpchdata/outputs/scores/tuple_measures.parquet
      (tuple-level inconsistency measures)

Output:
  - /Users/Desktop/tpchdata/outputs/icqa/icqa_shap.parquet
"""

from pathlib import Path
from typing import List, Dict, Set, Tuple

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE = Path("/Users/Desktop/tpchdata")

PROV_FILE = BASE / "outputs" / "icqa" / "icqa_prov.parquet"
SUPPORT_FILE = BASE / "support_sets" / "all_support_sets.parquet"
TUPLE_MEASURES_FILE = BASE / "outputs" / "scores" / "tuple_measures.parquet"

OUT_DIR = BASE / "outputs" / "icqa"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "icqa_shap.parquet"

MEASURES = ["CBM", "CIM", "PIM", "RIM"]

# Shapley parameters
N_EXACT = 14          # |U| <= 12 -> exact enumeration
N_SAMPLES = 10000      # |U| > 12 -> Monte Carlo permutations
RNG_SEED = 0          # for reproducibility


# ---------------------------------------------------------------------------
# Shapley helper functions
# ---------------------------------------------------------------------------

def _support_sets_to_masks(support_sets: List[Set[int]], n: int) -> List[int]:
    """Convert support_sets (as sets of indices) to bit masks."""
    masks = []
    for S in support_sets:
        m = 0
        for i in S:
            idx = int(i)        
            m |= (1 << idx)
        masks.append(m)
    return masks



def _compute_v_masks(support_sets: List[Set[int]], n: int) -> Tuple[List[int], List[int]]:
    """
    Precompute v_mask[mask] = 1 if coalition (bitmask) hits all supports, else 0.
    Also return support_masks.
    """
    support_masks = _support_sets_to_masks(support_sets, n)
    size = 1 << n
    v_mask = [0] * size
    for mask in range(size):
        if all(mask & sm for sm in support_masks):
            v_mask[mask] = 1
    return v_mask, support_masks


def exact_shapley(support_sets: List[Set[int]], n: int) -> List[float]:
    """
    Exact Shapley for game v(C) = 1 iff C hits all support sets.
    Coalition representation via bitmasks, enumeration over all subsets.
    """
    if n == 0:
        return []

    v_mask, _ = _compute_v_masks(support_sets, n)
    size = 1 << n

    # factorials
    fact = [1] * (n + 1)
    for i in range(1, n + 1):
        fact[i] = fact[i - 1] * i
    denom = fact[n]

    popcount = int.bit_count
    phi = [0.0] * n

    for t in range(n):
        bit_t = 1 << t
        s = 0.0
        for mask in range(size):
            if mask & bit_t:
                continue
            k = popcount(mask)
            vC = v_mask[mask]
            vCt = v_mask[mask | bit_t]
            if vCt == vC:
                continue
            # weight for coalition size k
            weight = fact[k] * fact[n - k - 1] / denom
            s += weight * (vCt - vC)   # here vCt - vC ∈ {0,1}
        phi[t] = s

    return phi


def approx_shapley(
    support_sets: List[Set[int]],
    n: int,
    num_samples: int = N_SAMPLES,
    rng: np.random.Generator | None = None
) -> List[float]:
    if n == 0:
        return []

    if rng is None:
        rng = np.random.default_rng(RNG_SEED)

    support_masks = _support_sets_to_masks(support_sets, n)
    counts = np.zeros(n, dtype=float)

    for _ in range(num_samples):
        perm = rng.permutation(n)
        coalition_mask = 0
        vC = 0  # current v(C): 0 or 1

        for idx in perm:
            idx = int(idx)            
            if vC:
                break

            coalition_mask |= (1 << idx)

            hit = True
            for sm in support_masks:
                if not (coalition_mask & sm):
                    hit = False
                    break
            new_vC = 1 if hit else 0

            if (not vC) and new_vC:
                counts[idx] += 1.0
                vC = new_vC
                break

            vC = new_vC

    phi = (counts / num_samples).tolist()
    return phi



# ---------------------------------------------------------------------------
# Per-answer ICQA_shap computation
# ---------------------------------------------------------------------------

def compute_icqa_shap_for_answer(
    scale: str,
    subset: str,
    ratio: float,
    seed: int,
    qname: str,
    answer_id: int,
    support_ans: pd.DataFrame,
    tm_db: pd.DataFrame,
    rng: np.random.Generator,
) -> Dict[str, object]:
    """
    Compute ICQA_shap^m(q, answer) for this single answer.
    support_ans: rows of support_sets for this DB + qname + answer_id.
    tm_db: tuple_measures for this DB.
    """
    # tuple_id
    support_ans = support_ans.copy()
    support_ans["relation"] = support_ans["rel"].astype(str)
    support_ans["pk"] = support_ans["pk"].astype(str)
    support_ans["tuple_id"] = support_ans["relation"] + "#" + support_ans["pk"]

    answervalue = support_ans["answervalue"].iloc[0]

    # universe U
    uniq_tuples = support_ans["tuple_id"].drop_duplicates().tolist()
    tid2idx = {tid: i for i, tid in enumerate(uniq_tuples)}
    n = len(uniq_tuples)

    # per-support sets S ⊆ U
    support_sets: List[Set[int]] = []
    for _, g in support_ans.groupby("support_id"):
        S = {tid2idx[tid] for tid in g["tuple_id"]}
        if S:
            support_sets.append(S)

    if n == 0 or not support_sets:
        # degenerate: no tuples/supports -> ICQA_shap = 0
        icqa = {m: 0.0 for m in MEASURES}
    else:
        # Shapley weights for tuples
        if n <= N_EXACT:
            phi_list = exact_shapley(support_sets, n)
        else:
            phi_list = approx_shapley(support_sets, n, num_samples=N_SAMPLES, rng=rng)

        # map back to tuple_id
        phi_by_tid = {tid: phi_list[idx] for tid, idx in tid2idx.items()}

        # restrict tuple_measures to tuples in this answer
        tuple_meta = support_ans[["relation", "pk", "tuple_id"]].drop_duplicates()
        tm_ans = tm_db.merge(tuple_meta, on=["relation", "pk"], how="inner")

        if tm_ans.empty:
            icqa = {m: 0.0 for m in MEASURES}
        else:
            icqa = {m: 0.0 for m in MEASURES}
            for _, r in tm_ans.iterrows():
                tid = r["tuple_id"]
                m = str(r["measure"]).upper()
                if m not in icqa:
                    continue
                w = phi_by_tid.get(tid, 0.0)
                v = float(r["value"])
                icqa[m] += w * v

    row = {
        "scale": scale,
        "subset": subset,
        "ratio": ratio,
        "seed": seed,
        "qname": qname,
        "answer_id": answer_id,
        "answervalue": answervalue,
    }
    for m in MEASURES:
        row[f"icqa_shap_{m.lower()}"] = icqa[m]

    return row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[INFO] Starting ICQA Shapley computation")

    con = duckdb.connect()

    # 1. (scale, subset, ratio, seed, qname, answer_id)
    tasks = con.execute(f"""
        SELECT DISTINCT
            scale,
            subset,
            ratio,
            seed,
            qname,
            answer_id
        FROM read_parquet('{PROV_FILE.as_posix()}')
        WHERE icqa_prov_cbm IS NOT NULL
        ORDER BY scale, subset, ratio, seed, qname, answer_id
    """).df()

    print(f"[INFO] Number of answers to compute: {len(tasks)}")
    if tasks.empty:
        print("[WARN] No tasks found (no non-null icqa_prov_cbm). Nothing to do.")
        return

    rng = np.random.default_rng(RNG_SEED)
    all_rows: List[Dict[str, object]] = []

    # group by DB
    grouped = tasks.groupby(["scale", "subset", "ratio", "seed"], as_index=False)

    for _, db_grp in grouped:
        scale = db_grp["scale"].iloc[0]
        subset = db_grp["subset"].iloc[0]
        ratio = db_grp["ratio"].iloc[0]
        seed = db_grp["seed"].iloc[0]

        print(f"[DB] scale={scale}, subset={subset}, ratio={ratio}, seed={seed}")

        # (qname, answer_id) for current DB
        qa_list = db_grp[["qname", "answer_id"]].drop_duplicates()

        # read support_sets & tuple_measures for this DB
        support_db = con.execute(f"""
            SELECT *
            FROM read_parquet('{SUPPORT_FILE.as_posix()}')
            WHERE scale = ? AND subset = ? AND ratio = ? AND seed = ?
        """, [scale, subset, ratio, seed]).df()

        if support_db.empty:
            print("   [WARN] No support rows for this DB, skip.")
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
            print("   [WARN] No tuple_measures rows for this DB, all ICQA_shap=0.")
            for _, row in qa_list.iterrows():
                qname = row["qname"]
                answer_id = row["answer_id"]
                sup_ans = support_db[
                    (support_db["qname"] == qname) &
                    (support_db["answer_id"] == answer_id)
                ]
                if sup_ans.empty:
                    continue
                ansv = sup_ans["answervalue"].iloc[0]
                out = {
                    "scale": scale,
                    "subset": subset,
                    "ratio": ratio,
                    "seed": seed,
                    "qname": qname,
                    "answer_id": answer_id,
                    "answervalue": ansv,
                }
                for m in MEASURES:
                    out[f"icqa_shap_{m.lower()}"] = 0.0
                all_rows.append(out)
            continue

        # normal case: support_db & tm_db both non-empty
        for _, row in qa_list.iterrows():
            qname = row["qname"]
            answer_id = row["answer_id"]

            sup_ans = support_db[
                (support_db["qname"] == qname) &
                (support_db["answer_id"] == answer_id)
            ]
            if sup_ans.empty:
                print(f"   [Q={qname}, ans={answer_id}] no support rows, skip.")
                continue

            print(f"   [Q={qname}, ans={answer_id}] support rows = {len(sup_ans)}")

            out_row = compute_icqa_shap_for_answer(
                scale=scale,
                subset=subset,
                ratio=ratio,
                seed=seed,
                qname=qname,
                answer_id=answer_id,
                support_ans=sup_ans,
                tm_db=tm_db,
                rng=rng,
            )
            all_rows.append(out_row)

    if not all_rows:
        print("[WARN] No ICQA_shap rows produced.")
        return

    out_df = pd.DataFrame(all_rows)
    front_cols = [
        "scale", "subset", "ratio", "seed",
        "qname", "answer_id", "answervalue"
    ]
    other_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + other_cols]

    out_df.to_parquet(OUT_FILE, index=False)
    print(f"[INFO] Written {len(out_df)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
