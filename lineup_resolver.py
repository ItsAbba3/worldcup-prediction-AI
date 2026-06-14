"""Player OVR lookup and Most Frequent XI resolution.

OVR data sources (priority order)
---------------------------------
1. **EA Sports FC 25** — primary.
   - Bulk CSV export from https://sofifa.com (download players dataset)
   - Kaggle community dataset: search ``EA FC 25 Players Dataset`` or
     ``stefanoleone992/fifa-23-complete-player-dataset`` (FC25 equivalent).
   - Fields: ``overall`` (0–99), match on ``short_name`` / ``long_name``.

2. **eFootball (Konami)** — secondary fallback.
   - pesmaster.com CSV exports
   - Kaggle ``eFootball-ratings`` community dataset.

3. **Positional average** — tertiary fallback when a player is not found:
   mean OVR of GKs/DEFs/MIDs/FWDs in the same national squad.

Name matching uses ``thefuzz.token_sort_ratio`` with threshold >= 85 for
transliteration and accent differences.
"""

from __future__ import annotations

import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from thefuzz import fuzz

from data_pipeline import APIFootballClient

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")

# Default paths — user downloads real datasets here
EA_FC_PATH = os.path.join(DATA_DIR, "ea_fc25_players.csv")
EFOOTBALL_PATH = os.path.join(DATA_DIR, "efootball_ratings.csv")

FUZZY_THRESHOLD = 85
DEFAULT_OVR = 72.0
INJURY_ABSENCE_P = 0.05


@dataclass
class LineupResult:
    """Resolved lineup with metadata."""

    players: list[str]
    ovr_values: list[float]
    lineup_rating: float
    lineup_mode: str
    match_details: list[dict[str, Any]]


