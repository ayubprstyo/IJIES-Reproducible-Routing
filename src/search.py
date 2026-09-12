"""
src/search.py — corrective search for FR/RG/SA (NR requires no search).

Every numeric parameter used here (T0, cooling, lambda_s, iteration
budget, candidate split, adaptive-weight multipliers/bounds, risk
weights, depot start time) is REQUIRED as an explicit argument or via the
`sa_config` dict loaded from `configs/sa_config.json` -- there are no
hardcoded defaults in this module. `configs/sa_config.json` is the single
source of truth; if you change a parameter, change it there, not here.

Served prefix and vehicle assignment are structurally immutable:
operators only ever receive/return the `unserved` list.
"""
import math
import random
from src.simulator import simulate_mixed_route, route_stability, objective_Z

OP_NAMES = ['swap', 'relocate', 'two_opt']


def op_swap(seq, rng, i=None, j=None):
    if len(seq) < 2:
        return seq
    if i is None or j is None:
        i, j = rng.sample(range(len(seq)), 2)
    s = seq.copy(); s[i], s[j] = s[j], s[i]
    return s


def op_relocate(seq, rng, i=None, j=None):
    if len(seq) < 2:
        return seq
    if i is None:
        i = rng.randrange(len(seq))
    if j is None:
        j = rng.randrange(len(seq))
    s = seq.copy(); node = s.pop(i); s.insert(j, node)
    return s


def op_two_opt(seq, rng, i=None, j=None):
    if len(seq) < 3:
        return seq
    if i is None or j is None:
        i, j = sorted(rng.sample(range(len(seq)), 2))
    else:
        i, j = sorted((i, j))
    s = seq.copy(); s[i:j+1] = reversed(s[i:j+1])
    return s


OP_FUNCS = {'swap': op_swap, 'relocate': op_relocate, 'two_opt': op_two_opt}


def per_customer_scores(ctx, date, served, unserved_seq, disruption, sa_config, risk_weighted=False):
    depot_start_min = ctx.depot_start_min
    risk_weights = sa_config['risk_weights']  # {"L85": .., "L95": ..}

    def sim_scores(quantile, extra_delay):
        t, prev = depot_start_min, "DEPOT_1"
        for node in served:
            t += ctx.travel_time(date, prev, node, 'p50')
            cust = ctx.customers[(date, node)]
            if t < cust['tw_start']:
                t = cust['tw_start']
            t += cust['service_min']; prev = node
        t += extra_delay
        out = []
        for node in unserved_seq:
            t += ctx.travel_time(date, prev, node, quantile)
            cust = ctx.customers[(date, node)]
            if t < cust['tw_start']:
                t = cust['tw_start']
            out.append(max(0.0, t - cust['tw_end']))
            t += cust['service_min']; prev = node
        return out
    is_delay = disruption.startswith('delay')
    q = 'p50' if is_delay else disruption
    delay_amount = {'delay20': 20.0, 'delay30': 30.0}.get(disruption, 0.0)
    if not risk_weighted:
        return sim_scores(q, delay_amount)
    l85 = sim_scores('p85', 0.0); l95 = sim_scores('p95', 0.0)
    return [risk_weights['L85'] * a + risk_weights['L95'] * b for a, b in zip(l85, l95)]


