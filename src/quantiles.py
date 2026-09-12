"""
src/quantiles.py — travel-time quantile representation.

p50 is the real OSRM base duration matrix (no multiplier). p85/p95 are
TomTom-empirically-verified multipliers derived from 960 observed
historical/no-traffic travel-time ratios across 30 representative
origin-destination pairs and 32 departure-time combinations (see
notebooks/02_TOMTOM_QUANTILE_CALIBRATION.ipynb for the derivation).

IMPORTANT: these are NOT the 1.1503/1.3071 values embedded in the raw
`osrm_tomtom_saved_matrices` package's own pre-computed p85/p95 columns
(an earlier/different calibration run). Only that package's p50 column
(base OSRM duration, unaffected by any multiplier choice) is used as
input; p85/p95 are always re-derived here.

SINGLE SOURCE OF TRUTH: these multiplier values and their bootstrap CIs
are loaded from configs/experiment_config.json at import time, not
hardcoded as separate literals here -- the module-level names below
(P50_MULTIPLIER etc.) are a convenience re-export for callers, not an
independent value.
"""
import json as _json
import os as _os

_CONFIG_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                              "configs", "experiment_config.json")
with open(_CONFIG_PATH) as _f:
    _exp_cfg = _json.load(_f)
_quantile_cfg = _exp_cfg["quantile_multipliers"]

P50_MULTIPLIER = _quantile_cfg["p50"]
P85_MULTIPLIER = _quantile_cfg["p85"]
P95_MULTIPLIER = _quantile_cfg["p95"]

# OD-pair cluster-bootstrap (5,000 resamples) 95% CIs, for reference/reporting.
P85_BOOTSTRAP_CI95 = tuple(_exp_cfg["quantile_bootstrap_ci95"]["p85"])
P95_BOOTSTRAP_CI95 = tuple(_exp_cfg["quantile_bootstrap_ci95"]["p95"])


def apply_multiplier(base_p50_minutes, quantile):
    if quantile == 'p50':
        return base_p50_minutes * P50_MULTIPLIER
    elif quantile == 'p85':
        return base_p50_minutes * P85_MULTIPLIER
    elif quantile == 'p95':
        return base_p50_minutes * P95_MULTIPLIER
    raise ValueError(f"Unknown quantile: {quantile}")


def derive_multipliers_from_raw_tomtom(raw_validation_csv_path):
    """Recompute P85_MULTIPLIER / P95_MULTIPLIER from the raw 960-observation
    TomTom file (with pair_id/pair_type/weekday/hour structure), for
    verification/auditability under PRIVATE/Level-2 reproduction. Should
    reproduce 1.1559 / 1.2935 (and the bootstrap CIs above) when run
    against the original source file. Not published publicly -- see
    derive_multipliers_from_aggregated_pool() for the authorized/private
    aggregated-pool utility."""
    import pandas as pd
    import numpy as np

    df = pd.read_csv(raw_validation_csv_path)
    ratios = df['historic_ratio'].dropna()
    pooled_median = ratios.median()
    normalized = ratios / pooled_median
    p85 = normalized.quantile(0.85)
    p95 = normalized.quantile(0.95)

    rng = np.random.default_rng(2024)
    pair_ids = df['pair_id'].unique()
    boot_p85, boot_p95 = [], []
    for _ in range(5000):
        sampled_pairs = rng.choice(pair_ids, size=len(pair_ids), replace=True)
        sample = pd.concat([df[df['pair_id'] == p] for p in sampled_pairs])
        r = sample['historic_ratio'].dropna()
        rn = r / r.median()
        boot_p85.append(rn.quantile(0.85))
        boot_p95.append(rn.quantile(0.95))
    ci85 = (float(np.percentile(boot_p85, 2.5)), float(np.percentile(boot_p85, 97.5)))
    ci95 = (float(np.percentile(boot_p95, 2.5)), float(np.percentile(boot_p95, 97.5)))

    return dict(p85=float(p85), p95=float(p95), p85_ci95=ci85, p95_ci95=ci95, n_observations=len(ratios))


def derive_multipliers_from_aggregated_pool(aggregated_pool_csv_path):
    """
    Authorized/private aggregated-pool utility: works from an aggregated
    ratio-value pool (available only under `data_private/` -- see
    REPRODUCIBILITY_NOTE.md for why this is not published in
    `data_deidentified/`), which contains only the anonymized
    `historic_ratio` values with no origin-destination-pair or timestamp
    structure (that structure was removed as a data-minimization step
    when this artifact was first prepared).

    Because pair-level clustering information is not available in this
    aggregated private artifact, the bootstrap here resamples individual
    OBSERVATIONS (not pairs) with replacement -- a simple (not
    cluster-aware) bootstrap. This is expected to give a similar but not
    numerically identical CI to the private, pair-clustered bootstrap in
    derive_multipliers_from_raw_tomtom(); both are reported as CIs, not
    as the frozen point-estimate multiplier itself.
    """
    import pandas as pd
    import numpy as np

    df = pd.read_csv(aggregated_pool_csv_path)
    ratios = df['historic_ratio'].dropna()
    pooled_median = ratios.median()
    normalized = ratios / pooled_median
    p85 = normalized.quantile(0.85)
    p95 = normalized.quantile(0.95)

    rng = np.random.default_rng(2024)
    n = len(ratios)
    boot_p85, boot_p95 = [], []
    for _ in range(5000):
        sample = ratios.sample(n=n, replace=True, random_state=rng.integers(0, 2**32 - 1))
        rn = sample / sample.median()
        boot_p85.append(rn.quantile(0.85))
        boot_p95.append(rn.quantile(0.95))
    ci85 = (float(np.percentile(boot_p85, 2.5)), float(np.percentile(boot_p85, 97.5)))
    ci95 = (float(np.percentile(boot_p95, 2.5)), float(np.percentile(boot_p95, 97.5)))

    return dict(p85=float(p85), p95=float(p95), p85_ci95=ci85, p95_ci95=ci95, n_observations=len(ratios),
                bootstrap_note="observation-level (not pair-clustered) bootstrap -- see docstring")
