"""Dixon-Coles Negative Binomial model with dynamic ratings and covariates.

Replaces independent Poisson with overdispersed NB marginals and a Dixon-Coles
low-score correction. Team attack/defence ratings receive prediction-error updates
after each match (state-space / Elo-style step). Covariates (lineup OVR gap,
altitude, travel) enter the log-linear intensity:

    log(lambda_home) = mu + home_adv + att_h + def_a
                       + gamma * (lineup_h - lineup_a)
                       + beta_alt * altitude_m / 1000
                       + beta_travel * travel_km / 1000
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from scipy import optimize
from scipy.special import gammaln

ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_GOALS = 12
SINCE = "2018-01-01"

DEFAULTS: dict[str, float] = {
    "half_life": 1000.0,
    "friendly_w": 0.6,
    "shrink": 8.0,
    "rho": -0.10,
    "margin_cap": 99.0,
    "nb_dispersion": 8.0,
    "gamma": 0.02,
    "beta_altitude": -0.08,
    "beta_travel": -0.05,
    "beta_rest": -0.04,
    "rest_baseline_days": 7.0,
    "dynamic_alpha": 0.15,
    "dynamic_decay": 0.995,
}


@dataclass
class MatchRecord:
    """Single international match used for training or inference."""

    date: date
    home: str
    away: str
    hg: int
    ag: int
    neutral: bool
    weight: float
    city: str = ""
    country: str = ""
    lineup_home: float | None = None
    lineup_away: float | None = None
    altitude_m: float = 0.0
    travel_home_km: float = 0.0
    travel_away_km: float = 0.0
    rest_home_days: float = 7.0
    rest_away_days: float = 7.0
    fixture_id: int | None = None


@dataclass
class TrainedModel:
    """Fitted Dixon-Coles NB parameters and team ratings."""

    att: dict[str, float]
    dfn: dict[str, float]
    mu: float
    hadv: float
    rho: float
    nb_r: float
    gamma: float
    beta_altitude: float
    beta_travel: float
    beta_rest: float
    rest_baseline_days: float
    dynamic_alpha: float
    dynamic_decay: float
    teams: list[str] = field(default_factory=list)
    params: dict[str, float] = field(default_factory=dict)
    dynamic_state: dict[str, dict[str, float]] = field(default_factory=dict)

    def lineup_delta(self, lineup_home: float, lineup_away: float) -> float:
        return self.gamma * (lineup_home - lineup_away)

    def covariate_terms(
        self,
        lineup_home: float,
        lineup_away: float,
        altitude_m: float,
        travel_home_km: float,
        travel_away_km: float,
        rest_home_days: float = 7.0,
        rest_away_days: float = 7.0,
    ) -> tuple[float, float]:
        """Extra log-intensity for home and away from covariates."""
        lineup = self.lineup_delta(lineup_home, lineup_away)
        alt = self.beta_altitude * (altitude_m / 1000.0)
        # Fatigue: fewer rest days than baseline -> negative deficit -> lower intensity.
        rest_h = self.beta_rest * max(0.0, self.rest_baseline_days - rest_home_days)
        rest_a = self.beta_rest * max(0.0, self.rest_baseline_days - rest_away_days)
        return (
            lineup + alt - self.beta_travel * (travel_home_km / 1000.0) + rest_h,
            -lineup - self.beta_travel * (travel_away_km / 1000.0) + rest_a,
        )


def load_params(path: str | None = None) -> dict[str, float]:
    path = path or os.path.join(ROOT, "wc26_params.json")
    try:
        loaded = json.load(open(path, encoding="utf-8"))["params"]
        return {**DEFAULTS, **loaded}
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return dict(DEFAULTS)


def load_matches(
    cutoff: str,
    half_life: float,
    friendly_w: float,
    margin_cap: float = 99.0,
    csv_path: str | None = None,
    patches_path: str | None = None,
) -> list[MatchRecord]:
    """Load weighted international matches from CSV with optional score patches."""
    csv_path = csv_path or os.path.join(ROOT, "international_results.csv")
    patches_path = patches_path or os.path.join(ROOT, "wc26_data_patches.json")
    try:
        patches = json.load(open(patches_path, encoding="utf-8"))
    except FileNotFoundError:
        patches = {"score_fixes": [], "additions": []}
    fixes = {
        (f["date"], f["home_team"], f["away_team"]): (f["home_score"], f["away_score"])
        for f in patches.get("score_fixes", [])
    }
    cut = date.fromisoformat(cutoff)
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    seen = {(r["date"], r["home_team"], r["away_team"]) for r in rows}
    for a in patches.get("additions", []):
        key = (a["date"], a["home_team"], a["away_team"])
        if key not in seen:
            rows.append(
                {
                    "date": a["date"],
                    "home_team": a["home_team"],
                    "away_team": a["away_team"],
                    "home_score": str(a["home_score"]),
                    "away_score": str(a["away_score"]),
                    "tournament": a["tournament"],
                    "city": a.get("city", ""),
                    "country": a.get("country", ""),
                    "neutral": "TRUE" if a["neutral"] else "FALSE",
                }
            )
    out: list[MatchRecord] = []
    last_played: dict[str, date] = {}
    # Sort raw rows by date first so rest-day tracking is chronological even
    # for matches before the SINCE/cutoff window (used only to seed history).
    rows.sort(key=lambda r: r["date"])
    for r in rows:
        if r["home_score"] == "NA":
            continue
        d = date.fromisoformat(r["date"])
        home, away = r["home_team"], r["away_team"]
        rest_h = float((d - last_played[home]).days) if home in last_played else 7.0
        rest_a = float((d - last_played[away]).days) if away in last_played else 7.0
        last_played[home] = d
        last_played[away] = d
        if not (SINCE <= r["date"] < cutoff):
            continue
        w = 0.5 ** ((cut - d).days / half_life)
        if r.get("tournament") == "Friendly":
            w *= friendly_w
        key = (r["date"], r["home_team"], r["away_team"])
        if key in fixes:
            hg, ag = fixes[key]
        else:
            hg, ag = int(r["home_score"]), int(r["away_score"])
        if hg - ag > margin_cap:
            hg = ag + int(margin_cap)
        elif ag - hg > margin_cap:
            ag = hg + int(margin_cap)
        out.append(
            MatchRecord(
                date=d,
                home=r["home_team"],
                away=r["away_team"],
                hg=hg,
                ag=ag,
                neutral=r.get("neutral", "FALSE") == "TRUE",
                weight=w,
                city=r.get("city", ""),
                country=r.get("country", ""),
                rest_home_days=min(rest_h, 60.0),
                rest_away_days=min(rest_a, 60.0),
            )
        )
    out.sort(key=lambda m: m.date)
    return out


def nb_pmf(k: int, mu: float, r: float) -> float:
    """Negative binomial PMF (NB2: mean=mu, variance=mu+mu^2/r)."""
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    p = r / (r + mu)
    return math.exp(gammaln(k + r) - gammaln(r) - gammaln(k + 1) + r * math.log(p) + k * math.log(1 - p))


def nb_row(lmbda: float, r: float, max_goals: int = MAX_GOALS) -> list[float]:
    return [nb_pmf(k, lmbda, r) for k in range(max_goals + 1)]


def score_grid(l1: float, l2: float, rho: float, r: float, max_goals: int = MAX_GOALS) -> list[list[float]]:
    """Independent NB marginals with Dixon-Coles low-score adjustment."""
    ph, pa = nb_row(l1, r, max_goals), nb_row(l2, r, max_goals)
    grid = [[ph[i] * pa[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    grid[0][0] *= max(0.0, 1.0 - l1 * l2 * rho)
    grid[1][0] *= max(0.0, 1.0 + l2 * rho)
    grid[0][1] *= max(0.0, 1.0 + l1 * rho)
    grid[1][1] *= max(0.0, 1.0 - rho)
    total = sum(v for row in grid for v in row)
    return [[v / total for v in row] for row in grid]


def lambdas(
    model: TrainedModel,
    home: str,
    away: str,
    home_field: bool,
    lineup_home: float = 75.0,
    lineup_away: float = 75.0,
    altitude_m: float = 0.0,
    travel_home_km: float = 0.0,
    travel_away_km: float = 0.0,
    rest_home_days: float = 7.0,
    rest_away_days: float = 7.0,
    att_override: dict[str, float] | None = None,
    dfn_override: dict[str, float] | None = None,
) -> tuple[float, float]:
    hf = model.hadv if home_field else 0.0
    cov_h, cov_a = model.covariate_terms(
        lineup_home, lineup_away, altitude_m, travel_home_km, travel_away_km,
        rest_home_days, rest_away_days,
    )
    if att_override is not None and dfn_override is not None:
        att_h = att_override[home]
        dfn_h = dfn_override[home]
        att_a = att_override[away]
        dfn_a = dfn_override[away]
    else:
        # Apply dynamic state on top of base ratings
        ds_home = model.dynamic_state.get(home, {"att": 0.0, "dfn": 0.0})
        ds_away = model.dynamic_state.get(away, {"att": 0.0, "dfn": 0.0})
        att_h = model.att[home] + ds_home["att"]
        dfn_h = model.dfn[home] + ds_home["dfn"]
        att_a = model.att[away] + ds_away["att"]
        dfn_a = model.dfn[away] + ds_away["dfn"]
    l1 = math.exp(model.mu + hf + att_h + dfn_a + cov_h)
    l2 = math.exp(model.mu + att_a + dfn_h + cov_a)
    return l1, l2


def one_x_two(grid: list[list[float]]) -> tuple[float, float, float]:
    r = range(len(grid))
    p_h = sum(grid[i][j] for i in r for j in r if i > j)
    p_d = sum(grid[i][i] for i in r)
    return p_h, p_d, 1.0 - p_h - p_d


def sample_scores(
    l1: float,
    l2: float,
    rho: float,
    r: float,
    n: int,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample n scorelines from the Dixon-Coles NB grid via inverse CDF."""
    rng = rng or np.random.default_rng()
    grid = np.array(score_grid(l1, l2, rho, r), dtype=float)
    flat = grid.ravel()
    idx = rng.choice(flat.size, size=n, p=flat)
    goals = np.unravel_index(idx, grid.shape)
    return goals[0].astype(int), goals[1].astype(int)


