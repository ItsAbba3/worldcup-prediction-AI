"""Build the WC2026 static site from match/team data + new NB simulator output.

Reads:  fifa_world_cup_2026.json
        fifa_world_cup_2026_group_matches.json
        wc26_tournament_nb.json   (output of simulator.py / TournamentSimulator.run())
        wc26_matches.json         (per-match NB simulation results, optional)
Writes: docs/  (index.html, matches.html, futures.html, teams/*.html, matches/*.html)

Usage:
    python wc26_build_site.py            # full rebuild
    python wc26_build_site.py snapshot   # rebuild + archive snapshot
"""

import json
import re
import shutil
import sys
from html import escape
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "docs"
BUILD_V = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")

# --- data loading ---

teams_data  = json.loads((ROOT / "fifa_world_cup_2026.json").read_text(encoding="utf-8"))
matches_data = json.loads((ROOT / "fifa_world_cup_2026_group_matches.json").read_text(encoding="utf-8"))

try:
    _t = json.loads((ROOT / "wc26_tournament_nb.json").read_text(encoding="utf-8"))
    TOURNEY   = _t.get("teams", {})
    TOURNEY_METHOD = _t.get("method", "")
    TOURNEY_AT = _t.get("generated_at", "")
except FileNotFoundError:
    TOURNEY, TOURNEY_METHOD, TOURNEY_AT = {}, "", ""

try:
    _m = json.loads((ROOT / "wc26_matches.json").read_text(encoding="utf-8"))
    MATCH_SIMS = {str(x["match_id"]): x for x in _m} if isinstance(_m, list) else _m
except FileNotFoundError:
    MATCH_SIMS = {}

TEAMS   = {t["country"]: t for t in teams_data["teams"]}
MATCHES = matches_data["matches"]

team_group: dict[str, str] = {}
for _m in MATCHES:
    team_group[_m["home"]] = _m["group"]
    team_group[_m["away"]] = _m["group"]

# --- helpers ---

def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("c\u0327", "c")).strip("-")

def match_slug(m: dict) -> str:
    return f"{slug(m['home'])}-vs-{slug(m['away'])}"

def fmt_date(iso: str) -> tuple[str, str]:
    dt = datetime.fromisoformat(iso)
    day = str(dt.day)          # no %-d (Linux only)
    return f"{day} {dt.strftime('%b %Y')}", dt.strftime("%H:%M")

def stats(team: dict) -> dict:
    ms = team.get("last_10_matches", [])
    w = d = l = gf = ga = o25 = btts = cs = 0
    for m in ms:
        r = m.get("result", "")
        if r == "W": w += 1
        elif r == "D": d += 1
        elif r == "L": l += 1
        f, a = (int(x) for x in m["score"].split("-"))
        gf += f; ga += a
        if f + a > 2: o25 += 1
        if f > 0 and a > 0: btts += 1
        if a == 0: cs += 1
    n = len(ms) or 1
    return {"record": f"{w}-{d}-{l}", "gf_pg": gf/n, "ga_pg": ga/n,
            "cs": cs, "o25": o25, "btts": btts, "n": len(ms)}

def form_chips(team: dict, count: int = 5) -> str:
    ms = team.get("last_10_matches", [])[:count]
    chips = "".join(f'<b class="f {m["result"]}">{m["result"]}</b>' for m in ms)
    return f'<span class="form">{chips}</span>'

def team_link(name: str, depth: int = 0) -> str:
    pre = "../" * depth
    return f'<a href="{pre}teams/{slug(name)}.html">{escape(name)}</a>'

def wt(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")

# --- HTML shell ---

def page(title: str, body: str, depth: int = 0, crumb: str = "", lang: str = "en") -> str:
    pre = "../" * depth
    body = body.replace(' title="', ' data-tip="')
    upd = TOURNEY_AT[:10] if TOURNEY_AT else "-"
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} - WC26 Predictions</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%23211d16'/%3E%3Cpath d='M8 4l3 2.2-1.1 3.6H6.1L5 6.2z' fill='%23f6f1e6'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,900&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{pre}style.css?v={BUILD_V}">
</head>
<body>
<header class="masthead">
  <div class="kicker">Dixon-Coles NB Model - 100k Simulations</div>
  <a class="wordmark" href="{pre}index.html">World Cup 26</a>
  <nav>
    <a href="{pre}index.html">Groups</a><span>.</span>
    <a href="{pre}matches.html">Matches</a><span>.</span>
    <a href="{pre}futures.html">Futures</a><span>.</span>
    <a href="{pre}method.html">Method</a>
  </nav>
