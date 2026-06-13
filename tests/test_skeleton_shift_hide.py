"""Test hide_past_months: nasconde i mesi passati senza perdere dati/formule."""

from __future__ import annotations

import openpyxl

from verticals.condges.skeleton_shift import hide_past_months


def _ws_con_mesi(first_col: int):
    """ws con header mesi riga 2 a partire da first_col: SET..DIC (18 mesi rolling)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    labels = [
        "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
        "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
        "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
    ]
    for i, lab in enumerate(labels):
        ws.cell(row=2, column=first_col + i, value=lab)
        ws.cell(row=6, column=first_col + i, value=1000)  # dati, non devono sparire
    return wb, ws


def test_hide_past_months_master():
    wb, ws = _ws_con_mesi(first_col=3)  # C..R
    # primo mese aperto = MAGGIO (5). MAGGIO è la colonna K (3+8=11).
    hide_past_months(ws, 3, 18, primo_mese_aperto=5)
    # C..J (3..10) nascoste, K (11=MAGGIO) e oltre visibili
    assert ws.column_dimensions["C"].hidden is True
    assert ws.column_dimensions["J"].hidden is True
    assert ws.column_dimensions["K"].hidden is False
    # i dati restano (solo nascosti, mai cancellati)
    assert ws.cell(row=6, column=3).value == 1000


def test_hide_past_months_no_target_noop():
    # nessun header MAGGIO → no-op, niente nascosto
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=2, column=3, value="GENNAIO")
    hide_past_months(ws, 3, 18, primo_mese_aperto=5)
    assert ws.column_dimensions["C"].hidden is False
