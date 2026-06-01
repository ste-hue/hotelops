from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from verticals.condges.pf_rotate.step3_scadenzario import (
    UnmappedFornitoriError,
    UnmappedPolicy,
    apply_scadenzario,
)


@pytest.fixture
def tmp_fornitori_csv(tmp_path: Path) -> Path:
    p = tmp_path / "d_fornitori.csv"
    p.write_text(
        "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany,is_excluded,exclude_reason,societa_id\n"
        "100,KNOWN SPA,Known,USCITE_UTENZE,False,False,,ORTI\n"
    )
    return p


def _make_scad_df(codici: list[int]) -> tuple[pd.DataFrame, list[int]]:
    return pd.DataFrame(
        [
            {
                "codice_fornitore": c,
                "nome": f"Forn{c}",
                "totale": 1000.0,
                "scaduto": 0.0,
                "mese_5": 1000.0,
                "mese_6": 0.0,
            }
            for c in codici
        ]
    ), [5, 6]


def test_policy_fail_raises_on_unmapped(minimal_pf_orti_bytes, tmp_fornitori_csv):
    scad_df, buckets = _make_scad_df([100, 999])  # 999 unknown
    with pytest.raises(UnmappedFornitoriError) as exc:
        apply_scadenzario(
            pf_bytes=minimal_pf_orti_bytes,
            scad_df=scad_df,
            bucket_months=buckets,
            societa="ORTI",
            fornitori_csv=tmp_fornitori_csv,
            policy=UnmappedPolicy.FAIL,
        )
    assert 999 in exc.value.codici


def test_policy_skip_writes_known_only(minimal_pf_orti_bytes, tmp_fornitori_csv):
    scad_df, buckets = _make_scad_df([100, 999])
    out_bytes, summary = apply_scadenzario(
        pf_bytes=minimal_pf_orti_bytes,
        scad_df=scad_df,
        bucket_months=buckets,
        societa="ORTI",
        fornitori_csv=tmp_fornitori_csv,
        policy=UnmappedPolicy.SKIP,
    )
    assert summary["skipped_unmapped"] == [999]
    # Code 100 (Known → USCITE_UTENZE → foglio Utenze) scritto
    wb = openpyxl.load_workbook(BytesIO(out_bytes))
    ut = wb["Utenze"]
    # cerca riga con codice 100
    found = False
    for r in range(4, 30):
        if ut.cell(r, 1).value == 100:
            found = True
            break
    assert found
