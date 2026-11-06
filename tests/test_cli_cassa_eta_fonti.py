"""`hotelops cdg cassa --eta-massima-fonti GIORNI`: il limite del presidio sul pubblicare
si passa dalla riga di comando; senza flag vale il default dichiarato in una sede sola."""

import pytest


def _cattura(monkeypatch, argv):
    import cli as cli_module
    from verticals.condges import build_cassa_artifact as bca

    chiamate = []
    monkeypatch.setattr(bca, "run", lambda *a, **k: chiamate.append((a, k)))
    monkeypatch.setattr("sys.argv", ["hotelops", *argv])
    cli_module.main()
    assert len(chiamate) == 1
    return chiamate[0]


def test_il_flag_arriva_a_run(monkeypatch):
    a, k = _cattura(monkeypatch, ["cdg", "cassa", "--push", "--eta-massima-fonti", "3"])
    assert a[2] is True and k == {"max_eta_fonti_giorni": 3}


def test_senza_flag_vale_il_default_dichiarato(monkeypatch):
    from verticals.condges.build_cassa_artifact import ETA_MASSIMA_FONTI_GIORNI

    _, k = _cattura(monkeypatch, ["cdg", "cassa"])
    assert "max_eta_fonti_giorni" not in k and ETA_MASSIMA_FONTI_GIORNI == 7


def test_il_flag_vuole_un_intero(monkeypatch):
    import cli as cli_module

    monkeypatch.setattr(
        "sys.argv", ["hotelops", "cdg", "cassa", "--eta-massima-fonti", "tre"]
    )
    with pytest.raises(SystemExit):
        cli_module.main()
