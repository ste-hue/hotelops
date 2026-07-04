"""Scan NLP reputation: keywords pos/neg, temi, aggregati + renderer HTML.

Funzioni pure (niente BQ, niente Streamlit): `build_scan` produce il dict dei
dati, `render_scan_html` lo rende come pagina HTML self-contained embeddata
dalla pagina hub (verticals/reviews/app.py) via st.components.v1.html.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter, defaultdict

# Stopword multilingua (it/en/de/fr/es) + parole di dominio senza segnale.
_STOPWORDS = frozenset(
    """
il lo la i gli le un uno una di a da in con su per tra fra e o ma anche non che
chi cui come dove quando piu meno molto poco tanto tutto tutti tutta tutte del
della dei delle dello degli al alla ai alle allo agli dal dalla dai dalle nel
nella nei nelle sul sulla sui sulle e' è sono era stato stata stati state essere
avere ha hanno ho abbiamo c'è se già solo però quindi perche perché qualche
questa questo questi queste quella quello quelle quelli si no noi voi loro lei
lui io tu mi ti ci vi ne li qui qua cosi così ed ad
the a an and or but not no of to in on at for from with by as is are was were
be been being have has had do does did this that these those we you they he she
it i my our your their his her its me us them there here very too also just so
than then when where how what which who whom all any some more most much many
few little over under again once during
der die das und oder aber nicht kein von zu im am auf für mit bei aus als ist
sind war waren sein haben hat hatte wir ihr sie er es ich du mein unser sehr
auch nur noch schon dann wenn wo wie was welche wer alle einige mehr
les des du et ou mais pas ne à dans sur pour avec par comme est sont était être
avoir ont nous vous ils elles elle je très aussi seulement encore alors où
comment que qui tout tous toute toutes plus moins beaucoup peu
el los las unos unas y pero en como es son ser estar tener han nosotros ellos
ella él yo muy también aún entonces donde cuando cómo qué quién todo todos toda
todas más menos mucho
hotel albergo struttura appartamento residence casa posto place stay soggiorno
vacanza notte notti giorni giorno sempre stata volta
""".split()
)

# Aggettivi di rating / filler: veri nel corpus ma inutili nel cloud.
_JUNK = frozenset(
    """
exceptional superb good great nice pleasant excellent wonderful lovely amazing
perfect fantastic beautiful best really would could made make well also get got
one two three everything definitely certainly ottimo ottima buona buono bella
bello molto assolutamente sicuramente consiglio consigliato recommend
recommended recommends nie caro cara nostra nostro stayed felt bit way take
even want need experience esperienza soggiornato trascorso
""".split()
)

_WORD_RE = re.compile(r"[a-zàèéìòùäöüßçâêîôûáíóúñ']+", re.IGNORECASE)

# Bucket tematici multilingua: 1 recensione conta 1 per tema se il suo testo
# pos/neg contiene almeno una keyword del tema.
_THEMES = {
    "Colazione": "colazione breakfast frühstück petit-déjeuner desayuno cornetti brioche buffet",
    "Camera": "camera camere room rooms zimmer chambre habitación stanza letto bed beds bagno bathroom doccia shower balcone balcony terrazza terrace",
    "Vista": "vista view panorama aussicht vue mare sea meer mer seaview panoramica",
    "Staff": "staff personale gentilezza gentili gentile cordiale cordialità disponibile disponibili disponibilità accoglienza friendly helpful kind personnel freundlich",
    "Pulizia": "pulizia pulito pulita pulite puliti clean cleanliness sauber propre limpio igiene sporco dirty",
    "Posizione": "posizione location lage emplacement ubicación centrale centro vicino vicina comoda fermata bus porto",
    "Cibo/Ristorante": "ristorante cena pranzo cibo food dinner essen mangiato piatti cucina menu pensione",
    "Parcheggio": "parcheggio parking parcheggiare garage parkplatz",
    "Prezzo": "prezzo price rapporto costoso expensive preis prix precio value",
    "Piscina/Spiaggia": "piscina pool spiaggia beach lido ombrellone strand plage playa",
    "Rumore": "rumore rumorosa rumoroso noise noisy strada traffico laut bruit insonorizzazione",
    "Struttura/Manutenzione": "vecchia vecchio datata datato ristrutturare manutenzione arredamento mobili old dated renovation ascensore condizionata climatizzazione riscaldamento wifi",
}
_THEME_KW = {t: frozenset(v.split()) for t, v in _THEMES.items()}

_MESI = {
    "01": "Gen",
    "02": "Feb",
    "03": "Mar",
    "04": "Apr",
    "05": "Mag",
    "06": "Giu",
    "07": "Lug",
    "08": "Ago",
    "09": "Set",
    "10": "Ott",
    "11": "Nov",
    "12": "Dic",
}

_TRIP_IT = {
    "COPPIA": "Coppie",
    "FAMIGLIA": "Famiglie",
    "AMICI": "Amici",
    "SOLO": "Solo",
    "?": "Non indicato",
}


def _text(v) -> str:
    """Coerce robusto per valori da df.to_dict('records'): None/NaN → ''."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v)