</header>
{f'<div class="crumb">{crumb}</div>' if crumb else ''}
<main>
{body}
</main>
<footer>
  <p>Model: Dixon-Coles Negative Binomial with dynamic ratings, lineup OVR (EA FC 25), fatigue/rest covariate.</p>
  <p>Last simulation run: {upd} - 100,000 Monte Carlo tournaments.</p>
  <p>Data: martj42/international_results - API-Football - EA FC 25 via sofifa.com</p>
</footer>
</body>
</html>"""

# --- index: group tables ---

def build_index() -> None:
    groups: dict[str, list[str]] = {}
    for name, g in team_group.items():
        groups.setdefault(g, []).append(name)

    cards = []
    for g in sorted(groups):
        rows = []
        for name in sorted(groups[g], key=lambda n: TEAMS[n]["fifa_ranking"]):
            t = TEAMS[name]
            host = ' <sup class="host">host</sup>' if t.get("host") else ""
            champ = ""
            if TOURNEY and name in TOURNEY:
                pct = TOURNEY[name].get("champion", 0) * 100
                champ = f'<td class="num">{pct:.1f}%</td>'
            else:
                champ = '<td class="num dim">-</td>'
            rows.append(
                f"<tr><td>{team_link(name)}{host}</td>"
                f'<td class="num">{t["fifa_ranking"]}</td>'
                f"<td>{form_chips(t)}</td>"
                f"{champ}</tr>"
            )
        champ_th = '<th class="num" title="probability of winning the tournament">Champion</th>' if TOURNEY else ""
        cards.append(f"""<section class="group">
<h2><span>Group</span> {g}</h2>
<table>
<thead><tr><th>Team</th><th class="num" title="FIFA ranking Apr 2026">FIFA</th><th title="last 5 results, most recent first">Form</th>{champ_th}</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>The twelve groups</h1>
<p class="standfirst">48 teams across 12 groups. Click any team for its full dossier. Champion % from 100,000 simulated tournaments.</p>
<div class="groups">{''.join(cards)}</div>"""
    wt(OUT / "index.html", page("Groups", body))

# --- matches list ---

def build_matches_list() -> None:
    by_day: dict[str, list] = {}
    for m in MATCHES:
        by_day.setdefault(m["date_utc"][:10], []).append(m)

    sections = []
    for day in sorted(by_day):
        date_label, _ = fmt_date(by_day[day][0]["date_utc"])
        rows = []
        for m in sorted(by_day[day], key=lambda x: x["date_utc"]):
            _, time_ = fmt_date(m["date_utc"])
            sim = MATCH_SIMS.get(str(m.get("match_id", "")), {})
            prob_h = f'{sim["moneyline"]["home"]*100:.0f}%' if sim.get("moneyline") else "-"
            prob_d = f'{sim["moneyline"]["draw"]*100:.0f}%' if sim.get("moneyline") else "-"
            prob_a = f'{sim["moneyline"]["away"]*100:.0f}%' if sim.get("moneyline") else "-"
            rows.append(f"""<tr>
<td class="num">{time_}</td>
<td><b class="gchip">{m['group']}</b></td>
<td class="fixture"><a href="matches/{match_slug(m)}.html">{escape(m['home'])} v {escape(m['away'])}</a></td>
<td class="venue">{escape(m['venue'])}, {escape(m['city'])}</td>
<td class="num">{prob_h}</td><td class="num dim">{prob_d}</td><td class="num">{prob_a}</td>
</tr>""")
        sections.append(f"""<section class="matchday">
