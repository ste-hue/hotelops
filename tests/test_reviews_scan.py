"""Test del motore scan NLP reviews (build_scan) e del renderer HTML."""

from verticals.reviews.scan import build_scan


def _booking_row(**kw):
    row = dict(
        data_review="2026-06-20",
        piattaforma="BOOKING",
        business_unit_id="HOTEL",
        punteggio_norm=9.0,
        lingua="it",
        titolo="Ottimo",
        testo="Staff gentile e colazione abbondante Camera datata e rumore dalla strada",
        testo_positivo="Staff gentile e colazione abbondante",
        testo_negativo="Camera datata e rumore dalla strada",
        categoria_nlp="STRUTTURA",
        sentiment_nlp="MISTO",
        riassunto_nlp="Staff ottimo, camera datata",
        reviewer_paese="Italy",
        tipo_viaggio="COPPIA",
    )
    row.update(kw)
    return row


def _google_row(**kw):
    row = dict(
        data_review="2026-05-02",
        piattaforma="GOOGLE",
        business_unit_id="RESIDENCE",
        punteggio_norm=4.0,
        lingua="en",
        titolo="Disappointing",
        testo="Parking impossible and the room was noisy",
        testo_positivo=None,
        testo_negativo=None,
        categoria_nlp="STRUTTURA",
        sentiment_nlp="NEGATIVO",
        riassunto_nlp="Parcheggio impossibile e camera rumorosa",
        reviewer_paese="United Kingdom",
        tipo_viaggio="FAMIGLIA",
    )
    row.update(kw)
    return row


ROWS = [
    _booking_row(),
    _google_row(),
    _google_row(
        data_review="2026-05-10",
        punteggio_norm=10.0,
        titolo="Wonderful",
        testo="Wonderful sea view and friendly staff",
        sentiment_nlp="POSITIVO",
        riassunto_nlp="Vista e staff",
        tipo_viaggio="AMICI",
    ),
]


def test_empty_rows():
    assert build_scan([]) == {"total": 0}


def test_corpora_split():
    scan = build_scan(ROWS)
    # Booking: campi espliciti → 1 pos + 1 neg. Google: fallback per voto
    # (10 → pos, 4 → neg). Totale 2 e 2.
    assert scan["n_pos_texts"] == 2
    assert scan["n_neg_texts"] == 2


def test_keywords():
    scan = build_scan(ROWS)
    pos = dict(scan["pos_words"])
    neg = dict(scan["neg_words"])
    assert "staff" in pos
    assert "parking" in neg
    # stopword multilingua rimosse
    assert "the" not in neg
    assert "della" not in neg


def test_themes():
    scan = build_scan(ROWS)
    tpos = dict(scan["themes_pos"])
    tneg = dict(scan["themes_neg"])
    assert tpos.get("Staff") == 2  # booking pos + google pos
    assert tneg.get("Parcheggio") == 1
    assert tneg.get("Rumore") == 2  # "rumore" (booking) + "noisy" (google)


def test_aggregates():
    scan = build_scan(ROWS)
    assert scan["total"] == 3
    assert scan["neg_count"] == 1
    assert scan["by_bu"]["HOTEL"] == {"n": 1, "avg": 9.0, "neg": 0}
    assert scan["by_bu"]["RESIDENCE"]["n"] == 2
    assert scan["by_month"]["2026-05"]["n"] == 2
    assert scan["score_dist"] == {9: 1, 4: 1, 10: 1}


def test_neg_reviews_list():
    scan = build_scan(ROWS)
    assert len(scan["neg_reviews"]) == 1
    item = scan["neg_reviews"][0]
    assert item["s"] == 4.0
    assert item["bu"] == "RESIDENCE"
    assert "Parcheggio" in item["sum"]


def test_nan_and_timestamp_tolerated():
    import datetime

    row = _booking_row(
        testo_positivo=float("nan"),
        testo_negativo=float("nan"),
        riassunto_nlp=None,
        data_review=datetime.datetime(2026, 6, 20),
    )
    scan = build_scan([row])
    assert scan["total"] == 1
    assert "2026-06" in scan["by_month"]
