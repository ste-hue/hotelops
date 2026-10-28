"""Avanzamento dei controlli in-foglio al nuovo mese chiuso.

Le formule del foglio Controlli sono statiche: ancorate al mese chiuso di
quando furono scritte, dopo ogni rotation mostrano ERRORE finti sulla colonna
appena chiusa (thread "control-discrepancy"). Qui le riscriviamo spostando il
confine: mesi chiusi = hardcoded, primo mese aperto = catena dal saldo reale.

Le righe da riscrivere si trovano per pattern (non per posizione fissa) e le
righe saldo/periodo si estraggono dalle formule esistenti — layout-agnostico.
Se il foglio o i pattern non ci sono, no-op.

Le formule riscritte sono SEMPRE esplicite cella-per-cella (ISFORMULA su una
cella sola, AND di uguaglianze): il master è un xlsx su Drive che si apre anche
in Google Sheets, dove ISFORMULA su un intervallo dà #N/A / #VALUE!
(2026-10-28). Il layout "matriciale" (SUMPRODUCT/INDEX+MATCH su intervalli,
ORTI_PF_2026-09) viene riconosciuto e sostituito.
"""

from __future__ import annotations

import re

from openpyxl import Workbook
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from verticals.condges.pf_rotate.excel_model import (
    MESI_IT,
    find_month_periods,
    periodo_anno_mese,
    require_periodo,
)

PF_SHEET = "Piano Finanziario"
_SCAN_ROWS = 30
# 'Piano Finanziario'!D4='Piano Finanziario'!C37
_EQ_RE = re.compile(
    r"'Piano Finanziario'!([A-Z]{1,2})(\d+)='Piano Finanziario'!([A-Z]{1,2})(\d+)"
)

# ROUND('Piano Finanziario'!D4:Q4-'Piano Finanziario'!C37:P37 (catena matriciale:
# la prima colonna del minuendo è UNA a destra di quella del sottraendo)
_RANGE_DIFF_RE = re.compile(
    r"'Piano Finanziario'!([A-Z]{1,2})(\d+):[A-Z]{1,2}\d+"
    r"-'Piano Finanziario'!([A-Z]{1,2})(\d+):"
)
_INDEX_RE = re.compile(r"INDEX\('Piano Finanziario'![A-Z]{1,2}(\d+):")

_MESE_NOME = {v: k.lower() for k, v in MESI_IT.items()}


def _ftext(v) -> str | None:
    if isinstance(v, ArrayFormula):
        v = v.text
    return v if isinstance(v, str) and v.startswith("=") else None


def _chain_range(text: str):
    """(saldo_row, periodo_row) se `text` è la catena matriciale, altrimenti None."""
    m = _RANGE_DIFF_RE.search(text)
    if m is None:
        return None
    if column_index_from_string(m.group(1)) != column_index_from_string(m.group(3)) + 1:
        return None  # es. riga 12 = SUM(6:11): stesse colonne, non è la catena
    return int(m.group(2)), int(m.group(4))


