from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

TupleKey = Tuple[str, Tuple[int, ...]]  # (relation, pk_tuple)
MIS = Dict[str, Any]


def normalize_pk(pk: Any) -> Tuple[int, ...]:
    """
    Normalize a primary key representation into a hashable tuple of ints.
    Examples:
      - part: [16353] -> (16353,)
      - orders: [123] -> (123,)
      - lineitem: [[692228, 3]] -> (692228, 3)   (after caller extracts inner list)
      - if already int -> (int,)
    """
    if pk is None:
        raise ValueError("pk is None")
    if isinstance(pk, int):
        return (pk,)
    if isinstance(pk, (list, tuple)):
        # pk may be [a,b] or [a]
        if len(pk) == 0:
            raise ValueError("empty pk list")
        # ensure all ints
        return tuple(int(x) for x in pk)
    # fallback
    return (int(pk),)


def iter_mis_tuples(mis: MIS) -> Iterable[TupleKey]:
    """
    Yield normalized TupleKey from one MIS dict:
      {'dc': 'DC4', 'tuples': {'lineitem': [[ok, ln]], 'part': [pk], ...}}
    Note:
      - For relations where pks are lists of lists (lineitem/partsupp), we iterate inner lists.
      - For relations where pks are lists of ints (part/orders), iterate ints.
    """
    tuples_obj = mis.get("tuples", {})
    if not isinstance(tuples_obj, dict):
        return

    for rel, pks in tuples_obj.items():
        if pks is None:
            continue

        # lineitem / partsupp are often list of [..] keys
        if isinstance(pks, list):
            for item in pks:
                # item can be int OR list/tuple of ints
                if isinstance(item, (list, tuple)):
                    yield (rel, normalize_pk(item))
                else:
                    yield (rel, normalize_pk(item))
        else:
            # uncommon, but handle
            yield (rel, normalize_pk(pks))


def load_mis_file(path: Path) -> List[MIS]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "mis" in data:
        return data["mis"]
    raise ValueError(f"Unexpected MIS JSON structure at {path}")


@dataclass(frozen=True)
class DBInstance:
    scale: str
    subset: str
    ratio: str
    seed: str
    mis_dir: Path

    @property
    def db_id(self) -> str:
        return f"{self.scale}/{self.subset}/{self.ratio}/{self.seed}"


def discover_db_instances(violations_root: Path, scales: Optional[Sequence[str]] = None) -> List[DBInstance]:
    """
    Scan violations directory, expecting:
      violations/sf1/subsetB/0p1pct/seed10/mis/DC*.json
    """
    instances: List[DBInstance] = []
    if scales is None:
        scale_dirs = [p for p in violations_root.iterdir() if p.is_dir() and p.name.startswith("sf")]
    else:
        scale_dirs = [violations_root / s for s in scales]

    for scale_dir in scale_dirs:
        if not scale_dir.exists():
            continue
        for subset_dir in scale_dir.iterdir():
            if not subset_dir.is_dir() or not subset_dir.name.startswith("subset"):
                continue
            for ratio_dir in subset_dir.iterdir():
                if not ratio_dir.is_dir():
                    continue
                for seed_dir in ratio_dir.iterdir():
                    if not seed_dir.is_dir() or not seed_dir.name.startswith("seed"):
                        continue
                    mis_dir = seed_dir / "mis"
                    if mis_dir.is_dir():
                        instances.append(
                            DBInstance(
                                scale=scale_dir.name,
                                subset=subset_dir.name,
                                ratio=ratio_dir.name,
                                seed=seed_dir.name,
                                mis_dir=mis_dir,
                            )
                        )
    # stable order
    instances.sort(key=lambda x: x.db_id)
    return instances


def now_ms() -> int:
    return int(time.time() * 1000)
