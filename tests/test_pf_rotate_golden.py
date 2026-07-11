from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from verticals.condges.pf_rotate.rotate import ScadenzarioVuotoError, rotate
from verticals.condges.pf_rotate.step1_saldi import SaldiIncompletiError
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy


def _minimal_scad_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "codice_fornitore": 18,
                "nome": "Acqua Ausino",
                # convenzione parse_scadenze: debiti negativi (avere)
                "totale": -500.0,
                "scaduto": 0.0,
                "mese_5": -500.0,
                "mese_6": 0.0,
            },
        ]
    )


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
                # convenzione parse_scadenze: debiti negativi (avere)
                "totale": -500.0,
                "scaduto": 0.0,
                "mese_5": -500.0,
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


def test_rotate_hard_fail_missing_required_saldo(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    """Manca un conto obbligatorio (INTESA per ORTI) → hard-fail prima di scrivere."""
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)
    out_dir = tmp_path / "out"

    with pytest.raises(SaldiIncompletiError) as ei:
        rotate(
            pf_path=pf_path,
            scad_df=_minimal_scad_df(),
            bucket_months=[5, 6],
            societa="ORTI",
            mese_chiuso=4,
            data_saldo=date(2026, 4, 30),
            saldi={"MPS": 251897.54},  # manca INTESA (obbligatorio)
            fornitori_csv=fornitori_csv_orti,
            out_dir=out_dir,
            unmapped_policy=UnmappedPolicy.FAIL,
        )
    assert "ORTI/INTESA/2026-04-30" in str(ei.value)
    # Preflight: nessun file prodotto (fallisce prima del lavoro).
    assert not out_dir.exists() or not list(out_dir.glob("*.xlsx"))


def test_rotate_allow_partial_writes_failed_checks(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    """--allow-partial-saldi → scrive comunque, ma marcato _FAILED_CHECKS."""
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)

    result = rotate(
        pf_path=pf_path,
        scad_df=_minimal_scad_df(),
        bucket_months=[5, 6],
        societa="ORTI",
        mese_chiuso=4,
        data_saldo=date(2026, 4, 30),
        saldi={"MPS": 251897.54},  # manca INTESA
        fornitori_csv=fornitori_csv_orti,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.FAIL,
        allow_partial_saldi=True,
    )
    assert result.failed is True
    assert "_FAILED_CHECKS" in result.out_path.name
    assert any("INTESA" in c for c in result.failed_checks)


def test_rotate_exclude_flag_drops_fornitore(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    """`extra_excluded={18}` → il fornitore 18 (unico nello scad) non viene scritto."""
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)

    result = rotate(
        pf_path=pf_path,
        scad_df=_minimal_scad_df(),
        bucket_months=[5, 6],
        societa="ORTI",
        mese_chiuso=4,
        data_saldo=date(2026, 4, 30),
        saldi={"MPS": 251897.54, "Intesa": 87439.92},
        fornitori_csv=fornitori_csv_orti,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.FAIL,
        extra_excluded={18},
    )
    assert result.scadenzario_summary["totale_fornitori_scritti"] == 0
    assert 18 in result.scadenzario_summary["excluded_adhoc"]


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
        scad_df=_minimal_scad_df(),
        bucket_months=[5, 6],
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


def test_rotate_hard_fail_su_scadenzario_vuoto(
    minimal_pf_orti_bytes,
    fornitori_csv_orti,
    tmp_path,
):
    """0 scadenze parsate (export sbagliato) → hard fail PRIMA di toccare il PF.

    Regressione del 2026-07-10: un registro documenti (senza date scadenza) parsava
    a 0 righe e la rotation proseguiva, cancellando le uscite pianificate dei mesi
    aperti senza riscrivere nulla.
    """
    pf_path = tmp_path / "in.xlsx"
    pf_path.write_bytes(minimal_pf_orti_bytes)
    out_dir = tmp_path / "out"

    with pytest.raises(ScadenzarioVuotoError):
        rotate(
            pf_path=pf_path,
            scad_df=pd.DataFrame(
                columns=["codice_fornitore", "nome", "totale", "scaduto"]
            ),
            bucket_months=[],
            societa="ORTI",
            mese_chiuso=4,
            data_saldo=date(2026, 4, 30),
            saldi={"MPS": 250000.0, "Intesa": 90000.0},
            fornitori_csv=fornitori_csv_orti,
            out_dir=out_dir,
            unmapped_policy=UnmappedPolicy.SKIP,
        )

    assert not out_dir.exists(), "nessun file deve essere scritto su scadenzario vuoto"
