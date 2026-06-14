"""Monte Carlo World Cup tournament simulator with motivation dynamics.

Enhancements over the legacy wc26_tournament.py engine:
  - Dixon-Coles Negative Binomial score sampling
  - Lineup OVR covariates, altitude & travel penalties
  - In-tournament motivation: teams that have mathematically secured
    qualification before Matchday 3 get a 10–15% attack reduction on MD3
"""

from __future__ import annotations

import json
import math
import os
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from data_pipeline import CITY_COUNTRY, lookup_altitude, travel_distance_km  # noqa: F401
from lineup_resolver import LineupResolver
from model import TrainedModel, lambdas, sample_scores, train

ROOT = os.path.dirname(os.path.abspath(__file__))
N_BOOT = 200
N_SIMS = 100_000
MAX_G = 12
MOTIVATION_REDUCTION = 0.12  # 12% attack reduction when qualified early

HOSTS = {"United States", "Mexico", "Canada"}

R32 = [
    (73, ("R", "A"), ("R", "B")),
    (74, ("W", "E"), ("T", "ABCDF")),
    (75, ("W", "F"), ("R", "C")),
    (76, ("W", "C"), ("R", "F")),
    (77, ("W", "I"), ("T", "CDFGH")),
    (78, ("R", "E"), ("R", "I")),
    (79, ("W", "A"), ("T", "CEFHI")),
    (80, ("W", "L"), ("T", "EHIJK")),
    (81, ("W", "D"), ("T", "BEFIJ")),
    (82, ("W", "G"), ("T", "AEHIJ")),
    (83, ("R", "K"), ("R", "L")),
    (84, ("W", "H"), ("R", "J")),
    (85, ("W", "B"), ("T", "EFGIJ")),
    (86, ("W", "J"), ("R", "H")),
    (87, ("W", "K"), ("T", "DEIJL")),
    (88, ("R", "D"), ("R", "G")),
]
R16 = [(89, 74, 77), (90, 73, 75), (91, 76, 78), (92, 79, 80),
       (93, 83, 84), (94, 81, 82), (95, 86, 88), (96, 85, 87)]
QF = [(97, 89, 90), (98, 93, 94), (99, 91, 92), (100, 95, 96)]
SF = [(101, 97, 98), (102, 99, 100)]
FINAL = (104, 101, 102)
THIRD_SLOTS = [
    (no, set(allowed))
    for no, s1, s2 in R32
    for k2, allowed in (s2,)
    if k2 == "T"
]


@dataclass
class FixtureContext:
    match_id: int
    home: str
    away: str
    group: str
    matchday: int
    city: str
    venue: str
    lineup_home: float
    lineup_away: float
    altitude_m: float
    travel_home_km: float
    travel_away_km: float


def load_fixtures(path: str | None = None) -> list[dict[str, Any]]:
    path = path or os.path.join(ROOT, "fifa_world_cup_2026_group_matches.json")
    return json.load(open(path, encoding="utf-8"))["matches"]


def build_fixture_contexts(
    fixtures: list[dict[str, Any]],
    resolver: LineupResolver,
    last_city: dict[str, str] | None = None,
) -> list[FixtureContext]:
    """Precompute lineup ratings and travel for all group fixtures."""
    last_city = last_city or {}
    alt_cache: dict[str, float] = {}
    contexts: list[FixtureContext] = []
    sorted_fx = sorted(fixtures, key=lambda m: (m.get("date_utc", ""), m["match_id"]))

    for m in sorted_fx:
        home, away = m["home"], m["away"]
        city = m.get("city", "")
        venue = m.get("venue", "")
        alt = lookup_altitude(venue, city, alt_cache)
        th = travel_distance_km(last_city.get(home, city), city)
        ta = travel_distance_km(last_city.get(away, city), city)
        lh = resolver.resolve(home, simulate_injuries=True)
        la = resolver.resolve(away, simulate_injuries=True)
        contexts.append(
            FixtureContext(
                match_id=m["match_id"],
                home=home,
                away=away,
                group=m["group"],
                matchday=m.get("matchday", 1),
                city=city,
                venue=venue,
                lineup_home=lh.lineup_rating,
                lineup_away=la.lineup_rating,
                altitude_m=alt,
                travel_home_km=th,
                travel_away_km=ta,
            )
        )
        last_city[home] = city
        last_city[away] = city
    return contexts


def home_field(team: str, city: str) -> bool:
    venue_country = CITY_COUNTRY.get(city, "United States")
    return team == venue_country


