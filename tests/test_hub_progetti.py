"""Hub — pagina Progetti: contratto dei dati dichiarati e della distanza dalle tappe."""

from datetime import date

from verticals.hub.pages_ import progetti


def test_render_importabile():
    assert callable(progetti.render)


def test_progetti_hanno_tre_porte_e_almeno_una_tappa():
    for p in progetti.PROGETTI:
        assert p.app_url.startswith("https://"), p.id
        assert p.drive_url.startswith("https://drive.google.com/"), p.id
        assert p.cockpit_url.startswith("https://drive.google.com/"), p.id
        assert p.tappe, p.id
        assert list(p.tappe) == sorted(p.tappe, key=lambda t: t.quando), p.id


def test_cantiere_due_tappe_finali():
    c = next(p for p in progetti.PROGETTI if p.id == "HPAN26PIANO3")
    labels = {t.label: t.quando for t in c.tappe}
    assert labels["Uscita impresa edile"] == date(2027, 3, 20)
    assert labels["Fine lavori"] == date(2027, 4, 14)


def test_giorni_mancanti():
    oggi = date(2026, 10, 26)
    assert progetti.giorni_mancanti(date(2026, 10, 26), oggi) == "oggi"
    assert progetti.giorni_mancanti(date(2027, 3, 20), oggi) == "fra 145 giorni"
    assert progetti.giorni_mancanti(date(2026, 10, 19), oggi) == "7 giorni fa"