def _tokens(text: str) -> list[str]:
    return [
        w.lower().strip("'")
        for w in _WORD_RE.findall(text)
        if len(w) > 2 and w.lower() not in _STOPWORDS
    ]


def _split_corpora(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Testi positivi/negativi: campi espliciti Booking/Expedia quando presenti,
    altrimenti testo intero assegnato per voto (>=8 pos, <=6 neg, 6-8 scartato)."""
    pos, neg = [], []
    for r in rows:
        tp, tn = _text(r.get("testo_positivo")), _text(r.get("testo_negativo"))
        if tp or tn:
            if tp:
                pos.append(tp)
            if tn:
                neg.append(tn)
        else:
            t = (_text(r.get("titolo")) + " " + _text(r.get("testo"))).strip()
            if not t:
                continue
            score = float(r.get("punteggio_norm") or 0)
            if score >= 8:
                pos.append(t)
            elif score <= 6:
                neg.append(t)
    return pos, neg


def _theme_counts(texts: list[str]) -> Counter:
    c = Counter()
    for txt in texts:
        tk = set(_tokens(txt))
        for theme, kws in _THEME_KW.items():
            if tk & kws:
                c[theme] += 1
    return c


def _agg(rows: list[dict], keyfn) -> dict:
    d = defaultdict(lambda: {"n": 0, "sum": 0.0, "neg": 0})
    for r in rows:
        k = keyfn(r)
        s = float(r.get("punteggio_norm") or 0)
        d[k]["n"] += 1
        d[k]["sum"] += s
        d[k]["neg"] += s <= 6
    return {
        k: {"n": v["n"], "avg": round(v["sum"] / v["n"], 2), "neg": v["neg"]}
        for k, v in sorted(d.items())
    }


def build_scan(rows: list[dict]) -> dict:
    """Calcola keywords, temi e aggregati da righe f_reviews. Puro."""
    if not rows:
        return {"total": 0}

    pos_texts, neg_texts = _split_corpora(rows)
    pos_counter = Counter(t for txt in pos_texts for t in _tokens(txt))
    neg_counter = Counter(t for txt in neg_texts for t in _tokens(txt))
    scores = [float(r.get("punteggio_norm") or 0) for r in rows]

    return {
        "total": len(rows),
        "avg": round(sum(scores) / len(rows), 2),
        "neg_count": sum(1 for s in scores if s <= 6),
        "n_pos_texts": len(pos_texts),
        "n_neg_texts": len(neg_texts),
        "by_month": _agg(rows, lambda r: _text(r.get("data_review"))[:7]),
        "by_platform": _agg(rows, lambda r: _text(r.get("piattaforma")) or "?"),
        "by_bu": _agg(rows, lambda r: _text(r.get("business_unit_id")) or "?"),
        "by_trip": _agg(rows, lambda r: _text(r.get("tipo_viaggio")) or "?"),
        "by_country": _agg(rows, lambda r: _text(r.get("reviewer_paese")) or "?"),
        "by_cat": _agg(rows, lambda r: _text(r.get("categoria_nlp")) or "?"),
        "score_dist": dict(Counter(int(s) for s in scores)),
        "pos_words": pos_counter.most_common(80),
        "neg_words": neg_counter.most_common(80),
        "themes_pos": _theme_counts(pos_texts).most_common(),
        "themes_neg": _theme_counts(neg_texts).most_common(),
        "neg_reviews": [
            {
                "d": _text(r.get("data_review"))[:10],
                "p": _text(r.get("piattaforma")),
                "bu": _text(r.get("business_unit_id")),
                "s": float(r.get("punteggio_norm") or 0),
                "cat": _text(r.get("categoria_nlp")) or "—",
                "sum": _text(r.get("riassunto_nlp")) or _text(r.get("testo"))[:120],
            }
            for r in sorted(rows, key=lambda x: _text(x.get("data_review")))
            if float(r.get("punteggio_norm") or 0) <= 6
        ],
    }


# ── Renderer HTML ────────────────────────────────────────────────────────────

_CSS = """
:root {
  --paper:#F2F5F4; --card:#FFFFFF; --ink:#1C2B33; --muted:#5F7178;
  --accent:#0E7C86; --accent-soft:#0E7C8618;
  --pos:#2E7D46; --neg:#BC4A3C; --neg-soft:#BC4A3C1F;
  --line:#D8E0DE; --mid:#C9A227;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:#0E181C; --card:#16232A; --ink:#E4ECE9; --muted:#8FA3A8;
    --accent:#45B4BE; --accent-soft:#45B4BE22;
    --pos:#5BBF7F; --neg:#E07B6B; --neg-soft:#E07B6B26;
    --line:#26363D; --mid:#D9B44A;
  }
}
* { box-sizing:border-box; }
body { background:var(--paper); color:var(--ink);
  font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  margin:0; padding:1.5rem 1rem 3rem; }
