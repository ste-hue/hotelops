from datetime import date
from io import BytesIO

import openpyxl

from verticals.condges.pf_rotate.step5_controlli import verifica_controlli, CheckOutcome
from verticals.condges.pf_rotate.step1_saldi import write_saldi_banca
from verticals.condges.pf_rotate.step2_azzera import azzera_mese


def test_controlli_su_fixture_minimal_post_step2(minimal_pf_orti_bytes):
    """Post step 2: tutti i controlli devono passare sul fixture minimale."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    # Replicate the witness flow: APRILE già "chiuso" nel fixture (entrate vuote),
    # quindi step 2 ulteriore è no-op. Eseguilo lo stesso per simmetria.
    azzera_mese(wb, mese_chiuso=4)

    report = verifica_controlli(wb)

    assert report.n_err == 0, (
        f"Errori inattesi: {[r for r in report.results if r.outcome == CheckOutcome.ERR]}"
    )


def test_controllo_1_c4_must_be_hardcoded(minimal_pf_orti_bytes):
    """Se C4 fosse formula → check #1 ERR."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    wb["Piano Finanziario"]["C4"] = "=C35"  # vandalismo

    report = verifica_controlli(wb)
    check_1 = next(r for r in report.results if r.check_id == "C1")
    assert check_1.outcome == CheckOutcome.ERR


def test_controllo_3_cascade_d4_eq_c37(minimal_pf_orti_bytes):
    """D4 cascade = C37 + r29 chain. Se cambio D4 a un numero hardcoded → ERR."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    wb["Piano Finanziario"]["D4"] = 999999.0  # rompe la cascade

    report = verifica_controlli(wb)
    check_3 = next(r for r in report.results if r.check_id == "C3")
    assert check_3.outcome == CheckOutcome.ERR


def test_controlli_su_intur_style_fixture(intur_pf_bytes):
    """Verifica engine layout-aware su INTUR-style layout."""
    wb = openpyxl.load_workbook(BytesIO(intur_pf_bytes), data_only=False)
    write_saldi_banca(
        wb,
        mese_chiuso=3,  # MARZO
        data_saldo=date(2026, 3, 31),
        saldi={"MPS": 682801.07, "Intesa": 1457.78, "Sella": 35186.34},
    )
    azzera_mese(wb, mese_chiuso=3)
    report = verifica_controlli(wb)
    assert report.n_err == 0, (
        f"Errori: {[r for r in report.results if r.outcome == CheckOutcome.ERR]}"
    )