<h2>{date_label}</h2>
<table>
<thead><tr>
<th class="num">UTC</th><th>Grp</th><th>Fixture</th><th>Venue</th>
<th class="num">Home%</th><th class="num">Draw%</th><th class="num">Away%</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>Group stage - 72 fixtures</h1>
<p class="standfirst">All group matches with model win probabilities. Click any fixture for head-to-head stats.</p>
{''.join(sections)}"""
    wt(OUT / "matches.html", page("Matches", body))

# --- team pages ---

def last10_table(team: dict) -> str:
    rows = []
    for m in team.get("last_10_matches", []):
        note = f' <small>({escape(m["note"])})</small>' if "note" in m else ""
        rows.append(
            f'<tr><td class="num">{escape(m["date"])}</td>'
            f'<td class="venue">{escape(m.get("competition",""))}</td>'
            f'<td>{escape(m.get("opponent",""))}{note}</td>'
            f'<td class="num">{escape(m["score"])}</td>'
            f'<td><b class="f {m["result"]}">{m["result"]}</b></td></tr>'
        )
    return f"""<table>
<thead><tr><th class="num">Date</th><th>Competition</th><th>Opponent</th><th class="num">Score</th><th>Result</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""

def stat_strip(s: dict) -> str:
    items = [
        ("Record (10)", s["record"]),
        ("Goals/game", f"{s['gf_pg']:.1f}"),
        ("Conceded/game", f"{s['ga_pg']:.1f}"),
        ("Clean sheets", f"{s['cs']}/10"),
        ("Over 2.5", f"{s['o25']}/10"),
        ("BTTS", f"{s['btts']}/10"),
    ]
    cells = "".join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in items)
    return f'<dl class="stats">{cells}</dl>'

def build_team_pages() -> None:
    for name, t in TEAMS.items():
        g = team_group.get(name, "?")
        fixtures = [m for m in MATCHES if name in (m["home"], m["away"])]
        fx_rows = []
        for m in sorted(fixtures, key=lambda x: x["date_utc"]):
            date_label, time_ = fmt_date(m["date_utc"])
            opp = m["away"] if m["home"] == name else m["home"]
            ha = "H" if m["home"] == name else "A"
            fx_rows.append(
                f'<tr><td class="num">{date_label} {time_}</td>'
                f'<td class="num">{ha}</td>'
                f'<td><a href="../matches/{match_slug(m)}.html">{escape(opp)}</a></td>'
                f'<td class="venue">{escape(m["venue"])}, {escape(m["city"])}</td></tr>'
            )
        futures_html = ""
        if TOURNEY and name in TOURNEY:
            od = TOURNEY[name]
            stages = [
                ("Win group",  od.get("win_group", 0)),
                ("Reach R32",  od.get("r32", 0)),
                ("Quarter-final", od.get("qf", 0)),
                ("Semi-final", od.get("sf", 0)),
                ("Final",      od.get("final", 0)),
                ("Champion",   od.get("champion", 0)),
            ]
            cells = "".join(
                f'<div><dt>{k}</dt><dd class="{"hot" if v >= 0.5 else ""}">{v*100:.1f}%</dd></div>'
                for k, v in stages
            )
            futures_html = f'<h2>Tournament odds (100k simulations)</h2><dl class="stats futures-dl">{cells}</dl>'

        host = '<span class="chip">Host nation</span>' if t.get("host") else ""
        body = f"""<div class="teamhead">
<h1>{escape(name)}</h1>
<p class="meta">
<span class="chip">Group {g}</span>
<span class="chip">FIFA #{t['fifa_ranking']}</span>
<span class="chip">{t['confederation']}</span>
{host}
</p>
{form_chips(t, 10)}
</div>
{stat_strip(stats(t))}
{futures_html}
<h2>Last ten internationals</h2>
{last10_table(t)}
<h2>Group {g} fixtures</h2>
<table>
<thead><tr><th class="num">Kick-off (UTC)</th><th class="num">H/A</th><th>Opponent</th><th>Venue</th></tr></thead>
<tbody>{''.join(fx_rows)}</tbody>
</table>"""
        crumb = f'<a href="../index.html">Groups</a> / Group {g} / {escape(name)}'
        wt(OUT / "teams" / f"{slug(name)}.html", page(name, body, depth=1, crumb=crumb))

