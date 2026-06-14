# World Cup Predictions

Personal research tool for betting on FIFA World Cup 2026 (Polymarket). Static site
("The Form Book") generated from JSON data + a Dixon-Coles simulation model.

## Pipeline (order matters)

```
python3 wc26_fetch.py        # refresh each team's last-10 matches (API-Football, Pro key inside)
curl -sL https://raw.githubusercontent.com/martj42/international_results/master/results.csv \
     -o international_results.csv          # refresh match history for the model
python3 wc26_simulate.py     # fit model, backtest, write wc26_simulations.json
python3 wc26_simulate.py tune   # (occasional) re-tune hyperparams -> wc26_params.json
.venv/bin/python3 wc26_tournament.py   # 200-model ensemble + 100k sims (needs numpy venv)
                             # -> wc26_tournament.json (futures) + wc26_predictions.json
                             #    (locked bracket; --force to re-lock, normally never)
python3 wc26_polymarket.py   # live Polymarket prices -> wc26_market_prices.json (free, no key)
python3 wc26_players.py      # squads + player intl goals + award market prices (~300 API calls)
.venv/bin/python3 wc26_awards.py       # Golden Boot model etc -> wc26_awards.json (after tournament.py)
python3 wc26_update_results.py  # during tournament: pull actual results, grade predictions
python3 wc26_build_site.py   # regenerate docs/ live pages
python3 wc26_charts.py        # (occasional) regenerate method-page SVG charts
python3 wc26_build_site.py snapshot  # ...plus freeze docs/archive/<date>/ (once per matchday;
                             # archive/ survives rebuilds, snapshots are immutable history)
python3 -m http.server 8742 --directory docs   # browse
```

## Files

- `fifa_world_cup_2026.json` — 48 teams: confederation, FIFA ranking, last 10 matches
- `fifa_world_cup_2026_group_matches.json` — 72 group fixtures (match_id = API-Football fixture id)
- `wc26_params.json` — tuned model hyperparameters (regenerate with `wc26_simulate.py tune`)
- `wc26_simulations.json` — per-match market probabilities (moneyline/totals/BTTS/spread/scorelines)
- `wc26_tournament.json` — per-team futures probabilities (win group → champion)
- `wc26_market_prices.json` — Polymarket moneyline snapshots (re-fetch near kickoff; some
  fixtures get listed late — the script picks them up on re-run)
- `wc26_model_notes.md` — method R&D, validation numbers, known blind spots
- `docs/` — generated output, never edit by hand

## Betting module (`betting/`)

- `find_bets.py` (plan from RAW-model edges vs live prices, Kelly-sized) →
  review `betting/state/plan.json` → `place_bets.py` (dry-run default,
  `--live` to execute, `--limit N` for partial batches). Uses the
  py-clob-client-v2 SDK (Polymarket migrated exchanges 2026-04-28).
- ALL personal betting data is gitignored and must stay that way:
  `betting/.env` (wallet key + API creds), `betting/config.local.json`
  (real caps), `betting/state/` (plans + ledger). The committed
  `betting/config.json` holds only generic placeholder caps.
- The ledger enforces the total cap across runs and prevents double-betting;
  never edit it by hand.

## Conventions

- Team names are normalized to the main JSON's spelling ("United States", "Turkey",
  "DR Congo", "South Korea"); API-Football and the history CSV use variants — alias
  maps exist in the scripts.
- Data sources: API-Football (Pro plan; key read from env API_FOOTBALL_KEY or the
  gitignored .api_football_key file) for fixtures/results;
  martj42/international_results for model training. Prefer free APIs; ask user for
  keys when needed.
- Mostly stdlib Python; numpy lives only in `.venv/` and only `wc26_tournament.py`
  needs it. Everything else must stay stdlib.
- `wc26_predictions.json` is LOCKED (pre-tournament bracket picks for accuracy
  grading). Only `wc26_update_results.py` may write to it (fills actuals);
  never regenerate it without the user explicitly asking (--force).
- Every result-writing script also archives a time-coded copy in `runs/`
  (via `save_versioned` in wc26_simulate.py). The site always shows the
  canonical "latest" files; run timestamps appear in the site footer.
- Group-match picks/probabilities are model×market blends (w=0.35 on
  Polymarket, log-opinion pool) where priced; `p_model`/`p_market` are kept
  alongside so the scorecard can grade model vs market vs blend separately.
