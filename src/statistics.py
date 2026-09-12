"""
src/statistics.py — daily-instance statistical inference.

Daily-instance level (date as the independent unit) is the PRIMARY
inferential analysis throughout this project; block-level statistics are
retained only as scenario-level descriptive evidence (see manuscript
Section 6.6 for the full rationale on why block-level pseudo-replication
inflates significance).
"""
from scipy.stats import friedmanchisquare, wilcoxon
from src.metrics import rank_biserial_signed, holm_correction, date_cluster_bootstrap_ci


def friedman_omnibus(daily_df, method_columns):
    """daily_df: one row per date, one column per method."""
    stat, p = friedmanchisquare(*[daily_df[m] for m in method_columns])
    n = len(daily_df)
    k = len(method_columns)
    kendalls_w = stat / (n * (k - 1))
    return dict(chi2=stat, p=p, n=n, k=k, kendalls_w=kendalls_w)


def paired_wilcoxon_report(daily_df, comparisons):
    """
    comparisons: list of (a, b) column-name tuples.
    Returns a list of dicts with mean/median diff, Wilcoxon stat/p, signed
    rank-biserial r, and n_nonzero, PLUS the Holm-corrected p-values across
    the whole comparison set (family-wise correction).
    """
    raw_p = []
    rows = []
    for a, b in comparisons:
        res = wilcoxon(daily_df[a], daily_df[b])
        r, nz = rank_biserial_signed(daily_df[a], daily_df[b])
        diff = daily_df[a] - daily_df[b]
        raw_p.append(res.pvalue)
        rows.append(dict(a=a, b=b, mean_diff=diff.mean(), median_diff=diff.median(),
                          n_nonzero=nz, wilcoxon_stat=res.statistic, p_raw=res.pvalue, r_signed=r))
    holm_p = holm_correction(raw_p)
    for row, hp in zip(rows, holm_p):
        row['p_holm'] = hp
    return rows


def bootstrap_all(daily_df, comparisons, n_boot=10000, seed=42):
    out = []
    for a, b in comparisons:
        lo, hi, _ = date_cluster_bootstrap_ci(daily_df[a], daily_df[b], n_boot=n_boot, seed=seed)
        out.append(dict(a=a, b=b, ci_lo=lo, ci_hi=hi, crosses_zero=(lo < 0 < hi)))
    return out