def fit_iterative(
    matches: list[MatchRecord],
    shrink: float,
    nb_r: float = 8.0,
    iters: int = 80,
) -> tuple[dict[str, float], dict[str, float], float, float]:
    """Iteratively reweighted attack/defence fit (NB-aware via variance weights)."""
    teams = sorted({m.home for m in matches} | {m.away for m in matches})
    att = {t: 0.0 for t in teams}
    dfn = {t: 0.0 for t in teams}
    mu, hadv = math.log(1.25), 0.25

    for _ in range(iters):
        tot_g = sum(m.weight * (m.hg + m.ag) for m in matches)
        tot_e = 0.0
        for m in matches:
            hf = 0.0 if m.neutral else hadv
            lh = math.exp(mu + hf + att[m.home] + dfn[m.away])
            la = math.exp(mu + att[m.away] + dfn[m.home])
            tot_e += m.weight * (lh + la)
        mu += math.log(tot_g / max(tot_e, 1e-9))

        hg_sum = he_sum = 0.0
        for m in matches:
            if not m.neutral:
                hf = hadv
                lh = math.exp(mu + hf + att[m.home] + dfn[m.away])
                hg_sum += m.weight * m.hg
                he_sum += m.weight * lh
        if he_sum > 0:
            hadv += math.log(max(hg_sum / he_sum, 1e-9))

        num_a = {t: shrink * math.exp(mu) for t in teams}
        den_a = {t: shrink for t in teams}
        num_d = {t: shrink * math.exp(mu) for t in teams}
        den_d = {t: shrink for t in teams}
        for m in matches:
            hf = 0.0 if m.neutral else hadv
            # base rates WITHOUT the parameter being solved for (standard iterative WLS)
            base_h = math.exp(mu + hf + dfn[m.away])    # for att[home] update
            base_a = math.exp(mu + dfn[m.home])          # for att[away] update
            base_dh = math.exp(mu + att[m.away])         # for dfn[home] update
            base_da = math.exp(mu + hf + att[m.home])   # for dfn[away] update
            lh = base_h * math.exp(att[m.home])
            la = base_a * math.exp(att[m.away])
            w_nb_h = m.weight * (1.0 + lh / nb_r)
            w_nb_a = m.weight * (1.0 + la / nb_r)
            num_a[m.home] += w_nb_h * m.hg
            den_a[m.home] += w_nb_h * base_h
            num_a[m.away] += w_nb_a * m.ag
            den_a[m.away] += w_nb_a * base_a
            num_d[m.home] += w_nb_a * m.ag
            den_d[m.home] += w_nb_a * base_dh
            num_d[m.away] += w_nb_h * m.hg
            den_d[m.away] += w_nb_h * base_da
        for t in teams:
            att[t] = math.log(num_a[t] / max(den_a[t], 1e-9))
            dfn[t] = math.log(num_d[t] / max(den_d[t], 1e-9))
        ma, md = sum(att.values()) / len(teams), sum(dfn.values()) / len(teams)
        for t in teams:
            att[t] -= ma
            dfn[t] -= md
        mu += ma + md
    return att, dfn, mu, hadv


