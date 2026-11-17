"""State-space nowcast: a dynamic factor model with GDP inside it, run through the Kalman filter.

Monthly indicators and quarterly GDP are treated as noisy readings of a few unobserved monthly factors:

    factor        f_t = phi * f_(t-1) + u_t                                (one AR(1) per factor)
    indicator     x_it = lambda_i' f_t + e_it                              (every month the indicator is published)
    GDP, y/y      y_q = mu + beta' (f_t + f_(t-1) + f_(t-2)) / 3 + g_t + eta  (third month of each released quarter)
    GDP's own     g_t = rho * g_(t-1) + w_t                                (what the indicators miss, persistent)

The filter reads whatever has been published by the nowcast date, month by month, skipping what is missing, so the
latest months (the ragged edge) and unreleased quarters are handled in one pass. The nowcast is the expected GDP
reading for the target quarter, and its variance comes from the filter (factor uncertainty plus GDP noise). The
persistent GDP term g carries the last releases forward, so the model nests the "last release" benchmark and moves
away from it only as far as the indicators justify.

Factors: a common factor that every indicator loads on, and, when news series are included, a news factor that only
they load on (block structure as in the New York Fed model). So news can sharpen the common factor where hard data
are not out yet, and can also carry information about GDP that shipping and markets miss.

Estimation is the two-step method of Doz, Giannone and Reichlin (2011): principal components and least squares give
the parameters, then the Kalman smoother gives the factors. It needs no iterative optimisation, so a nowcast takes
milliseconds and the backtest refits the model at every date.

GDP's weights on the factors are kept at zero or above (see `_signed_ridge`): an economic sign restriction, not a
fitted one.

Indicators are standardised on the data available at the nowcast date and passed through a soft cap at three
standard deviations (3 * tanh(z / 3)), so one extreme reading (shipping in a closure, a pandemic month) moves the
factor a lot but not without limit.

Because the smoother is linear in the data once the pattern of missing values is fixed, the nowcast splits exactly
into contributions: one per indicator, one for past GDP releases, and the average growth rate. A revision between
two dates splits the same way, plus a term for re-estimating the parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import data

HARD = ["hormuz", "ports", "imports", "exports", "uae_equity", "emaar", "enbd"]  # same real-activity set as `factor`
NEWS = {
    "kalman": {"non_oil": [], "real": []},
    "kalman_tone": {"non_oil": ["news_uae_tone"], "real": ["news_uae_tone", "news_hormuz_vol"]},
    "kalman_ai": {"non_oil": ["ai_nonoil"], "real": ["ai_nonoil", "ai_oil"]},
}
VARIANTS = {"kalman": "Kalman: hard data", "kalman_tone": "Kalman + news tone", "kalman_ai": "Kalman + AI news"}
# Inputs an analyst can switch on or off (the page's input panel). Market series are offered but off by default:
# with rates, the dollar and the VIX in the common factor it tracks the global financial cycle, not UAE activity.
OPTIONS = {
    "Shipping and trade": ["hormuz", "ports", "imports", "exports"],
    "UAE markets": ["uae_equity", "emaar", "enbd"],
    "Global markets": ["brent", "vix", "ust10", "dollar"],
    "Global economy": ["us_indpro", "wti", "copper", "eu_gas", "policy_unc"],
    "News": ["ai_nonoil", "ai_oil", "news_uae_tone", "news_hormuz_vol"],
}
NEWS_INPUTS = set(OPTIONS["News"])
START = pd.Period("2020-01", "M")
CAP = 3.0
Z70, Z90 = 1.036, 1.645


def _soft(z: pd.DataFrame) -> pd.DataFrame:
    return CAP * np.tanh(z / CAP)


@dataclass
class Model:
    names: list[str]          # indicator columns, in order
    blocks: list[list[int]]   # factor -> indicator positions that load on it (factor 0 = common)
    index: pd.PeriodIndex     # months
    X: np.ndarray             # standardised indicators (T x N), NaN where unpublished
    G: np.ndarray             # GDP reading at the third month of released quarters (T), NaN elsewhere
    lam: np.ndarray           # N x k loadings
    r: np.ndarray             # N indicator noise variances
    phi: np.ndarray           # k
    q: np.ndarray             # k
    mu: float
    beta: np.ndarray          # k
    r_y: float                # GDP reading noise
    rho: float                # monthly persistence of GDP's own component
    s_g: float                # variance of GDP's own component
    mean: pd.Series
    std: pd.Series


def _pc1(x: np.ndarray) -> np.ndarray:
    """First principal component of a matrix with NaNs (filled with zero, the mean), scaled to unit variance."""
    f = np.nan_to_num(x)
    if f.shape[1] == 1:
        pc = f[:, 0]
    else:
        u, s, _ = np.linalg.svd(f - f.mean(0), full_matrices=False)
        pc = u[:, 0] * s[0]
    sd = pc.std()
    return pc / sd if sd > 0 else pc


def _ols_masked(x: np.ndarray, F: np.ndarray) -> np.ndarray:
    m = ~np.isnan(x)
    if m.sum() < 6:
        return np.zeros(F.shape[1])
    return np.linalg.lstsq(F[m], x[m], rcond=None)[0]


def _ar1(f: np.ndarray) -> tuple[float, float]:
    a, b = f[:-1], f[1:]
    phi = float(np.clip((a @ b) / (a @ a), 0.0, 0.97)) if (a @ a) > 0 else 0.5
    return phi, max(float(np.var(b - phi * a)), 0.02)


# ---- state space --------------------------------------------------------------------------------------------------
# state: [f_0, f_0(-1), f_0(-2), f_1, f_1(-1), f_1(-2), ...]

def _system(m: Model, with_gdp: bool):
    k = len(m.phi)
    n = 3 * k + 1
    T = np.zeros((n, n))
    Q = np.zeros((n, n))
    for j in range(k):
        T[3 * j, 3 * j] = m.phi[j]
        T[3 * j + 1, 3 * j] = 1.0
        T[3 * j + 2, 3 * j + 1] = 1.0
        Q[3 * j, 3 * j] = m.q[j]
    T[-1, -1], Q[-1, -1] = m.rho, m.s_g * (1 - m.rho ** 2)
    N = len(m.names)
    Z = np.zeros((N + 1, n))
    for i in range(N):
        for j in range(k):
            Z[i, 3 * j] = m.lam[i, j]
    for j in range(k):
        Z[N, 3 * j:3 * j + 3] = m.beta[j] / 3
    Z[N, -1] = 1.0
    R = np.append(m.r, m.r_y)
    Y = np.column_stack([m.X, (m.G - m.mu) if with_gdp else np.full(len(m.G), np.nan)])
    P0 = np.zeros((n, n))
    for j in range(k):
        v = m.q[j] / max(1 - m.phi[j] ** 2, 0.05)
        P0[3 * j:3 * j + 3, 3 * j:3 * j + 3] = v * np.eye(3)
    P0[-1, -1] = m.s_g
    return T, Q, Z, R, Y, P0


def _smooth(T, Q, Z, R, Y, mask, P0):
    """Kalman filter and Rauch-Tung-Striebel smoother with missing observations. Starts from a zero mean, so the
    smoothed state is linear in Y for a fixed `mask`."""
    nT, n = Y.shape[0], T.shape[0]
    a_p, P_p = np.zeros((nT, n)), np.zeros((nT, n, n))
    a_f, P_f = np.zeros((nT, n)), np.zeros((nT, n, n))
    a, P = np.zeros(n), P0
    for t in range(nT):
        if t:
            a, P = T @ a, T @ P @ T.T + Q
        a_p[t], P_p[t] = a, P
        o = mask[t]
        if o.any():
            Zo = Z[o]
            F = Zo @ P @ Zo.T + np.diag(R[o])
            K = np.linalg.solve(F, Zo @ P).T
            a = a + K @ (Y[t, o] - Zo @ a)
            P = P - K @ Zo @ P
        a_f[t], P_f[t] = a, P
    a_s, P_s = a_f.copy(), P_f.copy()
    for t in range(nT - 2, -1, -1):
        J = P_f[t] @ T.T @ np.linalg.pinv(P_p[t + 1])
        a_s[t] = a_f[t] + J @ (a_s[t + 1] - a_p[t + 1])
        P_s[t] = P_f[t] + J @ (P_s[t + 1] - P_p[t + 1]) @ J.T
    return a_s, P_s


def _agg(k: int, beta: np.ndarray, gdp_own: bool = True) -> np.ndarray:
    c = np.zeros(3 * k + 1)
    for j in range(k):
        c[3 * j:3 * j + 3] = beta[j] / 3
    c[-1] = 1.0 if gdp_own else 0.0
    return c


# ---- fitting ------------------------------------------------------------------------------------------------------

def _frame(target: str, quarter: pd.Period, as_of: pd.Timestamp, names: list[str], pm: pd.DataFrame | None):
    pm = data.panel(as_of) if pm is None else pm
    names = [c for c in names if c in pm.columns and pm[c].notna().sum() >= 12]
    end = max(pm.index.max(), quarter.asfreq("M", "end")) if len(pm) else quarter.asfreq("M", "end")
    idx = pd.period_range(START, end, freq="M")
    x = pm.reindex(idx)[names]
    known = x.loc[: as_of.to_period("M")]  # standardise on data up to the nowcast date (a scenario's path is not data)
    mean, std = known.mean(), known.std().replace(0, 1).fillna(1)
    z = _soft((x - mean) / std)
    y = data.target(target, as_of, training=True)
    y = y[(y.index < quarter) & (y.index >= START.asfreq("Q"))]
    G = pd.Series(np.nan, index=idx)
    for qq, v in y.items():
        m3 = qq.asfreq("M", "end")
        if m3 in G.index:
            G[m3] = v
    return names, idx, z, G.values, mean, std, y


def fit(target: str, quarter: pd.Period, as_of: pd.Timestamp, variant: str = "kalman",
        pm: pd.DataFrame | None = None, ridge: float = 1.0, inputs: list[str] | None = None) -> Model | None:
    """`inputs`, when given, replaces the variant's inputs: news series get their own factor, the rest the common one."""
    if inputs is not None:
        hard = [c for c in inputs if c not in NEWS_INPUTS]
        news = [c for c in inputs if c in NEWS_INPUTS]
    else:
        hard = [c for c in HARD]
        news = NEWS[variant][target]
    names, idx, z, G, mean, std, y = _frame(target, quarter, as_of, hard + news, pm)
    hard_i = [i for i, c in enumerate(names) if c in hard]
    news_i = [i for i, c in enumerate(names) if c in news]
    if len(hard_i) < (2 if inputs is not None else 3) or len(y) < 4 or (news and not news_i):  # a news version needs its news series
        return None
    X = z.values
    obs = ~np.isnan(X).all(1)
    last = int(np.where(obs)[0].max()) + 1  # estimation sample: months with any data
    Xe = X[:last]
    # common factor from every indicator; a news factor from what the common factor leaves in the news series
    blocks = [hard_i + news_i] + ([news_i] if news_i else [])
    f0 = _pc1(Xe[:, blocks[0]])
    if "ports" in names and np.nansum(np.nan_to_num(Xe[:, names.index("ports")]) * f0) < 0:
        f0 = -f0
    F = [f0]
    lam = np.zeros((len(names), len(blocks)))
    for i in range(len(names)):
        lam[i, 0] = _ols_masked(Xe[:, i], f0[:, None])[0]
    if news_i:
        resid = Xe[:, news_i] - np.outer(f0, lam[news_i, 0])
        f1 = _pc1(resid)
        for i in news_i:
            col = Xe[:, i] - f0 * lam[i, 0]
            lam[i, 1] = _ols_masked(col, f1[:, None])[0]
        if lam[news_i[0], 1] < 0:  # sign: the news factor rises with the first news series (better news)
            f1, lam[news_i, 1] = -f1, -lam[news_i, 1]
        F.append(f1)
    Fm = np.column_stack(F)
    r = np.array([max(float(np.nanmean((Xe[:, i] - Fm @ lam[i]) ** 2)), 0.1) for i in range(len(names))])
    ar = [_ar1(f) for f in F]
    m = Model(names, blocks, idx, X, G, lam, r, np.array([a for a, _ in ar]), np.array([b for _, b in ar]),
              0.0, np.zeros(len(F)), 1.0, 0.0, 0.0, mean, std)
    # GDP loadings: ridge regression of released GDP on the smoothed factors' quarterly averages (step two)
    T, Q, Z, R, Y, P0 = _system(m, with_gdp=False)
    a_s, _ = _smooth(T, Q, Z, R, Y, ~np.isnan(Y), P0)
    k = len(F)
    rows = [i for i, g in enumerate(G) if not np.isnan(g)]
    A = np.column_stack([a_s[rows, 3 * j:3 * j + 3].mean(1) for j in range(k)])
    yy = G[rows]
    Am, ym = A.mean(0), yy.mean()
    beta = _signed_ridge(A - Am, yy - ym, ridge)
    m.beta, m.mu = beta, float(ym - Am @ beta)
    e = yy - m.mu - A @ beta
    var_e = max(float((e ** 2).sum() / max(len(yy) - k - 1, 1)), 0.25)
    pairs = [(e[i - 1], e[i]) for i in range(1, len(rows)) if rows[i] - rows[i - 1] == 3]
    num, den = sum(a * b for a, b in pairs), sum(a * a for a, _ in pairs)
    rho_q = float(np.clip(num / den, 0.0, 0.9)) if len(pairs) >= 3 and den > 0 else 0.5
    m.rho, m.s_g, m.r_y = rho_q ** (1 / 3), 0.75 * var_e, max(0.25 * var_e, 0.1)
    return m