def advance_controlli(wb: Workbook, periodo_chiuso: int) -> list[str]:
    """Riscrive i check ancorati al mese nel foglio Controlli. Ritorna le celle toccate."""
    require_periodo(periodo_chiuso, "periodo_chiuso")
    if "Controlli" not in wb.sheetnames or PF_SHEET not in wb.sheetnames:
        return []
    ct = wb["Controlli"]
    cols = find_month_periods(wb[PF_SHEET], header_row=2)
    if periodo_chiuso not in cols:
        return []

    closed_col = cols[periodo_chiuso]
    first_col = min(cols.values())
    last_col = max(cols.values())
    open_col = closed_col + 1
    if open_col > last_col:
        return []  # nessun mese aperto nel foglio: niente catena da riscrivere

    # Individua le 3 righe per pattern sulla formula in colonna B.
    hard_row = chain_start_row = chain_row = label_row = None
    saldo_row = periodo_row = label_src_row = None
    for r in range(1, _SCAN_ROWS + 1):
        v = _ftext(ct.cell(r, 2).value)
        if v is None or PF_SHEET not in v:
            continue
        rng = _chain_range(v)
        if rng is not None:  # catena matriciale (con o senza ISFORMULA)
            chain_row = chain_row or r
            saldo_row, periodo_row = rng
            continue
        if "ISFORMULA" in v and "INDEX(" in v:
            rows = [int(x) for x in _INDEX_RE.findall(v)]
            if len(rows) >= 2:  # INDEX(D4:Q4,…)=INDEX(C37:P37,…): primo mese aperto
                chain_start_row = chain_start_row or r
                saldo_row, periodo_row = rows[0], rows[1]
            elif rows:  # INDEX(D2:Q2,…): etichetta del primo mese proiettato
                label_row = label_row or r
                label_src_row = rows[0]
            continue
        if "ISFORMULA" in v:
            if hard_row is None:
                hard_row = r
            continue
        m = _EQ_RE.search(v)
        if m is None:
            continue
        if "AND(" in v:
            chain_row = chain_row or r
        else:
            chain_start_row = chain_start_row or r
            saldo_row = int(m.group(2))
            periodo_row = int(m.group(4))

    if saldo_row is None:
        # Senza il check-catena non conosciamo le righe saldo/periodo: no-op.
        return []

    closed_l = get_column_letter(closed_col)
    open_l = get_column_letter(open_col)
    first_l = get_column_letter(first_col)
    last_l = get_column_letter(last_col)
    changed: list[str] = []

    if hard_row is not None:
        # Estrai la riga del saldo iniziale dal check esistente (fallback: saldo_row).
        m = re.search(
            r"ISFORMULA\('Piano Finanziario'![A-Z]{1,2}(\d+)\)",
            _ftext(ct.cell(hard_row, 2).value),
        )
        hard_target_row = int(m.group(1)) if m else saldo_row

        def _isf(c: int) -> str:
            return f"_xlfn.ISFORMULA('Piano Finanziario'!{get_column_letter(c)}{hard_target_row})"

        refs = [f"NOT({_isf(c)})" for c in range(first_col, closed_col + 1)]
        refs += [_isf(c) for c in range(open_col, last_col + 1)]
        ct.cell(hard_row, 1).value = (
            f"{first_l}{hard_target_row}:{closed_l}{hard_target_row} = "
            f"saldi iniziali hardcoded (mesi chiusi), "
            f"{open_l}{hard_target_row}:{last_l}{hard_target_row} = formula (mesi aperti)?"
        )
        ct.cell(hard_row, 2).value = f'=IF(AND({",".join(refs)}),"OK","ERRORE")'
        changed.append(f"B{hard_row}")

    def _eq(col: int) -> str:
        cl = get_column_letter(col)
        prev = get_column_letter(col - 1)
        return f"'Piano Finanziario'!{cl}{saldo_row}='Piano Finanziario'!{prev}{periodo_row}"

    if chain_start_row is not None:
        _, mese_aperto = periodo_anno_mese(periodo_chiuso + 1)
        _, mese_chiuso_cal = periodo_anno_mese(periodo_chiuso)
        ct.cell(chain_start_row, 1).value = (
            f"{open_l}{saldo_row} = {closed_l}{periodo_row} "
            f"({_MESE_NOME[mese_aperto]} parte da saldo reale {_MESE_NOME[mese_chiuso_cal]})?"
        )
        ct.cell(chain_start_row, 2).value = f'=IF({_eq(open_col)},"OK","ERRORE")'
        changed.append(f"B{chain_start_row}")

    if chain_row is not None:
        eqs = ",".join(_eq(c) for c in range(open_col, last_col + 1))
        ct.cell(
            chain_row, 1
        ).value = f"Catena {open_l}{saldo_row}:{last_l}{saldo_row} = mese prec riga {periodo_row}?"
        ct.cell(chain_row, 2).value = f'=IF(AND({eqs}),"OK","ERRORE")'
        changed.append(f"B{chain_row}")

    if label_row is not None:
        ct.cell(label_row, 2).value = f"='Piano Finanziario'!{open_l}{label_src_row}"
        changed.append(f"B{label_row}")

    return changed
