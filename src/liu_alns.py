"""
src/liu_alns.py — Adapted Liu-ALNS (2024) external comparator.

Source: Liu, Sun, Duan, Liu (2024). "Parallel adaptive large neighborhood
search based on spark to solve VRPTW." Scientific Reports 14, 23809.
(Open-access.) This is NOT a replication of the paper's distributed Spark
architecture -- only the serial destroy/repair/acceptance/cooling
algorithm is adapted. See supplementary/LIU_ADAPTATION_MATRIX.md for the
full component-by-component adaptation table.

Route Removal is EXCLUDED (non-transferable: its defining cross-route
consolidation mechanism conflicts with the locked vehicle-assignment
constraint of this execution-stage problem). CW initialization is
EXCLUDED (the starting point is a locked route, not a from-scratch
construction problem). Objective is harmonized to
Z_ext = D + 0.15*T + 8*L + 8*O -- explicitly excluding the quantile-risk
and RSI/stability penalties unique to this study's own SA method.
"""
import math
import random
import numpy as np
from src.simulator import simulate_mixed_route, route_stability

OPS_DESTROY = ['random_removal', 'related_removal']
OPS_REPAIR = ['random_repair', 'greedy_insertion', 'random_criticality_repair']


def liu_random_removal(unserved, rng, n_remove):
    n_remove = min(n_remove, len(unserved))
    idx = rng.sample(range(len(unserved)), n_remove)
    removed = [unserved[i] for i in idx]
    remaining = [n for i, n in enumerate(unserved) if i not in idx]
    return remaining, removed


def liu_related_removal(unserved, rng, n_remove, dist_fn, max_dist):
    """Eq. 11: R(i,j)=1/(C_ij+y_ij). AUDITED: since every candidate pair here
    is inherently same-vehicle, y_ij is constant -- this operator is
    effectively DISTANCE-RELATED removal in this execution-stage setting
    (disclosed, not silently simplified)."""
    if len(unserved) <= 1:
        return unserved, []
    n_remove = min(n_remove, len(unserved))
    remaining = unserved.copy()
    removed = [remaining.pop(rng.randrange(len(remaining)))]
    y0 = 0.0
    while len(removed) < n_remove and remaining:
        ref = rng.choice(removed)
        def R(cand):
            c_ij = dist_fn(ref, cand) / max_dist if max_dist > 0 else 0.0
            return 1.0 / (c_ij + y0 + 1e-9)
        best = max(remaining, key=R)
        removed.append(best); remaining.remove(best)
    return remaining, removed


def liu_random_repair(remaining, removed, rng, capacity_ok_fn):
    """Returns None (infeasible candidate) if any removed node has zero
    feasible insertion positions -- no silent fallback to an infeasible
    position."""
    order = removed.copy(); rng.shuffle(order)
    seq = remaining.copy()
    for node in order:
        positions = [p for p in range(len(seq) + 1) if capacity_ok_fn(seq, node, p)]
        if not positions:
            return None
        seq.insert(rng.choice(positions), node)
    return seq


def liu_greedy_insertion(remaining, removed, eval_cost_fn, capacity_ok_fn):
    """Returns None (infeasible candidate) if, at any point, NO remaining
    node in the pool has any feasible insertion position -- no silent
    fallback to an infeasible position."""
    seq = remaining.copy(); pool = removed.copy()
    while pool:
        best = None
        for node in pool:
            positions = [p for p in range(len(seq) + 1) if capacity_ok_fn(seq, node, p)]
            for p in positions:
                c = eval_cost_fn(seq, node, p)
                if best is None or c < best[0]:
                    best = (c, node, p)
        if best is None:
            return None
        _, node, pos = best
        seq.insert(pos, node); pool.remove(node)
    return seq


def liu_random_criticality_repair(remaining, removed, rng, demand_fn, tw_width_fn, depot_dist_fn, capacity_ok_fn):
    """Eq. 12: phi_i = eta(d_i)/eta(b_i-a_i) + eta(c_0i); insert descending-phi
    at a random feasible position (the 'random path' in the original paper
    collapses to the fixed same-vehicle suffix here). Returns None
    (infeasible candidate) if any removed node has zero feasible insertion
    positions -- no silent fallback to an infeasible position."""
    if not removed:
        return remaining
    d = np.array([demand_fn(n) for n in removed], dtype=float)
    w = np.array([tw_width_fn(n) for n in removed], dtype=float)
    c0 = np.array([depot_dist_fn(n) for n in removed], dtype=float)
    def norm(x):
        r = x.max() - x.min()
        return (x - x.min()) / r if r > 1e-9 else np.zeros_like(x)
    phi = norm(d) / (norm(w) + 1e-6) + norm(c0)
    order = [removed[i] for i in np.argsort(-phi)]
    seq = remaining.copy()
    for node in order:
        positions = [p for p in range(len(seq) + 1) if capacity_ok_fn(seq, node, p)]
        if not positions:
            return None
        seq.insert(rng.choice(positions), node)
    return seq


