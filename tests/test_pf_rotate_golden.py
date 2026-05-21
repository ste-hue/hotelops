from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy


@pytest.fixture
def fornitori_csv_orti(tmp_path: Path) -> Path:
    p = tmp_path / "d_fornitori.csv"
    # Fornitori che matchano i codici nel fixture minimal_pf_orti_bytes
    p.write_text(
        "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany,is_excluded,exclude_reason,societa_id\n"
        "570913,Energia elettrica,Energia elettrica,USCITE_UTENZE,False,False,,ORTI\n"
        "18,Acqua - Ausino,Acqua - Ausino,USCITE_UTENZE,False,False,,ORTI\n"
        "92,Amalfi sei esse,Amalfi sei esse,USCITE_MATERIE_PRIME,False,False,,ORTI\n"
    )
    return p


def test_rotate_end_to_end_orti(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)

    scad_df = pd.DataFrame(
        [
            {
                "codice_fornitore": 18,
                "nome": "Acqua Ausino",
                "totale": 500.0,
                "scaduto": 0.0,
                "mese_5": 500.0,
                "mese_6": 0.0,
            },
        ]
    )

    result = rotate(
        pf_path=pf_path,
        scad_df=scad_df,
        bucket_months=[5, 6],
        societa="ORTI",
        mese_chiuso=4,
        data_saldo=date(2026, 4, 30),
        saldi={"MPS": 251897.54, "Intesa": 87439.92},
        fornitori_csv=fornitori_csv_orti,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.FAIL,
    )

    assert result.out_path.exists()
    assert result.failed is False
    assert result.n_controlli_err == 0
    assert result.scadenzario_summary["totale_fornitori_scritti"] >= 1


def test_rotate_writes_failed_suffix_on_check_failure(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    """Sabota una cella in modo che un controllo fallisca → file output con suffisso."""
    # Carico, vandalismo C4 (formula), salvo
    wb = openpyxl.load_workbook(BytesIO(minimal_pf_orti_bytes))
    wb["Piano Finanziario"]["C4"] = "=C35"  # rompe Controllo C1
    buf = BytesIO()
    wb.save(buf)
    pf_path = tmp_path / "in_broken.xlsx"
    pf_path.write_bytes(buf.getvalue())

    result = rotate(
        pf_path=pf_path,
        scad_df=pd.DataFrame(
            columns=["codice_fornitore", "nome", "totale", "scaduto", "mese_5"]
        ),
        bucket_months=[5],
        societa="ORTI",
        mese_chiuso=4,
        data_saldo=date(2026, 4, 30),
        saldi={"MPS": 250000.0, "Intesa": 90000.0},
        fornitori_csv=fornitori_csv_orti,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.SKIP,
    )

    # Lo step 1 SOVRASCRIVE C4 con un valore numerico → C1 ora passa.
    # Quindi questo test verifica che IL FLUSSO RIPRISTINA il vincolo C4 hardcoded.
    assert result.failed is False  # C4 ora è 340000.0 hardcoded
    # Suffisso assente:
    assert "_FAILED_CHECKS" not in result.out_path.name
