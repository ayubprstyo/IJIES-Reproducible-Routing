"""
src/preprocessing.py — raw order aggregation into customer-day stops.

Orders belonging to the same customer and date are aggregated into one
stop before the oversized-stop split (src/data.py) is applied. This
module operates on Level-2 (private, authorized) inputs; the
de-identified public package ships the ALREADY-aggregated
customer_day_stops file, so this module is only exercised in a full
computational reproduction (Level 2), not in the public Level-1
statistical reproduction path.
"""
import pandas as pd


def aggregate_orders_to_stops(orders_df):
    """
    Expected input columns: delivery_date, customer_code, order_weight,
    order_volume, order_count (or equivalent raw order-level fields).
    Returns one row per (delivery_date, customer_code) with summed demand.
    """
    required = ['delivery_date', 'customer_code']
    missing = [c for c in required if c not in orders_df.columns]
    if missing:
        raise ValueError(f"aggregate_orders_to_stops: missing required columns {missing}")

    agg_spec = {}
    for col in ['total_weight', 'total_volume', 'order_count']:
        if col in orders_df.columns:
            agg_spec[col] = 'sum'
    for col in ['tw_start_min', 'tw_end_min', 'service_time_min_baseline', 'longitude', 'latitude']:
        if col in orders_df.columns:
            agg_spec[col] = 'first'

    stops = orders_df.groupby(['delivery_date', 'customer_code'], as_index=False).agg(agg_spec)
    return stops


def verify_stop_count(stops_df, expected_count):
    actual = len(stops_df)
    if actual != expected_count:
        raise AssertionError(f"Expected {expected_count} customer-day stops, got {actual}.")
    return True