def apply_dynamic_updates(
    matches: list[MatchRecord],
    att: dict[str, float],
    dfn: dict[str, float],
    mu: float,
    hadv: float,
    alpha: float = 0.15,
    decay: float = 0.995,
    gamma: float = 0.0,
    beta_altitude: float = 0.0,
    beta_travel: float = 0.0,
    beta_rest: float = 0.0,
    rest_baseline_days: float = 7.0,
) -> dict[str, dict[str, float]]:
    """Prediction-error state updates after each match (chronological)."""
    dyn_att = {t: 0.0 for t in att}
    dyn_dfn = {t: 0.0 for t in dfn}
    for m in matches:
        for t in dyn_att:
            dyn_att[t] *= decay
            dyn_dfn[t] *= decay
        lh = m.lineup_home or 75.0
        la = m.lineup_away or 75.0
        rest_h = beta_rest * max(0.0, rest_baseline_days - m.rest_home_days)
        rest_a = beta_rest * max(0.0, rest_baseline_days - m.rest_away_days)
        cov_h = gamma * (lh - la) + beta_altitude * (m.altitude_m / 1000.0) - beta_travel * (m.travel_home_km / 1000.0) + rest_h
        cov_a = -gamma * (lh - la) - beta_travel * (m.travel_away_km / 1000.0) + rest_a
        hf = 0.0 if m.neutral else hadv
        exp_h = math.exp(mu + hf + att[m.home] + dfn[m.away] + dyn_att[m.home] + dyn_dfn[m.away] + cov_h)
        exp_a = math.exp(mu + att[m.away] + dfn[m.home] + dyn_att[m.away] + dyn_dfn[m.home] + cov_a)
        err_h = m.hg - exp_h
        err_a = m.ag - exp_a
        scale = m.weight * alpha
        dyn_att[m.home] += scale * err_h
        dyn_dfn[m.away] += scale * err_h
        dyn_att[m.away] += scale * err_a
        dyn_dfn[m.home] += scale * err_a
    return {t: {"att": dyn_att[t], "dfn": dyn_dfn[t]} for t in att}


