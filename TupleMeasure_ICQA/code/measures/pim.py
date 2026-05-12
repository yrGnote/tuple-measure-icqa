from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .common import TupleKey, iter_mis_tuples, load_mis_file


PIM_WEIGHTS = {
    "DC1": 1.0,
    "DC2": 0.5,
    "DC3": 0.5,
    "DC4": 1.0 / 3.0,
}


def compute_pim(mis_dir: Path, dcs: List[str]) -> Dict[TupleKey, float]:
    """
    PIM: each tuple in MIS gets +w(DC), no relation-specific weights.
    """
    score: Dict[TupleKey, float] = defaultdict(float)

    for dc in dcs:
        w = PIM_WEIGHTS.get(dc, 0.0)
        if w == 0.0:
            continue
        path = mis_dir / f"{dc}.json"
        if not path.exists():
            continue
        mis_list = load_mis_file(path)
        for mis in mis_list:
            for tk in iter_mis_tuples(mis):
                score[tk] += w

    return dict(score)
