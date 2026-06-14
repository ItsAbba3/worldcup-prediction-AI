"""Fetch Polymarket moneyline prices for all 72 WC2026 group fixtures.

Free Gamma API, no key. Event slug pattern: fifwc-{home}-{away}-{YYYY-MM-DD}
with lowercase FIFA trigrams. Falls back to public-search on slug miss.

Writes wc26_market_prices.json keyed by our match_id.
"""
import json
import os
import time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://gamma-api.polymarket.com"

FIFA_CODE = {
    "United States": "usa", "Canada": "can", "Mexico": "mex", "Panama": "pan",
    "Haiti": "hai", "Curaçao": "cuw", "Argentina": "arg", "Brazil": "bra",
    "Colombia": "col", "Uruguay": "uru", "Ecuador": "ecu", "Paraguay": "par",
    "Germany": "ger", "England": "eng", "France": "fra", "Spain": "esp",
    "Portugal": "por", "Netherlands": "ned", "Italy": "ita", "Belgium": "bel",
    "Austria": "aut", "Switzerland": "sui", "Turkey": "tur", "Norway": "nor",
    "Sweden": "swe", "Czech Republic": "cze", "Bosnia and Herzegovina": "bih",
    "Croatia": "cro", "Scotland": "sco", "Morocco": "mar", "Senegal": "sen",
    "Egypt": "egy", "Ivory Coast": "civ", "South Africa": "rsa",
    "DR Congo": "cod", "Tunisia": "tun", "Algeria": "alg", "Ghana": "gha",
    "Cape Verde": "cpv", "Japan": "jpn", "South Korea": "kor", "Iran": "irn",
    "Australia": "aus", "Saudi Arabia": "ksa", "Uzbekistan": "uzb",
    "Jordan": "jor", "Qatar": "qat", "Iraq": "irq", "New Zealand": "nzl",
}


def get(path, **q):
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "wc26-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# Polymarket question-text spellings that differ from ours
ALIASES = {
    "Turkey": ("türkiye", "turkiye", "turkey"),
    "South Korea": ("south korea", "korea republic"),
    "Ivory Coast": ("côte d'ivoire", "cote d'ivoire", "ivory coast"),
    "Czech Republic": ("czechia", "czech republic"),
    "Iran": ("ir iran", "iran"),
    "United States": ("united states", "usa"),
    "Bosnia and Herzegovina": ("bosnia",),
    "Curaçao": ("curaçao", "curacao"),
    "DR Congo": ("dr congo", "congo dr"),
}


def names_for(team):
    return ALIASES.get(team, (team.lower(),))


def parse_event(ev, home, away):
    """Extract home/draw/away Yes-prices from an event's binary markets."""
    out = {}
    for mk in ev.get("markets", []):
        q = mk["question"].lower()
        try:
            prices = json.loads(mk["outcomePrices"])
            yes = float(prices[0])
        except (KeyError, ValueError, IndexError):
            continue
        if "draw" in q:
            out["draw"] = yes
        elif any(f"will {n} win" in q for n in names_for(home)):
            out["home"] = yes
        elif any(f"will {n} win" in q for n in names_for(away)):
            out["away"] = yes
    if {"home", "draw", "away"} <= out.keys():
        return {
            "moneyline": out,
            "slug": ev["slug"],
            "volume": round(float(ev.get("volume") or 0)),
            "liquidity": round(float(ev.get("liquidity") or 0)),
        }
    return None


def fetch_fixture(m):
    from datetime import date, timedelta
    home, away = m["home"], m["away"]
    day = date.fromisoformat(m["date_utc"][:10])
    # Polymarket slugs use the US-local match date, often UTC-1 day
    days = [str(day - timedelta(days=1)), str(day), str(day + timedelta(days=1))]
    for d in days:
        slug = f"fifwc-{FIFA_CODE[home]}-{FIFA_CODE[away]}-{d}"
        try:
            evs = get("/events", slug=slug)
            if evs:
                r = parse_event(evs[0], home, away)
                if r:
                    return r
        except Exception as e:
            print(f"  slug fetch failed {slug}: {e}", flush=True)
    # fallback: search by title
    try:
        res = get("/public-search", q=f"{home} vs {away}", limit_per_type=5)
        for ev in res.get("events", []):
            if ev.get("slug", "").startswith("fifwc-") and \
                    any(d in ev["slug"] for d in days):
                r = parse_event(ev, home, away)
                if r:
                    return r
    except Exception as e:
        print(f"  search failed {home} v {away}: {e}", flush=True)
    return None


def main():
    fixtures = json.load(
        open(f"{ROOT}/fifa_world_cup_2026_group_matches.json"))["matches"]
    out, misses = {}, []
    for m in fixtures:
        r = fetch_fixture(m)
        if r:
            out[str(m["match_id"])] = r
        else:
            misses.append(f"{m['home']} v {m['away']} {m['date_utc'][:10]}")
        time.sleep(0.15)
    json.dump({"fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "source": "Polymarket Gamma API", "prices": out},
              open(f"{ROOT}/wc26_market_prices.json", "w"), indent=2)
    from wc26_simulate import save_versioned
    save_versioned(f"{ROOT}/wc26_market_prices.json")
    print(f"got prices for {len(out)}/72 fixtures")
    if misses:
        print("missing:", "; ".join(misses))


if __name__ == "__main__":
    main()
