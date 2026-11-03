import openpyxl

from verticals.condges.pf_rotate.pf_quadratura import main, quadratura

MESI = ("GENNAIO", "FEBBRAIO", "MARZO")


def _master(
    path,
    entrate=(100.0, 200.0, 300.0),
    utenze=(10.0, 20.0, 30.0),
    tot_entrate=None,
    tot_uscite=None,
):
    """Un master «Piano Finanziario» con i totali scritti come numeri (come dopo un salvataggio
    da Excel): tre mesi, una voce di entrata e una di uscita."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"
    ws["A1"], ws["C1"] = "ORTI", 2026
    for i, m in enumerate(MESI):
        ws.cell(2, 3 + i, m)
    ws["A4"] = "SALDO MESE PRECED."
    ws["A6"] = "Entrate Hotel"
    ws["A12"] = "TOTALE ENTRATE"
    ws["A15"] = "Utenze"
    ws["A27"] = "TOTALE USCITE"
    ws["A29"] = "CASH FLOW"
    for i in range(3):
        ws.cell(6, 3 + i, entrate[i])
        ws.cell(12, 3 + i, (tot_entrate or entrate)[i])
        ws.cell(15, 3 + i, utenze[i])
        ws.cell(27, 3 + i, (tot_uscite or utenze)[i])
    wb.save(path)
    return path


def test_quadra_quando_i_totali_del_master_sono_la_somma_delle_voci(tmp_path):
    o = quadratura(_master(tmp_path / "ORTI_PF_2026-01.xlsx"))
    assert o["righe"] == 6 and o["mesi"] == ["2026-01", "2026-02", "2026-03"]
    assert o["ok"], (o["diff_mesi"], o["anomalie"])
    assert (
        o["par_entrate"] == o["tot_entrate"] == 600.0
        and o["par_uscite"] == o["tot_uscite"] == 60.0
    )


def test_segnala_la_differenza_per_mese_quando_il_totale_del_foglio_non_torna(tmp_path):
    # il foglio dice 1,50 in più nel primo mese di entrate: una differenza, quel mese, quel segno
    o = quadratura(
        _master(tmp_path / "ORTI_PF_2026-01.xlsx", tot_entrate=(101.5, 200.0, 300.0))
    )
    assert not o["ok"] and o["diff_mesi"] == [
        ("ENTRATE", "2026-01", 100.0, 101.5, -1.5)
    ]


def test_main_esce_1_con_una_differenza_e_0_se_tutto_quadra(tmp_path, capsys):
    _master(tmp_path / "ORTI_PF_2026-01.xlsx")
    assert main([str(tmp_path)]) == 0 and "OK" in capsys.readouterr().out
    p = _master(tmp_path / "ORTI_PF_2026-02.xlsx", tot_uscite=(10.0, 22.0, 30.0))
    assert main([str(p)]) == 1 and "DIFF" in capsys.readouterr().out
