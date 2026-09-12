# Reproducibility Note (reviewer-facing)

This note summarizes, in one place, exactly what a reviewer can and
cannot reproduce from this repository, and the exact seeds/configuration
used. It intentionally does not narrate internal development history;
it describes the final, corrected state only.

## What can be reproduced publicly (no confidential data needed)

- SA calibration: T0/cooling grid audit and lambda_s sweep, with a
  programmatic selection rule (harm=0% -> unnecessary=0% -> retention
  >=90% -> maximize stability among feasible candidates).
- The 51-instance held-out NR/FR/RG/SA comparison (block-level and
  vehicle-continuation-level metrics, kept explicitly separate).
- The fuzzy decision-activation gate: calibration-only design (12
  calibration instances), threshold selection, and a single held-out
  robustness evaluation (51 instances) framed as a *post-review,
  calibration-only re-analysis evaluated as a robustness assessment* --
  not independent/blind validation, since these 51 instances were
  already examined in the main daily-instance analysis.
- The Adapted Liu-ALNS (2024) external comparator's results.
- The empirical-resampling (ERR) TomTom robustness check.
- Daily-instance statistical inference (Friedman, planned paired
  Wilcoxon with Holm correction, signed rank-biserial correlation,
  10,000-instance-cluster bootstrap 95% CIs).
- Every table and figure in the manuscript, generated programmatically
  from the above (see `notebooks/11_GENERATE_TABLES_FIGURES.ipynb`).

## What requires authorized private operational inputs

- Re-running route optimization (NR/FR/RG/SA search, Liu-ALNS search)
  from raw customer demand/time-window records and real distance/travel-
  time matrices. These are confidential commercial data and are not
  distributed here. `DATA_MODE="private"` documents the expected input
  layout for an authorized party to do this.

## Exact seeds and configuration

- Main held-out experiment seeds: 101, 202, 303 (see
  `configs/experiment_config.json`).
- SA calibration seed: 101 (12 calibration instances only).
- Fuzzy gate: no search seed of its own (deterministic given NR/SA
  outcomes); calibration uses the same 12 calibration instances.
- Liu-ALNS: search seed matches the corresponding NR/FR/RG/SA seed per
  block; T0/alpha/gap_iter frozen per `configs/liu_alns_config.json`.
- ERR (TomTom empirical-resampling robustness): resampling seeds 555
  (NR/SA) and 777 (Liu-ALNS); underlying search seed 101 throughout. See
  `configs/experiment_config.json`'s `err_robustness` block for the full
  disclosure, including the explicit stratified 11-instance subset used
  for Liu-ALNS (never claimed as equivalent in scope to SA/NR's full
  51-instance ERR run).

## Corrected canonical split-stop handling

Six oversized customer-day stops are split into 13 virtual stops (five
stops into 2 pieces each, one stop into 3), for 3,934 total optimization
stops. A canonical virtual-stop mapping (`src/data.py`,
`tests/test_split_stop_regression.py`) is the single source of truth for
every node ID used anywhere in the pipeline: customer attributes, matrix
lookups (split pieces resolve to their parent physical node, since they
share the same location), and route simulation. Every lookup is a hard
failure on a miss -- there is no silent fallback to a zero-cost phantom
stop anywhere in this codebase. Run `tests/test_split_stop_regression.py`
to verify this independently.

## External comparator implementation

The Adapted Liu-ALNS (2024) comparator (`src/liu_alns.py`) is a
serial-algorithm adaptation of Liu, Sun, Duan, Liu (2024, *Scientific
Reports* 14:23809) -- not a replication of their distributed Spark
architecture. Route Removal is excluded as non-transferable to this
study's locked-vehicle-assignment constraint; Clarke-Wright
initialization is excluded since the starting point is a locked route,
not a from-scratch construction problem.

**Adaptive weighting**: the operator-selection weighting is a
**simplified score-adaptive roulette weighting**, inspired by the
adaptive roulette framework Liu et al. cite from Ropke & Pisinger
(2006) -- it is not claimed as an exact reproduction of that scheme.
This implementation actually distinguishes three outcomes: a candidate
that becomes the new global best (score 33), any other accepted
candidate (score 13), and a rejected candidate (score 0). The classic
scheme's fourth outcome (a smaller reward for a candidate that improves
on the current solution without becoming a new global best) is not
implemented -- no code path in `src/liu_alns.py` ever records it, so no
`sigma2` parameter exists in `configs/liu_alns_config.json`.

The comparator's objective is
harmonized to Z_ext = D + 0.15T + 8L + 8O, deliberately excluding this
study's own quantile-risk and RSI-stability terms. Full
component-by-component adaptation detail:
`supplementary/LIU_ADAPTATION_MATRIX.md`.

## ERR (empirical-resampling robustness) scope

SA/NR are evaluated on the **full 51 held-out instances** (3,060
resampled scenarios). Liu-ALNS is evaluated on a **stratified 11-instance
computational-robustness subset** (330 resampled scenarios), selected
deterministically (every 5th instance from the sorted 51-instance list)
for computational tractability given its much higher per-evaluation
cost. This scope difference is disclosed everywhere the ERR results are
reported and should never be described as equivalent coverage.

Terminology used throughout: *"empirical-resampling robustness using
observed TomTom historical traffic ratios."* This is explicitly not
"live traffic replay," "fleet GPS validation," or "real vehicle
trajectory validation."

## Confidentiality constraints

No real customer names, raw customer identifiers, exact GPS coordinates,
or original delivery dates appear anywhere in this public repository.
All public identifiers are deterministic, one-way-published anonymizations
(`C0001...`, `INSTANCE_001...`, `PAIR_0001...` internally during
development; the released public artifacts carry no customer-level or
route-level identifiers at all -- see the data-minimization note below).
The mappings back to original values exist only in `data_private/`, which
is excluded from the public release by `.gitignore` and by the packaging
process that produced this ZIP.

**Data minimization**: `data_deidentified/` ships only aggregated,
block-level experiment outcomes (`experiment_outputs/`) and the
study-design calibration/held-out split -- never customer-level
demand/time-window records, locked routes, full derived
distance/travel-time matrices, or any TomTom-derived data (see below),
since those would effectively reconstruct the entire operational routing
structure. `data_demo_synthetic/` provides fully synthetic (fake) data
so the computational code path can still be exercised end-to-end without
any real data.

**TomTom redistribution**: permission to redistribute TomTom-derived
data was not confirmed for either the raw pair-level observations or an
aggregated ratio-value pool, so **no TomTom-derived file is published**
in `data_deidentified/`. The pre-computed ERR (empirical-resampling
robustness) experiment outcomes remain public, since they are aggregated
study results, not TomTom source data. Full empirical re-derivation of
the quantile multipliers and ERR resampling requires an authorized copy
of the TomTom data placed under `data_private/`.
