"""API-Football data fetching, lineup caching, and travel/altitude helpers.

Lineup data sources (priority order)
------------------------------------
1. **API-Football** (RapidAPI / api-sports.io) — primary for historical lineups.
   - ``GET /fixtures/lineups?fixture={fixture_id}``
   - ``GET /fixtures?team={team_id}&from={date}&to={date}`` — enumerate fixtures
   - ``GET /fixtures?league={league_id}&season={year}`` — competition fixtures
   - League IDs: 1=World Cup, 4=Euro, 34=AFCON, 10=CONMEBOL WCQ, etc.
   - Response: ``startXI[].player.name``, ``startXI[].player.id``

2. **Fallback scraper** — when API quota is exhausted:
   - football-lineups.com or soccerway.com via requests + BeautifulSoup.

All fetched lineups are cached in SQLite ``lineups_cache.db`` keyed by
``(fixture_id, team_id)``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DB = os.path.join(ROOT, "lineups_cache.db")
BASE_URL = "https://v3.football.api-sports.io"

CITY_COUNTRY = {
    "Mexico City": "Mexico",
    "Guadalajara": "Mexico",
    "Monterrey": "Mexico",
    "Toronto": "Canada",
    "Vancouver": "Canada",
}

# International competition league IDs on API-Football
LEAGUE_IDS = {
    "world_cup": 1,
    "euro": 4,
    "afcon": 34,
    "conmebol_wcq": 10,
    "uefa_nations": 5,
    "friendly": 10,
}

# Team name -> API-Football search hints (name, acceptable API names)
TEAM_API_MAP: dict[str, tuple[str, set[str]]] = {
    "United States": ("USA", {"USA", "United States"}),
    "Canada": ("Canada", {"Canada"}),
    "Mexico": ("Mexico", {"Mexico"}),
    "Iran": ("Iran", {"Iran"}),
    "Belgium": ("Belgium", {"Belgium"}),
    "England": ("England", {"England"}),
    "France": ("France", {"France"}),
    "Germany": ("Germany", {"Germany"}),
    "Spain": ("Spain", {"Spain"}),
    "Brazil": ("Brazil", {"Brazil"}),
    "Argentina": ("Argentina", {"Argentina"}),
    "Japan": ("Japan", {"Japan"}),
    "South Korea": ("Korea", {"South Korea", "Korea Republic"}),
    "Morocco": ("Morocco", {"Morocco"}),
    "Netherlands": ("Netherlands", {"Netherlands"}),
    "Portugal": ("Portugal", {"Portugal"}),
    "Croatia": ("Croatia", {"Croatia"}),
    "Switzerland": ("Switzerland", {"Switzerland"}),
    "Senegal": ("Senegal", {"Senegal"}),
    "Australia": ("Australia", {"Australia"}),
    "Saudi Arabia": ("Saudi", {"Saudi Arabia"}),
    "Ecuador": ("Ecuador", {"Ecuador"}),
    "Uruguay": ("Uruguay", {"Uruguay"}),
    "Colombia": ("Colombia", {"Colombia"}),
    "Paraguay": ("Paraguay", {"Paraguay"}),
    "Ivory Coast": ("Ivory", {"Ivory Coast", "Côte d'Ivoire", "Cote D'Ivoire"}),
    "Tunisia": ("Tunisia", {"Tunisia"}),
    "Egypt": ("Egypt", {"Egypt"}),
    "Ghana": ("Ghana", {"Ghana"}),
    "Cameroon": ("Cameroon", {"Cameroon"}),
    "Nigeria": ("Nigeria", {"Nigeria"}),
    "Algeria": ("Algeria", {"Algeria"}),
    "South Africa": ("South Africa", {"South Africa"}),
    "DR Congo": ("Congo", {"Congo DR", "DR Congo", "Congo-DR"}),
    "Scotland": ("Scotland", {"Scotland"}),
    "Austria": ("Austria", {"Austria"}),
    "Turkey": ("Turk", {"Turkey", "Türkiye", "Turkiye"}),
    "Poland": ("Poland", {"Poland"}),
    "Denmark": ("Denmark", {"Denmark"}),
    "Serbia": ("Serbia", {"Serbia"}),
    "Norway": ("Norway", {"Norway"}),
    "Sweden": ("Sweden", {"Sweden"}),
    "Czech Republic": ("Czech", {"Czech Republic", "Czechia"}),
    "Ukraine": ("Ukraine", {"Ukraine"}),
    "Wales": ("Wales", {"Wales"}),
    "Panama": ("Panama", {"Panama"}),
    "Haiti": ("Haiti", {"Haiti"}),
    "Jamaica": ("Jamaica", {"Jamaica"}),
    "Costa Rica": ("Costa Rica", {"Costa Rica"}),
    "New Zealand": ("New Zealand", {"New Zealand"}),
    "Qatar": ("Qatar", {"Qatar"}),
    "Jordan": ("Jordan", {"Jordan"}),
    "Uzbekistan": ("Uzbekistan", {"Uzbekistan"}),
    "Iraq": ("Iraq", {"Iraq"}),
    "Bosnia and Herzegovina": ("Bosnia", {"Bosnia and Herzegovina", "Bosnia-Herzegovina"}),
    "Cape Verde": ("Cape Verde", {"Cape Verde"}),
    "Curacao": ("Curacao", {"Curaçao", "Curacao"}),
}


def _api_key(required: bool = False) -> str:
    load_dotenv(os.path.join(ROOT, ".env"))
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if not key:
        legacy = os.path.join(ROOT, ".api_football_key")
        if os.path.exists(legacy):
            key = open(legacy, encoding="utf-8").read().strip()
    if not key and required:
        raise RuntimeError(
            "Set API_FOOTBALL_KEY in .env (or legacy .api_football_key file)."
        )
    return key


def init_cache(db_path: str = CACHE_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lineups (
            fixture_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            team_name TEXT,
            match_date TEXT,
            players_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (fixture_id, team_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_ids (
            team_name TEXT PRIMARY KEY,
            api_team_id INTEGER NOT NULL,
            api_name TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fixtures (
            fixture_id INTEGER PRIMARY KEY,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_id INTEGER,
            away_id INTEGER,
            league_id INTEGER,
            venue TEXT,
            city TEXT
        )
        """
    )
    conn.commit()
    return conn


