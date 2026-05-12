from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Iterable

from ortools.sat.python import cp_model

from .common import TupleKey, iter_mis_tuples, load_mis_file


@dataclass
class GammaResult:
    gamma: int
    status: str  # OPTIMAL | FEASIBLE | TIMEOUT | TRIVIAL
    runtime_ms: int
    n_edges: int
    n_nodes: int


def greedy_hitting_set_size(edges: List[Set[int]]) -> int:
    """
    Greedy set cover / hitting set heuristic to produce an upper bound.
    """
    uncovered = [set(e) for e in edges if e]
    if not uncovered:
        return 0
    # frequency
    size = 0
    while uncovered:
        freq = defaultdict(int)
        for e in uncovered:
            for u in e:
                freq[u] += 1
        # pick max frequency
        best_u, best_f = None, -1
        for u, f in freq.items():
            if f > best_f:
                best_u, best_f = u, f
        if best_u is None:
            break
        size += 1
        # remove edges hit by best_u
        uncovered = [e for e in uncovered if best_u not in e]
    return size


def solve_min_hitting_set_size_cpsat(
    edges: List[Set[int]],
    time_limit_s: float = 1.0,
    upper_bound: Optional[int] = None,
) -> Tuple[int, str]:
    """
    Solve min hitting set size:
      min sum x_i
      s.t. for each edge e: sum_{i in e} x_i >= 1
    """
    if not edges:
        return 0, "TRIVIAL"

    model = cp_model.CpModel()
    nodes: Set[int] = set()
    for e in edges:
        nodes |= e
    nodes_list = sorted(nodes)

    x = {i: model.NewBoolVar(f"x_{i}") for i in nodes_list}

    for e in edges:
        # guard: empty edge would be infeasible; ignore because it should not happen
        if e:
            model.Add(sum(x[i] for i in e) >= 1)

    obj = sum(x[i] for i in nodes_list)
    model.Minimize(obj)

    if upper_bound is not None:
        # optional pruning: objective <= upper_bound
        model.Add(obj <= upper_bound)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = 8  # adjust if needed

    status = solver.Solve(model)

    if status == cp_model.OPTIMAL:
        return int(solver.ObjectiveValue()), "OPTIMAL"
    if status == cp_model.FEASIBLE:
        return int(solver.ObjectiveValue()), "FEASIBLE"
    # UNKNOWN typically means timeout
    return (upper_bound if upper_bound is not None else int(solver.ObjectiveValue()) if status == cp_model.FEASIBLE else -1), "TIMEOUT"


def build_hypergraph_from_mis(mis_list: List[dict]) -> Tuple[List[Set[TupleKey]], Set[TupleKey]]:
    """
    Build hyperedges (as sets of TupleKey) from MIS list, and the universe of tuples.
    """
    edges: List[Set[TupleKey]] = []
    universe: Set[TupleKey] = set()
    for mis in mis_list:
        e = set(iter_mis_tuples(mis))
        if not e:
            continue
        edges.append(e)
        universe |= e
    return edges, universe


def compute_rim_for_dc(
    mis_list: List[dict],
    time_limit_s: float = 1.0,
    enable_cache: bool = True,
) -> Tuple[Dict[TupleKey, float], Dict[TupleKey, GammaResult]]:
    """
    For one DC:
      - let m = |MIS|
      - for each tuple t in union MIS:
           Gamma(t) = min hitting set size of edges that do NOT contain t
           rho(t)=1/(1+Gamma)
      - normalize rho' within this DC
      - contribution to RIM: rho'(t)*m
    Returns:
      rim_contrib: per tuple contribution for this DC
      gamma_details: per tuple GammaResult for logging
    """
    m = len(mis_list)
    if m == 0:
        return {}, {}

    edges_tk, universe = build_hypergraph_from_mis(mis_list)

    # map TupleKey -> int id for solver input (per t we will filter edges and rebuild ids)
    # We keep per-DC stable id mapping to speed caching/edge signature.
    all_nodes = sorted(universe)
    node_id = {tk: i for i, tk in enumerate(all_nodes)}
    edges_ids: List[Set[int]] = [set(node_id[tk] for tk in e) for e in edges_tk]

    # cache by filtered edge-signature (optional)
    cache: Dict[Tuple[int, ...], Tuple[int, str]] = {}

    gamma_details: Dict[TupleKey, GammaResult] = {}
    rho: Dict[TupleKey, float] = {}

    for t in universe:
        t_id = node_id[t]
        # filter edges that do NOT contain t
        filtered = [e for e in edges_ids if t_id not in e]
        # edge signature for caching: sorted tuple of hashes (each edge sorted tuple)
        sig: Optional[Tuple[int, ...]] = None
        if enable_cache:
            # compress signature: use frozenset hashes (order independent)
            edge_hashes = []
            for e in filtered:
                # stable hash via tuple
                edge_hashes.append(hash(tuple(sorted(e))))
            sig = tuple(sorted(edge_hashes))
            if sig in cache:
                g, st = cache[sig]
                gamma_details[t] = GammaResult(
                    gamma=g,
                    status=st,
                    runtime_ms=0,
                    n_edges=len(filtered),
                    n_nodes=len(all_nodes),
                )
                rho[t] = 1.0 / (1.0 + g)
                continue

        # get greedy upper bound
        ub = greedy_hitting_set_size(filtered)
        # solve exact/timeout
        import time as _time
        t0 = _time.time()
        g, st = solve_min_hitting_set_size_cpsat(filtered, time_limit_s=time_limit_s, upper_bound=ub)
        dt_ms = int((_time.time() - t0) * 1000)

        # fallback if timeout with no solution (should not happen with ub, but guard)
        if g < 0:
            g = ub
            st = "TIMEOUT"

        if enable_cache and sig is not None:
            cache[sig] = (g, st)

        gamma_details[t] = GammaResult(
            gamma=g,
            status=st,
            runtime_ms=dt_ms,
            n_edges=len(filtered),
            n_nodes=len(all_nodes),
        )
        rho[t] = 1.0 / (1.0 + g)

    # normalize rho -> rho'
    denom = sum(rho.values())
    if denom <= 0:
        # degenerate, shouldn't happen
        return {}, gamma_details

    rim_contrib = {t: (rho[t] / denom) * m for t in universe}
    return rim_contrib, gamma_details


def compute_rim(
    mis_dir: Path,
    dcs: List[str],
    time_limit_s: float = 1.0,
    enable_cache: bool = True,
) -> Tuple[Dict[TupleKey, float], Dict[str, Dict[TupleKey, GammaResult]]]:
    """
    Full RIM across DCs:
      RIM(t) = sum_{dc} rho'(t,dc) * |MIS(dc)|
    Returns:
      scores: per tuple RIM
      gamma_log: per dc -> per tuple -> GammaResult
    """
    total: Dict[TupleKey, float] = defaultdict(float)
    gamma_log: Dict[str, Dict[TupleKey, GammaResult]] = {}

    for dc in dcs:
        path = mis_dir / f"{dc}.json"
        if not path.exists():
            continue
        mis_list = load_mis_file(path)
        rim_dc, gamma_details = compute_rim_for_dc(
            mis_list=mis_list,
            time_limit_s=time_limit_s,
            enable_cache=enable_cache,
        )
        for t, v in rim_dc.items():
            total[t] += float(v)
        gamma_log[dc] = gamma_details

    return dict(total), gamma_log