# --- match pages ---

def compare_rows(h: dict, a: dict) -> str:
    sh, sa = stats(h), stats(a)
    rows = [
        ("FIFA ranking",     f"#{h['fifa_ranking']}",    f"#{a['fifa_ranking']}"),
        ("Form (last 5)",    form_chips(h),               form_chips(a)),
        ("Record (10)",      sh["record"],                sa["record"]),
        ("Goals/game",       f"{sh['gf_pg']:.1f}",        f"{sa['gf_pg']:.1f}"),
        ("Conceded/game",    f"{sh['ga_pg']:.1f}",        f"{sa['ga_pg']:.1f}"),
        ("Clean sheets",     f"{sh['cs']}/10",            f"{sa['cs']}/10"),
        ("Over 2.5 goals",   f"{sh['o25']}/10",           f"{sa['o25']}/10"),
        ("Both teams score", f"{sh['btts']}/10",          f"{sa['btts']}/10"),
    ]
    return "".join(
        f'<tr><td class="cl">{l}</td><th>{k}</th><td class="cr">{r}</td></tr>'
        for k, l, r in rows
    )

def sim_section(m: dict) -> str:
    sim = MATCH_SIMS.get(str(m.get("match_id", "")))
    if not sim:
        return ""
    ml = sim["moneyline"]
    bar = f"""<div class="mlbar">
<span class="seg home" style="flex:{ml['home']:.4f}"><b>{escape(m['home'])}</b> {ml['home']*100:.0f}%</span>
<span class="seg draw" style="flex:{ml['draw']:.4f}"><b>Draw</b> {ml['draw']*100:.0f}%</span>
<span class="seg away" style="flex:{ml['away']:.4f}"><b>{escape(m['away'])}</b> {ml['away']*100:.0f}%</span>
</div>"""
    t = sim.get("totals", {})
    totals_rows = ""
    if t:
        totals_data = [
            (f"{m['home']} to win", ml["home"]),
            ("Draw",                ml["draw"]),
            (f"{m['away']} to win", ml["away"]),
            ("Over 1.5 goals",  t.get("over_1.5", 0)),
            ("Under 1.5 goals", 1 - t.get("over_1.5", 0)),
            ("Over 2.5 goals",  t.get("over_2.5", 0)),
            ("Under 2.5 goals", 1 - t.get("over_2.5", 0)),
            ("Over 3.5 goals",  t.get("over_3.5", 0)),
            ("Both teams score - Yes", sim.get("btts", 0)),
            ("Both teams score - No",  1 - sim.get("btts", 0)),
        ]
        totals_rows = "".join(
            f'<tr><td>{escape(k)}</td><td class="num">{v*100:.1f}%</td></tr>'
            for k, v in totals_data
        )
    scorelines = " - ".join(
        f"<b>{s['score']}</b> <small>{s['p']*100:.0f}%</small>"
        for s in sim.get("top_scores", [])
    )
    xg = sim.get("xg", {})
    hf_note = (f'Home-field advantage applied to {escape(sim["home_field"])}.'
               if sim.get("home_field") else "Neutral venue.")
    return f"""<section class="sim">
<h2>Model prediction</h2>
<p class="meta center">{hf_note}</p>
<p class="meta center">Expected goals: {escape(m['home'])} {xg.get('home','?')} - {xg.get('away','?')} {escape(m['away'])}</p>
{bar}
<table class="markets">
<thead><tr><th>Market</th><th class="num">Probability</th></tr></thead>
<tbody>{totals_rows}</tbody>
</table>
<p class="scorelines">Most likely scorelines: {scorelines}</p>
<p class="modelnote">Dixon-Coles Negative Binomial - dynamic ratings - lineup OVR (EA FC 25) - fatigue/rest covariate.</p>
</section>"""