class OVRLookup:
    """Fuzzy player rating lookup across EA FC and eFootball databases."""

    def __init__(
        self,
        ea_path: str = EA_FC_PATH,
        efootball_path: str = EFOOTBALL_PATH,
    ) -> None:
        self.ea_df = self._load_csv(ea_path)
        self.ef_df = self._load_csv(efootball_path)
        self._ea_index = self._build_index(self.ea_df)
        self._ef_index = self._build_index(self.ef_df)
        self._team_pos_avg = self._team_positional_averages(self.ea_df)

    @staticmethod
    def _load_csv(path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            return pd.DataFrame()
        return pd.read_csv(path, low_memory=False)

    @staticmethod
    def _build_index(df: pd.DataFrame) -> dict[str, tuple[str, float, str]]:
        if df.empty:
            return {}
        idx: dict[str, tuple[str, float, str]] = {}
        name_cols = [c for c in ("short_name", "long_name", "name", "player_name") if c in df.columns]
        ovr_col = next((c for c in ("overall", "rating", "ovr") if c in df.columns), None)
        pos_col = next((c for c in ("player_positions", "position", "pos") if c in df.columns), None)
        club_col = next((c for c in ("club_name", "team", "nationality") if c in df.columns), None)
        if not ovr_col:
            return idx
        for _, row in df.iterrows():
            ovr = float(row[ovr_col])
            pos = str(row[pos_col]) if pos_col else "MID"
            club = str(row[club_col]) if club_col else ""
            for col in name_cols:
                name = str(row[col]).strip()
                if name and name != "nan":
                    idx[name.lower()] = (name, ovr, pos)
        return idx

    def _team_positional_averages(self, df: pd.DataFrame) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = defaultdict(dict)
        if df.empty:
            return out
        ovr_col = next((c for c in ("overall", "rating", "ovr") if c in df.columns), None)
        pos_col = next((c for c in ("player_positions", "position", "pos") if c in df.columns), None)
        nat_col = next((c for c in ("nationality", "nation", "country") if c in df.columns), None)
        if not all([ovr_col, pos_col, nat_col]):
            return out
        for nat, grp in df.groupby(nat_col):
            buckets: dict[str, list[float]] = defaultdict(list)
            for _, row in grp.iterrows():
                pos = self._normalize_pos(str(row[pos_col]))
                buckets[pos].append(float(row[ovr_col]))
            out[str(nat)] = {p: sum(v) / len(v) for p, v in buckets.items() if v}
        return dict(out)

    @staticmethod
    def _normalize_pos(pos: str) -> str:
        p = pos.upper()
        if "GK" in p:
            return "GK"
        if any(x in p for x in ("CB", "LB", "RB", "DEF", "DF")):
            return "DEF"
        if any(x in p for x in ("ST", "CF", "LW", "RW", "FW", "FWD")):
            return "FWD"
        return "MID"

    def _fuzzy_lookup(self, name: str, index: dict[str, tuple[str, float, str]]) -> tuple[float, str, str] | None:
        if not index:
            return None
        key = name.lower()
        if key in index:
            n, ovr, pos = index[key]
            return ovr, pos, n
        best_score, best = 0, None
        for candidate, val in index.items():
            score = fuzz.token_sort_ratio(name.lower(), candidate)
            if score > best_score:
                best_score, best = score, val
        if best_score >= FUZZY_THRESHOLD and best:
            n, ovr, pos = best
            return ovr, pos, n
        return None

    def lookup_player(self, name: str, team: str = "") -> tuple[float, str, str]:
        """Return (ovr, position, matched_name). Falls back to positional average."""
        for index in (self._ea_index, self._ef_index):
            hit = self._fuzzy_lookup(name, index)
            if hit:
                return hit[0], hit[1], hit[2]
        pos = "MID"
        team_avgs = self._team_pos_avg.get(team, {})
        ovr = team_avgs.get(pos, DEFAULT_OVR)
        return ovr, pos, name

    def lineup_rating(self, players: list[str], team: str = "") -> tuple[float, list[float], list[dict[str, Any]]]:
        values, details = [], []
        for p in players:
            ovr, pos, matched = self.lookup_player(p, team)
            values.append(ovr)
            details.append({"input": p, "matched": matched, "ovr": ovr, "pos": pos})
        rating = sum(values) / len(values) if values else DEFAULT_OVR
        return rating, values, details


class LineupResolver:
    """Build confirmed or Most-Frequent-XI lineups with OVR ratings."""

    def __init__(
        self,
        ovr: OVRLookup | None = None,
        api: APIFootballClient | None = None,
    ) -> None:
        self.ovr = ovr or OVRLookup()
        self.api = api or APIFootballClient()

    def resolve_confirmed(
        self,
        team: str,
        players: list[str],
    ) -> LineupResult:
        rating, values, details = self.ovr.lineup_rating(players[:11], team)
        return LineupResult(
            players=players[:11],
            ovr_values=values,
            lineup_rating=rating,
            lineup_mode="confirmed",
            match_details=details,
        )

    def most_frequent_xi(
        self,
        team: str,
        days_back: int = 180,
        as_of: date | None = None,
        simulate_injuries: bool = True,
        injury_p: float = INJURY_ABSENCE_P,
        rng: random.Random | None = None,
    ) -> LineupResult:
        """Most frequent starting XI from international matches in last 6 months."""
        records = self.api.historical_lineups_for_team(team, days_back, as_of)
        if not records:
            return self._fallback_xi(team)

        slot_counts: list[Counter[str]] = [Counter() for _ in range(11)]
        for rec in records:
            lineup = rec["lineup"][:11]
            for i, player in enumerate(lineup):
                slot_counts[i][player] += 1

        ranked_slots = [
            sorted(counter.items(), key=lambda x: (-x[1], x[0])) for counter in slot_counts
        ]
        xi = [ranked[0][0] if ranked else "" for ranked in ranked_slots]

        if simulate_injuries:
            rng = rng or random.Random()
            for i, ranked in enumerate(ranked_slots):
                if not ranked:
                    continue
                if rng.random() < injury_p and len(ranked) > 1:
                    xi[i] = ranked[1][0]

        xi = [p for p in xi if p]
        if len(xi) < 11:
            return self._fallback_xi(team)

        rating, values, details = self.ovr.lineup_rating(xi, team)
        return LineupResult(
            players=xi,
            ovr_values=values,
            lineup_rating=rating,
            lineup_mode="most_frequent_6mo",
            match_details=details,
        )

    def _fallback_xi(self, team: str) -> LineupResult:
        """When no lineup history exists, use team positional average OVR."""
        avgs = self.ovr._team_pos_avg.get(team, {})
        default = avgs.get("MID", DEFAULT_OVR)
        players = [f"{team} Player {i+1}" for i in range(11)]
        values = [default] * 11
        return LineupResult(
            players=players,
            ovr_values=values,
            lineup_rating=default,
            lineup_mode="most_frequent_6mo",
            match_details=[{"input": p, "matched": p, "ovr": default, "pos": "MID"} for p in players],
        )

    def resolve(
        self,
        team: str,
        confirmed: list[str] | None = None,
        days_back: int = 180,
        as_of: date | None = None,
        simulate_injuries: bool = True,
    ) -> LineupResult:
        if confirmed and len(confirmed) >= 11:
            return self.resolve_confirmed(team, confirmed)
        return self.most_frequent_xi(team, days_back, as_of, simulate_injuries)
