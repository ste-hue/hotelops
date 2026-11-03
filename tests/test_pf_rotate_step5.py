from datetime import date
from io import BytesIO

import openpyxl

from verticals.condges.pf_rotate.excel_model import periodo
from verticals.condges.pf_rotate.step5_controlli import verifica_controlli, CheckOutcome
from verticals.condges.pf_rotate.step1_saldi import write_saldi_banca
from verticals.condges.pf_rotate.step2_azzera import azzera_mese

P = lambda m: periodo(2026, m)  # noqa: E731


def test_controlli_su_fixture_minimal_post_step2(minimal_pf_orti_bytes):
    """Post step 2: tutti i controlli devono passare sul fixture minimale."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    # Replicate the witness flow: APRILE già "chiuso" nel fixture (entrate vuote),
    # quindi step 2 ulteriore è no-op. Eseguilo lo stesso per simmetria.
    azzera_mese(wb, periodo_chiuso=P(4))

    report = verifica_controlli(wb, periodo_chiuso=P(4))

    assert report.n_err == 0, (
        f"Errori inattesi: {[r for r in report.results if r.outcome == CheckOutcome.ERR]}"
    )


def test_controllo_1_c4_must_be_hardcoded(minimal_pf_orti_bytes):
    """Se C4 fosse formula → check #1 ERR."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    wb["Piano Finanziario"]["C4"] = "=C35"  # vandalismo

    report = verifica_controlli(wb, periodo_chiuso=P(4))
    check_1 = next(r for r in report.results if r.check_id == "C1")
    assert check_1.outcome == CheckOutcome.ERR


