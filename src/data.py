"""
src/data.py — data loading and the canonical virtual-stop mapping.

The canonical mapping is the SINGLE source of truth for every node ID used
anywhere in this pipeline (customer attributes, locked sequences, matrix
lookups, demand, service time, time windows). It exists to fix a
previously-discovered bug: an early build independently re-derived its own
split-stop naming (`{id}__v{k}`) that did not match the naming already
baked into the archived locked-route sequences (`{id}__SPLIT{k}of{n}`),
causing 13 virtual stops (from 6 oversized source stops) to silently
resolve to nothing and be treated as zero-demand, zero-travel phantom
stops. This module IS the single source of truth for the canonical
mechanism; there is no separate bug-history document shipped publicly.

Fix: canonicalize to the archived `__SPLITkofN` convention (chosen because
it is fixed, external input baked into the locked routes) and make every
lookup a HARD FAILURE on a miss -- no silent fallback to a default value
anywhere in this module or in src/simulator.py.
SINGLE SOURCE OF TRUTH: vehicle capacity limits and the default service
time are loaded from configs/experiment_config.json at import time, not
hardcoded as independent literals -- see WEIGHT_CAP_KG / VOLUME_CAP_CM3 /
DEFAULT_SERVICE_MIN below.
"""
import json
import math
import os
import pandas as pd

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "configs", "experiment_config.json")
with open(_CONFIG_PATH) as _f:
    _exp_cfg = json.load(_f)

WEIGHT_CAP_KG = _exp_cfg["vehicle_capacity"]["weight_cap_kg"]
VOLUME_CAP_CM3 = _exp_cfg["vehicle_capacity"]["volume_cap_cm3"]
DEFAULT_SERVICE_MIN = _exp_cfg["default_service_time_min"]["value"]


def build_canonical_mapping(stops_csv_path):
    """
    Returns:
      mapping_df: delivery_date | original_customer_id | virtual_stop_id |
                  piece_index | piece_count | parent_physical_node
      customers: dict keyed by (delivery_date, virtual_stop_id) -> dict of
                 weight, volume, tw_start, tw_end, service_min,
                 parent_physical_node
      oversized: the raw rows identified as exceeding vehicle capacity
                 (for audit/regression-test purposes)

    Demand/volume/service-time split rule for oversized stops: EQUAL
    division across pieces. The source data records only the combined
    per-customer-day total; no finer split ratio is recoverable from any
    available input file, so equal division is used and disclosed as a
    stated modeling choice (matching the manuscript's Section 5.1
    description), not a guess.
    """
    stops = pd.read_csv(stops_csv_path)
    stops.columns = [c.strip() for c in stops.columns]

    oversized_mask = (stops['total_weight'] > WEIGHT_CAP_KG) | (stops['total_volume'] > VOLUME_CAP_CM3)
    oversized = stops[oversized_mask].copy()
    normal = stops[~oversized_mask].copy()

    oversized['weight_ratio'] = oversized['total_weight'] / WEIGHT_CAP_KG
    oversized['volume_ratio'] = oversized['total_volume'] / VOLUME_CAP_CM3
    oversized['min_pieces'] = oversized[['weight_ratio', 'volume_ratio']].max(axis=1).apply(math.ceil)

    mapping_rows = []
    customers = {}

    for _, row in normal.iterrows():
        vid = row['customer_code']
        mapping_rows.append(dict(
            delivery_date=row['delivery_date'], original_customer_id=row['customer_code'],
            virtual_stop_id=vid, piece_index=1, piece_count=1, parent_physical_node=row['customer_code']))
        customers[(row['delivery_date'], vid)] = dict(
            weight=row['total_weight'], volume=row['total_volume'],
            tw_start=row['tw_start_min'], tw_end=row['tw_end_min'],
            service_min=row['service_time_min_baseline'] if row['service_time_min_baseline'] > 0 else DEFAULT_SERVICE_MIN,
            parent_physical_node=row['customer_code'])

    for _, row in oversized.iterrows():
        n = int(row['min_pieces'])
        root = row['customer_code']
        for k in range(1, n + 1):
            vid = f"{root}__SPLIT{k}of{n}"
            mapping_rows.append(dict(
                delivery_date=row['delivery_date'], original_customer_id=root,
                virtual_stop_id=vid, piece_index=k, piece_count=n, parent_physical_node=root))
            customers[(row['delivery_date'], vid)] = dict(
                weight=row['total_weight'] / n, volume=row['total_volume'] / n,
                tw_start=row['tw_start_min'], tw_end=row['tw_end_min'],
                service_min=(row['service_time_min_baseline'] if row['service_time_min_baseline'] > 0 else DEFAULT_SERVICE_MIN) / n,
                parent_physical_node=root)

    mapping_df = pd.DataFrame(mapping_rows)
    return mapping_df, customers, oversized


def verify_archived_ids_resolve(mapping_df, archived_split_ids):
    """Hard check used at pipeline startup: every __SPLIT id actually seen
    in the archived locked routes must resolve in the canonical mapping."""
    canonical_ids = set(mapping_df['virtual_stop_id'])
    unresolved = [i for i in archived_split_ids if i not in canonical_ids]
    if unresolved:
        raise ValueError(f"HARD FAIL: unresolved archived split IDs (no silent fallback): {unresolved}")
    return True


def load_distance_matrix(path):
    df = pd.read_csv(path)
    out = {}
    for date, grp in df.groupby('delivery_date'):
        out[date] = dict(zip(zip(grp['origin_id'], grp['destination_id']), grp['distance_km']))
    return out


def load_travel_time_p50_matrix(path):
    df = pd.read_csv(path)
    out = {}
    for date, grp in df.groupby('delivery_date'):
        out[date] = dict(zip(zip(grp['origin_id'], grp['destination_id']), grp['travel_time_min_p50']))
    return out


def load_locked_routes(sequences_csv_path, seed=101, trigger_fraction=0.25, shock='p85'):
    """Extract the locked pre-dispatch route per date/vehicle from the
    archived NR-method sequences. Verified identical across trigger
    fractions/shocks in prior analysis (a genuine fixed input, not a
    new-experiment output) -- any single (seed, trigger, shock) slice of
    the NR method recovers the same underlying full-day route."""
    seq = pd.read_csv(sequences_csv_path)
    nr_ref = seq[(seq['method'] == 'NR') & (seq['seed'] == seed) &
                 (seq['trigger_fraction'] == trigger_fraction) & (seq['shock'] == shock)]
    locked = {}
    for date, grp in nr_ref.groupby('delivery_date'):
        routes = {}
        for vid, vgrp in grp.groupby('vehicle_id'):
            routes[vid] = vgrp.sort_values('sequence')['node_id'].tolist()
        locked[date] = routes
    return locked


def validate_locked_routes_resolve(locked_routes, customers):
    """Hard assertion: every locked-route node must resolve to a canonical
    customer entry or be the depot, BEFORE any experiment runs."""
    unresolved = []
    for date, routes in locked_routes.items():
        for vid, nodes in routes.items():
            for node in nodes:
                if node == "DEPOT_1":
                    continue
                if (date, node) not in customers:
                    unresolved.append((date, vid, node))
    if unresolved:
        raise ValueError(f"HARD FAIL: {len(unresolved)} locked-route nodes do not resolve: {unresolved[:10]}")
    return True
