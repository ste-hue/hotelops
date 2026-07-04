"""Scan NLP reputation: keywords pos/neg, temi, aggregati + renderer HTML.

Funzioni pure (niente BQ, niente Streamlit): `build_scan` produce il dict dei
dati, `render_scan_html` lo rende come pagina HTML self-contained embeddata
dalla pagina hub (verticals/reviews/app.py) via st.components.v1.html.
"""

from __future__ import annotations

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
