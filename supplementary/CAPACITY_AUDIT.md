# Capacity-Hard Repair Audit

## Context
`src/liu_alns.py`'s repair operators (`liu_random_repair`,
`liu_greedy_insertion`, `liu_random_criticality_repair`) previously
contained a fallback that inserted a node at an infeasible position when
zero capacity-feasible positions existed. This has been removed: these
functions now return `None` (an explicit infeasible-candidate signal),
and the calling search loop treats a `None` candidate as REJECTED
without ever calling the objective function on it.

## Audit question
Was the removed fallback branch ever actually REACHABLE in the reported
experiments -- i.e., did any authorized original route already carry a
vehicle-day assignment exceeding capacity, which could make an
otherwise-feasible repair permutation become infeasible partway through
reconstruction?

## Method
Audited all locked pre-dispatch routes (NR method, seed=101,
trigger_fraction=0.25, shock=p85 -- the fixed input structure shared
across all triggers/shocks/seeds) across all 63 study dates (12
calibration + 51 held-out). For every (date, vehicle) pair, computed the
total assigned weight and volume across all stops on that route and
compared against `WEIGHT_CAP_KG` (10,000 kg) and `VOLUME_CAP_CM3`
(3,992,800 cm3).

## Result
- **163 vehicle-day routes audited** (across all 63 dates).
- **0 capacity violations** (0 exceeding weight cap, 0 exceeding volume cap).

## Theoretical explanation (why this was expected)
Destroy+repair in this comparator only ever reorders nodes within ONE
vehicle's unserved suffix -- it never adds or removes total demand, and
never moves nodes between vehicles (vehicle assignment is locked). The
capacity check itself (`capacity_ok_fn`) evaluates the TOTAL weight/volume
of the current partial reconstruction, which increases monotonically as
nodes are reinserted, converging to the SAME total as the original
(pre-destroy) unserved suffix once all removed nodes are back in. Since
every authorized original route already respects capacity (confirmed by
this audit), every intermediate state during repair is a subset of that
feasible total, and is therefore also feasible. The no-feasible-position
branch is **mathematically unreachable** given this structural property,
independent of which specific node ordering or insertion position is
tried.

## Conclusion
The capacity-hard fix is a **behavior-preserving change** for all
reported experiments in this study. The previously-existing fallback
branch was never exercised on any of the 163 audited vehicle-day routes,
so no existing Liu-ALNS result (calibration, held-out, or ERR) requires
re-evaluation. A regression test
(`tests/test_split_stop_regression.py::test_liu_repair_capacity_infeasible_never_silently_fallback`)
verifies the new behavior directly using a synthetic always-infeasible
capacity function, independent of this audit's real-data finding.

## If this had NOT been the result
Per the agreed protocol: had the audit found even one capacity violation
in an authorized original route, this would have been reported
immediately without proceeding further, since it would mean the
no-feasible-position branch could have been reachable in the reported
Liu-ALNS experiments, requiring those results to be re-evaluated with
the corrected repair logic before being treated as final.
