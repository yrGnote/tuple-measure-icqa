#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
import subprocess

# ========= configuration =========

BASE_DIR = os.path.expanduser("~/Desktop/tpchdata")

# setting
SCALES = ["sf0.01", "sf0.05", "sf0.1"]

DC_SUBSETS = ["subsetA", "subsetB"]

RATIOS = ["0p01pct", "0p05pct", "0p1pct"]

SEEDS = [f"seed{i:02d}" for i in range(1, 11)]

EXTRACT_SCRIPT = os.path.join(BASE_DIR, "code", "extract_mis.py")


# ========= functions =========

def find_single_duckdb(case_dir: str) -> str | None:
    """
    Find exactly one .duckdb file under case_dir (seed folder).
    Return its absolute path, or None if not found.
    Raise if multiple duckdb files exist (to avoid ambiguity).
    """
    if not os.path.isdir(case_dir):
        return None

    duckdb_files = [f for f in os.listdir(case_dir) if f.endswith(".duckdb")]
    if len(duckdb_files) == 0:
        return None
    if len(duckdb_files) > 1:
        raise RuntimeError(f"Multiple .duckdb files in {case_dir}: {duckdb_files}")

    return os.path.join(case_dir, duckdb_files[0])


def run_for_scale(scale: str, force: bool = False):
    print(f"\n===== Processing {scale} =====")

    violations_root = os.path.join(BASE_DIR, "violations", scale)
    if not os.path.isdir(violations_root):
        print(f"[WARN] violations root not found: {violations_root}")
        return 0

    total = 0
    skipped_existing = 0

    for subset in DC_SUBSETS:
        for ratio in RATIOS:
            for seed in SEEDS:
                case_dir = os.path.join(violations_root, subset, ratio, seed)

                db_path = find_single_duckdb(case_dir)
                if db_path is None:
                    print(f"[SKIP] no duckdb in {case_dir}")
                    continue

                out_dir = os.path.join(case_dir, "mis")
                os.makedirs(out_dir, exist_ok=True)

                # If drawn and is not forced to rerun, skip
                done_marker = os.path.join(out_dir, "index.json")
                if (not force) and os.path.exists(done_marker):
                    print(f"[SKIP] already extracted: {done_marker}")
                    skipped_existing += 1
                    continue

                cmd = [
                    "python",
                    EXTRACT_SCRIPT,
                    "--db", db_path,
                    "--out", out_dir
                ]

                print(f"[RUN] {scale} | {subset} | {ratio} | {seed}")
                subprocess.run(cmd, check=True)
                total += 1

    print(f"[DONE] {scale}: {total} cases processed. ({skipped_existing} skipped existing)")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract MIS even if mis/index.json already exists."
    )
    args = parser.parse_args()

    grand_total = 0
    for scale in SCALES:
        grand_total += run_for_scale(scale, force=args.force)

    print(f"\nALL SCALES FINISHED. Total processed: {grand_total}")


if __name__ == "__main__":
    main()