def generate_candidates(unserved_seq, scores, op_weights, rng, n_candidates, targeted_fraction):
    m = len(unserved_seq)
    if m < 2:
        return []
    ranked = sorted(range(m), key=lambda k: scores[k], reverse=True)
    top = ranked[:max(1, m // 3)]
    names = OP_NAMES
    weights = [op_weights[n] for n in names]
    n_targeted = int(n_candidates * targeted_fraction)
    n_random = n_candidates - n_targeted
    out = []
    for _ in range(n_targeted):
        op_name = rng.choices(names, weights=weights, k=1)[0]
        i = rng.choice(top); j = rng.randrange(m)
        while j == i and m > 1:
            j = rng.randrange(m)
        out.append((OP_FUNCS[op_name](unserved_seq, rng, i, j), op_name))
    for _ in range(n_random):
        op_name = rng.choices(names, weights=weights, k=1)[0]
        out.append((OP_FUNCS[op_name](unserved_seq, rng), op_name))
    return out


def distance_priority_construction(ctx, date, served_last_node, unserved_seq):
    remaining = unserved_seq.copy(); route = []; current = served_last_node
    while remaining:
        nxt = min(remaining, key=lambda n: ctx.distance(date, current, n))
        route.append(nxt); remaining.remove(nxt); current = nxt
    return route


def risk_priority_construction(ctx, date, unserved_seq):
    return sorted(unserved_seq, key=lambda n: ctx.customers[(date, n)]['tw_end'])


def corrective_search_one_vehicle(ctx, date, full_seq, frozen_flags, disruption, method, sa_config, seed):
    """
    method in {'FR','RG','SA'}. NR requires no search (use
    simulate_mixed_route directly on the unmodified route).

    `sa_config` must be the dict loaded from configs/sa_config.json (or an
    equivalent dict with the same keys) -- every parameter this function
    uses comes from it: T0, cooling, lambda_s, max_iter, no_improve_limit,
    n_candidates_per_iteration, candidate_split, adaptive_weight_*,
    risk_weights. There is no fallback default for any of these; a
    missing key raises KeyError rather than silently using a stale value.
    """
    T0 = sa_config['T0']
    cooling = sa_config['cooling']
    lambda_s = sa_config['lambda_s']
    max_iter = sa_config['max_iter']
    no_improve_limit = sa_config['no_improve_limit']
    n_candidates = sa_config['n_candidates_per_iteration']
    targeted_fraction = sa_config['candidate_split']['targeted']
    success_mult = sa_config['adaptive_weight_success_multiplier']
    failure_mult = sa_config['adaptive_weight_failure_multiplier']
    weight_cap = sa_config['adaptive_weight_cap']
    weight_floor = sa_config['adaptive_weight_floor']
    coefficients = sa_config['objective_coefficients']
    risk_weights = sa_config['risk_weights']

    rng = random.Random(seed)
    served = [n for n, f in zip(full_seq, frozen_flags) if f]
    unserved = [n for n, f in zip(full_seq, frozen_flags) if not f]
    op_weights = {n: 1.0 for n in OP_NAMES}
    use_risk = method in ('RG', 'SA')
    use_stab = method == 'SA'

    def evaluate(u_seq):
        cand_full = served + u_seq
        cand_frozen = [True] * len(served) + [False] * len(u_seq)
        m = simulate_mixed_route(ctx, date, cand_full, cand_frozen, disruption)
        L85 = L95 = RSI = None
        if use_risk:
            m85 = simulate_mixed_route(ctx, date, cand_full, cand_frozen, 'p85')
            m95 = simulate_mixed_route(ctx, date, cand_full, cand_frozen, 'p95')
            L85, L95 = m85['lateness'], m95['lateness']
        stab = route_stability(unserved, u_seq)
        if use_stab:
            RSI = stab['RSI']
        Z = objective_Z(m, L85, L95, RSI, use_risk=use_risk, use_stability=use_stab,
                         lambda_s=lambda_s, coefficients=coefficients, risk_weights=risk_weights)
        return Z, m, stab

    if len(unserved) < 2:
        m = simulate_mixed_route(ctx, date, full_seq, [True] * len(full_seq), disruption)
        return {'seq': unserved, 'metrics': m, 'changed': False, 'RSI': 1.0, 'iterations_run': 0}

    unchanged_Z, unchanged_m, unchanged_stab = evaluate(unserved)
    if method == 'FR':
        dp_seq = distance_priority_construction(ctx, date, served[-1] if served else "DEPOT_1", unserved)
        dp_Z, dp_m, dp_stab = evaluate(dp_seq)
        current_seq, current_Z, current_m, current_stab = (dp_seq, dp_Z, dp_m, dp_stab) if dp_Z < unchanged_Z else (unserved, unchanged_Z, unchanged_m, unchanged_stab)
    elif method in ('RG', 'SA'):
        rp_seq = risk_priority_construction(ctx, date, unserved)
        rp_Z, rp_m, rp_stab = evaluate(rp_seq)
        current_seq, current_Z, current_m, current_stab = (rp_seq, rp_Z, rp_m, rp_stab) if rp_Z < unchanged_Z else (unserved, unchanged_Z, unchanged_m, unchanged_stab)
    else:
        current_seq, current_Z, current_m, current_stab = unserved, unchanged_Z, unchanged_m, unchanged_stab

    best_seq, best_Z, best_m, best_stab = current_seq, current_Z, current_m, current_stab
    T = T0; no_improve = 0; it = 0
    for it in range(max_iter):
        scores = per_customer_scores(ctx, date, served, current_seq, disruption, sa_config, risk_weighted=use_risk)
        batch = generate_candidates(current_seq, scores, op_weights, rng, n_candidates, targeted_fraction)
        if not batch:
            break
        scored_batch = []
        for cand, op_name in batch:
            cZ, cm, cstab = evaluate(cand)
            scored_batch.append((cZ, cand, op_name, cm, cstab))
        scored_batch.sort(key=lambda x: x[0])
        cand_Z, cand, op_name, cand_m, cand_stab = scored_batch[0]
        delta = cand_Z - current_Z
        accepted = delta <= 0 or rng.random() < math.exp(-delta / max(T, 1e-9))
        if accepted:
            current_seq, current_Z, current_m, current_stab = cand, cand_Z, cand_m, cand_stab
            if cand_Z < best_Z - 1e-9:
                best_seq, best_Z, best_m, best_stab = cand, cand_Z, cand_m, cand_stab
                no_improve = 0
                op_weights[op_name] = min(op_weights[op_name] * success_mult, weight_cap)
            else:
                no_improve += 1
        else:
            no_improve += 1
            op_weights[op_name] = max(op_weights[op_name] * failure_mult, weight_floor)
        T *= cooling
        if no_improve >= no_improve_limit:
            break

    changed = (best_seq != unserved)
    return {'seq': best_seq, 'metrics': best_m, 'changed': changed, 'RSI': best_stab['RSI'], 'iterations_run': it + 1}
