"""Tests per verticals/condges/pf_rotate/interactive_map.py."""

from __future__ import annotations

import pandas as pd
import pytest

from verticals.condges.pf_rotate.fornitori_map import load_fornitori
from verticals.condges.pf_rotate.interactive_map import (
    VOCI_MENU,
    resolve_unmapped_interactive,
)

CSV_HEADER = (
    "codice_fornitore,nome_esolver,nome_pf,voce_id,"
    "is_intercompany,is_excluded,exclude_reason,societa_id\n"
)


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "d_fornitori.csv"
    p.write_text(
        CSV_HEADER
        + "1,FORNITORE NOTO,Fornitore Noto,USCITE_MATERIE_PRIME,False,False,,ORTI\n"
    )
    return p


def _scad(rows):
    return pd.DataFrame(rows, columns=["codice_fornitore", "nome", "totale"])


def _scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_gia_mappati_nessun_prompt(csv_path):
    df = _scad([(1, "FORNITORE NOTO", -100.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted([]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == []


def test_scelta_numerica_persiste(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted(["1"]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == [99]
    rows = load_fornitori(csv_path, "ORTI")
    assert rows[99].voce_id == VOCI_MENU[0]


def test_invio_accetta_suggerimento(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted([""]),
        print_fn=lambda *_: None,
        suggestions={99: ("USCITE_CANONE_PASSIVO", "dalle fatture: classe 65")},
    )
    assert resolved == [99]
    assert load_fornitori(csv_path, "ORTI")[99].voce_id == "USCITE_CANONE_PASSIVO"


def test_e_esclude(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted(["e"]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == [99]
    assert load_fornitori(csv_path, "ORTI")[99].is_excluded is True


def test_s_salta_senza_persistere(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted(["s"]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == []
    assert 99 not in load_fornitori(csv_path, "ORTI")


def test_input_invalido_richiede(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted(["xyz", "99", "2"]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == [99]
    assert load_fornitori(csv_path, "ORTI")[99].voce_id == VOCI_MENU[1]


def test_invio_senza_suggerimento_richiede(csv_path):
    df = _scad([(99, "FORNITORE NUOVO", -500.0)])
    resolved = resolve_unmapped_interactive(
        df,
        csv_path,
        "ORTI",
        input_fn=_scripted(["", "3"]),
        print_fn=lambda *_: None,
        suggestions={},
    )
    assert resolved == [99]
    assert load_fornitori(csv_path, "ORTI")[99].voce_id == VOCI_MENU[2]
