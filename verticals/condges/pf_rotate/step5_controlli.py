"""Step 5 — verifica programmatica dei 22 controlli del foglio Controlli.

Reimplementa la logica dei check come funzioni pure su valori sorgente.
Non dipende da openpyxl `data_only=True` (cache stale dopo edit Python).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from openpyxl import Workbook

from verticals.condges.pf_rotate.excel_model import (
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


def _eq(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return math.isclose(a, b, abs_tol=EPS)


def _check_C1_c4_hardcoded(wb) -> CheckResult:
    pf = wb["Piano Finanziario"]
    cell = pf["C4"]
    bad = is_formula_with_refs(cell)
    return CheckResult(
        "C1",
        "C4 = saldo iniziale hardcoded (no formula)",
        CheckOutcome.ERR if bad else CheckOutcome.OK,
        detail="C4 contiene formula" if bad else "",
    )


def _check_C2_d4_eq_c37(wb) -> CheckResult:
    pf = wb["Piano Finanziario"]
    d4 = _read_num(pf, "D4")
    c37 = _read_num(pf, "C37")
    if d4 is None or c37 is None:
        return CheckResult(
            "C2", "D4 = C37", CheckOutcome.INDET, "valori non determinabili"
        )
    return CheckResult(
        "C2",
        "D4 = C37 (cascata)",
        CheckOutcome.OK if _eq(d4, c37) else CheckOutcome.ERR,
        detail=f"D4={d4}, C37={c37}",
    )


def _check_C3_cascade_chain(wb) -> CheckResult:
    """Verifica che D4..K4 siano formule di cascata (riferimenti al mese precedente r37).

    Una cella hardcoded in D4..K4 rompe la cascata — check ERR.
    """
    pf = wb["Piano Finanziario"]
    cols = "CDEFGHIJK"
    for i in range(1, len(cols)):
        cur = cols[i]
        cell = pf[f"{cur}4"]
        # La cascata richiede una formula con riferimento (al mese precedente r37).
        # Se la cella è un valore hardcoded (non formula con ref) → cascata rotta.
        if not is_formula_with_refs(cell):
            return CheckResult(
                "C3",
                "Catena D4:K4 = mese prec r37",
                CheckOutcome.ERR,
                detail=f"{cur}4={cell.value!r} non è formula di cascata",
            )
    return CheckResult("C3", "Catena D4:K4 = mese prec r37", CheckOutcome.OK)


def _check_totale_entrate(wb) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    cols = "CDEFGHIJK"
    results: list[CheckResult] = []
    for col in cols:
        total = _read_num(pf, f"{col}12")
        parts = [_read_num(pf, f"{col}{r}") for r in range(6, 12)]
        if total is None or any(p is None for p in parts):
            results.append(
                CheckResult(
                    f"E{col}",
                    f"{col}12 = SUM({col}6:{col}11)",
                    CheckOutcome.INDET,
                    f"col {col}",
                )
            )
            continue
        expected = sum(parts)
        outcome = CheckOutcome.OK if _eq(total, expected) else CheckOutcome.ERR
        results.append(
            CheckResult(
                f"E{col}",
                f"{col}12 = SUM({col}6:{col}11)",
                outcome,
                f"{total} vs {expected}",
            )
        )
    # Aggregato in un singolo CheckResult per § "Totale Entrate (riga 12)"
    err_cols = [r for r in results if r.outcome == CheckOutcome.ERR]
    if err_cols:
        return [
            CheckResult(
                "C4",
                "Totale Entrate r12 per mesi C:K",
                CheckOutcome.ERR,
                detail="; ".join(r.detail for r in err_cols),
            )
        ]
    if any(r.outcome == CheckOutcome.INDET for r in results):
        return [CheckResult("C4", "Totale Entrate r12", CheckOutcome.INDET)]
    return [CheckResult("C4", "Totale Entrate r12 per mesi C:K", CheckOutcome.OK)]


def _check_totale_uscite(wb) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    cols = "CDEFGHIJK"
    err = []
    indet = False
    for col in cols:
        total = _read_num(pf, f"{col}27")
        parts = [_read_num(pf, f"{col}{r}") for r in range(14, 27)]
        if total is None or any(p is None for p in parts):
            indet = True
            continue
        if not _eq(total, sum(parts)):
            err.append(f"{col}27={total} vs SUM={sum(parts)}")
    if err:
        return [
            CheckResult("C5", "Totale Uscite r27", CheckOutcome.ERR, "; ".join(err))
        ]
    if indet:
        return [CheckResult("C5", "Totale Uscite r27", CheckOutcome.INDET)]
    return [CheckResult("C5", "Totale Uscite r27", CheckOutcome.OK)]


def _check_cashflow(wb) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    cols = "CDEFGHIJK"
    err = []
    indet = False
    for col in cols:
        cf = _read_num(pf, f"{col}29")
        ent = _read_num(pf, f"{col}12")
        usc = _read_num(pf, f"{col}27")
        if any(v is None for v in (cf, ent, usc)):
            indet = True
            continue
        if not _eq(cf, ent - usc):
            err.append(f"{col}29={cf} ≠ {ent}-{usc}")
    if err:
        return [
            CheckResult(
                "C6", "Cash Flow r29 = r12 - r27", CheckOutcome.ERR, "; ".join(err)
            )
        ]
    if indet:
        return [CheckResult("C6", "Cash Flow r29", CheckOutcome.INDET)]
    return [CheckResult("C6", "Cash Flow r29 = r12 - r27", CheckOutcome.OK)]


# Voce -> (master_row, detail_sheet_aliases, detail_row).
# Riga master è una formula =detail!<col><detail_row>. Detail_row è 3 per la
# maggior parte, 4 per Godimento / Canoni (osservato).
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


def _check_voce_link(wb, check_id, voce_label, master_row, alias_spec, detail_row):
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
    for col in "CDEFGHIJK":
        m_val = _read_num(pf, f"{col}{master_row}")
        d_val = _read_num(detail, f"{col}{detail_row}")
        if m_val is None or d_val is None:
            continue  # indeterminate per questa cella
        # Materie Prime usa MAX(detail, X) — qui tollerante: master >= detail
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


def _check_saldo_proiettato(wb) -> CheckResult:
    pf = wb["Piano Finanziario"]
    err = []
    for col in "CDEFGHIJK":
        r37 = _read_num(pf, f"{col}37")
        r4 = _read_num(pf, f"{col}4")
        r29 = _read_num(pf, f"{col}29")
        if any(v is None for v in (r37, r4, r29)):
            continue
        if not _eq(r37, r4 + r29):
            err.append(f"{col}37={r37} ≠ {r4}+{r29}")
    if err:
        return CheckResult(
            "C17",
            "Saldo proiettato r37 = r4 + r29",
            CheckOutcome.ERR,
            "; ".join(err),
        )
    return CheckResult("C17", "Saldo proiettato r37 = r4 + r29", CheckOutcome.OK)


def _check_colonna_totali(wb) -> list[CheckResult]:
    pf = wb["Piano Finanziario"]
    results = []
    # L12 = SUM(C12:K12)
    l12 = _read_num(pf, "L12")
    parts = [_read_num(pf, f"{c}12") for c in "CDEFGHIJK"]
    if l12 is not None and all(p is not None for p in parts):
        ok = _eq(l12, sum(parts))
        results.append(
            CheckResult(
                "C18",
                "L12 = SUM(C12:K12)",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"L12={l12} vs SUM={sum(parts)}",
            )
        )
    else:
        results.append(CheckResult("C18", "L12 = SUM(C12:K12)", CheckOutcome.INDET))
    # L27
    l27 = _read_num(pf, "L27")
    parts27 = [_read_num(pf, f"{c}27") for c in "CDEFGHIJK"]
    if l27 is not None and all(p is not None for p in parts27):
        ok = _eq(l27, sum(parts27))
        results.append(
            CheckResult(
                "C19",
                "L27 = SUM(C27:K27)",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"L27={l27} vs SUM={sum(parts27)}",
            )
        )
    else:
        results.append(CheckResult("C19", "L27 = SUM(C27:K27)", CheckOutcome.INDET))
    # L29 = L12 - L27
    l29 = _read_num(pf, "L29")
    if l29 is not None and l12 is not None and l27 is not None:
        ok = _eq(l29, l12 - l27)
        results.append(
            CheckResult(
                "C20",
                "L29 = L12 - L27",
                CheckOutcome.OK if ok else CheckOutcome.ERR,
                f"L29={l29} vs {l12}-{l27}",
            )
        )
    else:
        results.append(CheckResult("C20", "L29 = L12 - L27", CheckOutcome.INDET))
    return results


def verifica_controlli(wb: Workbook) -> ControlReport:
    """Esegui i 22 check sul workbook in input. Niente cache, puro Python."""
    results: list[CheckResult] = []
    results.append(_check_C1_c4_hardcoded(wb))
    results.append(_check_C2_d4_eq_c37(wb))
    results.append(_check_C3_cascade_chain(wb))
    results.extend(_check_totale_entrate(wb))
    results.extend(_check_totale_uscite(wb))
    results.extend(_check_cashflow(wb))
    for check_id, label, m_row, alias, d_row in VOCE_LINKS:
        results.append(_check_voce_link(wb, check_id, label, m_row, alias, d_row))
    results.append(_check_saldo_proiettato(wb))
    results.extend(_check_colonna_totali(wb))
    return ControlReport(results=results)
