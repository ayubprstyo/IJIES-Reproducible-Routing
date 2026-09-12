"""
src/simulator.py — execution-stage route simulation (Section 4.1-4.2).

Every lookup here is a HARD FAILURE on a miss. There is no silent fallback
to demand=0, service=0, distance=0, or lateness=0 anywhere in this module
-- this is the direct fix for the split-stop naming bug (see src/data.py
docstring). Matrix lookups for a split-piece node resolve to its PARENT
PHYSICAL NODE (same GPS location -- correct, not a fallback), since the
distance/travel-time matrices were built pre-split and have no entry for
split-specific IDs.

There are NO module-level parameter constants in this file. Depot start
time, operating-window end, and objective coefficients are all supplied
explicitly (via `SimulationContext` / `objective_Z` arguments), sourced
from `configs/sa_config.json` -- that file is the single source of truth.
"""


class SimulationContext:
    """Bundles the matrices, canonical mapping, quantile multipliers, and
    timing parameters needed to simulate routes for one dataset.
    Constructed once per notebook/run and passed to simulate_mixed_route().

    `depot_start_min` and `operating_window_end_min` must be supplied
    explicitly (e.g. from configs/sa_config.json's `depot_start_min` /
    `operating_window_end_min` fields) -- there is no built-in default.
    """

    def __init__(self, dist_matrix, p50_matrix, customers, parent_of, p85_mult, p95_mult,
                 depot_start_min, operating_window_end_min):
        self.dist_matrix = dist_matrix
        self.p50_matrix = p50_matrix
        self.customers = customers
        self.parent_of = parent_of
        self.p85_mult = p85_mult
        self.p95_mult = p95_mult
        self.depot_start_min = depot_start_min
        self.operating_window_end_min = operating_window_end_min

    def _resolve(self, date, node):
        if node == "DEPOT_1":
            return node
        parent = self.parent_of.get((date, node))
        if parent is None:
            raise KeyError(f"HARD FAIL: node '{node}' on {date} not in canonical mapping.")
        return parent

    def travel_time(self, date, i, j, quantile):
        ri, rj = self._resolve(date, i), self._resolve(date, j)
        if ri == rj:
            base = 0.0  # same physical location (e.g. split-piece siblings) -- correct, not a fallback
        else:
            base = self.p50_matrix[date].get((ri, rj))
            if base is None:
                base = self.p50_matrix[date].get((rj, ri))
            if base is None:
                raise KeyError(f"HARD FAIL: no p50 matrix entry for ({ri},{rj}) on {date}.")
        if quantile == 'p50':
            return base
        elif quantile == 'p85':
            return base * self.p85_mult
        elif quantile == 'p95':
            return base * self.p95_mult
        raise ValueError(quantile)

    def distance(self, date, i, j):
        ri, rj = self._resolve(date, i), self._resolve(date, j)
        if ri == rj:
            return 0.0
        d = self.dist_matrix[date].get((ri, rj))
        if d is None:
            d = self.dist_matrix[date].get((rj, ri))
        if d is None:
            raise KeyError(f"HARD FAIL: no distance entry for ({ri},{rj}) on {date}.")
        return d


def simulate_mixed_route(ctx, date, node_seq, frozen_flags, disruption, start_time=None):
    """
    Section 4.2: the executed prefix (frozen_flags[k]=True) is evaluated at
    p50 (as actually realized); the remaining continuation is exposed to
    the active disruption -- p85/p95 (quantile swap) or delay20/delay30
    (p50 matrix + a one-time added delay at the frozen->unfrozen boundary).

    `start_time` defaults to `ctx.depot_start_min` (itself sourced from
    config) if not overridden.
    """
    if start_time is None:
        start_time = ctx.depot_start_min
    is_delay = disruption.startswith('delay')
    remainder_q = 'p50' if is_delay else disruption
    delay_amount = {'delay20': 20.0, 'delay30': 30.0}.get(disruption, 0.0)

    t, prev, prev_frozen = start_time, "DEPOT_1", True
    total_distance = total_travel = total_lateness = 0.0
    for node, frozen in zip(node_seq, frozen_flags):
        q = 'p50' if frozen else remainder_q
        tt = ctx.travel_time(date, prev, node, q)
        dd = ctx.distance(date, prev, node)
        total_distance += dd
        total_travel += tt
        t += tt
        if prev_frozen and not frozen:
            t += delay_amount
        cust = ctx.customers.get((date, node))
        if cust is None:
            raise KeyError(f"HARD FAIL: customer attributes for '{node}' on {date} not found.")
        if t < cust['tw_start']:
            t = cust['tw_start']
        total_lateness += max(0.0, t - cust['tw_end'])
        t += cust['service_min']
        prev, prev_frozen = node, frozen

    q_back = 'p50' if prev_frozen else remainder_q
    total_distance += ctx.distance(date, prev, "DEPOT_1")
    tt_back = ctx.travel_time(date, prev, "DEPOT_1", q_back)
    total_travel += tt_back
    t += tt_back
    overtime = max(0.0, t - ctx.operating_window_end_min)
    return {'lateness': total_lateness, 'distance': total_distance, 'travel_time': total_travel,
            'overtime': overtime, 'completion_time': t}


def route_stability(old_seq, new_seq):
    """Eq. 4a-4c: positional shift (PS), edge retention (ER), route
    stability index (RSI). The 0.5/0.5 weighting between PS and ER is part
    of the RSI definition itself, not a tunable research parameter, so it
    is not sourced from config."""
    m = len(old_seq)
    if m <= 1:
        return {'PS': 0.0, 'ER': 1.0, 'RSI': 1.0}
    pos_old = {node: i for i, node in enumerate(old_seq)}
    ps_sum = sum(abs(new_seq.index(node) - pos_old[node]) for node in old_seq)
    PS = ps_sum / (m * (m - 1))
    old_edges = set(zip(old_seq[:-1], old_seq[1:]))
    new_edges = set(zip(new_seq[:-1], new_seq[1:]))
    ER = len(old_edges & new_edges) / max(len(old_edges), 1)
    return {'PS': PS, 'ER': ER, 'RSI': 0.5 * (1 - PS) + 0.5 * ER}


def objective_Z(m, L85=None, L95=None, RSI=None, use_risk=False, use_stability=False,
                lambda_s=0.0, coefficients=None, risk_weights=None):
    """
    Eq. 5: Z = D + c_T*T + c_L*L + c_O*O + I_R*c_risk*(w85*L85+w95*L95) + I_S*lambda_s*(1-RSI)

    `coefficients` must be a dict with keys 'travel_time', 'lateness',
    'overtime', 'risk_term' (configs/sa_config.json's
    `objective_coefficients`). `risk_weights` must be a dict with keys
    'L85','L95' (configs/sa_config.json's `risk_weights`), required only
    if `use_risk` is True. There is no hardcoded default for either dict;
    a missing value raises rather than silently using a stale constant.
    """
    if coefficients is None:
        raise ValueError("objective_Z requires an explicit `coefficients` dict (see configs/sa_config.json).")
    Z = m['distance'] + coefficients['travel_time'] * m['travel_time'] + \
        coefficients['lateness'] * m['lateness'] + coefficients['overtime'] * m['overtime']
    if use_risk:
        if risk_weights is None:
            raise ValueError("objective_Z requires `risk_weights` when use_risk=True (see configs/sa_config.json).")
        Z += coefficients['risk_term'] * (risk_weights['L85'] * L85 + risk_weights['L95'] * L95)
    if use_stability:
        Z += lambda_s * (1.0 - RSI)
    return Z
