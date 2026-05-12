
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from measures.common import discover_db_instances, TupleKey
from measures import compute_cim, compute_pim, compute_cbm, compute_rim


DEFAULT_DCS = ["DC1", "DC2", "DC3", "DC4"]


def tuplekey_to_cols(tk: TupleKey) -> Tuple[str, str]:
    rel, pk = tk
    # store pk as compact string, stable
    pk_str = ",".join(str(x) for x in pk)
    return rel, pk_str


def scores_to_df(db, measure_name: str, scores: Dict[TupleKey, float]) -> pd.DataFrame:
    rows = []
    for tk, v in scores.items():
        rel, pk_str = tuplekey_to_cols(tk)
        rows.append(
            {
                "scale": db.scale,
                "subset": db.subset,
                "ratio": db.ratio,
                "seed": db.seed,
                "db_id": db.db_id,
                "relation": rel,
                "pk": pk_str,
                "measure": measure_name,
                "value": float(v),
            }
        )
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=str, default=str(Path.home() / "Desktop/tpchdata"))
    ap.add_argument("--violations", type=str, default="violations")
    ap.add_argument("--out", type=str, default="outputs")
    ap.add_argument("--dcs", type=str, default=",".join(DEFAULT_DCS))
    ap.add_argument("--measures", type=str, default="CIM,PIM,CBM,RIM")
    ap.add_argument("--rim_time_limit_s", type=float, default=1.0)
    ap.add_argument("--rim_cache", action="store_true", default=True)
    ap.add_argument("--no_rim_cache", action="store_true", default=False)
    ap.add_argument("--limit", type=int, default=0, help="limit number of DB instances (0 = all)")
    args = ap.parse_args()

    root = Path(args.root)
    violations_root = root / args.violations
    out_root = root / args.out
    (out_root / "scores").mkdir(parents=True, exist_ok=True)
    (out_root / "runtimes").mkdir(parents=True, exist_ok=True)
    (out_root / "gamma").mkdir(parents=True, exist_ok=True)

    dcs = [x.strip() for x in args.dcs.split(",") if x.strip()]
    measures = [x.strip().upper() for x in args.measures.split(",") if x.strip()]

    rim_cache = args.rim_cache and (not args.no_rim_cache)

    instances = discover_db_instances(violations_root)
    if args.limit and args.limit > 0:
        instances = instances[: args.limit]

    all_score_dfs: List[pd.DataFrame] = []
    runtime_rows = []

    for idx, db in enumerate(instances, 1):
        print(f"[{idx}/{len(instances)}] {db.db_id}")
        # CIM
        if "CIM" in measures:
            t0 = time.time()
            scores = compute_cim(db.mis_dir, dcs)
            dt = time.time() - t0
            all_score_dfs.append(scores_to_df(db, "CIM", scores))
            runtime_rows.append({"db_id": db.db_id, "measure": "CIM", "seconds": dt, "nonzero": len(scores)})

        # PIM
        if "PIM" in measures:
            t0 = time.time()
            scores = compute_pim(db.mis_dir, dcs)
            dt = time.time() - t0
            all_score_dfs.append(scores_to_df(db, "PIM", scores))
            runtime_rows.append({"db_id": db.db_id, "measure": "PIM", "seconds": dt, "nonzero": len(scores)})

        # CBM
        if "CBM" in measures:
            t0 = time.time()
            scores = compute_cbm(db.mis_dir, dcs)
            dt = time.time() - t0
            all_score_dfs.append(scores_to_df(db, "CBM", scores))
            runtime_rows.append({"db_id": db.db_id, "measure": "CBM", "seconds": dt, "nonzero": len(scores)})

        # RIM
        if "RIM" in measures:
            t0 = time.time()
            scores, gamma_log = compute_rim(
                db.mis_dir, dcs, time_limit_s=args.rim_time_limit_s, enable_cache=rim_cache
            )
            dt = time.time() - t0
            all_score_dfs.append(scores_to_df(db, "RIM", scores))
            runtime_rows.append({"db_id": db.db_id, "measure": "RIM", "seconds": dt, "nonzero": len(scores)})

            # write gamma details per DB (json) for debugging / later analysis
            gamma_out = out_root / "gamma" / (db.db_id.replace("/", "__") + ".gamma.json")
            gamma_out.parent.mkdir(parents=True, exist_ok=True)
            # convert to jsonable
            serial = {}
            for dc, per_t in gamma_log.items():
                serial[dc] = {}
                for (rel, pk), gr in per_t.items():
                    key = f"{rel}:{','.join(map(str, pk))}"
                    serial[dc][key] = {
                        "gamma": gr.gamma,
                        "status": gr.status,
                        "runtime_ms": gr.runtime_ms,
                        "n_edges": gr.n_edges,
                        "n_nodes": gr.n_nodes,
                    }
            gamma_out.write_text(json.dumps(serial, ensure_ascii=False))

    # concat & write outputs
    if all_score_dfs:
        scores_df = pd.concat(all_score_dfs, ignore_index=True)
    else:
        scores_df = pd.DataFrame(columns=["scale", "subset", "ratio", "seed", "db_id", "relation", "pk", "measure", "value"])

    runtimes_df = pd.DataFrame(runtime_rows)

    # parquet preferred
    try:
        scores_path = out_root / "scores" / "tuple_measures.parquet"
        scores_df.to_parquet(scores_path, index=False)
        rt_path = out_root / "runtimes" / "runtimes.parquet"
        runtimes_df.to_parquet(rt_path, index=False)
        print(f"Wrote: {scores_path}")
        print(f"Wrote: {rt_path}")
    except Exception as e:
        # fallback csv
        scores_path = out_root / "scores" / "tuple_measures.csv"
        scores_df.to_csv(scores_path, index=False)
        rt_path = out_root / "runtimes" / "runtimes.csv"
        runtimes_df.to_csv(rt_path, index=False)
        print(f"Parquet failed ({e}); wrote CSV instead.")
        print(f"Wrote: {scores_path}")
        print(f"Wrote: {rt_path}")


if __name__ == "__main__":
    main()

