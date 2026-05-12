# -7822 (Tuple Inconsistency Measures + ICQA)

This repository provides the full reproducible pipeline to generate the experimental results on tuple inconsistency measures and ICQA metrics using the TPC-H benchmark.

## 0. Environment Setup

We recommend using conda for reproducibility:

conda create -n tpch python=3.11 -y
conda activate tpch
pip install -r requirements.txt

Main Python dependencies:
- duckdb
- pandas
- numpy
- tqdm
- pyarrow

## 1. TPC-H Data Generation

TPC-H `.tbl` files are generated using the official `dbgen` tool for the scale factors:

SF = {0.01, 0.05, 0.1}

The `.tbl` files are stored under:

data/
  sf0.01/
  sf0.05/
  sf0.1/

Each folder contains the 8 standard TPC-H tables:
customer.tbl, lineitem.tbl, nation.tbl, orders.tbl, part.tbl, partsupp.tbl, region.tbl, supplier.tbl

## 2. Convert `.tbl` → DuckDB

Convert the TPC-H `.tbl` files into clean DuckDB databases:

python build_tpch_duckdb.py --input-root data --output-root db

Produces:

db/
  sf0.01/*.duckdb
  sf0.05/*.duckdb
  sf0.1/*.duckdb

## 3. Check Denial Constraints on Clean Databases

Verify that all clean TPC-H databases satisfy the intended denial constraints:

python check_constraints.py --db-root db

This ensures that all subsequent violations are introduced solely by our injection procedure.

## 4. Inject Violations (10 Seeds per Setting)

Inject violations under the selected combinations of scale × ratio × DC-set:

python inject_violations.py --db-root db --num-seeds 10

This produces 180 injected databases in total.

## 5. Extract Minimal Inconsistent Subsets (MIS)

Extract MIS for all injected databases, stored per DC per DB:

python run_extract_all_scales.py --db-root db

## 6. Compute Tuple Inconsistency Measures

Compute all tuple measures on all inconsistent tuples for all injected databases:

python run_measures.py --db-root db

Measured set includes:
{CBM, CIM, PIM, RIM}

## 7. Compute Provenance Sets for ICQA

Generate minimal provenance sets (one per answer) for all queries:

python support_sets.py --db-root db

This produces for each DB × query:
- all answers
- all minimal provenance sets per answer

## 8. Compute ICQA Metrics (12 Variants)

Compute the ICQA metrics using the provenance sets and the tuple measures:

python compute_icqa_prov.py  --db-root db
python compute_icqa_resp.py  --db-root db
python compute_icqa_shap.py  --db-root db

Total ICQA variants:
(IM × Aggregation) = {CBM, CIM, PIM, RIM} × {Prov, Resp, Shap} = 12



## Notes on Reproducibility

- Clean TPCH databases are constraint-consistent before injection.
- All violations are introduced deterministically via controlled seeds.
- ICQA computations depend on both measures and provenance sets.
- The entire pipeline is deterministic given fixed seeds and configuration.