def test_controllo_3_cascade_d4_eq_c37(minimal_pf_orti_bytes):
    """D4 cascade = C37 + r29 chain. Se cambio D4 a un numero hardcoded → ERR."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    wb["Piano Finanziario"]["D4"] = 999999.0  # rompe la cascade

    report = verifica_controlli(wb, periodo_chiuso=P(4))
    check_3 = next(r for r in report.results if r.check_id == "C3")
    assert check_3.outcome == CheckOutcome.ERR


def test_controlli_su_intur_style_fixture(intur_pf_bytes):
    """Verifica engine layout-aware su INTUR-style layout."""
    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    write_saldi_banca(
        wb,
        periodo_chiuso=P(3),  # MARZO
        data_saldo=date(2026, 3, 31),
        saldi={"MPS": 682801.07, "Intesa": 1457.78, "Sella": 35186.34},
    )
    azzera_mese(wb, periodo_chiuso=P(3))
    report = verifica_controlli(wb, periodo_chiuso=P(3))
    assert report.n_err == 0, (
        f"Errori: {[r for r in report.results if r.outcome == CheckOutcome.ERR]}"
    )


def test_verifica_controlli_uses_mese_chiuso_not_first_col(intur_pf_bytes):
    """Cutover col deve derivare da mese_chiuso, non dalla prima colonna mese.

    Setup: D=MARZO con formula `=C35` (cascata), E=APRILE con 100.0 hardcoded.
    - mese_chiuso=4 → C1 controlla E (hardcoded) → OK.
    - mese_chiuso=3 → C1 controlla D (formula) → ERR.
    """
    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    pf["D3"] = "=C35"  # cascata legittima per APRILE-chiuso
    pf["E3"] = 100.0  # cutover hardcoded per APRILE-chiuso

    report_apr = verifica_controlli(wb, periodo_chiuso=P(4))
    c1_apr = next(r for r in report_apr.results if r.check_id == "C1")
    assert c1_apr.outcome == CheckOutcome.OK

    report_mar = verifica_controlli(wb, periodo_chiuso=P(3))
    c1_mar = next(r for r in report_mar.results if r.check_id == "C1")
    assert c1_mar.outcome == CheckOutcome.ERR


def test_c1_fixed_snapshot_ok(intur_pf_bytes):
    """Layout fixed-snapshot (INTUR): C1 OK quando C2 popolato + saldi banca in col C hardcoded."""
    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    pf["C1"] = "DATA RILEVAZ"  # attiva branch fixed-snapshot
    pf["C2"] = "30/04/2026"
    pf["C31"] = 49609.01
    pf["C32"] = 376510.97
    pf["C33"] = 1696.48

    report = verifica_controlli(wb, periodo_chiuso=P(4))
    c1 = next(r for r in report.results if r.check_id == "C1")
    assert c1.outcome == CheckOutcome.OK, f"detail={c1.detail}"
    assert "Snapshot C" in c1.title


def test_c1_fixed_snapshot_err_c2_vuota(intur_pf_bytes):
    """Layout fixed-snapshot: C1 ERR quando C2 (data rilevazione) è vuota."""
    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    pf["C1"] = "DATA RILEVAZ"
    pf["C2"] = None  # data rilevazione mancante
    pf["C31"] = 49609.01
    pf["C32"] = 376510.97
    pf["C33"] = 1696.48

    report = verifica_controlli(wb, periodo_chiuso=P(4))
    c1 = next(r for r in report.results if r.check_id == "C1")
    assert c1.outcome == CheckOutcome.ERR
    assert "C2 vuota" in c1.detail


def test_c1_fixed_snapshot_data_in_c1_ok(intur_pf_bytes):
    """PF INTUR da settembre 2026: data della fotografia in C1, C2 vuota → OK."""
    from datetime import datetime

    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    pf["C1"] = datetime(2026, 9, 30)
    pf["C2"] = None
    pf["C31"] = 49609.01
    pf["C32"] = 376510.97
    pf["C33"] = 1696.48

    report = verifica_controlli(wb, periodo_chiuso=P(4))
    c1 = next(r for r in report.results if r.check_id == "C1")
    assert c1.outcome == CheckOutcome.OK, f"detail={c1.detail}"


# ── C7–C16: riga del master per etichetta, colonne per mese ──


def _wb_voce(
    master_row: int, det_offset: int, master_val, det_val, etichetta="Salari e Stipendi"
):
    """Master con la voce Salari alla riga `master_row` e mesi in D..I (2026-04..09);
    foglio di dettaglio con gli stessi mesi spostati di `det_offset` colonne."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    pf = wb.create_sheet("Piano Finanziario")
    det = wb.create_sheet("Salari e Stipendi")
    mesi = ["APRILE", "MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE"]
    pf["D1"] = 2026
    det.cell(1, 4 + det_offset, 2026)
    for i, m in enumerate(mesi):
        pf.cell(2, 4 + i, m)
        det.cell(2, 4 + det_offset + i, m)
    pf.cell(master_row, 1, etichetta)
    pf.cell(master_row, 4 + 5, master_val)  # SETTEMBRE
    det.cell(4, 4 + det_offset + 5, det_val)  # SETTEMBRE nel dettaglio, riga 4
    return wb


def _c7(wb):
    from verticals.condges.pf_rotate.step5_controlli import _check_voce_link

    return _check_voce_link(wb, "C7", "Salari", 14, "Salari e Stipendi", 4, ["I"])


def test_c7_riga_spostata_e_mesi_spostati_come_intur():
    # INTUR: Salari alla riga 15, riga 14 vuota; dettaglio spostato di 5 colonne. Il
    # master è una formula: niente da confrontare → OK, non il falso ERR di prima.
    wb = _wb_voce(15, 5, "='Salari e Stipendi'!N3", 9393.33)
    assert _c7(wb).outcome == CheckOutcome.OK


def test_c7_confronta_lo_stesso_mese_anche_se_le_colonne_differiscono():
    assert _c7(_wb_voce(14, 5, 100.0, 100.0)).outcome == CheckOutcome.OK
    r = _c7(_wb_voce(15, 5, 100.0, 250.0))
    assert r.outcome == CheckOutcome.ERR and "Riga 15" in r.title and "2026-09" in r.detail


def test_c7_senza_riga_della_voce_e_indeterminato():
    wb = _wb_voce(15, 0, 100.0, 250.0, etichetta="Altro")
    assert _c7(wb).outcome == CheckOutcome.INDET
