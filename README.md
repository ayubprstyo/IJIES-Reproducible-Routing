# IJIES Reproducible Routing

Reproducibility package for **"A Stability-Aware Computational
Intelligence Framework for Risk-Guided Corrective Decision Support in
Execution-Stage Routing Systems"** (submitted to IJIES / INASS).

## Study, briefly

This study addresses execution-stage corrective vehicle routing:
after a route has already been partially executed and a travel-time
disruption is observed, which part of the *remaining* route (if any)
should be re-sequenced? The framework combines:

- **quantile-risk guidance** (p85/p95 tail-risk awareness of travel time),
- **route-stability control** (an explicit penalty on unnecessary
  sequence changes, so a corrective layer does not disrupt a plan more
  than the situation warrants),
- **decision restraint** (an unchanged continuation is always an
  admissible outcome -- the method can recommend "do nothing"),
- a **fuzzy decision-activation gate** that chooses between a
  do-nothing continuation and an already-computed corrective one, and
- comparison against a **recent (2024) external ALNS-based comparator**,
  adapted to this execution-stage setting.

None of these components (freezing served stops, re-optimizing a
remainder, simulated-annealing/ALNS search, penalizing route
inconsistency) is claimed as novel in isolation -- each has precedent in
the routing literature. The contribution is their integration into one
execution-stage decision layer, evaluated together rather than in
isolation.

## Repository structure

```
IJIES_Reproducible_Routing/
├── src/                    Single source of algorithmic logic (simulator,
│                           search, fuzzy gate, Liu-ALNS comparator,
│                           statistics, checkpoint utilities). Notebooks
│                           import from here; they never reimplement it.
├── configs/                Machine-readable, frozen parameter sets
│                           (SA, fuzzy, Liu-ALNS, overall experiment
│                           design). Authoritative source for every
│                           frozen number used anywhere in this repo.
├── notebooks/              00-11 (pipeline stages) + 99 (entry point).
│                           Thin orchestration/documentation layers only.
├── tests/                  Mandatory split-stop regression tests.
├── data_deidentified/      Public, de-identified numerical artifacts
│                           (see "Data confidentiality" below).
├── data_demo_synthetic/    Fully synthetic (fake, randomly generated) demo
│                           data used only to smoke-test the computational
│                           code path (src/data.py, src/simulator.py,
│                           src/search.py, src/liu_alns.py) end-to-end
│                           without requiring any real commercial data.
├── data_private/           NOT included in the public release. Expected
│                           layout for authorized Level-2 reproduction.
├── results/                Generated at runtime (gitignored).
├── tables/                 Generated manuscript tables (.csv).
├── figures/                Generated manuscript figures (.png/.pdf).
└── supplementary/          Adaptation matrix and other reference docs.
```

## Reproducibility levels

### Level 1 — Public statistical reproduction (`DATA_MODE="public"`)

Requires **no confidential operational data**. From the de-identified
numerical artifacts in `data_deidentified/`, a reviewer can reproduce:

- SA calibration (T0/cooling audit, lambda_s sweep and selection)
- the 51-instance held-out NR/FR/RG/SA summary
- the fuzzy decision-gate calibration and robustness evaluation
- the external Liu-ALNS comparator results
- the empirical-resampling (ERR) TomTom robustness check
- daily-instance statistical inference (Friedman, Wilcoxon-Holm, signed
  rank-biserial, bootstrap CIs)
- every table and figure used in the manuscript

### Level 2 — Full computational reproduction (`DATA_MODE="private"`)

Requires **authorized private operational routing inputs** (raw
customer-day demand/time-window records, real coordinates, and the
corresponding distance/travel-time matrices), which are **not
distributed in this repository** because they are confidential
commercial data. With those inputs supplied under `data_private/`, the
full pipeline can be re-run from preprocessing through route
optimization.

## Data confidentiality

This repository does **not** publish: real customer names, raw
customer identifiers, exact GPS coordinates, delivery dates, or any
other confidential commercial/operational record. Public identifiers
have been deterministically anonymized:

- Customers: `C0001`, `C0002`, ... (per-date-scoped)
- Dates: `INSTANCE_001` ... `INSTANCE_063` (with a `day_index` and a
  `calibration`/`heldout` split label)
- TomTom origin-destination pairs: `PAIR_0001` ... `PAIR_0030`

The mappings from these anonymized IDs back to the original values are
kept only in `data_private/` and are **not part of the public release**.
Do not assume the raw commercial dataset is available from this
repository at any reproducibility level.

**Data minimization**: the public `data_deidentified/` package contains
only aggregated, block-level numerical experiment outcomes
(`data_deidentified/experiment_outputs/`) -- sufficient for Level-1
statistical reproduction -- plus the study-design date/calibration split
(see below). It does **not**
include customer-level operational data, locked routes, full
derived distance/travel-time matrices, or any TomTom-derived data (which
is private-only -- see below), since those would effectively
reconstruct the entire operational routing structure. Code-path
computational smoke-testing instead uses `data_demo_synthetic/`, which
is entirely fake data with no connection to any real operational record.

