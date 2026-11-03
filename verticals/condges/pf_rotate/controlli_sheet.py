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

import logging
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
# ='Piano Finanziario'!H2 — etichetta "primo mese proiettato" scritta come
# riferimento secco alla riga dei nomi-mese (layout esplicito, ORTI 2026-11).
_LABEL_RE = re.compile(r"^='Piano Finanziario'![A-Z]{1,2}(2)$")

_MESE_NOME = {v: k.lower() for k, v in MESI_IT.items()}
log = logging.getLogger(__name__)


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
        m_lab = _LABEL_RE.match(v)
        if m_lab is not None:
            label_row = label_row or r
            label_src_row = int(m_lab.group(1))
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


# ── Allungamento dell'orizzonte ───────────────────────────────────────────────
#
# I check dei blocchi 2-10 sono ancorati all'orizzonte di quando furono scritti:
# intervalli C:Q (mesi), colonna R (TOTALI), vettore ROW(C1:C15)^0 (15 mesi).
# insert_cols sul master non traduce le formule del foglio Controlli, quindi
# dopo un allungamento la vecchia TOTALI è diventata un mese e i check 9/10
# danno ERRORE finti, mentre gli altri guardano solo fino alla vecchia ultima
# colonna (ORTI_PF_2026-10 → 2029-12, 2026-11-03: 5 ERRORE su 25). Qui si
# ripuntano per foglio: riferimento alla vecchia ultima colonna-mese → nuova
# ultima; alla vecchia TOTALI → nuova TOTALI; conteggio mesi → nuovo conteggio.

# Riferimento sheet-qualified, cella singola o intervallo, nome foglio con o
# senza apici. I riferimenti NON qualificati (COUNTIF(B4:B47)) sono del foglio
# Controlli stesso e restano intatti.
_QREF_RE = re.compile(
    r"(?P<sheet>'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!"
    r"(?P<d1>\$?)(?P<l1>[A-Z]{1,3})(?P<r1>\$?\d+)"
    r"(?::(?P<d2>\$?)(?P<l2>[A-Z]{1,3})(?P<r2>\$?\d+))?"
)
# ROW('Piano Finanziario'!C1:C15)^0 — vettore di 1 lungo quanti sono i mesi.
_ONES_RE = re.compile(
    r"ROW\((?P<sheet>'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!(?P<l>[A-Z]{1,3})1:(?P=l)(?P<n>\d+)\)\^0"
)
# Token colonna/cella nelle etichette di colonna A ("C:Q", "(R)", "R12", "Q37").
_LABEL_TOKEN_RE = re.compile(r"(?<![A-Za-z$])([A-Z]{1,3})(\d*)(?![A-Za-z])")


def _orizzonte_dei_controlli(ct, sheet: str, first_col: int) -> int | None:
    """L'ultima colonna-mese per cui i check sono stati scritti: la più a destra
    fra gli estremi degli intervalli `sheet!<first><r>:<X><r>` (con X ≠ first,
    così il vettore ROW(C1:C15) non conta). None se non ci sono intervalli."""
    ends: list[int] = []
    for r in range(1, ct.max_row + 1):
        text = _ftext(ct.cell(r, 2).value)
        if text is None:
            continue
        for m in _QREF_RE.finditer(text):
            if m.group("sheet").strip("'") != sheet or not m.group("l2"):
                continue
            c1 = column_index_from_string(m.group("l1"))
            c2 = column_index_from_string(m.group("l2"))
            if c1 == first_col and c2 > c1:
                ends.append(c2)
    return max(ends) if ends else None