main { max-width:980px; margin:0 auto; display:flex; flex-direction:column; gap:1.8rem; }
h1,h2 { font-family:"Iowan Old Style", Georgia, serif; text-wrap:balance; margin:0; }
h1 { font-size:1.8rem; line-height:1.15; font-weight:600; }
h2 { font-size:1.25rem; font-weight:600; margin-bottom:.8rem; }
.eyebrow { font-size:.7rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); font-weight:700; margin-bottom:.35rem; }
.sub { color:var(--muted); margin:.4rem 0 0; max-width:62ch; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:1.2rem 1.4rem; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:.7rem; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:.9rem 1rem; }
.kpi b { display:block; font-size:1.7rem; font-weight:650;
  font-variant-numeric:tabular-nums; font-family:Georgia, serif; }
.kpi small { color:var(--muted); font-size:.75rem; }
.foto p { margin:.5rem 0; max-width:70ch; }
.foto b { color:var(--accent); }
.foto .warn b { color:var(--neg); }
.mrow { display:grid; grid-template-columns:3rem 1fr 4rem 6.5rem; gap:.7rem;
  align-items:center; padding:.25rem 0; }
.mlabel { font-size:.82rem; color:var(--muted); font-weight:600; }
.mbar { background:var(--accent-soft); border-radius:5px; height:1.4rem; }
.mfill { background:var(--accent); border-radius:5px; height:100%;
  display:flex; align-items:center; justify-content:flex-end; min-width:1.9rem; }
.mfill span { color:#fff; font-size:.72rem; font-weight:700; padding-right:.45rem;
  font-variant-numeric:tabular-nums; }