class APIFootballClient:
    """Thin wrapper around API-Football v3 with rate-limit handling."""

    def __init__(self, sleep_s: float = 0.25, db_path: str = CACHE_DB) -> None:
        self.sleep_s = sleep_s
        self.conn = init_cache(db_path)
        self.session = requests.Session()
        self._key = _api_key(required=False)
        if self._key:
            self.session.headers.update({"x-apisports-key": self._key})

    def _get(self, path: str, **params: Any) -> dict[str, Any] | None:
        if not self._key:
            return None
        url = f"{BASE_URL}/{path}"
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                errs = data.get("errors")
                if errs and (not isinstance(errs, list) or len(errs) > 0):
                    if isinstance(errs, dict) and ("rateLimit" in errs or "requests" in errs):
                        time.sleep(65)
                        continue
                    return None
                time.sleep(self.sleep_s)
                return data
            except requests.RequestException:
                time.sleep(10)
        return None

    def resolve_team_id(self, team_name: str) -> tuple[int | None, str | None]:
        row = self.conn.execute(
            "SELECT api_team_id, api_name FROM team_ids WHERE team_name = ?",
            (team_name,),
        ).fetchone()
        if row:
            return row[0], row[1]
        hints = TEAM_API_MAP.get(team_name, (team_name.split()[0], {team_name}))
        search, accept = hints
        data = self._get("teams", search=search)
        if not data:
            return None, None
        accept_lower = {a.lower() for a in accept}
        nationals = [t["team"] for t in data["response"] if t["team"].get("national")]
        for t in nationals:
            if t["name"].lower() in accept_lower:
                self.conn.execute(
                    "INSERT OR REPLACE INTO team_ids VALUES (?, ?, ?)",
                    (team_name, t["id"], t["name"]),
                )
                self.conn.commit()
                return t["id"], t["name"]
        if len(nationals) == 1:
            t = nationals[0]
            self.conn.execute(
                "INSERT OR REPLACE INTO team_ids VALUES (?, ?, ?)",
                (team_name, t["id"], t["name"]),
            )
            self.conn.commit()
            return t["id"], t["name"]
        return None, None

    def get_cached_lineup(self, fixture_id: int, team_id: int) -> list[str] | None:
        row = self.conn.execute(
            "SELECT players_json FROM lineups WHERE fixture_id = ? AND team_id = ?",
            (fixture_id, team_id),
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def cache_lineup(
        self,
        fixture_id: int,
        team_id: int,
        team_name: str,
        match_date: str,
        players: list[str],
        source: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO lineups
            (fixture_id, team_id, team_name, match_date, players_json, fetched_at, source)
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
            """,
            (fixture_id, team_id, team_name, match_date, json.dumps(players), source),
        )
        self.conn.commit()

    def fetch_lineup_api(self, fixture_id: int, team_id: int) -> list[str] | None:
        cached = self.get_cached_lineup(fixture_id, team_id)
        if cached:
            return cached
        data = self._get("fixtures/lineups", fixture=fixture_id)
        if not data:
            return self._fetch_lineup_scraper(fixture_id, team_id)
        for block in data.get("response", []):
            if block["team"]["id"] != team_id:
                continue
            players = [p["player"]["name"] for p in block.get("startXI", [])]
            if len(players) >= 11:
                self.cache_lineup(
                    fixture_id,
                    team_id,
                    block["team"]["name"],
                    "",
                    players[:11],
                    "api-football",
                )
                return players[:11]
        return self._fetch_lineup_scraper(fixture_id, team_id)

    def _fetch_lineup_scraper(self, fixture_id: int, team_id: int) -> list[str] | None:
        """Fallback scraper when API quota is exhausted (best-effort)."""
        url = f"https://www.football-lineups.com/match/{fixture_id}/"
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            tables = soup.select("table.lineup")
            for table in tables:
                names = [a.get_text(strip=True) for a in table.select("a.player")]
                if len(names) >= 11:
                    self.cache_lineup(fixture_id, team_id, "", "", names[:11], "scraper")
                    return names[:11]
        except Exception:
            return None
        return None

    def team_fixtures(
        self,
        team_name: str,
        days_back: int = 180,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        """International fixtures for a team in the last ``days_back`` days."""
        as_of = as_of or date.today()
        start = (as_of - timedelta(days=days_back)).isoformat()
        end = as_of.isoformat()
        team_id, _ = self.resolve_team_id(team_name)
        if team_id is None:
            return []
        data = self._get("fixtures", team=team_id, **{"from": start, "to": end})
        if not data:
            return []
        finished = {"FT", "AET", "PEN", "AWD", "WO"}
        fixtures = []
        for fx in data.get("response", []):
            if fx["fixture"]["status"]["short"] not in finished:
                continue
            fixtures.append(
                {
                    "fixture_id": fx["fixture"]["id"],
                    "date": fx["fixture"]["date"][:10],
                    "home": fx["teams"]["home"]["name"],
                    "away": fx["teams"]["away"]["name"],
                    "home_id": fx["teams"]["home"]["id"],
                    "away_id": fx["teams"]["away"]["id"],
                    "venue": fx["fixture"].get("venue", {}).get("name", ""),
                    "city": fx["fixture"].get("venue", {}).get("city", ""),
                }
            )
        return fixtures

    def league_fixtures(self, league_id: int, season: int) -> list[dict[str, Any]]:
        data = self._get("fixtures", league=league_id, season=season)
        if not data:
            return []
        return [
            {
                "fixture_id": fx["fixture"]["id"],
                "date": fx["fixture"]["date"][:10],
                "home": fx["teams"]["home"]["name"],
                "away": fx["teams"]["away"]["name"],
                "home_id": fx["teams"]["home"]["id"],
                "away_id": fx["teams"]["away"]["id"],
            }
            for fx in data.get("response", [])
        ]

    def historical_lineups_for_team(
        self,
        team_name: str,
        days_back: int = 180,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch starting XIs for all recent international matches of a team."""
        team_id, _ = self.resolve_team_id(team_name)
        if team_id is None:
            return []
        records = []
        for fx in self.team_fixtures(team_name, days_back, as_of):
            is_home = fx["home_id"] == team_id
            opp_id = fx["away_id"] if is_home else fx["home_id"]
            lineup = self.fetch_lineup_api(fx["fixture_id"], team_id)
            if lineup:
                records.append(
                    {
                        "fixture_id": fx["fixture_id"],
                        "date": fx["date"],
                        "team": team_name,
                        "opponent": fx["away"] if is_home else fx["home"],
                        "is_home": is_home,
                        "lineup": lineup,
                    }
                )
        return records


# ---- Stadium altitude & travel distance ----

STADIUM_ALTITUDES_PATH = os.path.join(ROOT, "data", "stadium_altitudes.csv")

# Approximate city centroids (lat, lon) for travel distance
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Mexico City": (19.4326, -99.1332),
    "Guadalajara": (20.6597, -103.3496),
    "Monterrey": (25.6866, -100.3161),
    "Toronto": (43.6532, -79.3832),
    "Vancouver": (49.2827, -123.1207),
    "Los Angeles": (34.0522, -118.2437),
    "San Francisco Bay Area": (37.7749, -122.4194),
    "New York New Jersey": (40.7128, -74.0060),
    "Boston": (42.3601, -71.0589),
    "Houston": (29.7604, -95.3698),
    "Dallas": (32.7767, -96.7970),
    "Philadelphia": (39.9526, -75.1652),
    "Atlanta": (33.7490, -84.3880),
    "Seattle": (47.6062, -122.3321),
    "Miami": (25.7617, -80.1918),
    "Kansas City": (39.0997, -94.5786),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def load_stadium_altitudes(path: str = STADIUM_ALTITUDES_PATH) -> dict[str, float]:
    import csv

    out: dict[str, float] = {}
    if not os.path.exists(path):
        return out
    for row in csv.DictReader(open(path, encoding="utf-8")):
        name = row.get("stadium", row.get("venue", "")).strip()
        alt = float(row.get("altitude_m", row.get("altitude", 0)))
        if name:
            out[name.lower()] = alt
            if row.get("city"):
                out[row["city"].lower()] = alt
    return out


def lookup_altitude(
    venue: str,
    city: str = "",
    cache: dict[str, float] | None = None,
) -> float:
    """Resolve stadium altitude from bundled CSV or OpenElevation API fallback."""
    cache = cache or load_stadium_altitudes()
    for key in (venue.lower(), city.lower()):
        if key in cache:
            return cache[key]
    try:
        q = requests.get(
            "https://api.open-elevation.com/api/v1/lookup",
            params={"locations": city or venue},
            timeout=10,
        )
        if q.status_code == 200:
            results = q.json().get("results", [])
            if results:
                return float(results[0]["elevation"])
    except requests.RequestException:
        pass
    return 0.0


def travel_distance_km(city_a: str, city_b: str) -> float:
    if city_a == city_b:
        return 0.0
    ca, cb = CITY_COORDS.get(city_a), CITY_COORDS.get(city_b)
    if ca and cb:
        return haversine_km(ca[0], ca[1], cb[0], cb[1])
    return 500.0