def build_match_pages() -> None:
    for m in MATCHES:
        h, a = TEAMS[m["home"]], TEAMS[m["away"]]
        date_label, time_ = fmt_date(m["date_utc"])
        score = f'<div class="bigscore">{m["score"]}</div>' if m.get("score") else ""
        body = f"""<div class="card">
<p class="meta center">Group {m['group']} - Matchday {m['matchday']} - {date_label}, {time_} UTC<br>
{escape(m['venue'])}, {escape(m['city'])}</p>
<div class="versus">
<h1>{team_link(m['home'], 1)}</h1>
<span class="v">v</span>
<h1>{team_link(m['away'], 1)}</h1>
</div>
{score}
<table class="compare">{compare_rows(h, a)}</table>
</div>
{sim_section(m)}
<div class="twocol">
<section><h2>{escape(m['home'])} - last ten</h2>{last10_table(h)}</section>
<section><h2>{escape(m['away'])} - last ten</h2>{last10_table(a)}</section>
</div>"""
        crumb = (f'<a href="../matches.html">Matches</a> / Matchday {m["matchday"]} / '
                 f'{escape(m["home"])} v {escape(m["away"])}')
        wt(OUT / "matches" / f"{match_slug(m)}.html",
           page(f"{m['home']} v {m['away']}", body, depth=1, crumb=crumb))

# --- futures page ---

def build_futures() -> None:
    if not TOURNEY:
        wt(OUT / "futures.html", page("Futures", "<h1>Tournament futures</h1><p>Run TournamentSimulator and save wc26_tournament_nb.json first.</p>"))
        return
    rows = []
    for name, p in TOURNEY.items():
        if name not in TEAMS:
            continue
        g = team_group.get(name, "?")
        cells = "".join(
            f'<td class="num{"  hot" if p.get(k,0) >= 0.5 else ""}">{p.get(k,0)*100:.1f}%</td>'
            for k in ("win_group", "r32", "qf", "sf", "final", "champion")
        )
        rows.append(
            f'<tr><td>{team_link(name)}</td>'
            f'<td><b class="gchip">{g}</b></td>{cells}</tr>'
        )
    method_note = f'<p class="fineprint">{escape(TOURNEY_METHOD)}</p>' if TOURNEY_METHOD else ""
    body = f"""<h1>Tournament futures</h1>
<p class="standfirst">Probabilities from 100,000 Monte Carlo tournaments using the Dixon-Coles NB model with dynamic ratings, EA FC 25 lineup OVR, and fatigue/rest covariate.</p>
{method_note}
<p class="fineprint">Columns are nested: Champion is a subset of Final, Final of SF, and so on.
Win group = finish top of the group. Reach R32 = advance to the Round of 32 (top two per group
plus the eight best third-placed teams). Each column sums across all 48 teams to the available
slots: 12 group winners, 2 finalists, 1 champion.</p>
<table class="futures">
<thead><tr>
<th>Team</th><th title="group A-L">Grp</th>
<th class="num" title="finish top of the group">Win group</th>
<th class="num" title="advance to Round of 32">Reach R32</th>
<th class="num" title="reach quarter-finals">QF</th>
<th class="num" title="reach semi-finals">SF</th>
<th class="num" title="reach the final">Final</th>
<th class="num" title="win the tournament">Champion</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""
    wt(OUT / "futures.html", page("Futures", body))

# --- method page ---

def build_method() -> None:
    body = """<h1>How the model works</h1>
<p class="standfirst">Every number on this site is generated by open code from public data. No hand-picked scores, no gut feel.</p>

<h2>The data</h2>
<p><b>49,000+ international matches since 1872</b> (martj42 community dataset) - the model trains on
matches since 2018. Team form and fixtures from <b>API-Football</b>. Player ratings from <b>EA Sports FC 25</b> via sofifa.com.</p>

<h2>The match model</h2>
<p>A <b>Dixon-Coles Negative Binomial</b> model: every team gets an attack and defence rating
fitted to who they scored against and conceded to. Recent matches count more (exponential
time-weighting), friendlies are down-weighted (x0.6), thin-data teams are shrunk toward average,
and a low-score correction (Dixon-Coles rho) accounts for the real-world excess of 0-0 and 1-1 results.</p>

<p>On top of the base ratings, three covariates shift expected goals:</p>
<ul>
<li><b>Lineup OVR</b> - EA FC 25 average overall rating of the starting eleven. A 10-point gap shifts expected goals by ~20%.</li>
<li><b>Altitude and travel</b> - venue altitude and km traveled since last match penalize the away team.</li>
<li><b>Fatigue/rest days</b> - teams with fewer than 7 days rest since their last match receive a proportional scoring penalty (~4% per missing day).</li>
</ul>