class AdaptiveWeights:
    """
    Simplified score-adaptive roulette weighting, inspired by the adaptive
    roulette framework Liu et al. (2024) cite from Ropke & Pisinger (2006)
    -- NOT claimed as an exact reproduction of the original four-outcome
    (new-global-best / better-than-current / accepted-worse / rejected)
    scoring scheme. This implementation actually distinguishes only THREE
    outcomes: a candidate that becomes the new global best (score sigma1),
    any other accepted candidate (score sigma3), and a rejected candidate
    (score 0). A fourth "improved" outcome (a smaller sigma2 reward for
    candidates that are better than the current solution but not a new
    global best) was never wired into the outer search loop -- no code
    path ever records that outcome -- so it is not implemented and no
    sigma2 parameter exists here.
    """
    def __init__(self, names, sigma1, sigma3, reaction_factor):
        self.names = names
        self.sigma1, self.sigma3 = sigma1, sigma3
        self.reaction_factor = reaction_factor
        self.weights = {n: 1.0 for n in names}
        self.scores = {n: 0.0 for n in names}
        self.uses = {n: 0 for n in names}

    def choose(self, rng):
        return rng.choices(self.names, weights=[self.weights[n] for n in self.names], k=1)[0]

    def record(self, name, outcome):
        self.uses[name] += 1
        self.scores[name] += {'best': self.sigma1, 'accepted': self.sigma3, 'rejected': 0.0}[outcome]

    def update_segment(self):
        for n in self.names:
            avg = self.scores[n] / self.uses[n] if self.uses[n] > 0 else 0.0
            self.weights[n] = self.weights[n] * (1 - self.reaction_factor) + self.reaction_factor * avg
            self.scores[n], self.uses[n] = 0.0, 0


def liu_temperature(T0_base, t, alpha, gap_iter):
    """Eqs. 13-14: T0 decays multiplicatively each iteration; actual
    temperature oscillates around that decaying base via a cosine
    envelope."""
    T0_current = T0_base * (alpha ** t)
    return max(T0_current * (1 + math.cos(t * math.pi / gap_iter)), 1e-9)


