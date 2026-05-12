from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .common import TupleKey, iter_mis_tuples, load_mis_file


# CIM relation-specific weights by DC
CIM_WEIGHTS = {
    "DC1": {"lineitem": 1.0},
    "DC2": {"orders": 2.0, "lineitem": 2.0},
    "DC3": {"orders": 2.0, "lineitem": 2.0},
    "DC4": {"lineitem": 2.0, "partsupp": 3.0, "part": 1.0},
}


def compute_cim(mis_dir: Path, dcs: List[str]) -> Dict[TupleKey, float]:
    """
    CIM: each tuple in MIS gets +w(DC, relation).
    """
    score: Dict[TupleKey, float] = defaultdict(float)

    for dc in dcs:
        rel_w = CIM_WEIGHTS.get(dc, {})
        if not rel_w:
            continue
        path = mis_dir / f"{dc}.json"
        if not path.exists():
            continue
        mis_list = load_mis_file(path)
        for mis in mis_list:
            for rel, pk in iter_mis_tuples(mis):
                w = rel_w.get(rel, 0.0)
                if w:
                    score[(rel, pk)] += w

    return dict(score)
