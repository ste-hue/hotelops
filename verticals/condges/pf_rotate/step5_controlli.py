"""Step 5 — verifica programmatica dei 22 controlli del foglio Controlli.

Reimplementa la logica dei check come funzioni pure su valori sorgente.
Non dipende da openpyxl `data_only=True` (cache stale dopo edit Python).
Layout-aware: usa find_layout() per rilevare le posizioni di riga dinamicamente
(supporta sia ORTI che INTUR che hanno strutture di riga diverse).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import (
    find_layout,
    find_month_columns,
    is_formula_with_refs,
    resolve_sheet_name,
)

EPS = 1e-2  # tolleranza in euro per i confronti


class CheckOutcome(str, Enum):
    OK = "OK"
    ERR = "ERR"
    INDET = "INDET"  # cella sorgente è formula non valutabile in puro Python


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    outcome: CheckOutcome
    detail: str = ""


@dataclass(frozen=True)
class ControlReport:
    results: list[CheckResult]

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.results if r.outcome == CheckOutcome.OK)

    @property
    def n_err(self) -> int:
        return sum(1 for r in self.results if r.outcome == CheckOutcome.ERR)

    @property
    def n_indet(self) -> int:
        return sum(1 for r in self.results if r.outcome == CheckOutcome.INDET)


def _read_num(ws, ref: str) -> float | None:
    """Read a numeric value from a cell. Returns None if cell is empty or a
    formula-with-refs (cannot evaluate without engine)."""
    cell = ws[ref]
    v = cell.value
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.startswith("="):
        if is_formula_with_refs(cell):
            return None
        # Formula-of-constants — eval safely
        try:
            return float(eval(v[1:], {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            return None
    return None


def _read_num_rc(ws, row: int, col: int) -> float | None:
    """Read a numeric value from a cell by row/col. Returns None if formula-with-refs."""
    cell = ws.cell(row, col)
    v = cell.value
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.startswith("="):
        if is_formula_with_refs(cell):
            return None
        try:
            return float(eval(v[1:], {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            return None
    return None


def _eq(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return math.isclose(a, b, abs_tol=EPS)


def _check_C1_saldo_iniziale_hardcoded(
    wb, cutover_col: str, saldo_row: int
) -> CheckResult:
    pf = wb["Piano Finanziario"]
    ref = f"{cutover_col}{saldo_row}"
    cell = pf[ref]
    bad = is_formula_with_refs(cell)
    return CheckResult(
        "C1",
        f"{ref} = saldo iniziale hardcoded (no formula)",
        CheckOutcome.ERR if bad else CheckOutcome.OK,
        detail=f"{ref} contiene formula" if bad else "",
    )


def _check_C2_cascade_link(
    wb, second_col: str, cutover_col: str, saldo_row: int, saldo_proiettato_row: int
) -> CheckResult:
    pf = wb["Piano Finanziario"]
    d_ref = f"{second_col}{saldo_row}"
    c_ref = f"{cutover_col}{saldo_proiettato_row}"
    d_val = _read_num(pf, d_ref)
    c_val = _read_num(pf, c_ref)
    if d_val is None or c_val is None:
        return CheckResult(
            "C2",
            f"{d_ref} = {c_ref} (cascata)",
            CheckOutcome.INDET,
            "valori non determinabili",
        )
    return CheckResult(
        "C2",
        f"{d_ref} = {c_ref} (cascata)",
        CheckOutcome.OK if _eq(d_val, c_val) else CheckOutcome.ERR,
        detail=f"{d_ref}={d_val}, {c_ref}={c_val}",
    )


def _check_C3_cascade_chain(wb, tail_cols: list[str], saldo_row: int) -> CheckResult:
    """Verifica che tutte le colonne tail (escluso cutover) abbiano formule di cascata a saldo_row."""
    pf = wb["Piano Finanziario"]
    for col in tail_cols:
        cell = pf[f"{col}{saldo_row}"]
        if not is_formula_with_refs(cell):
            return CheckResult(
                "C3",
                f"Catena {tail_cols[0]}{saldo_row}:{tail_cols[-1]}{saldo_row} = mese prec",
                CheckOutcome.ERR,
                detail=f"{col}{saldo_row}={cell.value!r} non è formula di cascata",
            )
    chain_label = (
        f"{tail_cols[0]}{saldo_row}:{tail_cols[-1]}{saldo_row}" if tail_cols else "—"
    )
    return CheckResult("C3", f"Catena {chain_label} = mese prec", CheckOutcome.OK)


def _check_totale_entrate(
    wb, col_letters: list[str], totale_entrate_row: int, entrate_rows: list[int]
) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    err = []
    indet = False
    for col in col_letters:
        total = _read_num_rc(pf, totale_entrate_row, _col_idx(col))
        parts = [_read_num_rc(pf, r, _col_idx(col)) for r in entrate_rows]
        if total is None or any(p is None for p in parts):
            indet = True
            continue
        if not _eq(total, sum(parts)):
            err.append(f"{col}{totale_entrate_row}={total} vs SUM={sum(parts)}")
    if err:
        return [
            CheckResult(
                "C4",
                f"Totale Entrate r{totale_entrate_row} per mesi",
                CheckOutcome.ERR,
                "; ".join(err),
            )
        ]
    if indet:
        return [
            CheckResult(
                "C4", f"Totale Entrate r{totale_entrate_row}", CheckOutcome.INDET
            )
        ]
    return [
        CheckResult(
            "C4", f"Totale Entrate r{totale_entrate_row} per mesi", CheckOutcome.OK
        )
    ]


def _check_totale_uscite(
    wb, col_letters: list[str], totale_uscite_row: int, uscite_rows: list[int]
) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    err = []
    indet = False
    for col in col_letters:
        total = _read_num_rc(pf, totale_uscite_row, _col_idx(col))
        parts = [_read_num_rc(pf, r, _col_idx(col)) for r in uscite_rows]
        if total is None or any(p is None for p in parts):
            indet = True
            continue
        if not _eq(total, sum(parts)):
            err.append(f"{col}{totale_uscite_row}={total} vs SUM={sum(parts)}")
    if err:
        return [
            CheckResult(
                "C5",
                f"Totale Uscite r{totale_uscite_row}",
                CheckOutcome.ERR,
                "; ".join(err),
            )
        ]
    if indet:
        return [
            CheckResult("C5", f"Totale Uscite r{totale_uscite_row}", CheckOutcome.INDET)
        ]
    return [CheckResult("C5", f"Totale Uscite r{totale_uscite_row}", CheckOutcome.OK)]


def _check_cashflow(
    wb,
    col_letters: list[str],
    cashflow_row: int,
    totale_entrate_row: int,
    totale_uscite_row: int,
) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    err = []
    indet = False
    for col in col_letters:
        cf = _read_num_rc(pf, cashflow_row, _col_idx(col))
        ent = _read_num_rc(pf, totale_entrate_row, _col_idx(col))
        usc = _read_num_rc(pf, totale_uscite_row, _col_idx(col))
        if any(v is None for v in (cf, ent, usc)):
            indet = True
            continue
        if not _eq(cf, ent - usc):
            err.append(f"{col}{cashflow_row}={cf} ≠ {ent}-{usc}")
    if err:
        return [
            CheckResult(
                "C6",
                f"Cash Flow r{cashflow_row} = r{totale_entrate_row} - r{totale_uscite_row}",
                CheckOutcome.ERR,
                "; ".join(err),
            )
        ]
    if indet:
        return [CheckResult("C6", f"Cash Flow r{cashflow_row}", CheckOutcome.INDET)]
    return [
        CheckResult(
            "C6",
            f"Cash Flow r{cashflow_row} = r{totale_entrate_row} - r{totale_uscite_row}",
            CheckOutcome.OK,
        )
    ]


# Voce -> (master_row, detail_sheet_aliases, detail_row).
VOCE_LINKS = [
    ("C7", "Salari", 14, "Salari e Stipendi", 4),
    ("C8", "Utenze", 15, "Utenze", 3),
    ("C9", "Materie Prime", 16, ["Materie Prime-Consumo ", "Materie Prime-Conumo "], 3),
    ("C10", "Tasse", 17, "Tasse e Imposte", 3),
    ("C11", "Commissioni", 18, "Commisisoni Portali", 3),
    ("C12", "Mutui", 19, "Mutui e Finaziamenti", 3),
    ("C13", "Consulenze", 20, "Consulenze", 3),
    ("C14", "Godimento", 21, "Godimento Beni di Terzi", 4),
    ("C15", "Varie", 22, " Varie ed Eventuali", 3),
    ("C16", "Canoni", 23, "Canoni e servizi", 4),
]


def _check_voce_link(
    wb, check_id, voce_label, master_row, alias_spec, detail_row, col_letters: list[str]
):
    pf = wb["Piano Finanziario"]
    name = resolve_sheet_name(
        wb, [alias_spec] if isinstance(alias_spec, str) else alias_spec
    )
    if name is None:
        return CheckResult(
            check_id,
            f"Riga {master_row} — {voce_label}",
            CheckOutcome.INDET,
            "foglio dettaglio assente",
        )
    detail = wb[name]
    err_cols = []
    for col in col_letters:
        col_i = _col_idx(col)
        m_val = _read_num_rc(pf, master_row, col_i)
        d_val = _read_num_rc(detail, detail_row, col_i)
        if m_val is None or d_val is None:
            continue
        if voce_label == "Materie Prime":
            if m_val + EPS < d_val:
                err_cols.append(f"{col}: master={m_val} < detail={d_val}")
        else:
            if not _eq(m_val, d_val):
                err_cols.append(f"{col}: master={m_val} vs detail={d_val}")
    if err_cols:
        return CheckResult(
            check_id,
            f"Riga {master_row} — {voce_label}",
            CheckOutcome.ERR,
            "; ".join(err_cols),
        )
    return CheckResult(check_id, f"Riga {master_row} — {voce_label}", CheckOutcome.OK)


def _check_saldo_proiettato_structural(
    wb, saldo_proiettato_row: int, col_letters: list[str]
) -> CheckResult:
    """Verifica strutturale: le celle saldo proiettato devono essere formule con riferimenti."""
    pf = wb["Piano Finanziario"]
    err = []
    for col in col_letters:
        cell = pf.cell(saldo_proiettato_row, _col_idx(col))
        if not is_formula_with_refs(cell):
            err.append(f"{col}{saldo_proiettato_row}={cell.value!r} non è formula")
    if err:
        return CheckResult(
            "C17",
            f"Saldo proiettato r{saldo_proiettato_row} = formula strutturale",
            CheckOutcome.ERR,
            "; ".join(err),
        )
    return CheckResult(
        "C17",
        f"Saldo proiettato r{saldo_proiettato_row} = formula strutturale",
        CheckOutcome.OK,
    )


def _check_colonna_totali(
    wb,
    totale_entrate_row: int,
    totale_uscite_row: int,
    cashflow_row: int,
    col_letters: list[str],
) -> list[CheckResult]:
    """Controlla la colonna TOTALI se presente. Se non trovata, INDET."""
    pf = wb["Piano Finanziario"]
    # Cerca colonna con header "TOTALI" in riga 2
    totali_col = None
    for c in range(1, pf.max_column + 1):
        v = pf.cell(2, c).value
        if isinstance(v, str) and v.strip().upper() == "TOTALI":
            totali_col = c
            break

    if totali_col is None:
        return [
            CheckResult(
                "C18",
                f"L{totale_entrate_row} = SUM(col mesi)",
                CheckOutcome.INDET,
                "colonna TOTALI non presente",
            ),
            CheckResult(
                "C19",
                f"L{totale_uscite_row} = SUM(col mesi)",
                CheckOutcome.INDET,
                "colonna TOTALI non presente",
            ),
            CheckResult(
                "C20",
                f"L{cashflow_row} = L{totale_entrate_row} - L{totale_uscite_row}",
                CheckOutcome.INDET,
                "colonna TOTALI non presente",
            ),
        ]

    results = []
    col_indices = [_col_idx(c) for c in col_letters]

    # C18: totali_col × totale_entrate_row = SUM(col mesi × totale_entrate_row)
    l_ent = _read_num_rc(pf, totale_entrate_row, totali_col)
    parts_ent = [_read_num_rc(pf, totale_entrate_row, ci) for ci in col_indices]
    if l_ent is not None and all(p is not None for p in parts_ent):
        ok = _eq(l_ent, sum(parts_ent))
        results.append(
            CheckResult(
                "C18",
                f"Totali r{totale_entrate_row}",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"totali={l_ent} vs SUM={sum(parts_ent)}",
            )
        )
    else:
        results.append(
            CheckResult("C18", f"Totali r{totale_entrate_row}", CheckOutcome.INDET)
        )

    # C19: totali_col × totale_uscite_row
    l_usc = _read_num_rc(pf, totale_uscite_row, totali_col)
    parts_usc = [_read_num_rc(pf, totale_uscite_row, ci) for ci in col_indices]
    if l_usc is not None and all(p is not None for p in parts_usc):
        ok = _eq(l_usc, sum(parts_usc))
        results.append(
            CheckResult(
                "C19",
                f"Totali r{totale_uscite_row}",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"totali={l_usc} vs SUM={sum(parts_usc)}",
            )
        )
    else:
        results.append(
            CheckResult("C19", f"Totali r{totale_uscite_row}", CheckOutcome.INDET)
        )

    # C20: totali_col × cashflow_row = totali_ent - totali_usc
    l_cf = _read_num_rc(pf, cashflow_row, totali_col)
    if l_cf is not None and l_ent is not None and l_usc is not None:
        ok = _eq(l_cf, l_ent - l_usc)
        results.append(
            CheckResult(
                "C20",
                f"Totali r{cashflow_row} = r{totale_entrate_row} - r{totale_uscite_row}",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"cf={l_cf} vs {l_ent}-{l_usc}",
            )
        )
    else:
        results.append(
            CheckResult("C20", f"Totali r{cashflow_row}", CheckOutcome.INDET)
        )

    return results


def _col_idx(col_letter: str) -> int:
    """Convert column letter(s) to 1-based index."""
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(col_letter)


def verifica_controlli(wb: Workbook) -> ControlReport:
    """Esegui i check sul workbook in input. Layout-aware. Niente cache, puro Python."""
    pf = wb["Piano Finanziario"]
    layout = find_layout(wb)
    month_cols = find_month_columns(pf, header_row=2)

    ordered_mesi = sorted(month_cols.keys())
    col_letters = [get_column_letter(month_cols[m]) for m in ordered_mesi]
    cutover_col = col_letters[0]
    tail_cols = col_letters[1:]

    R_S = layout.saldo_iniziale_row
    R_TE = layout.totale_entrate_row
    R_TU = layout.totale_uscite_row
    R_CF = layout.cashflow_row
    R_SP = layout.saldo_proiettato_row

    results: list[CheckResult] = []
    results.append(_check_C1_saldo_iniziale_hardcoded(wb, cutover_col, R_S))
    if tail_cols:
        results.append(_check_C2_cascade_link(wb, tail_cols[0], cutover_col, R_S, R_SP))
    results.append(_check_C3_cascade_chain(wb, tail_cols, R_S))
    results.extend(_check_totale_entrate(wb, col_letters, R_TE, layout.entrate_rows))
    results.extend(_check_totale_uscite(wb, col_letters, R_TU, layout.uscite_rows))
    results.extend(_check_cashflow(wb, col_letters, R_CF, R_TE, R_TU))
    for check_id, label, m_row, alias, d_row in VOCE_LINKS:
        results.append(
            _check_voce_link(wb, check_id, label, m_row, alias, d_row, col_letters)
        )
    results.append(_check_saldo_proiettato_structural(wb, R_SP, col_letters))
    results.extend(_check_colonna_totali(wb, R_TE, R_TU, R_CF, col_letters))
    return ControlReport(results=results)
