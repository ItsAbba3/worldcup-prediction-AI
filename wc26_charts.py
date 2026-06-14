"""Generate the Method-page charts as static SVGs (pure stdlib).

  python3 wc26_charts.py   ->  charts/*.svg  (4 files)

Charts are committed and copied into docs/img/ by wc26_build_site.py.
Re-run after retuning or major data refreshes; they read real model data:
the fitted score grid, the actual backtest, the real goals histogram.
"""
import json
import math
from collections import Counter

from wc26_simulate import (ROOT, TODAY, SPLIT, params, load_matches, fit,
                           lambdas, score_grid, one_x_two, test_set)

INK = "#211d16"
PAPER = "#f6f1e6"
SOFT = "#6b6353"
RULE = "#cfc4ab"
GREEN = "#14633f"
RED = "#a72a1e"
AMBER = "#9a7b2d"
FONT = 'font-family="ui-monospace,Menlo,monospace"'

import os
os.makedirs(f"{ROOT}/charts", exist_ok=True)


def svg_open(w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="{PAPER}"/>')


def text(x, y, s, size=12, fill=INK, anchor="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" {FONT} {extra}>{s}</text>')


P = params()


# ---------------- 1. time-decay curve ----------------
def chart_decay():
    W, H = 640, 340
    L, R, T, B = 70, 20, 30, 50
    pw, ph = W - L - R, H - T - B
    days_max = 3000
    pts = []
    for d in range(0, days_max + 1, 25):
        w = 0.5 ** (d / P["half_life"])
        pts.append((L + pw * d / days_max, T + ph * (1 - w)))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    hx = L + pw * P["half_life"] / days_max
    hy = T + ph * 0.5
    s = svg_open(W, H)
    for frac in (0, .25, .5, .75, 1):
        y = T + ph * (1 - frac)
        s += f'<line x1="{L}" y1="{y}" x2="{W-R}" y2="{y}" stroke="{RULE}" stroke-width="1"/>'
        s += text(L - 8, y + 4, f"{frac:.2f}", 11, SOFT, "end")
    for yr in range(0, 9, 2):
        x = L + pw * (yr * 365) / days_max
        s += text(x, H - B + 18, f"{yr}y", 11, SOFT, "middle")
    s += f'<polyline points="{line}" fill="none" stroke="{GREEN}" stroke-width="2.5"/>'
    s += (f'<line x1="{hx}" y1="{hy}" x2="{hx}" y2="{T+ph}" stroke="{RED}" '
          f'stroke-width="1.5" stroke-dasharray="4 3"/>')
    s += text(hx + 6, hy - 6, f"half-life: {P['half_life']} days", 12, RED)
    s += text(L, 18, "weight of a result in the fit, by age", 13, INK)
    s += text(W - R, H - B + 18, "match age", 11, SOFT, "end")
    return s + "</svg>"


# ---------------- 2. Poisson vs reality ----------------
def chart_poisson():
    ms = load_matches(TODAY.isoformat(), P["half_life"], P["friendly_w"])
    goals = Counter()
    n = 0
    for m in ms:
        goals[min(m["hg"], 8)] += 1
        goals[min(m["ag"], 8)] += 1
        n += 2
    lam = sum(k * v for k, v in goals.items()) / n
    W, H = 640, 340
    L, R, T, B = 70, 20, 30, 50
    pw, ph = W - L - R, H - T - B
    kmax = 7
    ymax = max(goals[k] / n for k in range(kmax + 1)) * 1.15
    bw = pw / (kmax + 1)
    s = svg_open(W, H)
    for frac in (0, .1, .2, .3):
        if frac > ymax:
            continue
        y = T + ph * (1 - frac / ymax)
        s += f'<line x1="{L}" y1="{y}" x2="{W-R}" y2="{y}" stroke="{RULE}"/>'
        s += text(L - 8, y + 4, f"{frac*100:.0f}%", 11, SOFT, "end")
    pois_pts = []
    for k in range(kmax + 1):
        obs = goals[k] / n
        x = L + bw * k
        bh = ph * obs / ymax
        s += (f'<rect x="{x+6:.1f}" y="{T+ph-bh:.1f}" width="{bw-12:.1f}" '
              f'height="{bh:.1f}" fill="{INK}" opacity="0.82"/>')
        s += text(x + bw / 2, H - B + 18, str(k), 11, SOFT, "middle")
        pk = math.exp(-lam) * lam ** k / math.factorial(k)
        pois_pts.append((x + bw / 2, T + ph * (1 - pk / ymax)))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pois_pts)
    s += f'<polyline points="{line}" fill="none" stroke="{GREEN}" stroke-width="2"/>'
    for x, y in pois_pts:
        s += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{GREEN}"/>'
    s += text(L, 18, f"goals per team per match, {len(ms):,} internationals "
                     f"(bars) vs Poisson λ={lam:.2f} (dots)", 13, INK)
    s += text(W - R, H - B + 18, "goals", 11, SOFT, "end")
    return s + "</svg>"


# ---------------- 3. score-grid heatmap ----------------
def chart_grid():
    sims = json.load(open(f"{ROOT}/wc26_simulations.json"))["simulations"]
    m = next(v for v in sims.values()
             if v["home"] == "Mexico" and v["away"] == "South Africa")
    l1, l2 = m["xg"]["home"], m["xg"]["away"]
    g = score_grid(l1, l2, P["rho"])
    K = 6
    W = 560
    L, T = 110, 84
    cell = 64
    H = T + cell * (K + 1) + 30
    s = svg_open(W, H)
    s += text(L, 22, "the score grid: Mexico v South Africa", 14, INK)
    s += text(L, 42, f"model xG {l1:.2f} — {l2:.2f}; every market is a sum "
                     "over these cells", 11, SOFT)
    pmax = g[1][0]
    for i in range(K + 1):          # Mexico goals (rows)
        for j in range(K + 1):      # South Africa goals (cols)
            p = g[i][j]
            x = L + j * cell
            y = T + i * cell
            op = min(p / pmax, 1.0) * 0.92
            s += (f'<rect x="{x}" y="{y}" width="{cell-3}" height="{cell-3}" '
                  f'fill="{GREEN if i > j else RED if j > i else AMBER}" '
                  f'opacity="{max(op, 0.04):.3f}"/>')
            if p >= 0.005:
                fill = PAPER if op > 0.45 else INK
                s += text(x + (cell - 3) / 2, y + cell / 2 + 4,
                          f"{p*100:.1f}", 13, fill, "middle")
    for k in range(K + 1):
        s += text(L + k * cell + (cell - 3) / 2, T - 10, str(k), 12, SOFT, "middle")
        s += text(L - 12, T + k * cell + cell / 2 + 4, str(k), 12, SOFT, "end")
    s += text(L - 12, T - 32, "MEX ↓", 11, SOFT, "end")
    s += text(L + (K + 1) * cell - 3, T - 32, "RSA →", 11, SOFT, "end")
    y0 = T + (K + 1) * cell + 16
    s += text(L, y0, "■ Mexico win", 11, GREEN)
    s += text(L + 130, y0, "■ draw", 11, AMBER)
    s += text(L + 210, y0, "■ South Africa win", 11, RED)
    return s + "</svg>"


# ---------------- 4. calibration curve ----------------
def chart_calibration():
    model = fit(load_matches(SPLIT, P["half_life"], P["friendly_w"],
                             P["margin_cap"]), P["shrink"])
    bins = [[] for _ in range(10)]
    for r in test_set():
        if r["home_team"] not in model["att"] or r["away_team"] not in model["att"]:
            continue
        l1, l2 = lambdas(model, r["home_team"], r["away_team"],
                         r["neutral"] != "TRUE")
        pH, pD, pA = one_x_two(score_grid(l1, l2, P["rho"]))
        res = "H" if int(r["home_score"]) > int(r["away_score"]) else \
              "A" if int(r["away_score"]) > int(r["home_score"]) else "D"
        for k, p in (("H", pH), ("D", pD), ("A", pA)):
            bins[min(int(p * 10), 9)].append((p, 1 if k == res else 0))
    W, H = 560, 560
    L, R, T, B = 80, 24, 50, 64
    pw, ph = W - L - R, H - T - B
    s = svg_open(W, H)
    s += text(L, 22, "calibration on 1,071 held-out matches", 14, INK)
    s += text(L, 40, "a forecaster saying 60% should be right 60% of the time", 11, SOFT)
    for frac in (0, .2, .4, .6, .8, 1):
        x = L + pw * frac
        y = T + ph * (1 - frac)
        s += f'<line x1="{L}" y1="{y}" x2="{W-R}" y2="{y}" stroke="{RULE}"/>'
        s += text(L - 8, y + 4, f"{frac*100:.0f}%", 11, SOFT, "end")
        s += text(x, H - B + 18, f"{frac*100:.0f}%", 11, SOFT, "middle")
    s += (f'<line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T}" stroke="{SOFT}" '
          f'stroke-width="1.5" stroke-dasharray="5 4"/>')
    nmax = max(len(b) for b in bins if b)
    for b in bins:
        if len(b) < 12:
            continue
        mp = sum(p for p, _ in b) / len(b)
        obs = sum(o for _, o in b) / len(b)
        x = L + pw * mp
        y = T + ph * (1 - obs)
        r_ = 4 + 8 * math.sqrt(len(b) / nmax)
        s += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_:.1f}" fill="{GREEN}" '
              f'opacity="0.75"/>')
    s += text(L, H - 18, "x: predicted probability · y: observed frequency · "
                         "dot size: sample count", 11, SOFT)
    return s + "</svg>"


for name, fn in (("decay", chart_decay), ("poisson", chart_poisson),
                 ("grid", chart_grid), ("calibration", chart_calibration)):
    out = f"{ROOT}/charts/{name}.svg"
    open(out, "w").write(fn())
    print("wrote", out)