def _signed_ridge(A: np.ndarray, y: np.ndarray, ridge: float) -> np.ndarray:
    """Ridge with every coefficient kept at zero or above. The factors are signed so that they rise with activity
    (port calls) and with better news, so a negative weight on GDP would mean more trade lowers growth: with 13
    quarters that is noise, not economics (before 2026 the sample has no recession to pin the sign down)."""
    free = list(range(A.shape[1]))
    beta = np.zeros(A.shape[1])
    while free:
        Af = A[:, free]
        b = np.linalg.solve(Af.T @ Af + ridge * np.eye(len(free)), Af.T @ y)
        if (b >= 0).all():
            beta[free] = b
            break
        free.pop(int(np.argmin(b)))  # drop the most negative weight and refit the rest
    return beta


def _month(m: Model, quarter: pd.Period) -> int:
    return int(m.index.get_loc(quarter.asfreq("M", "end")))


def predict(m: Model, quarter: pd.Period) -> tuple[float, float]:
    """Nowcast and its standard deviation for `quarter`."""
    T, Q, Z, R, Y, P0 = _system(m, with_gdp=True)
    a_s, P_s = _smooth(T, Q, Z, R, Y, ~np.isnan(Y), P0)
    t, c = _month(m, quarter), _agg(len(m.phi), m.beta)
    return m.mu + float(c @ a_s[t]), float(np.sqrt(c @ P_s[t] @ c + m.r_y))


