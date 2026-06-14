"""Live match prediction interface for in-tournament use.

Usage (Python):
    from predict import predict_upcoming_match
    result = predict_upcoming_match(
        match_name="Iran vs Belgium",
        venue="SoFi Stadium",
        lineup_home=None,   # -> Most Frequent XI (last 6 months)
        lineup_away=["Courtois", ...],
    )

Usage (CLI):
    python predict.py --match "Iran vs Belgium" --venue "SoFi Stadium"
    python predict.py --json input.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np

from data_pipeline import CITY_COORDS, lookup_altitude, travel_distance_km, APIFootballClient
from lineup_resolver import LineupResolver
from model import TrainedModel, lambdas, sample_scores, train

ROOT = os.path.dirname(os.path.abspath(__file__))
N_SIMS = 10_000

from data_pipeline import CITY_COUNTRY


@dataclass
class MatchPrediction:
    match_name: str
    home: str
    away: str
    venue: str
    city: str
    altitude_m: float
    travel_home_km: float
    travel_away_km: float
    rest_home_days: float
    rest_away_days: float
    xg_home: float
    xg_away: float
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    top_scorelines: list[dict[str, Any]]
    lineup_home: dict[str, Any]
    lineup_away: dict[str, Any]
    model_version: str = "dixon-coles-nb-v2"


def parse_match_name(match_name: str) -> tuple[str, str]:
    """Parse 'Iran vs Belgium' or 'Iran v Belgium' into (home, away)."""
    parts = re.split(r"\s+(?:vs\.?|v\.?|-)\s+", match_name.strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse match name: {match_name!r}")
    return parts[0].strip(), parts[1].strip()


def resolve_venue_city(venue: str) -> tuple[str, str]:
    """Map stadium name to city using WC2026 fixtures or heuristics."""
    fixtures_path = os.path.join(ROOT, "fifa_world_cup_2026_group_matches.json")
    if os.path.exists(fixtures_path):
        for m in json.load(open(fixtures_path, encoding="utf-8"))["matches"]:
            if m.get("venue", "").lower() == venue.lower():
                return m["venue"], m.get("city", "")
    for city in CITY_COORDS:
        if city.lower() in venue.lower():
            return venue, city
    return venue, venue


def home_field(team: str, city: str) -> bool:
    return team == CITY_COUNTRY.get(city, "United States")


def estimate_travel(team: str, city: str, api: APIFootballClient) -> float:
    """Km traveled since team's last international match."""
    fixtures = api.team_fixtures(team, days_back=60)
    if not fixtures:
        return 0.0
    last = sorted(fixtures, key=lambda f: f["date"])[-1]
    last_city = last.get("city") or city
    return travel_distance_km(last_city, city)


def days_since_last_match(team: str, api: APIFootballClient, as_of: date) -> float:
    """Days since team's most recent match before as_of (default 7.0 if unknown)."""
    fixtures = api.team_fixtures(team, days_back=60)
    if not fixtures:
        return 7.0
    past = [f for f in fixtures if date.fromisoformat(f["date"]) < as_of]
    if not past:
        return 7.0
    last = sorted(past, key=lambda f: f["date"])[-1]
    delta = (as_of - date.fromisoformat(last["date"])).days
    return float(min(max(delta, 0), 60))


