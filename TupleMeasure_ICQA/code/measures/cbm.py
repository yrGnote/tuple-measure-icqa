from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from .common import TupleKey, iter_mis_tuples, load_mis_file


def compute_cbm(mis_dir: Path, dcs: List[str]) -> Dict[TupleKey, float]:
    """
    CBM (constraint-based):
    For each DC, every tuple that appears in at least one MIS of this DC gets +1.
    Multiple MIS of the same DC do NOT accumulate extra score.
    """
    score: Dict[TupleKey, float] = defaultdict(float)

    for dc in dcs:
        path = mis_dir / f"{dc}.json"
        if not path.exists():
            continue

        mis_list = load_mis_file(path)

        # for all the tuples appeared for each DC, +1
        tuples_for_dc = set()  # type: set[TupleKey]

        for mis in mis_list:
            for tk in iter_mis_tuples(mis):
                tuples_for_dc.add(tk)

        # Each DC contribute no more than once to each tuple
        for tk in tuples_for_dc:
            score[tk] += 1.0

    return dict(score)