def has_secured_qualification(
    team: str,
    group: str,
    played: list[tuple[int, int, int]],
    remaining_opponents: dict[str, list[tuple[str, str]]],
    all_group_matches: list[FixtureContext],
) -> bool:
    """Check if team is guaranteed top-2 in group before MD3."""
    pts = sum(3 if hg > ag else 1 if hg == ag else 0 for hg, ag, _ in played)
    gd = sum(hg - ag for hg, ag, _ in played)
    max_others = []
    group_teams = {fx.home for fx in all_group_matches if fx.group == group} | {
        fx.away for fx in all_group_matches if fx.group == group
    }
    for other in group_teams - {team}:
        other_pts = 0
        other_max = 0
        for fx in all_group_matches:
            if fx.group != group or fx.matchday > 2:
                continue
            if fx.home == other or fx.away == other:
                other_max += 3
        max_others.append(other_max)
    max_others.sort(reverse=True)
    if len(max_others) < 2:
        return False
    second_best_max = max_others[1]
    return pts > second_best_max or (pts == second_best_max and gd > 6)


def allocate_thirds(thirds: list[tuple[str, str]], slots: list[tuple[int, set[str]]]) -> dict[int, str]:
    assign: dict[int, str] = {}

    def rec(i: int) -> bool:
        if i == len(slots):
            return True
        no, allowed = slots[i]
        for t, g in thirds:
            if g in allowed and t not in assign.values():
                assign[no] = t
                if rec(i + 1):
                    return True
                del assign[no]
        return False

    return assign if rec(0) else {}