def widen_controlli(wb: Workbook) -> list[str]:
    """Ripunta i check del foglio Controlli all'orizzonte attuale dei fogli.

    L'orizzonte per cui i check furono scritti si legge dalle formule stesse
    (`_orizzonte_dei_controlli`), non da uno stato "prima": così vale anche per
    un file già allungato in passato senza aggiornare i controlli. Per ogni
    foglio citato: riferimenti alla vecchia ultima colonna-mese → ultima attuale;
    sul master, alla colonna subito dopo (vecchia TOTALI) → TOTALI attuale;
    vettore ROW(C1:C<n>)^0 → nuovo numero di mesi. Poi il blocco 1 (confine
    chiuso/aperto, catena, etichetta) viene riscritto da `advance_controlli`.
    Idempotente. No-op senza foglio Controlli; se dopo l'ultimo mese del master
    non c'è la colonna TOTALI, avvisa e non tocca niente.
    """
    if "Controlli" not in wb.sheetnames or PF_SHEET not in wb.sheetnames:
        return []
    ct = wb["Controlli"]
    cols_pf = find_month_periods(wb[PF_SHEET], header_row=2)
    if not cols_pf:
        return []
    last_pf = max(cols_pf.values())
    hdr = wb[PF_SHEET].cell(2, last_pf + 1).value
    if not (isinstance(hdr, str) and hdr.strip().upper().startswith("TOTAL")):
        log.warning(
            "Controlli non aggiornati: nessuna colonna TOTALI dopo %s in '%s'",
            get_column_letter(last_pf),
            PF_SHEET,
        )
        return []

    # Per foglio: (vecchia ultima, ultima attuale, vecchia TOTALI | None, n vecchio, n nuovo)
    mappe: dict[str, tuple[int, int, int | None, int, int]] = {}
    for name in wb.sheetnames:
        if name == "Controlli":
            continue
        try:
            cols = find_month_periods(wb[name], header_row=2)
        except ValueError:
            continue  # foglio di servizio senza anno: nessun check lo cita
        if not cols:
            continue
        first, last = min(cols.values()), max(cols.values())
        stale = _orizzonte_dei_controlli(ct, name, first)
        if stale is None or stale == last:
            continue
        tot = stale + 1 if name == PF_SHEET else None
        mappe[name] = (stale, last, tot, stale - first + 1, last - first + 1)
    if not mappe:
        return [f"Controlli!{c}" for c in _avanza(wb, ct)]

    def _col(name: str, col: int) -> int:
        stale, last, tot, _, _ = mappe[name]
        if col == stale:
            return last
        if tot is not None and col == tot:
            return last + 1
        return col

    def _ref(m: re.Match) -> str:
        name = m.group("sheet").strip("'")
        if name not in mappe:
            return m.group(0)
        c1 = get_column_letter(_col(name, column_index_from_string(m.group("l1"))))
        out = f"{m.group('sheet')}!{m.group('d1')}{c1}{m.group('r1')}"
        if m.group("l2"):
            c2 = get_column_letter(_col(name, column_index_from_string(m.group("l2"))))
            out += f":{m.group('d2')}{c2}{m.group('r2')}"
        return out

    def _ones(m: re.Match) -> str:
        name = m.group("sheet").strip("'")
        if name not in mappe or int(m.group("n")) != mappe[name][3]:
            return m.group(0)
        return (
            f"ROW({m.group('sheet')}!{m.group('l')}1:{m.group('l')}{mappe[name][4]})^0"
        )

    def _label(m: re.Match) -> str:
        if PF_SHEET not in mappe:
            return m.group(0)
        col = column_index_from_string(m.group(1))
        nuovo = _col(PF_SHEET, col)
        return m.group(0) if nuovo == col else f"{get_column_letter(nuovo)}{m.group(2)}"

    changed: list[str] = []
    for r in range(1, ct.max_row + 1):
        cell = ct.cell(r, 2)
        v = cell.value
        text = _ftext(v)
        if text is not None:
            new = _ONES_RE.sub(_ones, _QREF_RE.sub(_ref, text))
            if new != text:
                cell.value = (
                    ArrayFormula(v.ref, new) if isinstance(v, ArrayFormula) else new
                )
                changed.append(f"Controlli!B{r}")
        a = ct.cell(r, 1).value
        if isinstance(a, str):
            new_a = _LABEL_TOKEN_RE.sub(_label, a)
            if new_a != a:
                ct.cell(r, 1).value = new_a
                changed.append(f"Controlli!A{r}")

    changed += [f"Controlli!{c}" for c in _avanza(wb, ct)]
    return changed


def _avanza(wb: Workbook, ct) -> list[str]:
    """Blocco 1 riscritto per intero sull'orizzonte attuale, se dalle formule
    si legge qual è il mese chiuso."""
    periodo_chiuso = _periodo_chiuso_da_controlli(wb, ct)
    return advance_controlli(wb, periodo_chiuso) if periodo_chiuso is not None else []


def _periodo_chiuso_da_controlli(wb: Workbook, ct) -> int | None:
    """Il mese chiuso secondo il check 'primo mese aperto = riga 37 del mese
    precedente' (`'Piano Finanziario'!I4='Piano Finanziario'!H37` → chiuso = H)."""
    cols = find_month_periods(wb[PF_SHEET], header_row=2)
    per_col = {c: p for p, c in cols.items()}
    for r in range(1, _SCAN_ROWS + 1):
        v = _ftext(ct.cell(r, 2).value)
        if v is None or "AND(" in v:
            continue
        m = _EQ_RE.search(v)
        if m is None:
            continue
        return per_col.get(column_index_from_string(m.group(3)))
    return None
