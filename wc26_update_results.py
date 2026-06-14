"""Refresh actual WC2026 results and grade the locked predictions.

Run any time during the tournament:
  python3 wc26_update_results.py

- Pulls all World Cup fixtures from API-Football (league 1, season 2026).
- Updates scores/status in fifa_world_cup_2026_group_matches.json.
- Fills actuals into wc26_predictions.json and recomputes accuracy:
  group 1X2 hit rate, exact scores, Brier score on the locked probabilities,
  per-stage overlap of predicted vs actual qualifiers, champion check.
Never touches the locked predictions themselves.
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(os.path.join(ROOT, ".api_football_key")).read().strip()

ALIAS = {
    "USA": "United States", "Korea Republic": "South Korea",
    "South Korea": "South Korea", "Türkiye": "Turkey", "Turkiye": "Turkey",
    "Congo DR": "DR Congo", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde Islands": "Cape Verde", "Côte d'Ivoire": "Ivory Coast",
    "Cote D'Ivoire": "Ivory Coast",
}
FINISHED = {"FT", "AET", "PEN"}
KO_ROUNDS = {  # API round name fragment -> stage key as in predictions file
    "round of 32": "r16",      # winners of R32 reach R16
    "round of 16": "qf",
    "quarter": "sf",
    "semi": "final",
}


def norm(name):
    return ALIAS.get(name, name)


def fetch_all():
    url = "https://v3.football.api-sports.io/fixtures?league=1&season=2026"
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["response"]


def main():
    fixtures = fetch_all()
    finished = [f for f in fixtures
                if f["fixture"]["status"]["short"] in FINISHED]
    print(f"{len(fixtures)} WC fixtures known, {len(finished)} finished")

    # ---- refresh group matches file ----
    gm_path = f"{ROOT}/fifa_world_cup_2026_group_matches.json"
    gm = json.load(open(gm_path))
    by_id = {f["fixture"]["id"]: f for f in fixtures}
    for m in gm["matches"]:
        f = by_id.get(m["match_id"])
        if f:
            m["status"] = f["fixture"]["status"]["long"]
            if f["fixture"]["status"]["short"] in FINISHED:
                m["score"] = f"{f['goals']['home']}-{f['goals']['away']}"
    json.dump(gm, open(gm_path, "w"), indent=2, ensure_ascii=False)

    # ---- grade predictions ----
    pred_path = f"{ROOT}/wc26_predictions.json"
    if not os.path.exists(pred_path):
        print("no locked predictions file; run wc26_tournament.py first")
        return
    pred = json.load(open(pred_path))

    import math
    res_hit = score_hit = graded = mkt_n = 0
    briers = {"blend": 0.0, "model": 0.0, "market": 0.0}
    lls = {"blend": 0.0, "model": 0.0, "market": 0.0}
    for p in pred["group_matches"]:
        f = by_id.get(p["match_id"])
        if not f or f["fixture"]["status"]["short"] not in FINISHED:
            p.pop("actual_score", None)
            continue
        gh, ga = f["goals"]["home"], f["goals"]["away"]
        actual = "H" if gh > ga else "A" if ga > gh else "D"
        p["actual_score"] = f"{gh}-{ga}"
        p["actual_result"] = actual
        p["hit"] = p["pred_result"] == actual
        graded += 1
        res_hit += p["hit"]
        score_hit += p["pred_score"] == p["actual_score"]
        sources = {"blend": p["p"], "model": p.get("p_model")}
        if p.get("p_market"):
            tot = sum(p["p_market"].values())
            sources["market"] = {k: v / tot for k, v in p["p_market"].items()}
            mkt_n += 1
        for src, probs in sources.items():
            if not probs:
                continue
            briers[src] += sum((probs[k] - (1 if k == actual else 0)) ** 2
                               for k in ("H", "D", "A"))
            lls[src] -= math.log(max(probs[actual], 1e-9))

    # knockout: who actually reached each stage + champion
    actual_stages = {k: set() for k in ("r16", "qf", "sf", "final")}
    champion = None
    for f in finished:
        rnd = f["league"]["round"].lower()
        h, a = norm(f["teams"]["home"]["name"]), norm(f["teams"]["away"]["name"])
        winner = h if f["teams"]["home"].get("winner") else \
            a if f["teams"]["away"].get("winner") else None
        for frag, stage in KO_ROUNDS.items():
            if frag in rnd and winner:
                actual_stages[stage].add(winner)
        if "final" in rnd and "semi" not in rnd and "3rd" not in rnd \
                and "third" not in rnd and winner:
            champion = winner

    stage_acc = {}
    for stage, actual in actual_stages.items():
        if actual:
            predicted = set(pred["predicted_stage_teams"][stage])
            stage_acc[stage] = {
                "predicted_correct": len(predicted & actual),
                "of": len(predicted),
                "actual_so_far": len(actual),
            }

    pred["actuals"] = {
        "stages": {k: sorted(v) for k, v in actual_stages.items() if v},
        "champion": champion,
    }
    pred["accuracy"] = {
        "graded_group_matches": graded,
        "result_hits": res_hit,
        "result_pct": round(res_hit / graded, 4) if graded else None,
        "exact_score_hits": score_hit,
        "exact_score_pct": round(score_hit / graded, 4) if graded else None,
        "brier": round(briers["blend"] / graded, 4) if graded else None,
        "compare": ({src: {"brier": round(briers[src] / n, 4),
                           "logloss": round(lls[src] / n, 4)}
                     for src, n in (("blend", graded), ("model", graded),
                                    ("market", mkt_n)) if n}
                    if graded else None),
        "market_priced_matches": mkt_n,
        "stages": stage_acc,
        "champion_correct": (champion == pred["champion"]) if champion else None,
    }
    json.dump(pred, open(pred_path, "w"), indent=2, ensure_ascii=False)
    from wc26_simulate import save_versioned
    save_versioned(pred_path)
    acc = pred["accuracy"]
    if graded:
        print(f"graded {graded} group matches: "
              f"{res_hit} results ({acc['result_pct']:.0%}), "
              f"{score_hit} exact scores")
        for src, v in acc["compare"].items():
            print(f"  {src:7s} brier {v['brier']}  log-loss {v['logloss']}")
    else:
        print("no finished matches yet — nothing to grade")
    print("rebuild the site to refresh the Bracket page")


if __name__ == "__main__":
    main()