<h2>Dynamic ratings</h2>
<p>After each historical match, prediction errors update per-team attack/defence state with a
learning rate of 0.15, decaying at 0.995 per match. This captures recent form shifts that
slow-moving MLE ratings miss - a team on a hot streak gets a boost, a team in poor form gets a penalty.</p>

<h2>The tournament simulation</h2>
<p><b>100,000 full tournaments per run</b> - about 7 million simulated matches - following the
official FIFA bracket including round-of-32 template and third-place allocation constraints.
Motivation dynamics are applied: teams that have already qualified on matchday 3 get a 15% intensity
reduction, and knockout matches get a small boost. Lineup OVRs are precomputed once per run for speed.</p>

<h2>Bug fixes vs the original</h2>
<p>The original open-source iterative fit had a self-reference bug in the denominator of the
Dixon-Coles update equations, causing attack/defence ratings to diverge to thousands after ~20
iterations (producing xG values in the millions). This has been corrected. Dynamic state updates
were also not being applied at prediction time - now fixed. The model is Negative Binomial
(dispersion parameter r=8) rather than Poisson, better handling overdispersion.</p>"""
    wt(OUT / "method.html", page("Method", body))

# --- CSS ---

CSS = """:root {
  --paper: #f6f1e6; --paper-2: #efe8d8; --ink: #211d16;
  --ink-soft: #6b6353; --rule: #cfc4ab;
  --green: #14633f; --red: #a72a1e; --amber: #9a7b2d;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.5 "IBM Plex Mono", monospace; }
main { max-width: 1080px; margin: 0 auto; padding: 0 24px 48px; }
h1, h2, .wordmark, .versus h1 { font-family: "Fraunces", serif; }
h1 { font-size: 2.4rem; font-weight: 900; letter-spacing: -.02em; margin: 1.2rem 0 .4rem; }
h2 { font-size: 1.2rem; font-weight: 600; border-bottom: 2px solid var(--ink); padding-bottom: .25rem; margin: 2rem 0 .8rem; }
a { color: var(--green); text-decoration: none; }
a:hover { text-decoration: underline; }
ul { padding-left: 1.5rem; }
li { margin-bottom: .4rem; }

.masthead { text-align: center; padding: 26px 16px 14px; border-bottom: 3px double var(--ink); margin-bottom: 8px; }
.kicker { font-size: .72rem; letter-spacing: .28em; text-transform: uppercase; color: var(--ink-soft); }
.wordmark { font-size: clamp(2rem,6vw,3.2rem); font-weight: 900; color: var(--ink); display: inline-block; line-height: 1; margin: 6px 0 10px; letter-spacing: -.03em; }
.wordmark:hover { text-decoration: none; color: var(--green); }
.masthead nav { font-size: .85rem; text-transform: uppercase; letter-spacing: .18em; }
.masthead nav span { color: var(--rule); margin: 0 10px; }
.crumb { max-width: 1080px; margin: 10px auto 0; padding: 0 24px; font-size: .78rem; color: var(--ink-soft); }
.standfirst { color: var(--ink-soft); margin-top: 0; }
.fineprint { font-size: .8rem; color: var(--ink-soft); }
footer { border-top: 1px solid var(--rule); max-width: 1080px; margin: 0 auto; padding: 20px 24px; font-size: .78rem; color: var(--ink-soft); }

table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th { font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--ink-soft); font-weight: 500; text-align: left; }
td, th { padding: .45rem .6rem .45rem 0; border-bottom: 1px solid var(--rule); vertical-align: baseline; }
tbody tr:hover { background: var(--paper-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.num { color: var(--ink-soft); }
.score { color: var(--ink) !important; font-weight: 600; }
.venue { color: var(--ink-soft); font-size: .78rem; }
.dim { opacity: .4; }
.hot { color: var(--green) !important; font-weight: 700; }

.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 24px; margin-top: 16px; }
.group h2 { font-size: 1rem; }
.gchip { display: inline-block; background: var(--ink); color: var(--paper); font-size: .7rem; padding: 1px 6px; border-radius: 3px; font-weight: 700; }
.host { font-size: .65rem; color: var(--amber); }
.chip { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; padding: 2px 8px; font-size: .78rem; margin-right: 6px; }

.form { display: inline-flex; gap: 3px; }
.f { display: inline-block; width: 20px; height: 20px; line-height: 20px; text-align: center; border-radius: 3px; font-size: .7rem; font-weight: 700; color: #fff; font-style: normal; }
.f.W { background: var(--green); }
.f.D { background: var(--amber); }
.f.L { background: var(--red); }

.stats { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.stats div { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 6px; padding: 8px 14px; min-width: 90px; }
.stats dt { font-size: .68rem; text-transform: uppercase; letter-spacing: .1em; color: var(--ink-soft); }
.stats dd { margin: 0; font-weight: 700; font-size: 1.1rem; }
.stats dd.hot { color: var(--green); }
.futures-dl { gap: 10px; }
.futures-dl div { min-width: 110px; }

.matchday { margin-bottom: 2rem; }
.fixture a { font-weight: 600; }

.teamhead { margin-bottom: 1.5rem; }
.teamhead h1 { margin-bottom: .3rem; }
.meta { font-size: .82rem; color: var(--ink-soft); }

.card { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 8px; padding: 20px; margin-bottom: 24px; }
.versus { display: flex; align-items: center; justify-content: center; gap: 24px; text-align: center; padding: 12px 0; }
.versus h1 { font-size: 1.6rem; margin: 0; }
.v { font-size: 1.4rem; color: var(--ink-soft); }
.bigscore { font-size: 2.5rem; font-weight: 900; text-align: center; letter-spacing: .05em; margin: 8px 0; }
.compare { font-size: .85rem; }
.compare .cl { text-align: right; color: var(--ink-soft); padding-right: 8px; }
.compare th { text-align: center; font-size: .82rem; text-transform: none; letter-spacing: 0; color: var(--ink); font-weight: 600; }
.compare .cr { color: var(--ink-soft); }

.sim { border: 1px solid var(--rule); border-radius: 8px; padding: 20px; margin-bottom: 24px; }
.mlbar { display: flex; border-radius: 6px; overflow: hidden; height: 44px; margin: 12px 0; }
.seg { display: flex; align-items: center; justify-content: center; font-size: .8rem; padding: 4px; text-align: center; color: #fff; }
.seg b { display: block; font-size: .9rem; }
.seg.home { background: var(--green); }
.seg.draw { background: var(--amber); }
.seg.away { background: var(--red); }
.markets { font-size: .83rem; }
.scorelines { font-size: .85rem; color: var(--ink-soft); margin-top: 12px; }
.modelnote { font-size: .75rem; color: var(--ink-soft); margin-top: 8px; }

.twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 24px; }
@media (max-width: 640px) { .twocol { grid-template-columns: 1fr; } .versus { flex-direction: column; gap: 8px; } }

.futures thead th { font-size: .7rem; }
.futures td, .futures th { padding: .35rem .5rem .35rem 0; }

[data-tip] { cursor: help; border-bottom: 1px dotted var(--rule); }
"""

# --- main ---

if OUT.exists():
    for item in OUT.iterdir():
        if item.name == "archive":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()

(OUT / "teams").mkdir(parents=True, exist_ok=True)
(OUT / "matches").mkdir(exist_ok=True)
wt(OUT / "style.css", CSS)

build_index()
build_matches_list()
build_team_pages()
build_match_pages()
build_futures()
build_method()

if "snapshot" in sys.argv:
    from datetime import date
    stamp = date.today().isoformat()
    dst = OUT / "archive" / stamp
    shutil.copytree(OUT, dst, ignore=shutil.ignore_patterns("archive"))
    print(f"snapshot saved: docs/archive/{stamp}/")

n = (len(list(OUT.glob("*.html")))
     + len(list((OUT / "teams").glob("*.html")))
     + len(list((OUT / "matches").glob("*.html"))))
print(f"Built {n} pages in {OUT}/")
