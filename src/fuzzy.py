"""
src/fuzzy.py — fuzzy decision-activation / intervention-restraint gate.

IMPORTANT ROLE CLARIFICATION: this gate does NOT generate new routes. It
selects between the NR (unchanged) continuation and the already-computed
SA corrective continuation, using severity (NR lateness) and flexibility
(trigger fraction) as inputs. Frame its contribution as decision-
activation / intervention restraint, never as a routing optimizer.

Severity breakpoints and threshold tau are CALIBRATION-ONLY (12 dates);
never derived from or retuned against the 51 held-out dates. See
configs/fuzzy_config.json for the frozen parameter values.
"""
import numpy as np


def trapmf(x, a, b, c, d):
    x = np.asarray(x, dtype=float)
    y = np.zeros_like(x)
    y = np.where((x >= a) & (x < b), (x - a) / (b - a + 1e-12), y)
    y = np.where((x >= b) & (x <= c), 1.0, y)
    y = np.where((x > c) & (x <= d), (d - x) / (d - c + 1e-12), y)
    return y


def trimf(x, a, b, c):
    return trapmf(x, a, b, b, c)


class FuzzyGate:
    def __init__(self, p33, p67, tau):
        self.p33 = p33
        self.p67 = p67
        self.tau = tau
        self.out_x = np.linspace(0, 1, 201)
        self.out_lo = trimf(self.out_x, 0.0, 0.0, 0.5)
        self.out_med = trimf(self.out_x, 0.0, 0.5, 1.0)
        self.out_hi = trimf(self.out_x, 0.5, 1.0, 1.0)
        self.rules = [
            ('lo', 'lo', 'lo'), ('lo', 'med', 'lo'), ('lo', 'hi', 'lo'),
            ('med', 'lo', 'lo'), ('med', 'med', 'med'), ('med', 'hi', 'med'),
            ('hi', 'lo', 'med'), ('hi', 'med', 'hi'), ('hi', 'hi', 'hi'),
        ]

    def severity_mfs(self, x):
        lo = trapmf(x, -1, -1, self.p33 * 0.5, self.p33)
        med = trimf(x, self.p33 * 0.5, (self.p33 + self.p67) / 2, self.p67 * 1.5)
        hi = trapmf(x, self.p67, self.p67 * 1.5, 1e9, 1e9)
        return lo, med, hi

    def flexibility_mfs(self, x):
        # 0.25=early/high flexibility, 0.50=medium, 0.75=late/low flexibility
        hi = trimf(x, 0.0, 0.25, 0.50)
        med = trimf(x, 0.25, 0.50, 0.75)
        lo = trimf(x, 0.50, 0.75, 1.00)
        return lo, med, hi

    def infer_activation(self, sev_lo, sev_med, sev_hi, flex_lo, flex_med, flex_hi):
        sev = {'lo': sev_lo, 'med': sev_med, 'hi': sev_hi}
        flex = {'lo': flex_lo, 'med': flex_med, 'hi': flex_hi}
        out_map = {'lo': self.out_lo, 'med': self.out_med, 'hi': self.out_hi}
        agg = np.zeros_like(self.out_x)
        for s_term, f_term, out_term in self.rules:
            strength = min(sev[s_term], flex[f_term])
            if strength <= 0:
                continue
            agg = np.maximum(agg, np.minimum(out_map[out_term], strength))
        if agg.sum() == 0:
            return 0.0
        return float(np.sum(self.out_x * agg) / np.sum(agg))

    def fuzzy_score(self, nr_lateness, trigger_fraction):
        sl, sm, sh = self.severity_mfs([nr_lateness])
        fl, fm, fh = self.flexibility_mfs([trigger_fraction])
        return self.infer_activation(sl[0], sm[0], sh[0], fl[0], fm[0], fh[0])

    def activate(self, nr_lateness, trigger_fraction):
        return self.fuzzy_score(nr_lateness, trigger_fraction) >= self.tau