class TournamentSimulator:
    """100k-tournament Monte Carlo with NB scoring and motivation dynamics."""

    def __init__(
        self,
        model: TrainedModel | None = None,
        resolver: LineupResolver | None = None,
        n_sims: int = N_SIMS,
        n_boot: int = N_BOOT,
        rng_seed: int = 2026,
    ) -> None:
        self.model = model or train()
        self.resolver = resolver or LineupResolver()
        self.n_sims = n_sims
        self.n_boot = n_boot
        self.rng = np.random.default_rng(rng_seed)
        random.seed(rng_seed)
        self.fixtures = load_fixtures()
        self.contexts = build_fixture_contexts(self.fixtures, self.resolver)
        self.groups = sorted({fx.group for fx in self.contexts})
        self.group_teams = {
            g: {fx.home for fx in self.contexts if fx.group == g}
            | {fx.away for fx in self.contexts if fx.group == g}
            for g in self.groups
        }
        # Precompute each team's lineup OVR once (avoids re-resolving on
        # every knockout match of every simulation — was 1.6M+ calls).
        all_teams = sorted({t for teams in self.group_teams.values() for t in teams})
        self.lineup_ratings: dict[str, float] = {
            t: self.resolver.resolve(t).lineup_rating for t in all_teams
        }

    def _fixture_lambdas(
        self,
        ctx: FixtureContext,
        motivation_factor: tuple[float, float] = (1.0, 1.0),
    ) -> tuple[float, float]:
        hf = home_field(ctx.home, ctx.city)
        l1, l2 = lambdas(
            self.model,
            ctx.home,
            ctx.away,
            hf,
            ctx.lineup_home,
            ctx.lineup_away,
            ctx.altitude_m,
            ctx.travel_home_km,
            ctx.travel_away_km,
        )
        return l1 * motivation_factor[0], l2 * motivation_factor[1]

    def sim_group_match(
        self,
        ctx: FixtureContext,
        secured: dict[str, bool],
    ) -> tuple[int, int]:
        mot_h = 1.0 - MOTIVATION_REDUCTION if secured.get(ctx.home) else 1.0
        mot_a = 1.0 - MOTIVATION_REDUCTION if secured.get(ctx.away) else 1.0
        l1, l2 = self._fixture_lambdas(ctx, (mot_h, mot_a))
        hg, ag = sample_scores(l1, l2, self.model.rho, self.model.nb_r, 1, self.rng)
        return int(hg[0]), int(ag[0])

    def sim_tournament(self) -> tuple[dict[str, str], dict[str, set[str]], dict[str, int]]:
        pts: dict[str, int] = defaultdict(int)
        gd: dict[str, int] = defaultdict(int)
        gf: dict[str, int] = defaultdict(int)
        goals: dict[str, int] = defaultdict(int)
        played: dict[str, list[tuple[int, int, int]]] = defaultdict(list)

        md_contexts: dict[int, list[FixtureContext]] = defaultdict(list)
        for ctx in self.contexts:
            md_contexts[ctx.matchday].append(ctx)

        for md in sorted(md_contexts):
            secured: dict[str, bool] = {}
            if md == 3:
                for g, teams in self.group_teams.items():
                    for t in teams:
                        team_played = played.get(t, [])
                        if len(team_played) >= 2:
                            secured[t] = has_secured_qualification(
                                t, g, team_played, {}, self.contexts
                            )
            for ctx in md_contexts[md]:
                i, j = self.sim_group_match(ctx, secured)
                for t, sf, sa in ((ctx.home, i, j), (ctx.away, j, i)):
                    pts[t] += 3 if sf > sa else 1 if sf == sa else 0
                    gd[t] += sf - sa
                    gf[t] += sf
                    goals[t] += sf
                    played[t].append((sf, sa, ctx.matchday))

        win, run, thirds = {}, {}, []
        for g in self.groups:
            order = sorted(
                self.group_teams[g],
                key=lambda t: (pts[t], gd[t], gf[t], random.random()),
                reverse=True,
            )
            win[g], run[g] = order[0], order[1]
            thirds.append((order[2], g))
        thirds.sort(key=lambda tg: (pts[tg[0]], gd[tg[0]], gf[tg[0]], random.random()), reverse=True)
        best8 = thirds[:8]
        alloc = allocate_thirds(best8, THIRD_SLOTS) or {
            no: best8[i][0] for i, (no, _) in enumerate(THIRD_SLOTS)
        }

        teams_in: dict[int, tuple[str, str]] = {}
        for no, s1, s2 in R32:
            def side(s: tuple[str, str], match_no: int = no) -> str:
                k, v = s
                return win[v] if k == "W" else run[v] if k == "R" else alloc[match_no]
            teams_in[no] = (side(s1), side(s2))

        winners: dict[int, str] = {}
        reached: dict[str, set[str]] = {
            s: set() for s in ("r32", "r16", "qf", "sf", "final", "champion")
        }

        def play_ko(a: str, b: str, rnd: int) -> str:
            ha = self.model.hadv if (a in HOSTS and (a == "United States" or rnd <= 2)) else 0.0
            hb = self.model.hadv if (b in HOSTS and (b == "United States" or rnd <= 2)) else 0.0
            lh = self.lineup_ratings[a]
            la = self.lineup_ratings[b]
            # lambdas() applies dynamic_state correctly; home_field=False gives
            # the base (no hadv) rate, then we add each side's own advantage
            # manually so two hosts meeting each get their bonus.
            l1_base, l2_base = lambdas(self.model, a, b, False, lh, la)
            l1 = l1_base * math.exp(ha)
            l2 = l2_base * math.exp(hb)
            hg, ag = sample_scores(l1, l2, self.model.rho, self.model.nb_r, 1, self.rng)
            i, j = int(hg[0]), int(ag[0])
            goals[a] += i
            goals[b] += j
            if i > j:
                return a
            if j > i:
                return b
            return a if random.random() < l1 / (l1 + l2) else b

        for no, (a, b) in teams_in.items():
            reached["r32"] |= {a, b}
            winners[no] = play_ko(a, b, 1)
        for rnd, stage, pairs in ((2, "r16", R16), (3, "qf", QF), (4, "sf", SF)):
            for no, m1, m2 in pairs:
                a, b = winners[m1], winners[m2]
                reached[stage] |= {a, b}
                winners[no] = play_ko(a, b, rnd)
        no, m1, m2 = FINAL
        a, b = winners[m1], winners[m2]
        reached["final"] |= {a, b}
        champ = play_ko(a, b, 5)
        reached["champion"] = {champ}
        return win, reached, dict(goals)

    def run(self) -> dict[str, Any]:
        stages = ["win_group", "r32", "r16", "qf", "sf", "final", "champion"]
        all_teams = sorted({t for g in self.groups for t in self.group_teams[g]})
        count = {t: dict.fromkeys(stages, 0) for t in all_teams}
        for s in range(self.n_sims):
            win, reached, _ = self.sim_tournament()
            for g in self.groups:
                count[win[g]]["win_group"] += 1
            for stage, ts in reached.items():
                for t in ts:
                    count[t][stage] += 1
            if s % 20000 == 19999:
                print(f"  {s + 1}/{self.n_sims} sims", flush=True)
        return {
            "method": (
                f"{self.n_sims} Monte Carlo tournaments; Dixon-Coles NB; "
                f"motivation reduction {MOTIVATION_REDUCTION:.0%} on MD3 when qualified; "
                f"lineup_mode=most_frequent_6mo"
            ),
            "teams": {
                t: {s: round(count[t][s] / self.n_sims, 4) for s in stages}
                for t in sorted(count, key=lambda x: -count[x]["champion"])
            },
        }


if __name__ == "__main__":
    sim = TournamentSimulator()
    out = sim.run()
    out_path = os.path.join(ROOT, "wc26_tournament_nb.json")
    json.dump(out, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