**TomTom-derived observations**: redistribution permission for
TomTom-derived data -- whether raw pair-level observations or even an
aggregated ratio-value pool -- has not been confirmed, so **no
TomTom-derived file is included in the public `data_deidentified/`
package**. `notebooks/02_TOMTOM_QUANTILE_CALIBRATION.ipynb` and
`notebooks/09_TOMTOM_EMPIRICAL_ROBUSTNESS.ipynb` report the frozen,
disclosed multiplier values and the pre-computed ERR experiment outcomes
(which remain public, since they are aggregated study results, not
TomTom source data) without requiring this file in PUBLIC mode; an
authorized copy under `data_private/` enables the full empirical
re-derivation in PRIVATE mode.

## Tested environment

`supplementary/tested_environment_manifest.json` records the exact
Python/package versions and audit outcomes from one validated
clean-runtime run (QUICK+PUBLIC mode) of notebooks 00-11 at packaging
time. Running `notebooks/00_SETUP_AND_DATA_AUDIT.ipynb` yourself
regenerates `results/environment_manifest.json` with your own
environment's versions, which may legitimately differ.

## How to reproduce

1. Clone or download this repository.
2. Open `notebooks/99_REPRODUCE_ALL.ipynb` in Google Colab (or a local
   Jupyter environment).
3. Set `RUN_MODE` (`"quick"` or `"full"`) and `DATA_MODE`
   (`"public"` or `"private"`) in the first code cell.
4. Run all cells. Generated tables land in `tables/`, figures in
   `figures/`, and intermediate/audit artifacts in `results/`.

| RUN_MODE | DATA_MODE | What happens |
|---|---|---|
| quick | public | Fast smoke test: load de-identified artifacts, run the integrity/regression audits, reproduce a small statistics subset, regenerate representative tables. |
| full | public | Full statistical reproduction of every publicly-reproducible manuscript result from the de-identified artifacts. |
| quick | private | Computational smoke test of the routing pipeline on a tiny slice of authorized inputs. |
| full | private | Complete computational reproduction: preprocessing -> quantile calibration -> simulator -> NR/FR/RG/SA -> calibration -> held-out experiment -> fuzzy gate -> Liu-ALNS -> ERR -> statistics -> tables. |

## Expected computational burden

Public statistical reproduction (`DATA_MODE="public"`) is relatively
fast in either `RUN_MODE`, since it primarily aggregates and tests
already-computed de-identified outcomes. Full private computational
reproduction (`DATA_MODE="private"`, `RUN_MODE="full"`) is substantially
heavier for NR/FR/RG/SA, and the Liu-ALNS external comparator is, by a
wide margin, the most computationally expensive component (its
per-evaluation cost is roughly an order of magnitude higher than SA's).
Exact runtimes are not promised here, since they depend heavily on the
hardware behind whichever Colab/local runtime you are using.

## Frozen configuration (authoritative source: `configs/*.json`)

**SA** (`configs/sa_config.json`): T0=111, cooling=0.95, lambda_s=120,
40 iterations, early stop=10, 10 candidate evaluations/iteration (70%
targeted / 30% random), adaptive operator weights (x1.3 success / x0.95
failure), operators = swap/relocate/2-opt, locked prefix, fixed vehicle
assignment.

**Fuzzy gate** (`configs/fuzzy_config.json`): tau=0.45, calibration-only
membership construction (12 calibration instances only), decision-
activation role (selects NR vs already-computed SA; not a route
optimizer).

**Liu-ALNS** (`configs/liu_alns_config.json`): T0=800, alpha=0.98,
gap_iter=20, 401 outer candidate proposals/search evaluations per call (not the total objective-function-call count -- see REPRODUCIBILITY_NOTE.md), Random+Related Removal (Route Removal
excluded as non-transferable to a locked-vehicle-assignment setting),
Random Repair/Greedy Insertion/Random-Criticality Repair, simplified
score-adaptive roulette weighting inspired by the Ropke-Pisinger (2006)
framework cited by Liu et al. (not an exact reproduction -- see
REPRODUCIBILITY_NOTE.md), Liu et al.'s cosine cooling schedule, objective
Z_ext = D + 0.15T + 8L + 8O (no quantile-risk or RSI terms).

See `supplementary/LIU_ADAPTATION_MATRIX.md` for the full
component-by-component adaptation table, and `REPRODUCIBILITY_NOTE.md`
for a reviewer-facing summary of exactly what is/isn't reproducible at
each level.

## License

MIT (see `LICENSE`) applies only to the source code, configuration,
notebooks, and fully synthetic demo data (`data_demo_synthetic/`) in
this repository. It does **not** apply to (and no license is granted
over): confidential operational data (none is distributed here); the
de-identified, aggregated experiment-outcome artifacts in
`data_deidentified/experiment_outputs/`, which are derived from
confidential data and provided for statistical reproduction only; any
TomTom-derived data (not distributed, pending redistribution-permission
confirmation); or the manuscript text itself. See `LICENSE`'s scope note
for the full statement.