def contributions(m: Model, quarter: pd.Period) -> dict[str, float]:
    """Exact split of (nowcast - average growth) into one part per indicator and one for past GDP releases."""
    T, Q, Z, R, Y, P0 = _system(m, with_gdp=True)
    mask = ~np.isnan(Y)
    t, c = _month(m, quarter), _agg(len(m.phi), m.beta)
    out = {}
    for j, name in enumerate(m.names + ["gdp"]):
        Yj = np.where(mask, 0.0, np.nan)
        Yj[:, j] = np.where(mask[:, j], Y[:, j], np.nan)
        a_s, _ = _smooth(T, Q, Z, R, np.nan_to_num(Yj), mask, P0)
        out[name] = float(c @ a_s[t])
    return out


def with_data(m: Model, target: str, quarter: pd.Period, as_of: pd.Timestamp, pm: pd.DataFrame | None) -> Model:
    """The same parameters applied to the data published by another date (for revision decompositions)."""
    names, idx, z, G, *_ = _frame(target, quarter, as_of, m.names, pm)
    x = (pm if pm is not None else data.panel(as_of)).reindex(m.index)
    X = np.column_stack([_soft((x[c] - m.mean[c]) / m.std[c]).values if c in x else np.full(len(m.index), np.nan)
                         for c in m.names])
    g = pd.Series(G, index=idx).reindex(m.index).values
    return Model(**{**m.__dict__, "X": X, "G": g})


