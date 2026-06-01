import csv
from pathlib import Path

import pytest

from verticals.condges.pf_rotate.fornitori_map import load_fornitori, append_fornitore


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    p = tmp_path / "d_fornitori.csv"
    p.write_text(
        "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany,is_excluded,exclude_reason,societa_id\n"
        "100,FAKE SPA,Fake,USCITE_UTENZE,False,False,,ORTI\n"
        "200,DITTA INTUR,Ditta,USCITE_VARIE_EXT,False,False,,INTUR\n"
        "300,EXCLUDED CO,,USCITE_VARIE_EXT,False,True,HPAN25PIANO1,INTUR\n"
    )
    return p


def test_load_fornitori_filter_orti(tmp_csv):
    m = load_fornitori(tmp_csv, societa="ORTI")
    assert 100 in m
    assert 200 not in m
    assert 300 not in m
    assert m[100].voce_id == "USCITE_UTENZE"


def test_load_fornitori_filter_intur_includes_excluded(tmp_csv):
    m = load_fornitori(tmp_csv, societa="INTUR")
    assert 200 in m and 300 in m
    assert m[300].is_excluded is True
    assert m[300].exclude_reason == "HPAN25PIANO1"


def test_append_fornitore_persist(tmp_csv):
    append_fornitore(
        tmp_csv,
        codice_fornitore=999,
        nome_esolver="NEW FORN",
        nome_pf="New Forn",
        voce_id="USCITE_VARIE_EXT",
        societa_id="INTUR",
        is_excluded=False,
        exclude_reason="",
    )
    # Re-leggi
    m = load_fornitori(tmp_csv, societa="INTUR")
    assert 999 in m
    assert m[999].nome_esolver == "NEW FORN"
