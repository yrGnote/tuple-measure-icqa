#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compute answer-level ICQA for all DBs and all 5 TPC-H queries (Q1..Q5),
for exactly ONE aggregation method at a time:

  - Provenance  ("prov")

Usage:
  AGGREGATOR = "prov" 。

Inputs:
  - Tuple-level measures:
      /Users/Desktop/tpchdata/outputs/scores/tuple_measures.parquet

  - Support sets (include pk):
      /Users/Desktop/tpchdata/support_sets/sf<scale>/<subset>/<ratio>/seed<seed>/Qk_support.parquet

Output:
  - Answer-level ICQA parquet:
      /Users/Desktop/tpchdata/outputs/icqa/icqa_prov.parquet

Schema:
  scale, subset, ratio, seed,
  qname, answer_id, answervalue,
  icqa_<agg>_cbm, icqa_<agg>_cim, icqa_<agg>_pim, icqa_<agg>_rim
"""

from pathlib import Path
import time

import pandas as pd

# ----------------------------------------------------------------------
# 0. Choose which aggregator to compute
# ----------------------------------------------------------------------

AGGREGATOR = "prov"   

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

BASE = Path("/Users/Desktop/tpchdata")

TUPLE_MEASURES_FILE = BASE / "outputs" / "scores" / "tuple_measures.parquet"
SUPPORT_ROOT        = BASE / "support_sets_v7"

OUT_DIR  = BASE / "outputs" / "icqa"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / f"icqa_{AGGREGATOR}.parquet"

# 5 queries
QUERIES  = ["Q1", "Q2", "Q3", "Q4", "Q5"]
# 4 tuple measures
MEASURES = ["CBM", "CIM", "PIM", "RIM"]


# ----------------------------------------------------------------------
# 1. Function: Standardize scale/seed, applicable to situations without prefix "sf"/"seed"
# ----------------------------------------------------------------------

def norm_scale(x: str) -> str:
    s = str(x)
    if s.startswith("sf"):
        return s[2:]
    return s

def norm_seed(x: str) -> str:
    s = str(x)
    if s.startswith("seed"):
        return s[4:]
    return s


# ----------------------------------------------------------------------
# 2. main
# ----------------------------------------------------------------------

def main():


    print(f"[INFO] AGGREGATOR = {AGGREGATOR}")
    print(f"[INFO] Loading tuple-level measures from: {TUPLE_MEASURES_FILE}")

    tm = pd.read_parquet(TUPLE_MEASURES_FILE)

    # Standardize types to avoid type mismatches during mergers
    for col in ["scale", "subset", "ratio", "seed", "relation", "pk", "measure"]:
        if col in tm.columns:
            tm[col] = tm[col].astype(str)
        else:
            raise ValueError(f"Column '{col}' not found in tuple_measures parquet")

    tm["measure"] = tm["measure"].str.upper()

    # ICQA for all answers
    all_rows = []

    # DB by (scale, subset, ratio, seed)
    db_groups = tm[["scale", "subset", "ratio", "seed"]].drop_duplicates().sort_values(
        ["scale", "subset", "ratio", "seed"]
    )

    print(f"[INFO] Found {len(db_groups)} DB configurations in tuple_measures.")

    for _, db_row in db_groups.iterrows():
        scale_raw  = db_row["scale"]
        subset     = db_row["subset"]
        ratio      = db_row["ratio"]
        seed_raw   = db_row["seed"]

        # Normalize scale/seed (remove possible prefixes such as "sf"/"seed")
        scale_norm = norm_scale(scale_raw)
        seed_norm  = norm_seed(seed_raw)

        print(f"== DB: scale={scale_raw} (sf{scale_norm}), subset={subset}, ratio={ratio}, seed={seed_raw} (seed{seed_norm})")

        # current DB tuple_measure
        tm_db = tm[
            (tm["scale"]  == scale_raw)
            & (tm["subset"] == subset)
            & (tm["ratio"]  == ratio)
            & (tm["seed"]   == seed_raw)
        ].copy()

        if tm_db.empty:
            print("   [WARN] no tuple_measures rows for this DB, skip.")
            continue

        
        tm_db = tm_db[["relation", "pk", "measure", "value"]].copy()

        # support_sets for current DB
        support_dir = SUPPORT_ROOT / f"sf{scale_norm}" / subset / ratio / f"seed{seed_norm}"
        if not support_dir.exists():
            print(f"   [WARN] support dir not found: {support_dir}, skip this DB.")
            continue

        # Traverse five queries
        for qname in QUERIES:
            supp_file = support_dir / f"{qname}_support.parquet"
            if not supp_file.exists():
                print(f"   [WARN] support file not found: {supp_file}, skip {qname}.")
                continue

            print(f"   [Q={qname}] loading support sets from {supp_file.name}")
            support_df = pd.read_parquet(supp_file)
            if support_df.empty:
                print("      [INFO] support_df empty, skip.")
                continue

            # check pk exsits or not
            if "pk" not in support_df.columns:
                raise ValueError(f"'pk' column not found in support file: {supp_file}")

            
            support_df = support_df.copy()
            support_df["relation"] = support_df["rel"].astype(str)
            support_df["pk"]       = support_df["pk"].astype(str)

            # Support size for each answer (number of deduplicated tuples)
            support_df["tuple_key"] = support_df["relation"] + "#" + support_df["pk"]
            support_size = (
                support_df.groupby("answer_id")["tuple_key"]
                .nunique()
                .rename("support_size")
                .reset_index()
            )

            # merge
            merged = support_df.merge(
                tm_db,
                on=["relation", "pk"],
                how="left",        # without inconsistency
                validate="m:m",
            )

            # measure for tuple measures exist
            measured = merged[merged["measure"].notna()].copy()

            if measured.empty:
                # For all answers: sum (im_m)=0 → ICQA by aggregator (currently all 0)
                answers = (
                    support_df[["answer_id", "answervalue"]]
                    .drop_duplicates()
                    .reset_index(drop=True)
                )
                answers = answers.merge(support_size, on="answer_id", how="left")

                for _, row in answers.iterrows():
                    ans_id  = int(row["answer_id"])
                    ans_val = row["answervalue"]
                    sup_sz  = int(row["support_size"])

                    out_row = {
                        "scale":  str(scale_raw),
                        "subset": str(subset),
                        "ratio":  str(ratio),
                        "seed":   str(seed_raw),
                        "qname":  qname,
                        "answer_id":   ans_id,
                        "answervalue": ans_val,
                    }

                    for m in MEASURES:
                        # no measure，sum(im_m)=0
                        icqa_val = 0.0

                    all_rows.append(out_row)

                print("      [INFO] no tuple_measures matched; all ICQA = 0 for this query.")
                continue

            # sum for each t im_m(t)  per (answer_id, answervalue, measure)
            agg = (
                measured
                .groupby(["answer_id", "answervalue", "measure"], as_index=False)["value"]
                .sum()
            )

            # pivot ：answer for row，attribute CBM/CIM/PIM/RIM  sum(im_m)
            sum_wide = agg.pivot_table(
                index=["answer_id", "answervalue"],
                columns="measure",
                values="value",
                aggfunc="sum",
            )

            for m in MEASURES:
                if m not in sum_wide.columns:
                    sum_wide[m] = 0.0

            sum_wide = sum_wide.reset_index()

            # merge support_size
            sum_wide = sum_wide.merge(support_size, on="answer_id", how="left")

            # compute ICQA for each answer
            for _, row in sum_wide.iterrows():
                ans_id  = int(row["answer_id"])
                ans_val = row["answervalue"]
                sup_sz  = int(row["support_size"])

                out_row = {
                    "scale":  str(scale_raw),
                    "subset": str(subset),
                    "ratio":  str(ratio),
                    "seed":   str(seed_raw),
                    "qname":  qname,
                    "answer_id":   ans_id,
                    "answervalue": ans_val,
                }

                for m in MEASURES:
                    sum_im = float(row[m])  # ∑_t im_m(t)
                    icqa_val = sum_im

                    

                    out_row[f"icqa_{AGGREGATOR}_{m.lower()}"] = icqa_val

                all_rows.append(out_row)

    
    if not all_rows:
        print("[INFO] No answers found; nothing to write.")
        return

    out_df = pd.DataFrame(all_rows)

    # use answervalue as index
    out_df["answervalue"] = out_df["answervalue"].astype(str)

    # scale/subset/ratio/seed string
    for col in ["scale", "subset", "ratio", "seed", "qname"]:
        out_df[col] = out_df[col].astype(str)

    # Adjust column order
    front_cols = ["scale", "subset", "ratio", "seed", "qname", "answer_id", "answervalue"]
    other_cols = [c for c in out_df.columns if c not in front_cols]
    out_df = out_df[front_cols + other_cols]

    print(f"[INFO] Writing {len(out_df)} rows to: {OUT_FILE}")
    out_df.to_parquet(OUT_FILE, index=False)


if __name__ == "__main__":
    t0 = time.time()
    main()
    t1 = time.time()
    print(f"[RUNTIME] Total = {t1 - t0:.2f} seconds")
