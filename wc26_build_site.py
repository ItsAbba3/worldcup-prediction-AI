"""Build the WC2026 Form Book static site from the two data JSONs.

Reads:  fifa_world_cup_2026.json, fifa_world_cup_2026_group_matches.json
Writes: wc26_site/  (index.html, matches.html, teams/*.html, matches/*.html, style.css)

Re-run after refreshing data; output is fully regenerated.
"""
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"   # served by GitHub Pages (main branch /docs)
BUILD_V = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")  # css cache-buster

teams_data = json.load(open(ROOT / "fifa_world_cup_2026.json"))
matches_data = json.load(open(ROOT / "fifa_world_cup_2026_group_matches.json"))
try:
    _sim = json.load(open(ROOT / "wc26_simulations.json"))
    SIMS, SIM_LOGLOSS = _sim["simulations"], _sim.get("backtest_logloss")
    SIM_AT = _sim.get("generated")
except FileNotFoundError:
    SIMS, SIM_LOGLOSS, SIM_AT = {}, None, None
try:
    _mkt = json.load(open(ROOT / "wc26_market_prices.json"))
    PRICES, PRICES_AT = _mkt["prices"], _mkt["fetched_at"]
except FileNotFoundError:
    PRICES, PRICES_AT = {}, None
try:
    TOURNEY = json.load(open(ROOT / "wc26_tournament.json"))["teams"]
except FileNotFoundError:
    TOURNEY = {}
try:
    PRED = json.load(open(ROOT / "wc26_predictions.json"))
except FileNotFoundError:
    PRED = None
try:
    AWARDS = json.load(open(ROOT / "wc26_awards.json"))
except FileNotFoundError:
    AWARDS = None

TEAMS = {t["country"]: t for t in teams_data["teams"]}
MATCHES = matches_data["matches"]

team_group = {}
for m in MATCHES:
    team_group[m["home"]] = m["group"]
    team_group[m["away"]] = m["group"]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("ç", "c")).strip("-")


def match_slug(m):
    return f"{slug(m['home'])}-vs-{slug(m['away'])}"