def predict_upcoming_match(
    match_name: str,
    venue: str,
    lineup_home: list[str] | None = None,
    lineup_away: list[str] | None = None,
    model: TrainedModel | None = None,
    resolver: LineupResolver | None = None,
    n_sims: int = N_SIMS,
    as_of: date | None = None,
    city: str | None = None,
    rng_seed: int | None = None,
) -> MatchPrediction:
    """Predict a single upcoming match with 10k localized Monte Carlo sims.

  Parameters
  ----------
  match_name : str
      e.g. ``"Iran vs Belgium"`` (first team = home).
  venue : str
      Stadium name for altitude lookup.
  lineup_home, lineup_away : list[str] | None
      Confirmed starting XI (11 names). ``None`` -> Most Frequent XI (6 months).
  """
    home, away = parse_match_name(match_name)
    venue_name, resolved_city = resolve_venue_city(venue)
    city = city or resolved_city
    model = model or train()
    resolver = resolver or LineupResolver()
    api = resolver.api

    lh = resolver.resolve(home, confirmed=lineup_home, as_of=as_of, simulate_injuries=lineup_home is None)
    la = resolver.resolve(away, confirmed=lineup_away, as_of=as_of, simulate_injuries=lineup_away is None)

    altitude_m = lookup_altitude(venue_name, city)
    travel_h = estimate_travel(home, city, api)
    travel_a = estimate_travel(away, city, api)
    hf = home_field(home, city)
    as_of_date = as_of or date.today()
    rest_h = days_since_last_match(home, api, as_of_date)
    rest_a = days_since_last_match(away, api, as_of_date)

    l1, l2 = lambdas(
        model,
        home,
        away,
        hf,
        lh.lineup_rating,
        la.lineup_rating,
        altitude_m,
        travel_h,
        travel_a,
        rest_h,
        rest_a,
    )

    rng = np.random.default_rng(rng_seed)
    hg, ag = sample_scores(l1, l2, model.rho, model.nb_r, n_sims, rng)
    outcomes = Counter()
    scores = Counter()
    for i, j in zip(hg, ag):
        outcomes["H" if i > j else "A" if j > i else "D"] += 1
        scores[(int(i), int(j))] += 1

    n = n_sims
    top = [
        {"score": f"{i}-{j}", "probability": round(c / n, 4)}
        for (i, j), c in scores.most_common(10)
    ]

    return MatchPrediction(
        match_name=match_name,
        home=home,
        away=away,
        venue=venue_name,
        city=city,
        altitude_m=round(altitude_m, 1),
        travel_home_km=round(travel_h, 1),
        travel_away_km=round(travel_a, 1),
        rest_home_days=rest_h,
        rest_away_days=rest_a,
        xg_home=round(l1, 3),
        xg_away=round(l2, 3),
        prob_home_win=round(outcomes["H"] / n, 4),
        prob_draw=round(outcomes["D"] / n, 4),
        prob_away_win=round(outcomes["A"] / n, 4),
        top_scorelines=top,
        lineup_home={
            "players": lh.players,
            "lineup_rating": round(lh.lineup_rating, 2),
            "lineup_mode": lh.lineup_mode,
            "ovr_details": lh.match_details,
        },
        lineup_away={
            "players": la.players,
            "lineup_rating": round(la.lineup_rating, 2),
            "lineup_mode": la.lineup_mode,
            "ovr_details": la.match_details,
        },
    )


def _print_prediction(pred: MatchPrediction) -> None:
    print(f"\n{'='*60}")
    print(f"  {pred.home} vs {pred.away}")
    print(f"  Venue: {pred.venue} ({pred.city})")
    print(f"  Altitude: {pred.altitude_m}m | Travel: {pred.travel_home_km}/{pred.travel_away_km} km")
    print(f"{'='*60}")
    print(f"\n  xG: {pred.xg_home:.2f} - {pred.xg_away:.2f}")
    print(f"\n  Match Odds:")
    print(f"    Home Win: {pred.prob_home_win:.1%}")
    print(f"    Draw:     {pred.prob_draw:.1%}")
    print(f"    Away Win: {pred.prob_away_win:.1%}")
    print(f"\n  Top Scorelines:")
    for s in pred.top_scorelines:
        print(f"    {s['score']}: {s['probability']:.1%}")
    print(f"\n  Lineups:")
    print(f"    {pred.home} [{pred.lineup_home['lineup_mode']}]: "
          f"OVR {pred.lineup_home['lineup_rating']}")
    print(f"    {pred.away} [{pred.lineup_away['lineup_mode']}]: "
          f"OVR {pred.lineup_away['lineup_rating']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live World Cup match predictor")
    parser.add_argument("--match", type=str, help='e.g. "Iran vs Belgium"')
    parser.add_argument("--venue", type=str, help="Stadium name")
    parser.add_argument("--json", type=str, help="JSON input file")
    parser.add_argument("--output", type=str, help="JSON output file")
    parser.add_argument("--lineup-home", type=str, nargs="*", help="11 home player names")
    parser.add_argument("--lineup-away", type=str, nargs="*", help="11 away player names")
    parser.add_argument("--sims", type=int, default=N_SIMS)
    args = parser.parse_args()

    if args.json:
        payload = json.load(open(args.json, encoding="utf-8"))
        pred = predict_upcoming_match(
            match_name=payload["match_name"],
            venue=payload["venue"],
            lineup_home=payload.get("lineup_home"),
            lineup_away=payload.get("lineup_away"),
            n_sims=payload.get("n_sims", args.sims),
        )
    elif args.match and args.venue:
        pred = predict_upcoming_match(
            match_name=args.match,
            venue=args.venue,
            lineup_home=args.lineup_home,
            lineup_away=args.lineup_away,
            n_sims=args.sims,
        )
    else:
        parser.error("Provide --match and --venue, or --json input file")

    if args.output:
        json.dump(asdict(pred), open(args.output, "w"), indent=2, ensure_ascii=False)
        print(f"Wrote {args.output}")
    else:
        _print_prediction(pred)


if __name__ == "__main__":
    main()
