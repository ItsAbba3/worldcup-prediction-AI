# ⚽ World Cup 2026 Prediction Engine

A production-grade football match prediction system for FIFA World Cup 2026 — built on **Dixon-Coles Negative Binomial** goal modeling, **100,000-match Monte Carlo** tournament simulation, **EA FC 25 lineup OVR** integration, and **Kalman-style dynamic ratings**.
Model Performance on 2026 FIFA World Cup Group Stage (72 matches):

Outcome accuracy (Win/Draw/Loss): 40/72 = 55.6%
Exact scoreline accuracy: 8/72 = 11.1%

Knockout Stage Prediction (100,000 simulations):

3rd place match: Brazil vs Spain → Brazil finishes 3rd
Final: Argentina vs Mexico → Argentina are champions

---

## ✨ Features

- **Dixon-Coles NB model** — Negative Binomial distribution replaces standard Poisson, correctly modeling overdispersion (big upsets, high-scoring games)
- **Dynamic ratings** — Elo-style per-team attack/defence adjustments that decay over time, capturing recent form
- **Lineup OVR integration** — EA FC 25 player ratings feed a lineup-strength covariate; confirmed squads automatically shift xG
- **Fatigue/rest covariate** — Teams with fewer rest days between matches are penalized proportionally
- **Altitude & travel covariates** — Venue altitude and km traveled since last match are factored in
- **Motivation dynamics** — Knockout-stage intensity, must-win group scenarios, and dead-rubber detection
- **Full tournament simulator** — 100,000 simulations of all 72 group matches + complete knockout bracket, outputting win probabilities, expected goals, and golden boot odds
- **Auto lineup resolver** — Pulls Most Frequent XI (last 6 months) from API-Football with fuzzy-matched OVR lookup; falls back gracefully when data is missing
- **Live single-match prediction** — CLI and Python API for predicting any match with confirmed or auto-resolved lineups

---

## 🏗️ Architecture

```
model.py            ← Dixon-Coles NB model: fit, dynamic updates, lambdas
predict.py          ← Single-match prediction (CLI + Python API)
simulator.py        ← Full tournament Monte Carlo simulator
lineup_resolver.py  ← API-Football lineup puller + EA FC 25 OVR matcher
data_pipeline.py    ← Data loading, venue altitude, travel distance
international_results.csv  ← 49k historical international matches (martj42)
data/ea_fc25_players.csv   ← EA FC 25 player ratings (expand for all 48 teams)
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. API key

Get a free/Pro key from [api-football.com](https://www.api-football.com) and put it in `.api_football_key` (or set `API_FOOTBALL_KEY` env var).

### 3. Refresh match history

```bash
curl -sL https://raw.githubusercontent.com/martj42/international_results/master/results.csv \
     -o international_results.csv
```

### 4. Predict a single match

```bash
# Auto lineup (Most Frequent XI pulled from API-Football)
python predict.py --match "Brazil vs Argentina" --venue "MetLife Stadium"

# With confirmed away lineup
python predict.py --match "Brazil vs Argentina" --venue "MetLife Stadium" \
  --lineup-away "Martinez" "Montiel" "Romero" "Lisandro" "Acuna" \
                "De Paul" "Mac Allister" "Fernandez" "Di Maria" "Alvarez" "Messi"

# Via JSON input (recommended for full lineups)
python predict.py --json input.json --output result.json
```

**`input.json` format:**
```json
{
  "match_name": "Brazil vs Argentina",
  "venue": "MetLife Stadium",
  "lineup_home": null,
  "lineup_away": ["Martinez", "Montiel", "Romero", "Lisandro", "Acuna",
                  "De Paul", "Mac Allister", "Fernandez", "Di Maria", "Alvarez", "Messi"],
  "n_sims": 10000
}
```

### 5. Simulate the full tournament

```python
from simulator import TournamentSimulator

