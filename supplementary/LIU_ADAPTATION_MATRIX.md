# Adapted Liu-ALNS (2024) — Adaptation Matrix

| Liu et al. Original Component | Exact Source Definition | Our Execution-Stage Adaptation | Reason for Adaptation |
|---|---|---|---|
| CW Initialization | Clarke-Wright savings (1964), standard | **Excluded** — starting route is the locked pre-dispatch route | Not a from-scratch construction problem |
| Random Removal | P random customers from a route, reinsert cross-route | Retained — P random from **same-vehicle unserved suffix only**, reinsert to that suffix only | Vehicle assignment locked |
| **Route Removal** | Remove a full route, redistribute across routes, **can reduce vehicle count** | **Excluded as non-transferable** | "its defining cross-route consolidation mechanism conflicts with the locked vehicle-assignment constraint of the execution-stage problem" |
| Related Removal | R(i,j)=1/(C_ij+y_ij), cross-route candidates | Same formula; y_ij is **constant** since all candidates are same-vehicle by construction — **effectively distance-related removal** in this setting (audited, documented, not silently changed) | Candidates restricted to same-vehicle suffix |
| Random Repair | Random insert, hard time-window rejection | Random insert, **capacity hard**; time-window violation **allowed, penalized via lateness** in Z_ext | Our problem is soft-penalized, not hard-infeasible |
| Greedy Insertion | Cheapest position, cross-route | Cheapest position by Z_ext, **within same-vehicle suffix only** | idem |
| Random-Criticality Repair | phi_i formula, insert at random position in random route | Same phi_i formula; insert at random position **within same-vehicle suffix** ("random path" collapses to the fixed suffix) | idem |
| Roulette adaptive weight | Cited to Ropke-Pisinger (2006), no explicit formula given by Liu et al. | Simplified score-adaptive roulette weighting, inspired by the cited framework: THREE outcomes actually used (global-best=score 33, accepted-non-best=score 13, rejected=score 0), not the original four-outcome scheme | Inspired by what Liu et al. cite, NOT claimed as an exact reproduction -- a fourth "improved" outcome exists in the classic scheme but is not implemented here (no code path records it) |
| Cooling: T=T0*(1+cos(t*pi/gapIter)), T0=T0*alpha | Exact formula from paper | Same formula exactly; T0/alpha/gapIter calibrated on 12 calibration dates (paper's own values for the Solomon benchmark are not transferable to this dataset's scale) | Different problem scale |
| Metropolis acceptance | f(Pnew)<f(Pbest) accept; else Metropolis | Same exactly | Universal mechanism |
| Objective | C1=min distance, C2=min vehicle count | **Replaced**: Z_ext = D+0.15T+8L+8O | Fair comparison; excludes RSI/quantile-risk unique to our own method |

## Explicit exclusions (never silently added back)
- No quantile-risk penalty (0.75*(0.4*L85+0.6*L95)) in the comparator's objective.
- No RSI/stability penalty (lambda_s*(1-RSI)) in the comparator's objective.
- No cross-vehicle candidate generation in any operator.
- No modification to the served prefix under any circumstance.

## Vehicle-assignment / served-prefix integrity
Structurally guaranteed: `served` is read-only in `liu_alns_search()`; only
`unserved` (a single vehicle's suffix) is ever passed to any destroy/repair
operator. No operator in this library has cross-vehicle capability.