.mavg { font-weight:700; font-variant-numeric:tabular-nums; text-align:right; }
.mneg { font-size:.74rem; color:var(--muted); text-align:right;
  font-variant-numeric:tabular-nums; }
.cloudgrid { display:grid; grid-template-columns:1fr 1fr; gap:.7rem; }
@media (max-width:760px) { .cloudgrid { grid-template-columns:1fr; } }
.cloudbox { background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:1.1rem 1.3rem 1.3rem; }
.cloudbox h3 { margin:0 0 .8rem; font-size:.75rem; letter-spacing:.12em;
  text-transform:uppercase; font-weight:700; }
.cloudbox.pos h3 { color:var(--pos); }
.cloudbox.neg h3 { color:var(--neg); }
.cloudwrap { display:flex; flex-wrap:wrap; gap:.3rem .65rem; align-items:baseline; }
.cw { line-height:1.1; }
.cw.cpos { color:var(--pos); } .cw.cneg { color:var(--neg); }
.cw.w1 { opacity:.55; } .cw.w2 { opacity:.8; } .cw.w3 { font-weight:700; }
.note { font-size:.74rem; color:var(--muted); margin:.8rem 0 0; }
.trow { display:grid; grid-template-columns:1fr 10rem 1fr; gap:.55rem;
  align-items:center; padding:.2rem 0; }
.tname { text-align:center; font-size:.85rem; font-weight:600; }
.tneg { display:flex; align-items:center; justify-content:flex-end; gap:.45rem; }
.tpos { display:flex; align-items:center; gap:.45rem; }
.tbar { height:.9rem; border-radius:4px; }
.bpos { background:var(--pos); } .bneg { background:var(--neg); }
.tnum { font-size:.73rem; color:var(--muted); font-variant-numeric:tabular-nums;
  min-width:1.2rem; }
.axis { display:grid; grid-template-columns:1fr 10rem 1fr; font-size:.7rem;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  margin-bottom:.45rem; }
.axis .l { text-align:right; color:var(--neg); font-weight:700; }
.axis .r { color:var(--pos); font-weight:700; }
.bugrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  gap:.7rem; }
.bu-head { display:flex; justify-content:space-between; align-items:baseline;
  margin-bottom:.6rem; }
.bu-name { font-weight:700; }
.bu-tag { font-size:.66rem; letter-spacing:.1em; color:var(--accent);
  background:var(--accent-soft); padding:.12rem .45rem; border-radius:99px;
  font-weight:700; }
.bu-stats { display:flex; gap:1.4rem; }
.bu-stats b { font-size:1.25rem; font-variant-numeric:tabular-nums; display:block; }
.bu-stats small { color:var(--muted); font-size:.7rem; }
.negtxt { color:var(--neg); }
.tables { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:.7rem; }
.twrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.85rem; }
th { text-align:left; font-size:.68rem; letter-spacing:.1em;
  text-transform:uppercase; color:var(--muted);
  padding:.3rem .55rem .3rem 0; border-bottom:1px solid var(--line); }
td { padding:.38rem .55rem .38rem 0; border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums; }
tr:last-child td { border-bottom:none; }
.tcap { font-size:.75rem; font-weight:700; letter-spacing:.1em;
  text-transform:uppercase; color:var(--accent); margin:0 0 .55rem; }
.dist { display:flex; gap:.4rem; align-items:flex-end; height:8.5rem;
  padding-top:.4rem; }
.dcol { flex:1; display:flex; flex-direction:column; align-items:center;
  gap:.15rem; height:100%; }
.dbarwrap { flex:1; width:100%; display:flex; align-items:flex-end; }
.dbar { width:100%; border-radius:4px 4px 0 0; }
.dpos { background:var(--pos); } .dmid { background:var(--mid); }
.dneg { background:var(--neg); }
.dnum { font-size:.7rem; color:var(--muted); font-variant-numeric:tabular-nums; }
.dlab { font-size:.72rem; font-weight:700; }
.negitem { border-left:3px solid var(--neg); padding:.45rem 0 .45rem .9rem;
  margin-bottom:.6rem; }
