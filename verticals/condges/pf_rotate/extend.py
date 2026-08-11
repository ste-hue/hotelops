"""Estensione dell'orizzonte del template PF — spec 2026-08-10.

Aggiunge colonne-mese fino al periodo target copiando il pattern dell'ultima
colonna-mese esistente con traduzione dei riferimenti (Translator). Non tocca
mai i valori esistenti. La colonna TOTALI (se presente, master) viene spostata
a destra e le sue formule ripuntate al nuovo orizzonte.
"""

from __future__ import annotations

import re

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from verticals.condges.pf_rotate.excel_model import (
    MESI_IT,
    find_month_periods,
    periodo_anno_mese,
    require_periodo,
)

_NOME_MESE = {v: k for k, v in MESI_IT.items()}
_HEADER_ROW = 2
_YEAR_ROW = 1

# Fogli-report generati da pf_generator.template (scrivi_da_mappare/scrivi_esclusi):
# 12 colonne mese-NUDO (no anno dichiarato in riga 1) — non sono griglie PF,
# find_month_periods ci solleverebbe sempre "Anno non dichiarato". Match per
# prefisso di titolo (case-sensitive, come i nomi reali): copre anche i
# duplicati auto-rinominati da openpyxl ("DA MAPPARE1", "ESCLUSI1").
_SERVICE_SHEET_PREFIXES = ("DA MAPPARE", "ESCLUSI")

# Riferimento cella A1-style, con eventuali $ (no supporto sheet-qualified: le
# formule della colonna TOTALI osservate nel template sono sempre same-sheet).
_CELL_REF_RE = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def _shift_totali_formula(formula: str, cols_to_shift: set[int], n_new: int) -> str:
    """Ripunta i riferimenti a `cols_to_shift` di `n_new` colonne a destra.

    Usato sulla colonna TOTALI dopo lo spostamento fisico: un riferimento
    all'ultimo mese vecchio (es. K37) o alla vecchia colonna TOTALI stessa
    (es. L12 dentro una formula su un'altra riga, tipo Cash Flow = TOTALE
    ENTRATE - TOTALE USCITE) deve seguire lo shift; i riferimenti al primo
    mese (es. C nel range di un SUM) restano fermi.
    """

    def repl(m: re.Match) -> str:
        dollar_col, col_letters, dollar_row, row = m.groups()
        col_idx = column_index_from_string(col_letters)
        if col_idx in cols_to_shift:
            col_letters = get_column_letter(col_idx + n_new)
        return f"{dollar_col}{col_letters}{dollar_row}{row}"

    return _CELL_REF_RE.sub(repl, formula)


def _extend_sheet(ws: Worksheet, target_periodo: int) -> list[str]:
    titolo = ws.title.strip()
    if titolo.startswith(_SERVICE_SHEET_PREFIXES):
        return [f"skip: {ws.title} (foglio di servizio)"]
    cols = find_month_periods(ws, header_row=_HEADER_ROW)
    if not cols:
        return []
    last_p = max(cols)
    if target_periodo <= last_p:
        return []
    src_col = cols[last_p]

    # TOTALI: colonna non-mese subito dopo l'ultimo mese (solo master).
    totali_col = src_col + 1
    has_totali = isinstance(ws.cell(_HEADER_ROW, totali_col).value, str)
    n_new = target_periodo - last_p
    if has_totali:
        ws.insert_cols(
            totali_col, n_new
        )  # sposta TOTALI a destra, formule NON tradotte
        # NB: le formule TOTALI restano testualmente identiche (=SUM(C6:K6), =K37):
        # i range esistenti non cambiano posizione, quindi restano corrette; si
        # estendono/ripuntano sotto.

    changed: list[str] = []
    for i in range(1, n_new + 1):
        p = last_p + i
        dst_col = src_col + i
        anno, mese = periodo_anno_mese(p)
        ws.cell(_HEADER_ROW, dst_col, _NOME_MESE[mese])
        if mese == 1:
            # marker anno sul primo mese dell'anno nuovo — decorativo (find_month_periods
            # deriva l'anno dal wrap, non da questa cella): se la riga 1 è merged in quel
            # punto (es. ORTI ' Varie ed Eventuali', I1:O1) la cella target è una
            # MergedCell read-only — salta il marker, non l'estensione delle colonne.
            if isinstance(ws.cell(_YEAR_ROW, dst_col), MergedCell):
                changed.append(
                    f"warn: marker anno saltato su '{ws.title}' (riga 1 merged)"
                )
            else:
                ws.cell(_YEAR_ROW, dst_col, anno)
        for r in range(1, ws.max_row + 1):
            v = ws.cell(r, src_col).value
            if isinstance(v, str) and v.startswith("="):
                src_ref = f"{get_column_letter(src_col)}{r}"
                dst_ref = f"{get_column_letter(dst_col)}{r}"
                ws.cell(r, dst_col).value = Translator(
                    v, origin=src_ref
                ).translate_formula(dst_ref)
        changed.append(f"{ws.title}!{get_column_letter(dst_col)} ({anno}-{mese:02d})")

    if has_totali:
        new_totali_col = totali_col + n_new
        # Righe di formula che vivevano su src_col (vecchio ultimo mese) o su
        # totali_col (vecchia colonna TOTALI, riferita da un'altra riga TOTALI,
        # es. Cash Flow = TOTALE ENTRATE - TOTALE USCITE) devono ripuntare di
        # n_new colonne: la prima diventa il nuovo ultimo mese, la seconda
        # diventa il nuovo TOTALI.
        cols_to_shift = {src_col, totali_col}
        for r in range(1, ws.max_row + 1):
            v = ws.cell(r, new_totali_col).value
            if not isinstance(v, str) or not v.startswith("="):
                continue
            v2 = _shift_totali_formula(v, cols_to_shift, n_new)
            if v2 != v:
                ws.cell(r, new_totali_col).value = v2
                changed.append(
                    f"{ws.title}!{get_column_letter(new_totali_col)}{r} (TOTALI)"
                )
    return changed


def extend_to(wb: Workbook, target_periodo: int) -> list[str]:
    """Estende ogni foglio con colonne-mese fino a target_periodo. In-place."""
    require_periodo(target_periodo, "target_periodo")
    changed: list[str] = []
    for name in wb.sheetnames:
        changed += _extend_sheet(wb[name], target_periodo)
    return changed