sim = TournamentSimulator(n_sims=100_000)
results = sim.run()
# results: dict with win_pct, group_advance_pct, top_scorer odds per team
```

---

## 📊 Model Details

### Goal Model

Goals scored by each team follow a **Negative Binomial** distribution:

```
Goals_home ~ NB(μ = exp(μ + hadv + att_h + dfn_a + covariates), r)
Goals_away ~ NB(μ = exp(μ        + att_a + dfn_h + covariates), r)
```

where `r` is the dispersion parameter (fit via MLE, default 8.0).

### Covariates (log-intensity adjustments)

| Covariate | Effect | Default coefficient |
|---|---|---|
| Home advantage | +hadv to home log-intensity | fit from data (~0.18) |
| Lineup OVR delta | ±gamma × (OVR_h − OVR_a) | γ = 0.02 |
| Altitude (per 1000m) | +beta_alt to home | β = −0.08 |
| Travel distance (per 1000km) | −beta_travel to traveler | β = −0.05 |
| Fatigue (rest days < 7) | −beta_rest × deficit | β = −0.04 |

### Dynamic Ratings

After each historical match, prediction errors update per-team attack/defence state:

```
dyn_att[team] = dyn_att[team] × decay + alpha × error
```

with `decay = 0.995`, `alpha = 0.15`. Applied on top of base MLE ratings at prediction time.

### Iterative Fit

Attack/defence ratings are fit via **iterative WLS** (Dixon-Coles update equations), correctly keeping the solved parameter *out* of its own denominator to avoid the divergence bug present in some open-source implementations.

---

## 📂 Data

### Match History

`international_results.csv` — sourced from [martj42/international_results](https://github.com/martj42/international_results). Refresh before each matchday:

```bash
curl -sL https://raw.githubusercontent.com/martj42/international_results/master/results.csv \
     -o international_results.csv
```

### Player OVR Ratings

Place `data/ea_fc25_players.csv` from one of:
- [sofifa.com](https://sofifa.com) bulk CSV export
- Kaggle: `stefanoleone992/fifa-23-complete-player-dataset` (or FC25 equivalent)

Required columns: `overall`, `short_name`, `long_name`, `player_positions`, `nationality`

A minimal sample (Iran + Belgium) is bundled for smoke-testing. **Replace with the full dataset for accurate tournament-wide OVR covariates.**

---

## 🔄 Matchday Routine

```bash
# 1. Refresh historical data
curl -sL https://raw.githubusercontent.com/.../results.csv -o international_results.csv

# 2. Fetch latest fixtures & form
python wc26_fetch.py

# 3. Update results after matches
python wc26_update_results.py

# 4. Re-run tournament simulation
python -c "from simulator import TournamentSimulator; TournamentSimulator(100000).run()"

# 5. Rebuild static site (optional)
python wc26_build_site.py
```

---

## ⚙️ Configuration

All hyperparameters live in `model.py`'s `DEFAULTS` dict and can be overridden via `wc26_params.json`:

```python
DEFAULTS = {
    "half_life": 1000.0,       # days; older matches down-weighted
    "friendly_w": 0.6,         # weight for friendlies vs. competitive
    "shrink": 8.0,             # regularization toward league average
    "rho": -0.10,              # Dixon-Coles low-score correlation
    "nb_dispersion": 8.0,      # Negative Binomial r parameter
    "gamma": 0.02,             # lineup OVR coefficient
    "beta_altitude": -0.08,    # altitude fatigue (per 1000m)
    "beta_travel": -0.05,      # travel fatigue (per 1000km)
    "beta_rest": -0.04,        # rest-day fatigue
    "rest_baseline_days": 7.0, # baseline rest; less than this → penalty
    "dynamic_alpha": 0.15,     # dynamic rating learning rate
    "dynamic_decay": 0.995,    # dynamic state decay per match
}
```

---

## 📦 Requirements

```
pandas>=2.0
numpy>=1.24
scipy>=1.10
thefuzz>=0.22
python-Levenshtein>=0.21
requests>=2.28
```

API-Football key required for live lineup resolution. Without it, the model falls back to positional average OVR from the EA FC 25 dataset.

---

## 🙏 Credits

- Historical match data: [martj42/international_results](https://github.com/martj42/international_results)
- Original open-source World Cup forecasting model: [amirdaraee/world-cup-predictions](https://github.com/amirdaraee/world-cup-predictions)
- Player ratings: EA Sports FC 25 via sofifa.com / Kaggle
- Live fixtures & lineups: [API-Football](https://www.api-football.com)
