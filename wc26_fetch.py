"""Fetch last 10 matches for all WC2026 teams from API-Football (free tier).

Pro plan: 7500 req/day, 300 req/min. We make 49 search + 49 fixture calls.
Output: wc26_matches.json
"""
import json
import os
import time
import urllib.request
import urllib.parse

_DIR = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(os.path.join(_DIR, ".api_football_key")).read().strip()
BASE = "https://v3.football.api-sports.io"
SLEEP = 0.25

# (name in our JSON, search term, acceptable API team names)
TEAMS = [
    ("United States", "USA", {"USA", "United States"}),
    ("Canada", "Canada", {"Canada"}),
    ("Mexico", "Mexico", {"Mexico"}),
    ("Panama", "Panama", {"Panama"}),
    ("Honduras", "Honduras", {"Honduras"}),
    ("Jamaica", "Jamaica", {"Jamaica"}),
    ("Argentina", "Argentina", {"Argentina"}),
    ("Brazil", "Brazil", {"Brazil"}),
    ("Colombia", "Colombia", {"Colombia"}),
    ("Uruguay", "Uruguay", {"Uruguay"}),
    ("Ecuador", "Ecuador", {"Ecuador"}),
    ("Paraguay", "Paraguay", {"Paraguay"}),
    ("Venezuela", "Venezuela", {"Venezuela"}),
    ("Germany", "Germany", {"Germany"}),
    ("England", "England", {"England"}),
    ("France", "France", {"France"}),
    ("Spain", "Spain", {"Spain"}),
    ("Portugal", "Portugal", {"Portugal"}),
    ("Netherlands", "Netherlands", {"Netherlands"}),
    ("Italy", "Italy", {"Italy"}),
    ("Belgium", "Belgium", {"Belgium"}),
    ("Austria", "Austria", {"Austria"}),
    ("Switzerland", "Switzerland", {"Switzerland"}),
    ("Turkey", "Turk", {"Turkey", "Türkiye", "Turkiye"}),
    ("Poland", "Poland", {"Poland"}),
    ("Denmark", "Denmark", {"Denmark"}),
    ("Serbia", "Serbia", {"Serbia"}),
    ("Croatia", "Croatia", {"Croatia"}),
    ("Scotland", "Scotland", {"Scotland"}),
    ("Morocco", "Morocco", {"Morocco"}),
    ("Nigeria", "Nigeria", {"Nigeria"}),
    ("Senegal", "Senegal", {"Senegal"}),
    ("Egypt", "Egypt", {"Egypt"}),
    ("Ivory Coast", "Ivory", {"Ivory Coast", "Côte d'Ivoire", "Cote D'Ivoire"}),
    ("Cameroon", "Cameroon", {"Cameroon"}),
    ("South Africa", "South Africa", {"South Africa"}),
    ("DR Congo", "Congo", {"Congo DR", "DR Congo", "Congo-DR"}),
    ("Tunisia", "Tunisia", {"Tunisia"}),
    ("Mali", "Mali", {"Mali"}),
    ("Japan", "Japan", {"Japan"}),
    ("South Korea", "Korea", {"South Korea", "Korea Republic"}),
    ("Iran", "Iran", {"Iran"}),
    ("Australia", "Australia", {"Australia"}),
    ("Saudi Arabia", "Saudi", {"Saudi Arabia"}),
    ("Uzbekistan", "Uzbekistan", {"Uzbekistan"}),
    ("Jordan", "Jordan", {"Jordan"}),
    ("Qatar", "Qatar", {"Qatar"}),
    ("New Zealand", "New Zealand", {"New Zealand"}),
]


def api(path, **params):
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            errs = data.get("errors")
            if errs and (not isinstance(errs, list) or len(errs) > 0):
                print(f"  API error on {path} {params}: {errs}", flush=True)
                if isinstance(errs, dict) and ("rateLimit" in errs or "requests" in errs):
                    time.sleep(65)
                    continue
                return None
            return data
        except Exception as e:
            print(f"  HTTP error on {path} {params}: {e}", flush=True)
            time.sleep(10)
    return None


def find_team_id(search, accept):
    data = api("teams", search=search)
    if not data:
        return None, None
    accept_lower = {a.lower() for a in accept}
    nationals = [t["team"] for t in data["response"] if t["team"].get("national")]
    for t in nationals:
        if t["name"].lower() in accept_lower:
            return t["id"], t["name"]
    if len(nationals) == 1:
        return nationals[0]["id"], nationals[0]["name"]
    return None, None


FINISHED = {"FT", "AET", "PEN", "AWD", "WO"}


def parse_fixtures(data, team_id):
    matches = []
    for fx in data["response"]:
        if fx["fixture"]["status"]["short"] not in FINISHED:
            continue
        if fx["goals"]["home"] is None or fx["goals"]["away"] is None:
            continue
        home, away = fx["teams"]["home"], fx["teams"]["away"]
        is_home = home["id"] == team_id
        us, them = (home, away) if is_home else (away, home)
        gf = fx["goals"]["home"] if is_home else fx["goals"]["away"]
        ga = fx["goals"]["away"] if is_home else fx["goals"]["home"]
        if us.get("winner") is True:
            result = "W"
        elif them.get("winner") is True:
            result = "L"
        else:
            result = "D"
        match = {
            "date": fx["fixture"]["date"][:10],
            "opponent": them["name"],
            "home_away": "H" if is_home else "A",
            "score": f"{gf}-{ga}",
            "result": result,
            "competition": fx["league"]["name"],
        }
        if fx["fixture"]["status"]["short"] == "PEN":
            pen = fx["score"]["penalty"]
            pf = pen["home"] if is_home else pen["away"]
            pa = pen["away"] if is_home else pen["home"]
            match["note"] = f"{'won' if result == 'W' else 'lost'} {pf}-{pa} on penalties"
        matches.append(match)
    matches.sort(key=lambda m: m["date"], reverse=True)
    return matches[:10]


def main():
    out = {}
    for i, (name, search, accept) in enumerate(TEAMS, 1):
        print(f"[{i}/{len(TEAMS)}] {name}: searching id...", flush=True)
        team_id, api_name = find_team_id(search, accept)
        time.sleep(SLEEP)
        if team_id is None:
            print(f"  !! could not resolve team id for {name}", flush=True)
            out[name] = {"error": "team id not found"}
            continue
        print(f"  id={team_id} ({api_name}); fetching last 10 fixtures...", flush=True)
        data = api("fixtures", team=team_id, last=15)
        time.sleep(SLEEP)
        if not data:
            out[name] = {"team_id": team_id, "error": "fixtures fetch failed"}
            continue
        out[name] = {"team_id": team_id, "matches": parse_fixtures(data, team_id)}
        # checkpoint so partial progress survives a crash
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wc26_matches.json"), "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