def liu_alns_search(ctx, date, full_seq, frozen_flags, disruption, liu_config, seed):
    """
    Objective: Z_ext = D + c_T*T + c_L*L + c_O*O (no risk/stability terms).
    Served prefix and vehicle assignment are structurally immutable.

    `liu_config` must be the dict loaded from configs/liu_alns_config.json
    (or equivalent) -- T0, alpha, gap_iter, max_iter, n_candidates,
    objective_coefficients, and adaptive_weight_params all come from it.
    There is no fallback default for any of these.
    """
    T0_base = liu_config['T0']
    alpha = liu_config['alpha']
    gap_iter = liu_config['gap_iter']
    max_iter = liu_config['max_iter']
    n_candidates = liu_config['n_candidates_per_iteration']
    coeffs = liu_config['objective_coefficients']
    awp = liu_config['adaptive_weight_params']

    rng = random.Random(seed)
    served = [n for n, f in zip(full_seq, frozen_flags) if f]
    unserved = [n for n, f in zip(full_seq, frozen_flags) if not f]

    max_dist = max(ctx.distance(date, a, b) for a in unserved + [served[-1] if served else "DEPOT_1"]
                    for b in unserved) if len(unserved) > 1 else 1.0
    max_dist = max(max_dist, 1e-6)

    total_objective_calls = [0]  # counts EVERY eval_Z() call, including internal
                                   # calls made by greedy_insertion's cost_fn for
                                   # each candidate insertion position -- this is
                                   # the TRUE total objective-function evaluation
                                   # count, which is substantially higher than the
                                   # outer proposal count when greedy_insertion is
                                   # selected as the repair operator.
    def eval_Z(u_seq):
        total_objective_calls[0] += 1
        cand_full = served + u_seq
        cand_frozen = [True] * len(served) + [False] * len(u_seq)
        m = simulate_mixed_route(ctx, date, cand_full, cand_frozen, disruption)
        return (m['distance'] + coeffs['travel_time'] * m['travel_time'] +
                coeffs['lateness'] * m['lateness'] + coeffs['overtime'] * m['overtime']), m

    def capacity_ok(seq_partial, node, pos):
        trial = seq_partial[:pos] + [node] + seq_partial[pos:]
        w = sum(ctx.customers.get((date, n), {}).get('weight', 0.0) for n in trial)
        v = sum(ctx.customers.get((date, n), {}).get('volume', 0.0) for n in trial)
        from src.data import WEIGHT_CAP_KG, VOLUME_CAP_CM3
        return w <= WEIGHT_CAP_KG and v <= VOLUME_CAP_CM3

    def demand_fn(n): return ctx.customers[(date, n)]['weight']
    def tw_width_fn(n):
        c = ctx.customers[(date, n)]; return max(c['tw_end'] - c['tw_start'], 1e-6)
    def depot_dist_fn(n): return ctx.distance(date, "DEPOT_1", n)
    def dist_fn(a, b): return ctx.distance(date, a, b)

    if len(unserved) < 2:
        m = simulate_mixed_route(ctx, date, full_seq, [True] * len(full_seq), disruption)
        return {'seq': unserved, 'metrics': m, 'changed': False, 'n_outer_proposals': 0, 'total_objective_calls': 0}

    best_seq = unserved
    best_Z, best_m = eval_Z(unserved)
    current_seq, current_Z, current_m = best_seq, best_Z, best_m
    destroy_w = AdaptiveWeights(OPS_DESTROY, awp['sigma1'], awp['sigma3'], awp['reaction_factor'])
    repair_w = AdaptiveWeights(OPS_REPAIR, awp['sigma1'], awp['sigma3'], awp['reaction_factor'])
    n_outer_proposals = 1  # counts outer candidate proposals/search evaluations only
                             # (NOT total objective-function calls -- see total_objective_calls)
    segment = 0
    for t in range(max_iter):
        T = liu_temperature(T0_base, t, alpha, gap_iter)
        for _ in range(n_candidates):
            d_op = destroy_w.choose(rng)
            r_op = repair_w.choose(rng)
            n_remove = max(1, min(len(current_seq) - 1, rng.randint(1, max(1, len(current_seq) // 3))))
            if d_op == 'random_removal':
                remaining, removed = liu_random_removal(current_seq, rng, n_remove)
            else:
                remaining, removed = liu_related_removal(current_seq, rng, n_remove, dist_fn, max_dist)
            if r_op == 'random_repair':
                cand = liu_random_repair(remaining, removed, rng, capacity_ok)
            elif r_op == 'greedy_insertion':
                def cost_fn(seq_p, node, pos):
                    trial = seq_p[:pos] + [node] + seq_p[pos:]
                    z, _ = eval_Z(trial)
                    return z
                cand = liu_greedy_insertion(remaining, removed, cost_fn, capacity_ok)
            else:
                cand = liu_random_criticality_repair(remaining, removed, rng, demand_fn, tw_width_fn, depot_dist_fn, capacity_ok)

            n_outer_proposals += 1
            if cand is None:
                # Repair could not find a capacity-feasible position for
                # every removed node -- this candidate is INFEASIBLE, not
                # silently inserted at an infeasible position. It is
                # rejected without ever calling eval_Z (no objective value
                # exists for an infeasible candidate).
                destroy_w.record(d_op, 'rejected'); repair_w.record(r_op, 'rejected')
                continue

            cand_Z, cand_m = eval_Z(cand)
            delta = cand_Z - current_Z
            if delta <= 0 or rng.random() < math.exp(-delta / max(T, 1e-9)):
                current_seq, current_Z, current_m = cand, cand_Z, cand_m
                if cand_Z < best_Z - 1e-9:
                    best_seq, best_Z, best_m = cand, cand_Z, cand_m
                    destroy_w.record(d_op, 'best'); repair_w.record(r_op, 'best')
                else:
                    destroy_w.record(d_op, 'accepted'); repair_w.record(r_op, 'accepted')
            else:
                destroy_w.record(d_op, 'rejected'); repair_w.record(r_op, 'rejected')
        segment += 1
        if segment % 5 == 0:
            destroy_w.update_segment(); repair_w.update_segment()

    changed = (best_seq != unserved)
    return {'seq': best_seq, 'metrics': best_m, 'changed': changed,
            'n_outer_proposals': n_outer_proposals, 'total_objective_calls': total_objective_calls[0]}
