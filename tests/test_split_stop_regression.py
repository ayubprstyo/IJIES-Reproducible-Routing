"""
tests/test_split_stop_regression.py — mandatory regression tests for the
canonical virtual-stop mapping bugfix.

Run: python3 -m pytest tests/test_split_stop_regression.py -v
or:  python3 tests/test_split_stop_regression.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data import build_canonical_mapping, verify_archived_ids_resolve

STOPS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'data_demo_synthetic', 'customer_stops', 'synthetic_customer_day_stops.csv')


def test_oversized_stops_detected_on_synthetic_data():
    """Structural test on synthetic demo data (public repo does not ship
    real customer-level data -- see REPRODUCIBILITY_NOTE.md). The
    manuscript's exact private-data counts (6 oversized / 13 virtual /
    3,934 total) are documented in configs/experiment_config.json and are
    re-verified only under PRIVATE/Level-2 reproduction with the real
    authorized input, not asserted here."""
    _, _, oversized = build_canonical_mapping(STOPS_PATH)
    assert len(oversized) >= 1, "Synthetic demo data should include at least one oversized stop"


def test_virtual_stops_generated_from_splits():
    mapping_df, _, oversized = build_canonical_mapping(STOPS_PATH)
    split_rows = mapping_df[mapping_df['piece_count'] > 1]
    assert len(split_rows) >= 2, f"Expected >=2 virtual split stops on synthetic data, got {len(split_rows)}"
    # Every oversized (date, original_customer_id) instance should have
    # produced at least 2 pieces -- compare unique (date, id) pairs, since
    # the same customer code can legitimately recur (and be oversized)
    # across multiple dates.
    unique_split_originals = split_rows[['delivery_date', 'original_customer_id']].drop_duplicates().shape[0]
    unique_oversized = oversized[['delivery_date', 'customer_code']].drop_duplicates().shape[0]
    assert unique_split_originals == unique_oversized


def test_total_optimization_stops_consistent():
    mapping_df, _, oversized = build_canonical_mapping(STOPS_PATH)
    n_source = len(__import__('pandas').read_csv(STOPS_PATH))
    split_rows = mapping_df[mapping_df['piece_count'] > 1]
    # total = source - oversized_originals + split_pieces (algebraic identity,
    # true regardless of the exact counts on whatever input is supplied).
    assert len(mapping_df) == n_source - len(oversized) + len(split_rows)


def test_no_unresolved_virtual_id():
    mapping_df, _, _ = build_canonical_mapping(STOPS_PATH)
    assert mapping_df['parent_physical_node'].notna().all(), "Found virtual stops with no parent_physical_node"


def test_every_virtual_stop_has_valid_attributes():
    _, customers, _ = build_canonical_mapping(STOPS_PATH)
    bad = [k for k, v in customers.items()
           if v['weight'] <= 0 or v['tw_end'] <= v['tw_start'] or v['service_min'] < 0]
    assert len(bad) == 0, f"{len(bad)} virtual stops have invalid demand/service/TW: {bad[:5]}"


def test_matrix_alias_resolves(dist_matrix_path=None):
    """Every virtual stop's parent_physical_node must be a valid key in the
    distance matrix (or the depot)."""
    import pandas as pd
    mapping_df, _, _ = build_canonical_mapping(STOPS_PATH)
    if dist_matrix_path is None:
        dist_matrix_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         'data_demo_synthetic', 'matrices', 'synthetic_distance_matrix.csv')
    dist_long = pd.read_csv(dist_matrix_path)
    valid_origins = dist_long.groupby('delivery_date')['origin_id'].apply(set).to_dict()
    valid_dests = dist_long.groupby('delivery_date')['destination_id'].apply(set).to_dict()
    bad = []
    for _, row in mapping_df.iterrows():
        date, parent = row['delivery_date'], row['parent_physical_node']
        if parent == "DEPOT_1":
            continue
        in_origin = date in valid_origins and parent in valid_origins[date]
        in_dest = date in valid_dests and parent in valid_dests[date]
        if not (in_origin or in_dest):
            bad.append((date, row['virtual_stop_id'], parent))
    assert len(bad) == 0, f"{len(bad)} virtual stops have no valid matrix alias: {bad[:5]}"


def test_archived_split_ids_resolve(sequences_path=None):
    """
    Every generated __SPLITkofN virtual stop ID must resolve to exactly one
    row in the canonical mapping, and the number of unique ORIGINAL
    (pre-split) customer IDs that produced a split must equal the number of
    oversized source stops. This checks the STRUCTURAL property (not
    hardcoded real customer codes, which must never appear in this public
    repository's de-identified data or test code).

    For Level-2 (private, authorized) reproduction, callers may additionally
    pass `sequences_path` pointing at the archived locked-route sequences
    file to verify those exact external IDs resolve too.
    """
    mapping_df, _, oversized = build_canonical_mapping(STOPS_PATH)
    split_rows = mapping_df[mapping_df['piece_count'] > 1]
    unique_split_originals = split_rows[['delivery_date', 'original_customer_id']].drop_duplicates().shape[0]
    unique_oversized = oversized[['delivery_date', 'customer_code']].drop_duplicates().shape[0]
    assert unique_split_originals == unique_oversized, (
        f"Expected {unique_oversized} unique original customers to have produced "
        f"split IDs, got {unique_split_originals}")
    # Every split ID must follow the canonical naming and resolve to itself
    # in the mapping (i.e. be a valid, lookup-able key).
    canonical_ids = set(mapping_df['virtual_stop_id'])
    for vid in split_rows['virtual_stop_id']:
        assert vid in canonical_ids, f"Split ID '{vid}' does not resolve in its own mapping (should be impossible)"
        assert '__SPLIT' in vid and 'of' in vid, f"Split ID '{vid}' does not follow the canonical naming convention"

    if sequences_path is not None:
        import pandas as pd
        seq = pd.read_csv(sequences_path)
        archived_ids = sorted(seq[seq['node_id'].astype(str).str.contains('__SPLIT', na=False)]['node_id'].unique())
        verify_archived_ids_resolve(mapping_df, archived_ids)


def test_served_prefix_structural_immutability():
    """Code-inspection test: the search functions must only ever pass the
    `unserved` list to neighborhood operators; `served` must be read-only."""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'search.py')
    with open(src_path) as f:
        src = f.read()
    assert "served = [n for n, f in zip(full_seq, frozen_flags) if f]" in src
    assert "served +" in src or "served+" in src


def test_liu_repair_capacity_infeasible_never_silently_fallback():
    """
    Regression test for the capacity-hard repair fix: liu_random_repair,
    liu_greedy_insertion, and liu_random_criticality_repair must return
    None (an explicit infeasible-candidate signal) when a node has zero
    capacity-feasible insertion positions -- NEVER fall back to inserting
    at an infeasible position.
    """
    import random
    from src.liu_alns import liu_random_repair, liu_greedy_insertion, liu_random_criticality_repair

    # A capacity function that is UNSATISFIABLE by construction (always
    # False) -- any node has zero feasible positions under this function.
    def always_infeasible(seq_partial, node, pos):
        return False

    rng = random.Random(42)
    remaining = ['A', 'B']
    removed = ['C', 'D']

    result_random = liu_random_repair(remaining, removed, rng, always_infeasible)
    assert result_random is None, "liu_random_repair must return None when no feasible position exists"

    def dummy_cost_fn(seq_p, node, pos):
        return 0.0
    result_greedy = liu_greedy_insertion(remaining, removed, dummy_cost_fn, always_infeasible)
    assert result_greedy is None, "liu_greedy_insertion must return None when no feasible position exists"

    def demand_fn(n): return 1.0
    def tw_width_fn(n): return 1.0
    def depot_dist_fn(n): return 1.0
    result_crit = liu_random_criticality_repair(remaining, removed, rng, demand_fn, tw_width_fn,
                                                  depot_dist_fn, always_infeasible)
    assert result_crit is None, "liu_random_criticality_repair must return None when no feasible position exists"

    # Sanity check: with an always-TRUE capacity function, all three must
    # succeed (return a real sequence, not None) -- confirms the None
    # path is specific to genuine infeasibility, not a blanket failure.
    def always_feasible(seq_partial, node, pos):
        return True
    assert liu_random_repair(remaining, removed, rng, always_feasible) is not None
    assert liu_greedy_insertion(remaining, removed, dummy_cost_fn, always_feasible) is not None
    assert liu_random_criticality_repair(remaining, removed, rng, demand_fn, tw_width_fn,
                                           depot_dist_fn, always_feasible) is not None



def run_all():
    tests = [v for k, v in globals().items() if k.startswith('test_') and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests.")
    return failed == 0


if __name__ == '__main__':
    ok = run_all()
    sys.exit(0 if ok else 1)
