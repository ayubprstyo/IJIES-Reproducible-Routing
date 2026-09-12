"""
src/metrics.py — shared metric computations used across the pipeline.

Kept unit-explicit throughout: vehicle-continuation-level vs block-level
metrics must never be silently mixed in one column (see README's
reproducibility notes for why this matters).
"""
import numpy as np


def on_time_counts(ctx, date, node_seq, frozen_flags, shock, depot_start_min=480):
    """Returns (num_on_time, total_stops) for a single vehicle route under
    the mixed prefix-p50 / remainder-disruption evaluation."""
    is_delay = shock.startswith('delay')
    remainder_q = 'p50' if is_delay else shock
    delay_amt = {'delay20': 20.0, 'delay30': 30.0}.get(shock, 0.0)
    t, prev, prev_frozen = depot_start_min, "DEPOT_1", True
    num, den = 0, 0
    for node, frozen in zip(node_seq, frozen_flags):
        q = 'p50' if frozen else remainder_q
        t += ctx.travel_time(date, prev, node, q)
        if prev_frozen and not frozen:
            t += delay_amt
        cust = ctx.customers[(date, node)]
        if t < cust['tw_start']:
            t = cust['tw_start']
        den += 1
        if t <= cust['tw_end']:
            num += 1
        t += cust['service_min']
        prev, prev_frozen = node, frozen
    return num, den


def empirical_no_harm_rate(method_lateness, baseline_lateness, tolerance=1e-6):
    """Fraction of paired observations where method_lateness does not
    exceed baseline_lateness (typically NR) by more than `tolerance`."""
    method_lateness = np.asarray(method_lateness)
    baseline_lateness = np.asarray(baseline_lateness)
    harm = (method_lateness > baseline_lateness + tolerance)
    return 100.0 * (1 - harm.mean()), int(harm.sum())


def benefit_retention(method_reduction_sum, reference_reduction_sum):
    """Retention of a reference method's total benefit (e.g. SA's retention
    of RG's lateness-reduction benefit, or a fuzzy gate's retention of
    always-SA benefit)."""
    if reference_reduction_sum == 0:
        return float('nan')
    return 100.0 * method_reduction_sum / reference_reduction_sum


def block_unchanged_rate(n_unchanged_vehicles, n_vehicles):
    """Vehicle-continuation-level unchanged rate for one block."""
    return 100.0 * n_unchanged_vehicles / n_vehicles if n_vehicles > 0 else 100.0


def rank_biserial_signed(a, b):
    """
    Matched-pairs rank-biserial correlation with an EXPLICIT sign
    convention: r > 0 means 'a' tends to be LARGER (worse, for a
    lateness-type metric) than 'b'; r < 0 means 'a' tends to be smaller.
    r in [-1, 1]. Returns (r, n_nonzero_pairs).
    """
    diff = np.asarray(a) - np.asarray(b)
    nz = diff[diff != 0]
    if len(nz) == 0:
        return 0.0, 0
    ranks = np.argsort(np.argsort(np.abs(nz))) + 1
    w_pos = ranks[nz > 0].sum()
    w_neg = ranks[nz < 0].sum()
    return (w_pos - w_neg) / (w_pos + w_neg), len(nz)


def holm_correction(pvalues):
    """Holm step-down correction for family-wise error rate control."""
    pvals = np.array(pvalues)
    order = np.argsort(pvals)
    m = len(pvals)
    adjusted = np.empty(m)
    prev = 0.0
    for i, idx in enumerate(order):
        val = min(max((m - i) * pvals[idx], prev), 1.0)
        adjusted[idx] = val
        prev = val
    return adjusted


def date_cluster_bootstrap_ci(daily_a, daily_b, n_boot=10000, seed=42, ci=(2.5, 97.5)):
    """10,000-resample date-cluster bootstrap 95% CI for the mean paired
    difference (a - b), resampling DATES (not blocks) with replacement --
    the independent unit for daily-instance inference."""
    rng = np.random.default_rng(seed)
    n = len(daily_a)
    daily_a = np.asarray(daily_a)
    daily_b = np.asarray(daily_b)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        diffs[i] = (daily_a[idx] - daily_b[idx]).mean()
    lo, hi = np.percentile(diffs, ci)
    return float(lo), float(hi), diffs
