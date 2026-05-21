from datetime import date
from io import BytesIO

import openpyxl

from verticals.condges.pf_rotate.step1_saldi import write_saldi_banca


def test_write_saldi_writes_to_cutover_column(minimal_pf_orti_bytes):
    """APRILE chiuso → col C. Saldi vanno in C32/C33."""
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    # pre-stato fixture: C32=251897.54, C33=87439.92, C4=339337.46
    # Aggiorna a un nuovo cutover ipotetico (es. 31/05):
    write_saldi_banca(
        wb,
        mese_chiuso=4,  # ancora APRILE (smoke: identica sovrascrittura)
        data_saldo=date(2026, 4, 30),
        saldi={"MPS": 300000.0, "Intesa": 50000.0},
    )
    assert pf["C32"].value == 300000.0
    assert pf["C33"].value == 50000.0
    assert pf["C4"].value == 350000.0  # hardcoded = somma
    # C35 resta formula
    assert pf["C35"].value == "=SUM(C32:C34)"
    # data scritta in C31
    assert pf["C31"].value == "30/04/2026"


def test_write_saldi_partial_only_known_banks(minimal_pf_orti_bytes):
    """Se passi solo MPS, Intesa resta com'era e il totale C4 riflette la somma osservata."""
    import datetime

    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes), data_only=False)
    pf = wb["Piano Finanziario"]
    pre_c33 = pf["C33"].value  # 87439.92

    write_saldi_banca(
        wb,
        mese_chiuso=4,
        data_saldo=datetime.date(2026, 4, 30),
        saldi={"MPS": 200000.0},
    )
    assert pf["C32"].value == 200000.0
    assert pf["C33"].value == pre_c33  # invariato
    assert pf["C4"].value == 200000.0 + pre_c33