def fmt_date(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%-d %b %Y"), dt.strftime("%H:%M")


def stats(team):
    ms = team["last_10_matches"]
    w = sum(1 for m in ms if m["result"] == "W")
    d = sum(1 for m in ms if m["result"] == "D")
    l = sum(1 for m in ms if m["result"] == "L")
    gf = ga = o25 = btts = cs = 0
    for m in ms:
        f, a = (int(x) for x in m["score"].split("-"))
        gf += f
        ga += a
        if f + a > 2:
            o25 += 1
        if f > 0 and a > 0:
            btts += 1
        if a == 0:
            cs += 1
    n = len(ms) or 1
    return {
        "record": f"{w}–{d}–{l}",
        "gf_pg": gf / n, "ga_pg": ga / n,
        "cs": cs, "o25": o25, "btts": btts, "n": len(ms),
    }


def form_chips(team, count=5):
    chips = "".join(
        f'<i class="f {m["result"]}">{m["result"]}</i>'
        for m in team["last_10_matches"][:count]
    )
    tip = (f"last {count} internationals, most recent first — "
           "W win, D draw (incl. pen shoot-outs), L loss")
    return f'<span class="form" title="{tip}">{chips}</span>'


def team_link(name, depth=0):
    pre = "../" * depth
    t = TEAMS[name]
    return f'<a class="tlink" href="{pre}teams/{slug(name)}.html">{escape(name)}</a>'


def page(title, body, depth=0, crumb="", lang="en", rtl=False, alt_lang=None):
    pre = "../" * depth
    # our title= attrs become CSS tooltips (instant, styled, tap-friendly)
    body = body.replace(' title="', ' data-tip="')
    fa_font = ('<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;800&display=swap" rel="stylesheet">'
               if rtl else "")
    switcher = (f'<div class="langsw"><a href="{alt_lang[0]}">{alt_lang[1]}</a></div>'
                if alt_lang else "")
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{'rtl' if rtl else 'ltr'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · WC26 Form Book</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%23211d16'/%3E%3Cpath d='M8 4l3 2.2-1.1 3.6H6.1L5 6.2z' fill='%23f6f1e6'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
{fa_font}<link rel="stylesheet" href="{pre}style.css?v={BUILD_V}">
</head>
<body>
<header class="masthead">
  {switcher}
  <div class="kicker">The Form Book — research edition</div>
  <a class="wordmark" href="{pre}index.html">World&nbsp;Cup&nbsp;26</a>
  <nav><a href="{pre}index.html">Groups</a><span>·</span><a href="{pre}matches.html">Matches</a><span>·</span><a href="{pre}futures.html">Futures</a><span>·</span><a href="{pre}awards.html">Awards</a><span>·</span><a href="{pre}bracket.html">Bracket</a><span>·</span><a href="{pre}method.html">Method</a></nav>
</header>
{f'<div class="crumb">{crumb}</div>' if crumb else ''}
<main>
{body}
</main>
<footer>
  <p>Form chips read most-recent first. Stats computed over each team's last 10 completed internationals.</p>
  <p>Model run: {SIM_AT or "—"} · Polymarket snapshot: {PRICES_AT or "—"} · every run archived in runs/</p>
  <p>Data: API-Football · FIFA rankings 2026 · <a href="{pre}method.html">how this works</a> ·
  <a href="{pre}archive.html">previous versions</a> ·
  <a href="https://github.com/amirdaraee/world-cup-predictions">code on GitHub</a> ·
  personal research, verify before staking.</p>
</footer>
</body>
</html>"""


# ---------- index: group tables ----------
def build_index():
    groups = {}
    for name, g in team_group.items():
        groups.setdefault(g, []).append(name)

    cards = []
    for g in sorted(groups):
        rows = []
        for name in sorted(groups[g], key=lambda n: TEAMS[n]["fifa_ranking"]):
            t = TEAMS[name]
            host = ' <sup class="host">host</sup>' if t.get("host") else ""
            rows.append(
                f"<tr><td>{team_link(name)}{host}</td>"
                f'<td class="num">{t["fifa_ranking"]}</td>'
                f"<td>{form_chips(t)}</td></tr>"
            )
        cards.append(f"""<section class="group">
<h2><span>Group</span> {g}</h2>
<table>
<thead><tr><th>Team</th><th class="num" title="official FIFA ranking, 1 Apr 2026 — shown for orientation; the model does not use it">FIFA</th><th title="last 5 internationals, most recent first — W win, D draw (pens count as draws), L loss">Form</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>The twelve groups</h1>
<p class="standfirst">48 teams, seeded here by FIFA ranking. Click any team for its full dossier.</p>
<p class="fineprint">Form = results of the last five internationals, <b>most recent first</b>
(W win, D draw — penalty shoot-outs count as draws, L loss); the team page shows all ten with
opponents and competitions. Friendlies are included here but weigh less in the model.
The FIFA column is the official 1 April 2026 ranking, shown for orientation only —
the simulation rates teams purely from match results and disagrees in places (France is FIFA #1
but mid-pack by title odds; the model prefers recent goals to reputation). The <sup class="host">host</sup>
marker matters beyond ceremony: hosts get a fitted home-crowd boost (~+30% scoring) whenever they
play in their own country, which is most of their matches.</p>
<div class="groups">{''.join(cards)}</div>"""
    (OUT / "index.html").write_text(page("Groups", body))


# ---------- matches list ----------
def build_matches_list():
    by_day = {}
    for m in MATCHES:
        by_day.setdefault(m["date_utc"][:10], []).append(m)

    sections = []
    for day in sorted(by_day):
        date_label, _ = fmt_date(by_day[day][0]["date_utc"])
        rows = []
        for m in sorted(by_day[day], key=lambda x: x["date_utc"]):
            _, time_ = fmt_date(m["date_utc"])
            rows.append(f"""<tr>
<td class="num">{time_}</td>
<td><b class="gchip">{m['group']}</b></td>
<td class="fixture"><a href="matches/{match_slug(m)}.html">{escape(m['home'])} <em>v</em> {escape(m['away'])}</a></td>
<td class="venue">{escape(m['venue'])}, {escape(m['city'])}</td>
</tr>""")
        sections.append(f"""<section class="matchday">
<h2>{date_label}</h2>
<table>
<thead><tr><th class="num" title="kick-off time, UTC — 00:00-02:00 games are US/Mexico evenings">UTC</th><th title="group A-L">Grp</th><th>Fixture</th><th>Venue</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>Group stage — all 72 fixtures</h1>
<p class="standfirst">Every match links to a head-to-head card comparing both teams' last ten.</p>
<p class="fineprint">Kick-offs are UTC — the 00:00–02:00 oddities are evening games in US/Mexico time
zones, landing a calendar day later than the local date Polymarket uses in its market slugs.
On matchday 3 both games in a group kick off simultaneously (FIFA's anti-collusion rule since 1982),
so their in-play prices move together.</p>
{''.join(sections)}"""
    (OUT / "matches.html").write_text(page("Matches", body))


# ---------- team pages ----------
def last10_table(team):
    rows = []
    for m in team["last_10_matches"]:
        note = f' <small>({escape(m["note"])})</small>' if "note" in m else ""
        rows.append(f"""<tr>
<td class="num">{m['date']}</td>
<td>{escape(m['opponent'])}</td>
<td class="num">{m['home_away']}</td>
<td class="num score">{m['score']}</td>
<td><i class="f {m['result']}">{m['result']}</i>{note}</td>
<td class="comp">{escape(m['competition'])}</td>
</tr>""")
    return f"""<table class="last10">
<thead><tr><th class="num">Date</th><th>Opponent</th><th class="num" title="home or away, from this team's perspective">H/A</th><th class="num" title="goals for-against, from this team's perspective">Score</th><th title="result: W win, D draw (pens count as draws), L loss">Res</th><th>Competition</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def stat_strip(s):
    return f"""<dl class="stats">
<div><dt title="wins-draws-losses over the last 10 internationals">Record</dt><dd>{s['record']}</dd></div>
<div><dt title="goals scored per game, last 10">Goals / game</dt><dd>{s['gf_pg']:.1f}</dd></div>
<div><dt title="goals conceded per game, last 10">Conceded / game</dt><dd>{s['ga_pg']:.1f}</dd></div>
<div><dt title="games without conceding, last 10">Clean sheets</dt><dd>{s['cs']}/{s['n']}</dd></div>
<div><dt title="games with 3+ total goals — the standard totals betting line">Over 2.5</dt><dd>{s['o25']}/{s['n']}</dd></div>
<div><dt title="both teams scored — a standard prediction-market category">BTTS</dt><dd>{s['btts']}/{s['n']}</dd></div>
</dl>"""


def build_team_pages():
    for name, t in TEAMS.items():
        g = team_group.get(name, "?")
        fixtures = [m for m in MATCHES if name in (m["home"], m["away"])]
        fx_rows = []
        for m in sorted(fixtures, key=lambda x: x["date_utc"]):
            date_label, time_ = fmt_date(m["date_utc"])
            opp = m["away"] if m["home"] == name else m["home"]
            ha = "H" if m["home"] == name else "A"
            fx_rows.append(
                f'<tr><td class="num">{date_label} {time_}</td><td class="num">{ha}</td>'
                f'<td><a href="../matches/{match_slug(m)}.html">{escape(opp)}</a></td>'
                f'<td class="venue">{escape(m["venue"])}, {escape(m["city"])}</td></tr>'
            )
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
<p class="fineprint">Over 2.5 (three-plus total goals) and BTTS (both teams scored) are counted
here because they're the totals categories prediction markets actually trade. Caveat on the
last ten: a few teams padded theirs with friendlies against club or B-team opposition — those
rows say little, and the model's training data excludes non-international opponents entirely.
Matches decided on penalties are recorded as draws (with a note): that's how FIFA counts them
and how the model scores them.</p>
<h2>Last ten internationals</h2>
{last10_table(t)}
<h2>Group {g} fixtures</h2>
<table>
<thead><tr><th class="num">Kick-off (UTC)</th><th class="num">H/A</th><th>Opponent</th><th>Venue</th></tr></thead>
<tbody>{''.join(fx_rows)}</tbody>
</table>"""
        crumb = f'<a href="../index.html">Groups</a> / Group {g} / {escape(name)}'
        (OUT / "teams" / f"{slug(name)}.html").write_text(
            page(name, body, depth=1, crumb=crumb))


# ---------- match pages ----------
def compare_rows(h, a):
    sh, sa = stats(h), stats(a)
    rows = [
        ("FIFA ranking", f"#{h['fifa_ranking']}", f"#{a['fifa_ranking']}"),
        ("Form (last 5)", form_chips(h), form_chips(a)),
        ("Record (10)", sh["record"], sa["record"]),
        ("Goals / game", f"{sh['gf_pg']:.1f}", f"{sa['gf_pg']:.1f}"),
        ("Conceded / game", f"{sh['ga_pg']:.1f}", f"{sa['ga_pg']:.1f}"),
        ("Clean sheets", f"{sh['cs']}/10", f"{sa['cs']}/10"),
        ("Over 2.5 goals", f"{sh['o25']}/10", f"{sa['o25']}/10"),
        ("Both teams scored", f"{sh['btts']}/10", f"{sa['btts']}/10"),
    ]
    tips = {
        "FIFA ranking": "official FIFA ranking, 1 Apr 2026 — not used by the model",
        "Form (last 5)": "most recent first — W win, D draw, L loss",
        "Record (10)": "wins-draws-losses over the last 10 internationals",
        "Clean sheets": "games without conceding, of the last 10",
        "Over 2.5 goals": "games with 3+ total goals, of the last 10",
        "Both teams scored": "games where neither side kept a clean sheet, of the last 10",
    }
    return "".join(
        f'<tr><td class="cl">{l}</td><th title="{tips.get(k, "")}">{k}</th>'
        f'<td class="cr">{r}</td></tr>'
        for k, l, r in rows
    )


def pct(p):
    return f"{p * 100:.0f}¢"


def sim_section(m):
    sim = SIMS.get(str(m["match_id"]))
    if not sim:
        return ""
    ml = sim["moneyline"]
    hf = (f'<p class="meta center">Home-field advantage applied to {escape(sim["home_field"])}.</p>'
          if sim.get("home_field") else
          '<p class="meta center">Neutral venue — no home-field advantage.</p>')
    bar = f"""<div class="mlbar">
<span class="seg home" style="flex:{ml['home']:.4f}"><b>{escape(m['home'])}</b> {pct(ml['home'])}</span>
<span class="seg draw" style="flex:{ml['draw']:.4f}"><b>Draw</b> {pct(ml['draw'])}</span>
<span class="seg away" style="flex:{ml['away']:.4f}"><b>{escape(m['away'])}</b> {pct(ml['away'])}</span>
</div>"""
    t = sim["totals"]
    mkt = PRICES.get(str(m["match_id"]), {}).get("moneyline", {})
    rows = [
        (f"{m['home']} to win", ml["home"], mkt.get("home")),
        ("Draw", ml["draw"], mkt.get("draw")),
        (f"{m['away']} to win", ml["away"], mkt.get("away")),
        ("Over 1.5 goals", t["over_1.5"], None), ("Under 1.5 goals", 1 - t["over_1.5"], None),
        ("Over 2.5 goals", t["over_2.5"], None), ("Under 2.5 goals", 1 - t["over_2.5"], None),
        ("Over 3.5 goals", t["over_3.5"], None), ("Under 3.5 goals", 1 - t["over_3.5"], None),
        ("Both teams score — Yes", sim["btts"], None), ("Both teams score — No", 1 - sim["btts"], None),
        (f"{m['home']} −1.5 (win by 2+)", sim["spread"]["home_-1.5"], None),
        (f"{m['away']} −1.5 (win by 2+)", sim["spread"]["away_-1.5"], None),
    ]
    market_rows = []
    for k, v, price in rows:
        if price is not None:
            edge = (v - price) * 100
            cls = "pos" if edge >= 3 else "neg" if edge <= -3 else ""
            mkt_cell = f'<td class="num">{price * 100:.1f}¢</td>' \
                       f'<td class="num edge {cls}">{edge:+.1f}¢</td>'
        else:
            mkt_cell = '<td class="num dim">—</td><td class="num dim">—</td>'
        market_rows.append(
            f'<tr><td>{escape(k)}</td><td class="num">{v * 100:.1f}%</td>'
            f'<td class="num fair">{pct(v)}</td>{mkt_cell}</tr>')
    market_note = (f'<p class="meta center">Polymarket prices as of {PRICES_AT}. '
                   'Positive edge = model thinks Yes is underpriced.</p>'
                   if mkt else
                   '<p class="meta center">No Polymarket market listed for this fixture yet.</p>')
    scorelines = " · ".join(
        f"<b>{s['score']}</b> <small>{s['p'] * 100:.0f}%</small>" for s in sim["top_scores"])
    bt = f" · backtest log-loss {SIM_LOGLOSS} vs 1.046 baseline on 1,071 matches" if SIM_LOGLOSS else ""
    return f"""<section class="sim">
<h2>Simulation — fair prices vs market</h2>
<p class="fineprint">Fair price is the model's probability written in Polymarket cents — a 56¢
fair price means 56%, and a share bought below it profits on average <em>if the model is right</em>.
Edge = fair minus market: green means the market sells the outcome cheaper than the model values it.
xG here is Dixon-Coles expected goals from attack/defence ratings, not the shot-based xG of
broadcast graphics. Spread −1.5 = win by two or more clear goals.</p>
{hf}
<p class="meta center">Model expected goals: {escape(m['home'])} {sim['xg']['home']} — {sim['xg']['away']} {escape(m['away'])}</p>
{bar}
<table class="markets">
<thead><tr><th>Market</th><th class="num" title="model probability of this outcome">Probability</th><th class="num" title="the model probability written as a share price — buy below this and you profit on average if the model is right">Fair</th><th class="num" title="live Polymarket YES price at last snapshot">Polymarket</th><th class="num" title="fair minus market — positive (green) means the market sells it cheaper than the model values it">Edge</th></tr></thead>
<tbody>{''.join(market_rows)}</tbody>
</table>
{market_note}
<p class="scorelines">Most likely scorelines: {scorelines}</p>
<p class="modelnote">Dixon-Coles weighted Poisson · internationals 2018–2026, tuned
hyperparameters{bt}.
A market priced below fair is value <em>if you trust the model</em>; it knows nothing about
injuries, lineups or motivation.</p>
</section>"""


def build_match_pages():
    for m in MATCHES:
        h, a = TEAMS[m["home"]], TEAMS[m["away"]]
        date_label, time_ = fmt_date(m["date_utc"])
        score = f'<div class="bigscore">{m["score"]}</div>' if m["score"] else ""
        body = f"""<div class="card">
<p class="meta center">Group {m['group']} · Matchday {m['matchday']} · {date_label}, {time_} UTC<br>
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
<section><h2>{escape(m['home'])} — last ten</h2>{last10_table(h)}</section>
<section><h2>{escape(m['away'])} — last ten</h2>{last10_table(a)}</section>
</div>"""
        crumb = (f'<a href="../matches.html">Matches</a> / Matchday {m["matchday"]} / '
                 f'{escape(m["home"])} v {escape(m["away"])}')
        (OUT / "matches" / f"{match_slug(m)}.html").write_text(
            page(f"{m['home']} v {m['away']}", body, depth=1, crumb=crumb))


# ---------- futures page ----------
def build_futures():
    if not TOURNEY:
        return
    rows = []
    for name, p in TOURNEY.items():
        if name not in TEAMS:
            continue
        cells = "".join(
            f'<td class="num{" hot" if p[k] >= 0.5 else ""}">{p[k] * 100:.1f}%</td>'
            for k in ("win_group", "r32", "qf", "sf", "final", "champion"))
        rows.append(f'<tr><td>{team_link(name)}</td>'
                    f'<td><b class="gchip">{team_group.get(name, "?")}</b></td>{cells}</tr>')
    body = f"""<h1>Tournament futures</h1>
<p class="standfirst">100,000 Monte Carlo tournaments on a 200-model bootstrap ensemble,
using the official FIFA bracket.</p>
<p class="fineprint">Reach R32 is not the same as win group — eight third-placed teams advance
too, which is why mid-tier teams clear 70% there. Columns nest (champion ⊂ final ⊂ SF…), and
each column sums across all 48 teams to the slots available: 12 group wins, 2 finalists, 1 champion.
Read every percentage as a fair Polymarket price for that future. The ensemble matters: simulating
with 200 bootstrap refits instead of one model widens uncertainty and shaves points off the
favourite — that haircut is honesty, not noise. Anomalies are modelled too, as zero-mean
randomness with assumed magnitudes: a per-tournament form shock (injuries, chemistry) on every
team, knockout attrition (a 10% chance each tie leaves lasting damage — cards, knocks), and a
fatigue penalty after 120-minute matches. None of it favours anyone on average; all of it
favours outsiders, because chaos always does.</p>
<table class="futures">
<thead><tr><th>Team</th><th title="group A-L">Grp</th><th class="num" title="finish top of the group">Win group</th><th class="num" title="advance to the round of 32 — top two per group plus the eight best third-placed teams">Reach R32</th>
<th class="num" title="reach the quarter-finals">QF</th><th class="num" title="reach the semi-finals">SF</th><th class="num" title="reach the final">Final</th><th class="num" title="win the tournament — column sums to 100% across all teams">Champion</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""
    (OUT / "futures.html").write_text(page("Futures", body))


# ---------- bracket / predictions page ----------
def build_bracket():
    if not PRED:
        return
    acc = PRED.get("accuracy")
    if acc and acc.get("graded_group_matches"):
        st = "".join(
            f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in (
                ("Matches graded", acc["graded_group_matches"]),
                ("Results called", f"{acc['result_hits']} ({acc['result_pct'] * 100:.0f}%)"),
                ("Exact scores", acc["exact_score_hits"]),
                ("Brier (blend)", acc["brier"]),
            ))
        acc_html = f'<dl class="stats">{st}</dl>'
        if acc.get("compare"):
            comp_rows = "".join(
                f'<tr><td>{src.title()}</td>'
                f'<td class="num">{v["brier"]}</td>'
                f'<td class="num">{v["logloss"]}</td></tr>'
                for src, v in acc["compare"].items())
            acc_html += f"""<table class="ko">
<thead><tr><th>Probability source</th><th class="num" title="mean squared error of the probabilities — lower is better; guessing equally scores 0.667">Brier</th><th class="num" title="penalises confident wrong calls hardest — lower is better; guessing equally scores 1.099">Log-loss</th></tr></thead>
<tbody>{comp_rows}</tbody></table>
<p class="meta center">Lower is better — this settles whether the model, the market,
or the blend prices matches best (market graded on {acc['market_priced_matches']} priced matches).</p>"""
    else:
        acc_html = ('<p class="standfirst">No matches graded yet — run '
                    '<code>wc26_update_results.py</code> then rebuild once games finish.</p>')

    rounds = {}
    for k in PRED["knockout"]:
        rounds.setdefault(k["round"], []).append(k)
    ko_html = ""
    for rname in ("Round of 32", "Round of 16", "Quarter-final",
                  "Semi-final", "Third place", "Final"):
        if rname not in rounds:
            continue
        lines = "".join(
            f'<tr><td class="num">{k["match"]}</td>'
            f'<td>{team_link(k["team1"])} <em>v</em> {team_link(k["team2"])}</td>'
            f'<td class="pick">{escape(k["pick"])}</td>'
            f'<td class="num">{k["p_pick"] * 100:.0f}%</td></tr>'
            for k in rounds[rname])
        ko_html += f"""<section><h2>{rname}</h2>
<table class="ko"><thead><tr><th class="num" title="official FIFA match number">#</th><th>Tie (predicted)</th><th>Pick</th><th class="num" title="the model's own probability for its pick — 50% means a forced coin-flip call">Conf.</th></tr></thead>
<tbody>{lines}</tbody></table></section>"""

    gt_html = ""
    for g in sorted(PRED["group_tables"]):
        rows = "".join(
            f'<tr><td class="num">{i + 1}</td><td>{team_link(r["team"])}</td>'
            f'<td class="num">{r["xpts"]:.1f}</td></tr>'
            for i, r in enumerate(PRED["group_tables"][g]))
        gt_html += f"""<section class="group"><h2><span>Group</span> {g}</h2>
<table><thead><tr><th class="num">#</th><th>Team</th><th class="num">xPts</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""

    rows = []
    for p in sorted(PRED["group_matches"], key=lambda x: x["date_utc"]):
        if "actual_score" in p:
            mark = '<i class="f W">✓</i>' if p["hit"] else '<i class="f L">✗</i>'
            actual = f'<td class="num score">{p["actual_score"]}</td><td>{mark}</td>'
        else:
            actual = '<td class="num dim">—</td><td class="dim">—</td>'
        conf = p["p"][p["pred_result"]] * 100
        rows.append(
            f'<tr><td class="num">{p["date_utc"][:10]}</td>'
            f'<td><b class="gchip">{p["group"]}</b></td>'
            f'<td>{escape(p["home"])} <em>v</em> {escape(p["away"])}</td>'
            f'<td class="num score">{p["pred_score"]}</td>'
            f'<td class="num">{conf:.0f}%</td>{actual}</tr>')
    track_html = f"""<table>
<thead><tr><th class="num">Date</th><th title="group A-L">Grp</th><th>Fixture</th>
<th class="num" title="most likely exact score under the model">Pred</th><th class="num" title="probability of the predicted 1X2 result (market-blended)">Conf.</th><th class="num" title="filled in by wc26_update_results.py as games finish">Actual</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>"""

    body = f"""<h1>The predicted tournament</h1>
<p class="standfirst">Every match called in advance — locked {PRED['locked_at']},
graded against reality as results land. Picks are modal outcomes from the mean model;
the official FIFA bracket decides who meets whom.</p>
<div class="champ">Predicted champion: <b>{team_link(PRED['champion'])}</b></div>
<p class="fineprint">A locked bracket never updates — when reality diverges, the picks stay frozen,
because a prediction you can revise isn't a prediction. The Conf column is the model's own
probability for its pick: a 50% pick is a coin flip it was forced to call, so judge the model by
the scorecard's probability metrics, not the ✓/✗ column. Brier and log-loss score the
probabilities themselves (lower is better; guessing ⅓-⅓-⅓ scores 0.667 Brier, 1.099 log-loss) —
and the model/market/blend comparison is the real experiment here: it settles which forecaster
deserves your trust with actual match results.</p>
<h2>Scorecard</h2>
{acc_html}
{ko_html}
<h2>Predicted group tables</h2>
<div class="groups">{gt_html}</div>
<h2>Group-stage match tracker</h2>
{track_html}"""
    (OUT / "bracket.html").write_text(page("Bracket", body))


# ---------- awards page ----------
def fmt_cents(v):
    return f"{v * 100:.1f}¢" if v is not None else "—"


def build_awards():
    if not AWARDS:
        return

    def edge_cell(e):
        if e is None:
            return '<td class="num dim">—</td>'
        cls = "pos" if e >= 0.03 else "neg" if e <= -0.03 else ""
        return f'<td class="num edge {cls}">{e * 100:+.1f}¢</td>'

    boot_rows = "".join(
        f'<tr><td>{escape(b["player"])}</td><td>{team_link(b["team"])}</td>'
        f'<td class="num">{b["intl_goals_24_26"]}</td>'
        f'<td class="num">{b["exp_goals"]:.1f}</td>'
        f'<td class="num fair">{b["p_model"] * 100:.1f}¢</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td>{edge_cell(b["edge"])}</tr>'
        for b in AWARDS["golden_boot"][:20])
    nation_rows = "".join(
        f'<tr><td>{team_link(n["team"])}</td>'
        f'<td class="num">{n["exp_goals"]:.1f}</td>'
        f'<td class="num fair">{n["p_model"] * 100:.1f}¢</td>'
        f'<td class="num">{fmt_cents(n["market"])}</td>{edge_cell(n["edge"])}</tr>'
        for n in AWARDS["top_scorer_nation"][:12])
    glove_rows = "".join(
        f'<tr><td class="num">{i + 1}</td><td>{escape(g["player"])}</td>'
        f'<td>{team_link(g["team"])}</td>'
        f'<td class="num">{g["p_final"] * 100:.1f}%</td>'
        f'<td class="num">{g["conceded_pg"]:.2f}</td>'
        f'<td class="num">{fmt_cents(g.get("market"))}</td></tr>'
        for i, g in enumerate(AWARDS["golden_glove"][:12]))
    ball_rows = "".join(
        f'<tr><td>{escape(b["player"])}</td>'
        f'<td>{team_link(b["team"]) if b["team"] else "—"}</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td>'
        f'<td class="num">{b["team_champion_p"] * 100:.1f}%'
        f'</td></tr>' if b["team_champion_p"] is not None else
        f'<tr><td>{escape(b["player"])}</td><td>—</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td><td class="num dim">—</td></tr>'
        for b in AWARDS["golden_ball"][:12])

    body = f"""<h1>The honours board</h1>
<p class="standfirst">Golden Boot and top-scoring nation are modelled — each player's
goals simulated across the same 100,000 tournaments behind the Futures page, using his
share of his team's international goals since 2024. Glove and Ball are softer ground:
one is a labelled heuristic, the other pure market.</p>

<h2>Golden Boot — modelled</h2>
<p class="fineprint">xG (tourn.) is the player's expected tournament goals: his share of his
team's international goals since 2024, applied to his team's goal count in each simulated
tournament — so deep-run odds are baked in, and a striker on a likely semi-finalist beats an
equal scorer on a group-stage exit. The share is not adjusted for opposition quality, which is
why CONCACAF strikers rate high and the market disagrees. A "—" market means Polymarket simply
hasn't listed the player: the model's co-favourite is unpriced, which is either an oversight
or a verdict.</p>
<table class="ko">
<thead><tr><th>Player</th><th>Team</th><th class="num" title="international goals 2024-26, all competitions — the basis of his share of team goals">Intl goals 24–26</th>
<th class="num" title="expected tournament goals: his share applied to his team's goals across 100k simulated tournaments — deep runs included">xG (tourn.)</th><th class="num" title="probability of winning the Golden Boot, as a fair price">Model</th><th class="num" title="live Polymarket YES price">Polymarket</th><th class="num" title="model minus market — positive means underpriced">Edge</th></tr></thead>
<tbody>{boot_rows}</tbody></table>

<h2>Top scoring nation — modelled</h2>
<table class="ko">
<thead><tr><th>Team</th><th class="num">Exp. goals</th><th class="num">Model</th>
<th class="num">Polymarket</th><th class="num">Edge</th></tr></thead>
<tbody>{nation_rows}</tbody></table>

<h2>Golden Glove — heuristic lean</h2>
<p class="standfirst">Rank = P(reach final) × defensive record. Not a calibrated
probability; the market column is the bettable number.</p>
<table class="ko">
<thead><tr><th class="num" title="heuristic rank: reach-final probability x defensive record — not a calibrated probability">#</th><th>Keeper</th><th>Team</th><th class="num" title="team's probability of reaching the final (Glove winners almost always come from finalists)">P(final)</th>
<th class="num" title="team goals conceded per game, last 10">Conceded/g</th><th class="num" title="live Polymarket YES price">Polymarket</th></tr></thead>
<tbody>{glove_rows}</tbody></table>

<h2>Golden Ball — market only</h2>
<p class="standfirst">Best-player awards are voted, not scored; we show the market
with each candidate's team title odds for context.</p>
<table class="ko">
<thead><tr><th>Player</th><th>Team</th><th class="num">Polymarket</th>
<th class="num">Team champion (model)</th></tr></thead>
<tbody>{ball_rows}</tbody></table>
<p class="modelnote">{escape(AWARDS["method"])} Prices as of {AWARDS["prices_at"]}.</p>"""
    (OUT / "awards.html").write_text(page("Awards", body))


# ---------- methodology page ----------
def build_method():
    try:
        prm = json.load(open(ROOT / "wc26_params.json"))
        P = prm["params"]
    except FileNotFoundError:
        prm, P = {}, {}
    body = f"""<h1>How the numbers are made</h1>
<p class="standfirst">Everything on this site is generated by open code from public data —
no hand-picked scores, no vibes. The full pipeline is on
<a href="https://github.com/amirdaraee/world-cup-predictions">GitHub</a>; this page is the
plain-language tour.</p>

<h2>The data</h2>
<p>Three sources. <b>49,450 international matches since 1872</b> (the community-maintained
martj42 dataset) — the model trains on the <b>8,081 played since 2018</b>. Team form and
fixtures come from <b>API-Football</b>. Live market prices come from <b>Polymarket's</b> public
API. The training data was audited against the primary source: four wrong scores were found,
adjudicated, and patched (the corrections file and methodology are in the repo).</p>

<h2>The match model</h2>
<p>A <b>Dixon-Coles weighted Poisson</b> — the classic bookmaking model: every team gets an
attack and a defence rating fitted to who they scored against and conceded to, recent matches
counting more (half-life {P.get('half_life', '?')} days), friendlies down-weighted
(×{P.get('friendly_w', '?')}), thin-data teams shrunk toward average, and a low-score
correction (ρ={P.get('rho', '?')}) because real football produces more 0-0s and 1-1s than
independent Poissons admit. Hosts get a fitted home-crowd boost (~+30% scoring) when playing
in their own country. From two expected-goals numbers the model computes the <em>entire</em>
scoreline probability grid — every market on the match cards is an exact sum over it,
no sampling.</p>
<figure><img src="img/grid.svg" alt="Scoreline probability grid for Mexico v South Africa">
<figcaption>The actual fitted grid for the opening match (probabilities in %).
Moneyline = the green vs red triangles; over 2.5 = everything below the third
anti-diagonal; BTTS = everything outside row 0 and column 0.</figcaption></figure>
<p class="fineprint">Hyperparameters were not hand-picked: they were chosen by cross-validation
on four rolling 12-month windows, 4,228 held-out matches ({prm.get('tuned_on', '')}).
Validation log-loss <b>{prm.get('cv_logloss', '?')}</b> against a 1.046 always-guess-the-base-rates
baseline (lower is better; this is bookmaker-grade calibration for internationals).
Two ideas the data rejected along the way: capping blowout scorelines, and shorter memory.
Both lost on held-out matches — the tune log is in the repo.</p>

<h2>Market blending</h2>
<p>For group-match picks, model probabilities are blended with live Polymarket prices
(a log-opinion pool, 35% weight on the market) — the market knows about lineups and injuries
hours before any goals data can. The raw model is kept separate for edge-finding, and the
<a href="bracket.html">scorecard</a> grades <b>model, market, and blend independently</b> as
results arrive, so the tournament itself decides which forecaster deserves trust.</p>

<h2>The tournament simulation</h2>
<p><b>100,000 full tournaments per run</b> — about 10 million simulated matches — on the
official FIFA bracket, including the round-of-32 template and third-place allocation
constraints. Each simulated tournament draws one of <b>200 bootstrap-refitted models</b>
(so parameter uncertainty flows into the odds), plus zero-mean anomaly shocks: a per-team
tournament form shock (injuries, chemistry — σ=0.06 on scoring rates), knockout attrition
(10% chance per tie of lasting damage), and a fatigue penalty after 120-minute matches.
None of it favours anyone on average; all of it favours outsiders, because variance always
taxes the favourite.</p>
<p class="fineprint">Monte Carlo noise at this scale: a 16.6% championship estimate carries a
standard error of about ±0.12 percentage points. Verified empirically — two independent
100,000-tournament runs agreed on every favourite within 0.0–0.2pp. More simulations would not
change the numbers; every meaningful uncertainty lives in the model, not the dice.</p>

<h2>Player awards</h2>
<p>Golden Boot and top-scoring-nation odds are simulated on top of the same 100k tournaments:
each player's tournament goals are drawn from his share of his team's international goals
since 2024, applied to his team's goal count in each simulated run — so reaching a final
buys more chances to score. Shares are not opposition-adjusted (stated limitation).
Golden Ball and Glove have no calibrated model and are shown market-priced only.</p>

<h2>Accountability</h2>
<p>The complete bracket — all 72 group matches and every knockout round to the champion —
was <b>locked before the tournament</b> and is graded publicly as results land: result hit
rate, exact scores, and probability quality (Brier / log-loss) for model, market, and blend.
Every calculation run is archived with a timestamp. A prediction you can revise afterwards
isn't a prediction.</p>

<h2>The science, in more depth</h2>

<h3>Why Poisson?</h3>
<p>Goals are rare events: ~2.7 per 90 minutes, arriving in any minute with small, roughly
independent probability. Counting processes like that converge to the
<a href="https://en.wikipedia.org/wiki/Poisson_distribution"><b>Poisson
distribution</b></a> — one number, the rate λ ("expected goals"), determines the probability of
0, 1, 2… goals: P(k) = λᵏe^(−λ)/k!. So the whole model reduces to estimating two rates per
match. The rates come from a <b>log-linear model</b>: log λ<sub>home</sub> = μ + attack
<sub>home</sub> + defence<sub>away</sub> (+ home advantage) — additive on the log scale,
multiplicative on goals, which is why a strong attack against a leaky defence compounds.</p>
<figure><img src="img/poisson.svg" alt="Observed goals per team per match vs the Poisson distribution">
<figcaption>Why the assumption holds: goals per team per match across the 8,081 training
internationals (bars) against the Poisson curve at the same mean (dots).</figcaption></figure>

<h3>The Dixon-Coles correction</h3>
<p>Two independent Poissons slightly mispredict reality in one corner: real football produces
more 0-0 and 1-1 draws than independence allows (teams settle, sit deep, kill games).
Dixon &amp; Coles (1997) patched exactly the four low-score cells of the grid with one
correlation parameter ρ — ours is −0.05, fitted, modest. This 30-year-old model family is
still the backbone of professional odds compilation.</p>

<h3>Fitting: weighted maximum likelihood</h3>
<p><a href="https://en.wikipedia.org/wiki/Maximum_likelihood_estimation"><b>Maximum
likelihood</b></a> asks: which ratings make the observed 8,081 results least
surprising? Each match enters the likelihood with a weight: exponential <b>time decay</b>
(a result loses half its influence every 1,000 days — recency matters, but slowly for
national teams) and ×0.8 for friendlies. <b>Shrinkage</b> adds a few phantom "average"
matches to every team, pulling thin-data teams (Curaçao has far fewer internationals than
Brazil) toward the middle — the
<a href="https://en.wikipedia.org/wiki/Bias%E2%80%93variance_tradeoff">bias-variance
trade</a>: a slightly biased estimate beats a wildly noisy one.</p>
<figure><img src="img/decay.svg" alt="Exponential time-decay weighting curve">
<figcaption>How much a result counts in the fit, by age — the tuned 1,000-day half-life
means a 2023 thrashing still whispers, but recent form speaks.</figcaption></figure>

<h3>Honest validation: cross-validation and scoring rules</h3>
<p>A model graded on data it trained on flatters itself. We grade <b>out-of-sample</b>
(<a href="https://en.wikipedia.org/wiki/Cross-validation_(statistics)">cross-validation</a>):
fit on matches up to a cutoff, predict the next 12 months, repeat over four rolling windows
(4,228 held-out matches). Quality is measured with
<a href="https://en.wikipedia.org/wiki/Scoring_rule"><b>proper scoring rules</b></a> —
functions a forecaster can only optimise by reporting its true beliefs: <b>log-loss</b>
(−log of the probability given to what happened; brutal on confident errors) and the
<a href="https://en.wikipedia.org/wiki/Brier_score"><b>Brier score</b></a>
(mean squared error of probabilities). Ours: log-loss 0.891 vs 1.046 for always guessing
base rates. Accuracy percentages are <em>not</em> proper scores — a forecaster can game them
by always picking favourites — which is why the scorecard leads with Brier and log-loss.</p>
<figure><img src="img/calibration.svg" alt="Calibration curve on held-out matches">
<figcaption>Calibration on the held-out year: each dot is a probability bucket; on the
dashed diagonal, claimed confidence equals observed reality.</figcaption></figure>

<h3>Monte Carlo and the law of large numbers</h3>
<p>The tournament has no closed-form answer — group tiebreakers, third-place allocation and
bracket paths interact too messily. <a href="https://en.wikipedia.org/wiki/Monte_Carlo_method"><b>Monte Carlo</b></a>
sidesteps the math: simulate the whole tournament 100,000 times and count. The
<a href="https://en.wikipedia.org/wiki/Law_of_large_numbers"><b>law of large
numbers</b></a> guarantees the counts converge to the true model probabilities; at N=100,000 the standard error of a championship
estimate is √(p(1−p)/N) ≈ ±0.12pp. We verified it empirically: two independent runs agreed on
every favourite within 0.2pp.</p>

<h3>The bootstrap: knowing what we don't know</h3>
<p>One fitted model pretends its ratings are exact. They aren't — they're estimates from
finite data. The
<a href="https://en.wikipedia.org/wiki/Bootstrapping_(statistics)"><b>bootstrap</b></a>
measures that: re-weight the dataset at random
(each match's weight multiplied by an exponential draw), refit, repeat 200 times. The spread
of those 200 models <em>is</em> the parameter uncertainty, and every simulated tournament
draws one of them. Effect: favourites' odds shrink toward the field — overconfidence
removed before it costs money.</p>

<h3>Combining forecasters: the opinion pool</h3>
<p>The model and the market know different things (goals history vs lineups and news). The
<b>logarithmic opinion pool</b> — multiply the probabilities, each raised to a weight, then
renormalise — is the standard way to merge them: p ∝ p<sub>model</sub>^0.65 ·
p<sub>market</sub>^0.35. Unlike simple averaging it respects how probabilities compound, and
the weight is an explicit, testable choice: the scorecard grades model, market and blend
separately, so the data itself will tell us if 0.35 was wrong.</p>

<h2>Known blind spots</h2>
<p class="fineprint">No lineups, injuries or suspensions (the market blend carries those);
no weather or altitude terms (magnitudes unfittable from our data — treated as caution flags,
not model inputs); no within-match simulation (final scores only); anomaly magnitudes are
stated assumptions, not estimates; matchday-3 dead-rubber motivation is handled by manual
review, the way odds compilers do it. The model is a fair-value anchor, not an oracle.</p>

<p class="fineprint">این صفحه به فارسی هم در دسترس است —
<a href="method-fa.html">نسخهٔ فارسی</a>.</p>"""
    (OUT / "method.html").write_text(
        page("Method", body, alt_lang=("method-fa.html", "فارسی")))


def build_method_fa():
    body = '''<h1>اعداد چگونه ساخته می‌شوند</h1>
<p class="standfirst">همهٔ آنچه در این سایت می‌بینید با کدِ باز و داده‌های عمومی ساخته شده است؛
نه نتیجه‌ای که دستی انتخاب شده باشد و نه حاصل حدس و گمان. کد کامل پروژه روی
<a href="https://github.com/amirdaraee/world-cup-predictions">گیت‌هاب</a> در دسترس است.
این صفحه فقط توضیح می‌دهد که این اعداد از کجا می‌آیند و پشت صحنهٔ آن‌ها چه می‌گذرد.</p>

<h2>داده‌ها</h2>
<p>سه منبع داده داریم. مهم‌ترین آن‌ها مجموعهٔ متن‌باز martj42 است که ۴۹٬۴۵۰ بازی ملی از سال
۱۸۷۲ را در بر می‌گیرد. مدل روی ۸٬۰۸۱ بازیِ برگزارشده از سال ۲۰۱۸ به بعد آموزش می‌بیند.
فرم فعلی تیم‌ها و برنامهٔ مسابقات از API-Football می‌آیند و قیمت‌های لحظه‌ای بازار از
API عمومی پالی‌مارکت دریافت می‌شوند.</p>
<p>داده‌های آموزشی پیش از استفاده با منابع اصلی تطبیق داده شدند. در این فرایند چهار نتیجهٔ
اشتباه پیدا شد و اصلاح شد. فایل این اصلاحات نیز در مخزن پروژه موجود است.</p>

<h2>مدل بازی</h2>
<p>هستهٔ سیستم یک مدل پواسونِ وزن‌دار دیکسون–کولز است؛ همان مدلی که سال‌هاست در صنعت
شرط‌بندی و پیش‌بینی فوتبال استفاده می‌شود.</p>
<p>برای هر تیم دو عدد تخمین زده می‌شود: قدرت حمله و قدرت دفاع. این اعداد از روی کیفیت
حریفان و تعداد گل‌هایی که تیم مقابل آن‌ها زده یا خورده به دست می‌آیند. بازی‌های جدیدتر
اهمیت بیشتری دارند (نیمه‌عمر ۱۰۰۰ روز)، مسابقات دوستانه وزن کمتری می‌گیرند (×۰٫۸)،
و تیم‌هایی که دادهٔ کمی دارند بیش از حد از میانگین دور نمی‌شوند.</p>
<p>همچنین یک اصلاح برای نتایج کم‌گل (ρ=−۰٫۰۵) در نظر گرفته می‌شود، چون فوتبال واقعی بیشتر
از چیزی که دو پواسون مستقل پیش‌بینی می‌کنند به نتایجی مثل ۰-۰ و ۱-۱ ختم می‌شود. تیم‌های
میزبان نیز زمانی که در کشور خودشان بازی می‌کنند از مزیت زمین خانگی بهره می‌برند که
تقریباً معادل ۳۰ درصد افزایش در نرخ گل‌زنی است.</p>
<p>از روی دو مقدار «گل انتظاری»، مدل شبکهٔ کامل احتمال تمام نتایج ممکن را می‌سازد. تمام
بازارهای هر مسابقه مستقیماً از همین شبکه محاسبه می‌شوند و در این مرحله هیچ شبیه‌سازی‌ای
انجام نمی‌شود.</p>
<figure><img src="img/grid.svg" alt="شبکهٔ احتمال نتایج مکزیک و آفریقای جنوبی">
<figcaption>شبکهٔ واقعی برازش‌شده برای بازی افتتاحیه (احتمال‌ها به درصد). برد مکزیک =
خانه‌های سبز؛ تساوی = قطر کهربایی؛ برد آفریقای جنوبی = خانه‌های قرمز.</figcaption></figure>
<p class="fineprint">ابرپارامترها به‌صورت دستی انتخاب نشده‌اند. آن‌ها با اعتبارسنجی متقابل
روی چهار پنجرهٔ غلتان ۱۲ ماهه و ۴٬۲۲۸ بازی خارج از نمونه انتخاب شده‌اند. لگ‌لاس
اعتبارسنجی ۰٫۸۹۱۲۷ بود، در حالی که حدسِ همیشگی بر اساس نرخ پایه به ۱٫۰۴۶ می‌رسید
(عدد کمتر بهتر است). دو ایده نیز در آزمایش‌ها رد شدند: سقف‌گذاری روی بردهای پرگل و
استفاده از حافظهٔ کوتاه‌تر.</p>

<h2>ترکیب با بازار</h2>
<p>برای پیش‌بینی مسابقات مرحلهٔ گروهی، احتمال‌های مدل با قیمت‌های لحظه‌ای پالی‌مارکت
ترکیب می‌شوند (میانگین‌گیری لگاریتمی با وزن ۳۵ درصد برای بازار).</p>
<p>دلیل این کار ساده است: بازار معمولاً ساعت‌ها زودتر از آن‌که نتایج و داده‌های گل اثرشان
را نشان دهند، از ترکیب تیم‌ها، مصدومیت‌ها و اخبار باخبر می‌شود. در عین حال نسخهٔ خام مدل
نیز جداگانه نگه داشته می‌شود تا بتوان اختلاف آن با بازار را بررسی کرد و فرصت‌های
ارزش‌گذاری را پیدا کرد.</p>
<p>عملکرد مدل، بازار و نسخهٔ ترکیبی نیز به‌صورت جداگانه و با نتایج واقعی در
<a href="bracket.html">کارنامه</a> سنجیده می‌شود.</p>

<h2>شبیه‌سازی تورنمنت</h2>
<p>در هر اجرا، ۱۰۰٬۰۰۰ تورنمنت کامل ــ معادل حدود ۱۰ میلیون مسابقهٔ شبیه‌سازی‌شده ــ روی
براکت رسمی فیفا اجرا می‌شود. این شبیه‌سازی قالب دور ۳۲ تیمی و تمام محدودیت‌های مربوط به
جایگذاری تیم‌های سوم را نیز در نظر می‌گیرد.</p>
<p>هر تورنمنتِ شبیه‌سازی‌شده یکی از ۲۰۰ مدلِ بازنمونه‌گیری‌شده (Bootstrap) را انتخاب
می‌کند تا عدم‌قطعیت پارامترها نیز در احتمال‌ها منعکس شود. علاوه بر این، چند منبع تصادفی
با میانگین صفر وارد شبیه‌سازی می‌شوند: تغییر فرم تیم‌ها در طول تورنمنت (مصدومیت،
هماهنگی و عوامل مشابه ــ σ=۰٫۰۶)، فرسایش مراحل حذفی (۱۰ درصد احتمال آسیب ماندگار در هر
مسابقهٔ حذفی) و جریمهٔ خستگی پس از بازی‌های ۱۲۰ دقیقه‌ای.</p>
<p>هیچ‌کدام از این عوامل در میانگین به نفع تیم خاصی نیستند؛ اما در عمل معمولاً کمی به سود
تیم‌های کوچک‌تر تمام می‌شوند، چون اتفاقات غیرمنتظره معمولاً بخشی از برتری مدعیان را از
بین می‌برند.</p>

<h2>کمی علم: مفاهیم و اصطلاح‌ها</h2>

<h3>چرا پواسون؟</h3>
<p>گل یک رخداد نسبتاً کمیاب است: به‌طور متوسط حدود ۲٫۷ گل در هر ۹۰ دقیقه و در هر دقیقه با
احتمالی کوچک و تقریباً مستقل.</p>
<p>شمارش چنین رخدادهایی به
<a href="https://fa.wikipedia.org/wiki/توزیع_پواسون">توزیع پواسون</a> منجر می‌شود. در این
توزیع، یک عدد یعنی نرخ λ («گل انتظاری») برای تعیین کامل احتمال ۰، ۱، ۲ و تعداد بیشتری گل
کافی است. در نتیجه کل مسئله به تخمین دو نرخ برای هر مسابقه تقلیل پیدا می‌کند؛ نرخ‌هایی
که از یک مدل لگ-خطی به دست می‌آیند:</p>
<p>لگاریتم نرخ = پایه + قدرت حملهٔ تیم + ضعف دفاع حریف (+ مزیت میزبانی)</p>
<figure><img src="img/poisson.svg" alt="مقایسهٔ گل‌های واقعی با توزیع پواسون">
<figcaption>چرا این فرض درست است: توزیع گلِ هر تیم در هر بازی در ۸٬۰۸۱ مسابقهٔ آموزشی
(ستون‌ها) در برابر منحنی پواسون با همان میانگین (نقطه‌ها).</figcaption></figure>

<h3>تصحیح دیکسون–کولز</h3>
<p>دو پواسون مستقل در یک بخش مهم از واقعیت دچار خطا می‌شوند. فوتبال واقعی بیشتر از چیزی که
استقلال آماری پیش‌بینی می‌کند نتایج ۰-۰ و ۱-۱ تولید می‌کند، چون تیم‌ها گاهی بازی را
کنترل می‌کنند و ریسک را کاهش می‌دهند.</p>
<p>دیکسون و کولز در سال ۱۹۹۷ دقیقاً همین بخش کم‌گل جدول احتمالات را با یک پارامتر همبستگی
ρ اصلاح کردند. با وجود گذشت نزدیک به سه دهه، این خانواده از مدل‌ها هنوز یکی از پایه‌های
اصلی محاسبهٔ ضرایب حرفه‌ای فوتبال است.</p>

<h3>برازش: درست‌نمایی بیشینهٔ وزن‌دار</h3>
<p><a href="https://fa.wikipedia.org/wiki/برآورد_درست‌نمایی_بیشینه">درست‌نمایی بیشینه</a>
به این سؤال پاسخ می‌دهد: چه مجموعه‌ای از پارامترها نتایج مشاهده‌شده را کمترین میزان
غافلگیرکننده می‌کند؟</p>
<p>هر مسابقه با وزن خاص خود وارد مدل می‌شود: افت زمانی نمایی (هر نتیجه پس از ۱٬۰۰۰ روز نیمی
از اثر خود را از دست می‌دهد) و ضریب ×۰٫۸ برای مسابقات دوستانه.</p>
<figure><img src="img/decay.svg" alt="منحنی افت زمانی وزن نتایج">
<figcaption>سهم هر نتیجه در برازش بر حسب قدمت آن — با نیمه‌عمر ۱٬۰۰۰ روزه، نتایج قدیمی
زمزمه می‌کنند و فرم اخیر بلند حرف می‌زند.</figcaption></figure>
<p>انقباض (Shrinkage) نیز برای هر تیم چند مسابقهٔ خیالیِ «متوسط» اضافه می‌کند تا تیم‌هایی
که دادهٔ کمی دارند بیش از حد از میانگین فاصله نگیرند. این همان مصالحهٔ کلاسیک بین اریب و
واریانس است: یک برآورد کمی اریب معمولاً از یک برآورد پرنوسان بهتر عمل می‌کند.</p>

<h3>اعتبارسنجی صادقانه و قواعد نمره‌دهی</h3>
<p>مدلی که روی داده‌های آموزشی خودش ارزیابی شود، در واقع دارد خودش را فریب می‌دهد.</p>
<p>به همین دلیل ارزیابی خارج از نمونه
(<a href="https://fa.wikipedia.org/wiki/اعتبارسنجی_متقابل">اعتبارسنجی متقابل</a>)
انجام می‌شود: تا یک تاریخ مشخص مدل برازش می‌شود،
۱۲ ماه بعد پیش‌بینی می‌کند و این فرایند روی چهار پنجره تکرار می‌شود.</p>
<p>کیفیت پیش‌بینی‌ها با قواعد نمره‌دهی سَره سنجیده می‌شود؛ یعنی معیارهایی که فقط در صورت
بیان صادقانهٔ باور واقعی بهینه می‌شوند. لگ‌لاس (منفی لگاریتم احتمالی که به رخداد واقعی
داده شده) با پیش‌بینی‌های بیش‌ازحد مطمئن بسیار سخت‌گیرانه برخورد می‌کند. نمرهٔ برایر نیز
میانگین مربع خطای احتمال‌ها را اندازه می‌گیرد.</p>
<p>درصد «پیش‌بینی درست» یک معیار سَره نیست، چون با انتخاب همیشگی فاوریت می‌توان آن را
دستکاری کرد. به همین دلیل کارنامهٔ مدل با برایر و لگ‌لاس شروع می‌شود.</p>
<figure><img src="img/calibration.svg" alt="منحنی کالیبراسیون روی بازی‌های خارج از نمونه">
<figcaption>کالیبراسیون روی سالِ خارج از نمونه: هر نقطه یک دستهٔ احتمال است؛ روی قطرِ
خط‌چین، اطمینانِ ادعاشده با واقعیتِ مشاهده‌شده برابر است.</figcaption></figure>

<h3>مونت‌کارلو و قانون اعداد بزرگ</h3>
<p>برای یک تورنمنت راه‌حل بسته و فرمولی وجود ندارد. قوانین تساوی گروه‌ها، جایگذاری تیم‌های
سوم و مسیر براکت بیش از حد پیچیده و درهم‌تنیده‌اند.</p>
<p><a href="https://fa.wikipedia.org/wiki/روش_مونت-کارلو">روش مونت‌کارلو</a>
این مشکل را دور می‌زند: کل تورنمنت را ۱۰۰٬۰۰۰ بار شبیه‌سازی کن و نتایج را بشمار.</p>
<p><a href="https://fa.wikipedia.org/wiki/قانون_اعداد_بزرگ">قانون اعداد بزرگ</a>
تضمین می‌کند که این شمارش‌ها به احتمال واقعی مدل همگرا شوند. خطای
استاندارد برآورد شانس قهرمانی در این مقیاس حدود ±۰٫۱۲ واحد درصد است و در عمل نیز تأیید
شده است: دو اجرای مستقل برای همهٔ مدعیان کمتر از ۰٫۲ واحد درصد اختلاف داشتند.</p>

<h3>بوت‌استرپ: دانستنِ آنچه نمی‌دانیم</h3>
<p>یک مدلِ برازش‌شده ممکن است این تصور را ایجاد کند که پارامترهایش دقیق و قطعی‌اند. در
واقع این‌طور نیست؛ این پارامترها فقط برآوردهایی هستند که از داده‌ای محدود به دست
آمده‌اند.</p>
<p>بوت‌استرپ دقیقاً برای اندازه‌گیری همین عدم‌قطعیت به کار می‌رود: وزن مسابقات به‌صورت
تصادفی تغییر می‌کند، مدل دوباره برازش می‌شود و این فرایند ۲۰۰ بار تکرار می‌شود.</p>
<p>پراکندگی این ۲۰۰ مدل همان عدم‌قطعیت پارامترهاست و هر تورنمنتِ شبیه‌سازی‌شده یکی از
آن‌ها را انتخاب می‌کند. نتیجه این است که بخشی از اعتمادبه‌نفس بیش‌ازحد مدعیان حذف می‌شود
و احتمال‌ها واقع‌بینانه‌تر می‌شوند.</p>

<h3>ترکیب پیش‌بینی‌گرها: میانگین لگاریتمی</h3>
<p>مدل و بازار اطلاعات متفاوتی دارند. یکی تاریخچهٔ گل‌ها را می‌بیند و دیگری ترکیب‌ها،
مصدومیت‌ها و اخبار را.</p>
<p>میانگین لگاریتمی احتمال‌ها ــ یعنی ضرب احتمال‌ها با توان‌های وزنی و سپس نرمال‌سازی ــ
روش استاندارد ترکیب این منابع اطلاعاتی است.</p>
<p>وزن ۰٫۳۵ برای بازار نیز یک انتخاب شفاف و آزمون‌پذیر است. عملکرد هر سه نسخه ــ مدل،
بازار و ترکیب ــ جداگانه ثبت می‌شود تا خود داده‌ها نشان دهند این وزن انتخاب مناسبی بوده
است یا نه.</p>

<h2>پاسخ‌گویی</h2>
<p>براکت کامل ــ شامل هر ۷۲ مسابقهٔ مرحلهٔ گروهی و تمام مراحل حذفی تا تعیین قهرمان ــ پیش
از آغاز تورنمنت قفل می‌شود و با ثبت نتایج واقعی به‌صورت عمومی در
<a href="bracket.html">کارنامه</a> ارزیابی می‌شود.</p>
<p>هر اجرای محاسبات با مهر زمانی آرشیو می‌شود و نسخه‌های روزانهٔ سایت در بخش
<a href="archive.html">نسخه‌های قبلی</a> منجمد باقی می‌مانند.</p>
<p>پیش‌بینی‌ای که بتوان آن را بعداً تغییر داد، پیش‌بینی نیست.</p>

<h2>نقاط کور شناخته‌شده</h2>
<p class="fineprint">ترکیب بازیکنان، مصدومیت‌ها و محرومیت‌ها مستقیماً در مدل حضور ندارند؛
این اطلاعات از طریق بازار وارد می‌شوند. آب‌وهوا و ارتفاع زمین ضریب مستقلی ندارند، چون با
داده‌های موجود قابل برآورد نیستند و فقط به‌عنوان هشدار در نظر گرفته می‌شوند. شبیه‌سازی
درون‌بازی انجام نمی‌شود و فقط نتیجهٔ نهایی مدل‌سازی می‌شود. اندازهٔ شوک‌های تصادفی
فرض‌هایی اعلام‌شده هستند، نه پارامترهایی که از داده برآورد شده باشند. همچنین انگیزهٔ
تیم‌ها در مسابقات کم‌اهمیت هفتهٔ سوم مرحلهٔ گروهی با بازبینی دستی مدیریت می‌شود؛ تقریباً
همان روشی که بسیاری از محاسبه‌گرهای حرفه‌ای ضرایب از آن استفاده می‌کنند.</p>
<p>این مدل قرار نیست آینده را پیشگویی کند. هدفش ارائهٔ یک مبنای منصفانه و سازگار برای
ارزش‌گذاری احتمالات است.</p>'''
    (OUT / "method-fa.html").write_text(
        page("روش‌شناسی", body, lang="fa", rtl=True,
             alt_lang=("method.html", "English")))


# ---------- version archive ----------
def build_archive_index():
    arch = OUT / "archive"
    snaps = sorted([d.name for d in arch.iterdir() if d.is_dir()],
                   reverse=True) if arch.exists() else []
    if snaps:
        rows = "".join(
            f'<tr><td class="num">{len(snaps) - i}</td>'
            f'<td><a href="archive/{s}/index.html">{s}</a></td></tr>'
            for i, s in enumerate(snaps))
        table = f"""<table class="ko" style="max-width:420px">
<thead><tr><th class="num">#</th><th>Snapshot</th></tr></thead>
<tbody>{rows}</tbody></table>"""
    else:
        table = '<p class="standfirst">No snapshots yet — the first will be taken before kickoff.</p>'
    body = f"""<h1>Previous versions</h1>
<p class="standfirst">The model recalculates after every matchday, but predictions shouldn't
vanish when they age — each snapshot below is the complete site, frozen as it stood that day.
Compare any past view against what actually happened.</p>
<p class="fineprint">Snapshots are immutable copies (every page and stylesheet). The live site
always reflects the latest data; the locked bracket on the live site never changes by design —
what changes between versions are the simulations, prices, futures and award odds.</p>
{table}"""
    (OUT / "archive.html").write_text(page("Versions", body))


def take_snapshot():
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dst = OUT / "archive" / stamp
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for item in OUT.iterdir():
        if item.name == "archive":
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name)
        else:
            shutil.copy(item, dst / item.name)
    # banner on every archived page, linking back to the live site
    for f in dst.rglob("*.html"):
        depth = len(f.relative_to(dst).parts) - 1
        up = "../" * (2 + depth)
        banner = (f'<div class="snapnote">Snapshot of {stamp} — predictions as they '
                  f'stood then. <a href="{up}index.html">Back to the latest →</a></div>')
        f.write_text(f.read_text().replace("<body>", f"<body>\n{banner}", 1))
    print(f"snapshot frozen: docs/archive/{stamp}/")


CSS = """/* WC26 Form Book — editorial racing-form aesthetic */
:root {
  --paper: #f6f1e6;
  --paper-2: #efe8d8;
  --ink: #211d16;
  --ink-soft: #6b6353;
  --rule: #cfc4ab;
  --green: #14633f;
  --red: #a72a1e;
  --amber: #9a7b2d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  background-image: repeating-linear-gradient(0deg, transparent 0 2px, rgba(33,29,22,.012) 2px 4px);
  color: var(--ink);
  font: 15px/1.5 "IBM Plex Mono", monospace;
}
main { max-width: 1080px; margin: 0 auto; padding: 0 24px 48px; }
h1, h2, .wordmark, .versus h1 { font-family: "Fraunces", serif; }
h1 { font-size: 2.6rem; font-weight: 900; letter-spacing: -.02em; margin: 1.2rem 0 .4rem; }
h2 { font-size: 1.25rem; font-weight: 600; border-bottom: 2px solid var(--ink); padding-bottom: .25rem; margin: 2rem 0 .8rem; }
a { color: var(--green); text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }

/* masthead */
.masthead {
  text-align: center; padding: 26px 16px 14px;
  border-bottom: 3px double var(--ink); margin-bottom: 8px;
}
.kicker { font-size: .72rem; letter-spacing: .28em; text-transform: uppercase; color: var(--ink-soft); }
.wordmark {
  font-size: clamp(2.4rem, 6vw, 3.6rem); font-weight: 900; color: var(--ink);
  display: inline-block; line-height: 1; margin: 6px 0 10px; letter-spacing: -.03em;
}
.wordmark:hover { text-decoration: none; color: var(--green); }
.masthead nav { font-size: .85rem; text-transform: uppercase; letter-spacing: .18em; }
.masthead nav span { color: var(--rule); margin: 0 10px; }
.crumb { max-width: 1080px; margin: 10px auto 0; padding: 0 24px; font-size: .78rem; color: var(--ink-soft); }
.standfirst { color: var(--ink-soft); margin-top: 0; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th { font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--ink-soft); font-weight: 500; text-align: left; }
td, th { padding: .45rem .6rem .45rem 0; border-bottom: 1px solid var(--rule); vertical-align: baseline; }
tbody tr:hover { background: var(--paper-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.num { color: var(--ink-soft); }
.score { color: var(--ink) !important; font-weight: 600; }
.comp, .venue { color: var(--ink-soft); font-size: .78rem; }

/* form chips */
.form { display: inline-flex; gap: 3px; }
.f {
  font-style: normal; font-weight: 600; font-size: .68rem;
  width: 1.45em; height: 1.45em; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 2px; color: var(--paper);
}
.f.W { background: var(--green); }
.f.L { background: var(--red); }
.f.D { background: var(--amber); }

/* groups grid */
.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 28px 36px; margin-top: 24px; }
.group h2 { display: flex; align-items: baseline; gap: .5rem; font-size: 1.6rem; font-weight: 900; border-bottom: 2px solid var(--ink); }
.group h2 span { font-size: .7rem; font-family: "IBM Plex Mono", monospace; font-weight: 500; letter-spacing: .25em; text-transform: uppercase; color: var(--ink-soft); }
.group td:last-child, .group th:last-child { text-align: right; }
.tlink { color: var(--ink); font-weight: 600; }
.tlink:hover { color: var(--green); }
sup.host { color: var(--red); font-size: .62rem; letter-spacing: .08em; }

/* matchday sections */
.matchday h2 { font-size: 1.1rem; }
.fixture a { color: var(--ink); font-weight: 600; }
.fixture a:hover { color: var(--green); }
.fixture em { font-style: italic; color: var(--ink-soft); font-weight: 400; }
.gchip { font-size: .72rem; border: 1px solid var(--ink); padding: 0 .35em; border-radius: 2px; }

/* team page */
.teamhead { text-align: center; padding: 1rem 0 .5rem; }
.teamhead h1 { margin-bottom: .6rem; }
.meta { display: flex; gap: .5rem; justify-content: center; flex-wrap: wrap; margin: .4rem 0 .9rem; }
.meta.center { display: block; text-align: center; color: var(--ink-soft); font-size: .8rem; }
.chip { border: 1px solid var(--ink); border-radius: 999px; padding: .1em .8em; font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; }
.stats { display: flex; flex-wrap: wrap; gap: 0; border: 2px solid var(--ink); margin: 1.4rem 0; }
.stats div { flex: 1 1 110px; padding: .7rem .9rem; border-right: 1px solid var(--rule); text-align: center; }
.stats div:last-child { border-right: 0; }
.stats dt { font-size: .62rem; text-transform: uppercase; letter-spacing: .14em; color: var(--ink-soft); }
.stats dd { margin: .15rem 0 0; font-size: 1.25rem; font-weight: 600; font-family: "Fraunces", serif; }

/* match page */
.card { text-align: center; }
.versus { display: flex; align-items: baseline; justify-content: center; gap: 1.2rem; flex-wrap: wrap; margin: .6rem 0; }
.versus h1 { font-size: clamp(1.6rem, 4.5vw, 2.8rem); margin: 0; }
.versus h1 a { color: var(--ink); }
.versus h1 a:hover { color: var(--green); text-decoration: none; }
.versus .v { font-family: "Fraunces", serif; font-style: italic; color: var(--red); font-size: 1.4rem; }
.bigscore { font-family: "Fraunces", serif; font-size: 3rem; font-weight: 900; }
.compare { max-width: 640px; margin: 1.2rem auto 0; }
.compare th { text-align: center; font-size: .68rem; padding: .5rem; }
.compare .cl { text-align: right; font-weight: 600; width: 38%; }
.compare .cr { text-align: left; font-weight: 600; width: 38%; }
.compare td .form { vertical-align: middle; }
.twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; margin-top: 1rem; }
.twocol .comp { display: none; }
@media (max-width: 860px) { .twocol { grid-template-columns: 1fr; } }

footer { max-width: 1080px; margin: 0 auto; padding: 18px 24px 40px; border-top: 3px double var(--ink); font-size: .72rem; color: var(--ink-soft); }
footer p { margin: .2rem 0; }

/* mobile */
@media (max-width: 700px) {
  main { padding: 0 14px 40px; }
  .crumb { padding: 0 14px; }
  h1 { font-size: 1.9rem; }
  .wordmark { font-size: 2.1rem; }
  .masthead { padding: 18px 8px 10px; }
  .masthead nav { font-size: .66rem; letter-spacing: .03em; }
  .masthead nav span { margin: 0 4px; }
  table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .group table { display: table; }   /* narrow enough to render full-width */
  table { font-size: .78rem; }
  td, th { padding: .4rem .45rem .4rem 0; }
  td.num, th.num { white-space: nowrap; }
  .comp, .venue { white-space: nowrap; }
  .stats div { flex: 1 1 90px; padding: .5rem .4rem; }
  .stats dd { font-size: 1.05rem; }
  .mlbar .seg { font-size: .58rem; padding: .5em .15em; }
  .versus { gap: .6rem; }
  .versus .v { font-size: 1rem; }
  .bigscore { font-size: 2.2rem; }
  .champ { font-size: 1.15rem; padding: .6rem .8rem; }
  .fineprint { font-size: .72rem; }
  .twocol { gap: 20px; }
  .langsw { top: 8px; right: 8px; font-size: .72rem; }
  figure { margin: 1rem auto; }
  h3 { font-size: .95rem; }
}

/* simulation section */
.sim { max-width: 640px; margin: 2.5rem auto 0; }
.sim h2 { text-align: center; border-bottom: 2px solid var(--ink); }
.mlbar { display: flex; gap: 2px; margin: 1rem 0 1.2rem; border: 2px solid var(--ink); padding: 2px; }
.mlbar .seg {
  min-width: 0; overflow: hidden; white-space: nowrap; text-align: center;
  font-size: .72rem; padding: .55em .2em; color: var(--paper);
}
.mlbar .seg b { display: block; font-weight: 600; }
.mlbar .home { background: var(--green); }
.mlbar .draw { background: var(--amber); }
.mlbar .away { background: var(--red); }
.markets td.fair { font-weight: 600; }
.markets td.edge.pos { color: var(--green); font-weight: 600; }
.markets td.edge.neg { color: var(--red); font-weight: 600; }
.markets td.dim { color: var(--rule); }
.futures td.hot { color: var(--green); font-weight: 600; }
.champ { text-align: center; font-family: "Fraunces", serif; font-size: 1.5rem;
  border: 3px double var(--ink); padding: .8rem 1rem; margin: 1.2rem auto; max-width: 560px; }
.ko .pick { font-weight: 600; }
.ko em, .standfirst code { font-style: italic; color: var(--ink-soft); }
.scorelines { text-align: center; font-size: .85rem; }
.scorelines small { color: var(--ink-soft); }
.modelnote { font-size: .72rem; color: var(--ink-soft); text-align: center; max-width: 54ch; margin: 1.2rem auto 0; }
[data-tip]:not([data-tip=""]) {
  cursor: help; position: relative;
  text-decoration: underline dotted var(--ink-soft);
  text-underline-offset: 3px;
}
[data-tip]:not([data-tip=""]):hover::after {
  content: attr(data-tip);
  position: absolute; left: 0; top: calc(100% + 4px); z-index: 20;
  background: var(--ink); color: var(--paper);
  font: 400 .72rem/1.45 "IBM Plex Mono", monospace;
  text-transform: none; letter-spacing: 0; text-align: left;
  padding: .5em .75em; border-radius: 2px;
  width: max-content; max-width: 250px; white-space: normal;
  pointer-events: none;
}
th.num[data-tip]:hover::after, dt[data-tip]:hover::after { left: auto; right: 0; }
span.form[data-tip]:hover::after { left: auto; right: 0; }
.fineprint {
  font-size: .76rem; color: var(--ink-soft); line-height: 1.55;
  border-left: 3px solid var(--rule); padding-left: .9rem; margin: .4rem 0 1.4rem;
}
.snapnote {
  background: var(--amber); color: var(--paper); text-align: center;
  font-size: .78rem; padding: .5em 1em;
}
.snapnote a { color: var(--paper); font-weight: 600; text-decoration: underline; }
figure { margin: 1.3rem auto; text-align: center; }
figure img { width: 100%; max-width: 660px; height: auto; display: block;
  margin: 0 auto; border: 1px solid var(--rule); }
figcaption { font-size: .72rem; color: var(--ink-soft); margin: .35rem auto 0;
  max-width: 600px; text-align: center; }

/* language switcher + Farsi (RTL) */
.masthead { position: relative; }
.langsw { position: absolute; top: 14px; right: 18px; font-size: .8rem; }
.langsw a { border: 1px solid var(--ink); border-radius: 999px; padding: .15em .8em; color: var(--ink); }
.langsw a:hover { background: var(--ink); color: var(--paper); text-decoration: none; }
html[dir="rtl"] body, html[dir="rtl"] main, html[dir="rtl"] h1, html[dir="rtl"] h2,
html[dir="rtl"] h3, html[dir="rtl"] footer { font-family: "Vazirmatn", "IBM Plex Mono", sans-serif; }
html[dir="rtl"] h1 { font-weight: 800; letter-spacing: 0; }
html[dir="rtl"] h2, html[dir="rtl"] h3 { font-weight: 700; letter-spacing: 0; }
html[dir="rtl"] .fineprint { border-left: 0; border-right: 3px solid var(--rule);
  padding-left: 0; padding-right: .9rem; }
h3 { font-family: "Fraunces", serif; font-size: 1.02rem; font-weight: 600; margin: 1.4rem 0 .3rem; }
.sim .fineprint { margin-left: auto; margin-right: auto; }
"""

if OUT.exists():
    # keep the archive across rebuilds; regenerate everything else
    for item in OUT.iterdir():
        if item.name == "archive":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
(OUT / "teams").mkdir(parents=True, exist_ok=True)
(OUT / "matches").mkdir(exist_ok=True)
if (ROOT / "charts").exists():   # method-page charts (generated by wc26_charts.py)
    (OUT / "img").mkdir(exist_ok=True)
    for f in (ROOT / "charts").glob("*.svg"):
        shutil.copy(f, OUT / "img" / f.name)
(OUT / "style.css").write_text(CSS)
build_index()
build_matches_list()
build_team_pages()
build_match_pages()
build_futures()
build_bracket()
build_awards()
build_method()
build_method_fa()
build_archive_index()
if "snapshot" in sys.argv:
    take_snapshot()
    build_archive_index()   # live index now lists the new snapshot
n = len(list(OUT.glob("*.html"))) + len(list((OUT / "teams").glob("*.html"))) \
    + len(list((OUT / "matches").glob("*.html")))
snaps = len(list((OUT / "archive").iterdir())) if (OUT / "archive").exists() else 0
print(f"built {n} live pages in {OUT} ({snaps} archived snapshots)")
