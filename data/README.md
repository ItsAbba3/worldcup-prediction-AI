# Player OVR datasets

Place downloaded rating CSVs here before running lineup-aware predictions.

## Primary — EA Sports FC 25

- **Source:** [sofifa.com](https://sofifa.com) bulk CSV export, or Kaggle
  **"EA FC 25 Players Dataset"** (search `stefanoleone992/fifa-23-complete-player-dataset`
  or the FC25 equivalent).
- **Filename:** `ea_fc25_players.csv`
- **Required columns:** `overall`, `short_name`, `long_name`, `player_positions`, `nationality`

A minimal sample file is bundled for Iran/Belgium smoke tests. Replace it with the
full export for production use.

## Secondary — eFootball (Konami)

- **Source:** [pesmaster.com](https://pesmaster.com) CSV exports, or Kaggle
  `eFootball-ratings` community dataset.
- **Filename:** `efootball_ratings.csv`
- Used when a player is not found in the EA FC file (fuzzy match threshold ≥ 85).

## Lineup history (API, not a static file)

Historical starting XIs are fetched from **API-Football**:

```
GET https://v3.football.api-sports.io/fixtures/lineups?fixture={fixture_id}
```

Responses are cached in `lineups_cache.db` at the project root.