# ---- public ------------------------------------------------------------------------------------------------------

def nowcast(target: str, quarter: pd.Period, as_of: pd.Timestamp, variant: str = "kalman",
            pm: pd.DataFrame | None = None, detail: bool = False, inputs: list[str] | None = None) -> dict | None:
    m = fit(target, quarter, as_of, variant, pm, inputs=inputs)
    if m is None:
        return None
    v, sd = predict(m, quarter)
    out = {"value": v, "sd": sd, "band70": [v - Z70 * sd, v + Z70 * sd], "band90": [v - Z90 * sd, v + Z90 * sd],
           "detail": {"inputs": m.names, "mu": m.mu, "beta": [round(float(b), 3) for b in m.beta],
                      "factors": len(m.phi), "rho_quarterly": round(m.rho ** 3, 3)}}
    if detail:
        out["contrib"] = contributions(m, quarter)
    return out


def revision(target: str, quarter: pd.Period, a: pd.Timestamp, b: pd.Timestamp, variant: str,
             pm_a: pd.DataFrame | None = None, pm_b: pd.DataFrame | None = None) -> dict | None:
    """Why the nowcast moved from date `a` to date `b`: re-estimation, then each indicator's new data, exactly."""
    ma, mb = fit(target, quarter, a, variant, pm_a), fit(target, quarter, b, variant, pm_b)
    if ma is None or mb is None:
        return None
    va, _ = predict(ma, quarter)
    vb, _ = predict(mb, quarter)
    mab = with_data(mb, target, quarter, a, pm_a)  # old data, new parameters
    vab, _ = predict(mab, quarter)
    ca, cb = contributions(mab, quarter), contributions(mb, quarter)
    steps = [{"input": "reestimation", "change": vab - va}]
    steps += [{"input": k, "change": cb[k] - ca.get(k, 0.0)} for k in cb]
    return {"from": va, "to": vb, "steps": steps, "check": va + sum(s["change"] for s in steps) - vb}