def _neg_log_likelihood_covariates(
    x: np.ndarray,
    matches: list[MatchRecord],
    att: dict[str, float],
    dfn: dict[str, float],
    mu: float,
    hadv: float,
    rho: float,
    nb_r: float,
) -> float:
    gamma, beta_alt, beta_trav = x
    ll = 0.0
    for m in matches:
        lh = m.lineup_home if m.lineup_home is not None else 75.0
        la = m.lineup_away if m.lineup_away is not None else 75.0
        cov_h = gamma * (lh - la) + beta_alt * (m.altitude_m / 1000.0) - beta_trav * (m.travel_home_km / 1000.0)
        cov_a = -gamma * (lh - la) - beta_trav * (m.travel_away_km / 1000.0)
        hf = 0.0 if m.neutral else hadv
        l1 = math.exp(mu + hf + att[m.home] + dfn[m.away] + cov_h)
        l2 = math.exp(mu + att[m.away] + dfn[m.home] + cov_a)
        p1 = nb_pmf(m.hg, l1, nb_r)
        p2 = nb_pmf(m.ag, l2, nb_r)
        ll -= m.weight * (math.log(max(p1, 1e-12)) + math.log(max(p2, 1e-12)))
    return ll


def learn_covariate_weights(
    matches: list[MatchRecord],
    att: dict[str, float],
    dfn: dict[str, float],
    mu: float,
    hadv: float,
    rho: float,
    nb_r: float,
    initial: dict[str, float] | None = None,
) -> tuple[float, float, float]:
    """MLE for gamma, beta_altitude, beta_travel via scipy.optimize."""
    init = initial or DEFAULTS
    x0 = np.array([init["gamma"], init["beta_altitude"], init["beta_travel"]])
    bounds = [(-0.2, 0.2), (-0.5, 0.0), (-0.5, 0.0)]
    result = optimize.minimize(
        _neg_log_likelihood_covariates,
        x0,
        args=(matches, att, dfn, mu, hadv, rho, nb_r),
        method="L-BFGS-B",
        bounds=bounds,
    )
    return float(result.x[0]), float(result.x[1]), float(result.x[2])


