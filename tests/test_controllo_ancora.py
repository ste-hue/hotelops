import json
from datetime import date

import openpyxl

from verticals.condges.pf_rotate.controllo_ancora import controlla, leggi, main


def _pf(path, saldi, prec, data=date(2026, 9, 30)):
    """Master INTUR-like: data in C1, mesi da D, righe «Saldo <banca>» con il valore in C."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"
    ws["A1"], ws["C1"], ws["D1"] = "INTUR", data, 2026
    for i, m in enumerate(("OTTOBRE", "NOVEMBRE", "DICEMBRE")):
        ws.cell(2, 4 + i, m)
    ws["A3"] = "SALDO MESE PRECED."
    for i, v in enumerate(prec):
        ws.cell(3, 4 + i, v)
    for r, (b, v) in enumerate(saldi.items(), start=32):
        ws.cell(r, 1, f"Saldo {b}")
        ws.cell(r, 3, v)
    wb.save(path)
    return path


def test_legge_saldi_data_e_saldo_di_partenza(tmp_path):
    p = _pf(
        tmp_path / "INTUR_PF_2026-10.xlsx",
        {"Banca Sella": 10.0, "MPS": 20.0, "Intesa": 5.5},
        [35.5, 35.5, 40],
    )
    soc, saldi, prec, mesi, data = leggi(p)
    assert soc == "INTUR" and saldi == {"SELLA": 10.0, "MPS": 20.0, "INTESA": 5.5}
    assert (
        prec == {3: 35.5, 4: 35.5, 5: 40.0}
        and mesi[3] == "OTTOBRE"
        and str(data) == "2026-09-30"
    )


def test_verde_quando_quadra_e_bq_coincide(tmp_path):
    p = _pf(
        tmp_path / "INTUR_PF_2026-10.xlsx",
        {"Sella": 10.0, "MPS": 20.0, "Intesa": 5.5},
        [35.5],
    )
    rosso, righe = controlla(
        p, {"bq": {"INTUR": {"SELLA": 10.0, "MPS": 20.0, "INTESA": 5.5}}}
    )
    assert not rosso and "OTTOBRE" in righe[0]


def test_rosso_sul_valore_noto_sbagliato_e_sullo_scarto_bq(tmp_path):
    # valori finti: il riferimento vero sta fuori dal repo
    p = _pf(
        tmp_path / "INTUR_PF_2026-10.xlsx",
        {"Sella": 10.0, "MPS": 20.0, "Intesa": 5000.0},
        [5030.0],
    )
    rosso, righe = controlla(p, {"rosse": {"INTUR|INTESA": 5000.0}})
    assert rosso and any("ROSSO: è il valore noto sbagliato" in r for r in righe)
    rosso, righe = controlla(p, {"bq": {"INTUR": {"INTESA": 5.5}}})
    assert rosso and any("BQ dice 5.50" in r for r in righe)
    rosso, _ = controlla(p, {"attesi": {"INTUR|INTESA": 3.0}})
    assert rosso


def test_rosso_se_il_saldo_di_partenza_non_e_la_somma(tmp_path):
    p = _pf(tmp_path / "ORTI_PF_2026-10.xlsx", {"MPS": 20.0, "Intesa": 5.0}, [100.0])
    rosso, righe = controlla(p, {})
    assert rosso and "NESSUNA colonna" in righe[0]


def test_main_esce_1_sul_rosso_e_2_senza_riferimento(tmp_path, monkeypatch, capsys):
    p = _pf(tmp_path / "INTUR_PF_2026-10.xlsx", {"Sella": 10.0}, [10.0])
    rif = tmp_path / "rif.json"
    rif.write_text(json.dumps({"rosse": {"INTUR|SELLA": 10.0}}))
    assert main([str(p), "--riferimento", str(rif)]) == 1
    assert "FERMATI" in capsys.readouterr().out
    monkeypatch.setenv("HOTELOPS_ANCORA_RIFERIMENTO", str(rif))
    assert main([str(p)]) == 1
    monkeypatch.delenv("HOTELOPS_ANCORA_RIFERIMENTO")
    assert main([str(p)]) == 2