.negmeta { font-size:.74rem; color:var(--muted); display:flex; flex-wrap:wrap;
  gap:.35rem; align-items:center; }
.negscore { background:var(--neg-soft); color:var(--neg); font-weight:700;
  padding:.08rem .4rem; border-radius:4px; }
.negcat { letter-spacing:.08em; font-weight:700; }
.negitem p { margin:.25rem 0 0; font-size:.9rem; max-width:75ch; }
"""


def _esc(v) -> str:
    return html.escape(_text(v), quote=True)


def _cloud(words: list[tuple[str, int]], klass: str, max_words: int = 42) -> str:
    ws = [(w, c) for w, c in words if w not in _JUNK][:max_words]
    if not ws:
        return '<span class="note">Nessun testo in questo corpus.</span>'
    cmax, cmin = ws[0][1], ws[-1][1]
    spans = []
    for w, c in sorted(ws, key=lambda x: x[0]):
        t = (math.sqrt(c) - math.sqrt(cmin)) / max(
            math.sqrt(cmax) - math.sqrt(cmin), 0.001
        )
        size = 0.78 + t * 1.7
        cls = "w3" if t > 0.66 else ("w2" if t > 0.33 else "w1")
        spans.append(
            f'<span class="cw {klass} {cls}" style="font-size:{size:.2f}rem" '
            f'title="{c} menzioni">{_esc(w)}</span>'
        )
    return "\n".join(spans)


def _month_rows(by_month: dict) -> str:
    if not by_month:
        return ""
    nmax = max(v["n"] for v in by_month.values())
    out = ""
    for m, v in by_month.items():
        label = _MESI.get(m[5:7], m)
        negpct = v["neg"] / v["n"] * 100
        warn = ' class="mavg negtxt"' if v["avg"] < 8.4 else ' class="mavg"'
        out += (
            f'<div class="mrow"><div class="mlabel">{_esc(label)}</div>'
            f'<div class="mbar"><div class="mfill" style="width:{v["n"] / nmax * 100:.0f}%">'
            f"<span>{v['n']}</span></div></div>"
            f"<div{warn}>{v['avg']:.2f}</div>"
            f'<div class="mneg">{v["neg"]} neg · {negpct:.0f}%</div></div>'
        )
    return out


def _theme_rows(themes_pos: list, themes_neg: list) -> str:
    tp, tn = dict(themes_pos), dict(themes_neg)
    all_t = sorted(set(tp) | set(tn), key=lambda t: -(tp.get(t, 0) + tn.get(t, 0)))
    if not all_t:
        return ""
    tmax = max(max(tp.values(), default=1), max(tn.values(), default=1))
    out = ""
    for t in all_t:
        p, n = tp.get(t, 0), tn.get(t, 0)
        out += (
            f'<div class="trow">'
            f'<div class="tneg"><span class="tnum">{n or ""}</span>'
            f'<div class="tbar bneg" style="width:{n / tmax * 100:.0f}%"></div></div>'
            f'<div class="tname">{_esc(t)}</div>'
            f'<div class="tpos"><div class="tbar bpos" style="width:{p / tmax * 100:.0f}%"></div>'
            f'<span class="tnum">{p or ""}</span></div></div>'
        )
    return out


def _bu_cards(by_bu: dict) -> str:
    out = ""
    for bu, v in sorted(by_bu.items(), key=lambda x: -x[1]["n"]):
        negpct = v["neg"] / v["n"] * 100
        out += (
            f'<div class="card"><div class="bu-head">'
            f'<span class="bu-name">{_esc(bu)}</span>'
            f'<span class="bu-tag">{v["n"]} review</span></div>'
            f'<div class="bu-stats">'
            f"<div><b>{v['avg']:.2f}</b><small>media /10</small></div>"
            f'<div><b class="{"negtxt" if negpct > 12 else ""}">{v["neg"]}</b>'
            f"<small>negative ({negpct:.0f}%)</small></div>"
            f"</div></div>"
        )
    return out


def _table(
    caption: str, rows: dict, label_map: dict | None = None, min_n: int = 0
) -> str:
    label_map = label_map or {}
    items = [
        (k, v)
        for k, v in sorted(rows.items(), key=lambda x: -x[1]["n"])
        if k != "?" and v["n"] >= min_n
    ]
    if not items:
        return ""
    body = ""
    for k, v in items:
        warn = ' class="negtxt"' if v["avg"] < 8 else ""
        body += (
            f"<tr><td>{_esc(label_map.get(k, k))}</td><td>{v['n']}</td>"
            f"<td{warn}>{v['avg']:.2f}</td><td>{v['neg']}</td></tr>"
        )
    return (
        f'<div class="card"><p class="tcap">{_esc(caption)}</p>'
        f'<div class="twrap"><table>'
        f"<tr><th></th><th>n</th><th>Media</th><th>Neg</th></tr>{body}"
        f"</table></div></div>"
    )


def _dist_cols(score_dist: dict) -> str:
    smax = max(score_dist.values(), default=1)
    out = ""
    for s in range(1, 11):
        c = score_dist.get(s, 0)
        klass = "dneg" if s <= 6 else ("dmid" if s <= 8 else "dpos")
        out += (
            f'<div class="dcol"><div class="dbarwrap">'
            f'<div class="dbar {klass}" style="height:{max(c / smax * 100, 1):.0f}%"></div></div>'
            f'<span class="dnum">{c or ""}</span><span class="dlab">{s}</span></div>'
        )
    return out


def _neg_items(neg_reviews: list[dict]) -> str:
    out = ""
    for r in reversed(neg_reviews):
        out += (
            f'<div class="negitem"><div class="negmeta">'
            f'<span class="negscore">{r["s"]:.0f}/10</span>'
            f"<span>{_esc(r['d'])}</span> · <span>{_esc(r['p'])}</span> · "
            f"<span>{_esc(r['bu'])}</span> · "
            f'<span class="negcat">{_esc(r["cat"])}</span></div>'
            f"<p>{_esc(r['sum'])}</p></div>"
        )
    return out or '<p class="note">Nessuna review negativa nel periodo. 🎉</p>'


def _fotografia(scan: dict) -> str:
    """Sintesi deterministica: solo frasi supportate dai dati."""
    parts = []
    total = scan["total"]
    dieci = scan["score_dist"].get(10, 0)

    top_pos = [t for t, _ in scan["themes_pos"][:3]]
    if top_pos:
        parts.append(
            f"<p><b>Punti di forza:</b> {', '.join(_esc(t) for t in top_pos)} "
            f"dominano il linguaggio positivo. {dieci} recensioni su {total} "
            f"({dieci / total * 100:.0f}%) sono un 10/10.</p>"
        )

    top_neg = [t for t, _ in scan["themes_neg"][:2]]
    if top_neg:
        parts.append(
            f'<p class="warn"><b>Fronte critico:</b> '
            f"{' e '.join(_esc(t) for t in top_neg)} sono i temi più frequenti "
            f"nei testi negativi ({scan['neg_count']} recensioni ≤6, "
            f"{scan['neg_count'] / total * 100:.0f}% del totale).</p>"
        )

    months = {m: v for m, v in scan["by_month"].items() if v["n"] >= 5}
    if len(months) >= 2:
        worst_m = min(months, key=lambda m: months[m]["avg"])
        v = months[worst_m]
        parts.append(
            f"<p><b>Mese più debole:</b> {_MESI.get(worst_m[5:7], worst_m)} "
            f"con media {v['avg']:.2f} e {v['neg']} negative su {v['n']}.</p>"
        )

    trips = {k: v for k, v in scan["by_trip"].items() if k != "?" and v["n"] >= 10}
    if len(trips) >= 2:
        worst_t = min(trips, key=lambda t: trips[t]["avg"])
        v = trips[worst_t]
        parts.append(
            f"<p><b>Segmento più critico:</b> {_esc(_TRIP_IT.get(worst_t, worst_t))} "
            f"({v['avg']:.2f} di media su {v['n']} recensioni).</p>"
        )

    return "\n".join(parts) or "<p>Dati insufficienti per una sintesi.</p>"


def render_scan_html(scan: dict, anno: int) -> str:
    """Pagina HTML self-contained del quadro reputation. scan['total'] > 0."""
    total = scan["total"]
    kpi = (
        f'<div class="kpi"><b>{total}</b><small>review {anno}</small></div>'
        f'<div class="kpi"><b>{scan["avg"]:.2f}</b><small>voto medio /10</small></div>'
        f'<div class="kpi"><b>{scan["neg_count"]}</b>'
        f"<small>negative ≤6 ({scan['neg_count'] / total * 100:.0f}%)</small></div>"
        f'<div class="kpi"><b>{scan["score_dist"].get(10, 0)}</b>'
        f"<small>voti 10/10</small></div>"
    )
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_CSS}</style></head><body><main>

<header>
  <div class="eyebrow">Scan NLP · f_reviews</div>
  <h1>Di cosa parlano le recensioni nel {anno}</h1>
  <p class="sub">Parole chiave estratte dai testi (positivo vs negativo),
  temi ricorrenti e quadro per struttura, sul periodo/filtri selezionati.</p>
</header>

<section class="kpis">{kpi}</section>

<section class="card foto">
  <h2>La fotografia</h2>
  {_fotografia(scan)}
</section>

<section class="card">
  <h2>Trend mensile</h2>
  {_month_rows(scan["by_month"])}
  <p class="note">Barre = volume recensioni · a destra media /10 e negative (≤6).</p>
</section>

<section>
  <h2>Le parole dei clienti</h2>
  <div class="cloudgrid">
    <div class="cloudbox pos">
      <h3>Nel positivo · {scan["n_pos_texts"]} testi</h3>
      <div class="cloudwrap">{_cloud(scan["pos_words"], "cpos")}</div>
    </div>
    <div class="cloudbox neg">
      <h3>Nel negativo · {scan["n_neg_texts"]} testi</h3>
      <div class="cloudwrap">{_cloud(scan["neg_words"], "cneg")}</div>
    </div>
  </div>
  <p class="note">Dimensione = frequenza nei campi "testo positivo"/"testo negativo"
  (Booking/Expedia); per Google/TripAdvisor il testo intero è assegnato per voto
  (≥8 positivo, ≤6 negativo). Stopword multilingua e aggettivi di rating rimossi.</p>
</section>

<section class="card">
  <h2>Temi: menzioni positive vs negative</h2>
  <div class="axis"><span class="l">Negative ←</span><span></span><span class="r">→ Positive</span></div>
  {_theme_rows(scan["themes_pos"], scan["themes_neg"])}
</section>

<section>
  <h2>Per struttura</h2>
  <div class="bugrid">{_bu_cards(scan["by_bu"])}</div>
</section>

<section class="card">
  <h2>Distribuzione voti</h2>
  <div class="dist">{_dist_cols(scan["score_dist"])}</div>
</section>

<section class="tables">
  {_table("Piattaforme", scan["by_platform"])}
  {_table("Tipo viaggio", scan["by_trip"], label_map=_TRIP_IT)}
  {_table("Paesi (n ≥ 5)", scan["by_country"], min_n=5)}
</section>

<section class="card">
  <h2>Le negative, una per una</h2>
  {_neg_items(scan["neg_reviews"])}
</section>

</main></body></html>"""