def train(
    cutoff: str | None = None,
    params: dict[str, float] | None = None,
    matches: list[MatchRecord] | None = None,
    learn_covariates: bool = True,
) -> TrainedModel:
    """Full training pipeline: iterative fit, covariate MLE, dynamic state."""
    p = params or load_params()
    cutoff = cutoff or date.today().isoformat()
    if matches is None:
        matches = load_matches(cutoff, p["half_life"], p["friendly_w"], p["margin_cap"])
    att, dfn, mu, hadv = fit_iterative(matches, p["shrink"], p.get("nb_dispersion", 8.0))
    gamma, beta_alt, beta_trav = p["gamma"], p["beta_altitude"], p["beta_travel"]
    if learn_covariates and any(m.lineup_home is not None for m in matches):
        gamma, beta_alt, beta_trav = learn_covariate_weights(
            matches, att, dfn, mu, hadv, p["rho"], p.get("nb_dispersion", 8.0), p
        )
    beta_rest = p.get("beta_rest", -0.04)
    rest_baseline = p.get("rest_baseline_days", 7.0)
    dynamic = apply_dynamic_updates(
        matches,
        att,
        dfn,
        mu,
        hadv,
        alpha=p.get("dynamic_alpha", 0.15),
        decay=p.get("dynamic_decay", 0.995),
        gamma=gamma,
        beta_altitude=beta_alt,
        beta_travel=beta_trav,
        beta_rest=beta_rest,
        rest_baseline_days=rest_baseline,
    )
    teams = sorted(att.keys())
    return TrainedModel(
        att=att,
        dfn=dfn,
        mu=mu,
        hadv=hadv,
        rho=p["rho"],
        nb_r=p.get("nb_dispersion", 8.0),
        gamma=gamma,
        beta_altitude=beta_alt,
        beta_travel=beta_trav,
        beta_rest=beta_rest,
        rest_baseline_days=rest_baseline,
        dynamic_alpha=p.get("dynamic_alpha", 0.15),
        dynamic_decay=p.get("dynamic_decay", 0.995),
        teams=teams,
        params=p,
        dynamic_state=dynamic,
    )


def effective_ratings(model: TrainedModel, team: str) -> tuple[float, float]:
    """Base att/def plus accumulated dynamic adjustment."""
    ds = model.dynamic_state.get(team, {"att": 0.0, "dfn": 0.0})
    return model.att[team] + ds["att"], model.dfn[team] + ds["dfn"]
