"""Tests for ingest_vendite_fb.

Pipeline POS Ristocube → f_vendite_fb (APPEND, dedup hash_riga).
"""

from datetime import date

from ingest.flussi.ingest_vendite_fb import _make_hash


def test_hash_distinguishes_segmento_cliente():
    """Regression bug_001 (ultrareview 2026-05-02): righe identiche su
    (societa, data, sala, codice, qty, netto) ma con segmento_cliente diverso
    devono produrre hash distinti.

    Senza segmento nel hash, `filter_new_rows_by_hash` collassava righe
    cross-segmento, droppando segmenti aggiunti in re-ingest e rompendo
    `v_food_cost_categoria` (che partiziona su segmento_cliente).

    Caso reale dal diagnostic SQL (PD.00015 2026-04-23): stesso articolo,
    stesso giorno, stessa sala, stesso netto venduto a INLE / ZRISTEST /
    ZRISTINT — 3 hash collassati a 1 in produzione pre-fix.
    """
    common = ("ORTI", date(2026, 4, 23), "RISTO_DINNER", "PD.00015", 1.0, 12.50)

    h_inle = _make_hash(*common[:4], "INLE", *common[4:])
    h_ztest = _make_hash(*common[:4], "ZRISTEST", *common[4:])
    h_zint = _make_hash(*common[:4], "ZRISTINT", *common[4:])

    assert len({h_inle, h_ztest, h_zint}) == 3


def test_hash_segmento_none_equals_empty_string():
    """None e "" devono produrre lo stesso hash — idempotenza per righe
    senza segmento esplicito (export pre-segmento_cliente).
    """
    common = ("ORTI", date(2026, 4, 23), "BAR", "ESP001", 1.0, 1.50)

    h_none = _make_hash(*common[:4], None, *common[4:])
    h_empty = _make_hash(*common[:4], "", *common[4:])

    assert h_none == h_empty


def test_hash_real_segment_differs_from_no_segment():
    """Una riga con segmento esplicito non deve collassare con la versione
    "senza segmento" della stessa tupla — pattern dominante nel diagnostic
    (470 hash collisioni in produzione, di cui ~78% del tipo (vuoto)+INLE).
    """
    common = ("ORTI", date(2026, 4, 23), "BAR", "ESP001", 1.0, 1.50)

    h_none = _make_hash(*common[:4], None, *common[4:])
    h_inle = _make_hash(*common[:4], "INLE", *common[4:])

    assert h_none != h_inle


def test_hash_quantita_and_netto_still_discriminate():
    """Sanity: il fix non ha rotto la discriminazione esistente su qty/netto
    (stesso articolo venduto a prezzi diversi durante happy hour, etc.).
    """
    base = ("ORTI", date(2026, 4, 23), "BAR", "ESP001", "INLE")

    h_qty1 = _make_hash(*base, 1.0, 1.50)
    h_qty2 = _make_hash(*base, 2.0, 1.50)
    h_netto = _make_hash(*base, 1.0, 1.20)

    assert len({h_qty1, h_qty2, h_netto}) == 3
