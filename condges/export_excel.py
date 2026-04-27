"""Export tesoreria data to a clean, printable Excel file.

No yellow highlights — clean muted palette only.

Usage:
    from condges.export_excel import generate_tesoreria_excel
    buf = generate_tesoreria_excel(societa, anno, cashflow_rows, voci_data, fornitori, saldi_banca)
    with open("tesoreria.xlsx", "wb") as f:
        f.write(buf.getvalue())
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from condges.cashflow import CashflowRow

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# ── Style constants (clean, no yellow) ────────────────────────────────────────
FONT_HEADER = Font(name="Arial", bold=True, size=11)
FONT_NORMAL = Font(name="Arial", size=10)
FONT_BOLD = Font(name="Arial", bold=True, size=10)
FONT_PREVISIONE = Font(name="Arial", size=10, color="0000FF")
FONT_DANGER = Font(name="Arial", bold=True, size=10, color="CC0000")
FILL_HEADER = PatternFill("solid", fgColor="D9E1F2")
FILL_ENTRATE = PatternFill("solid", fgColor="E2EFDA")
FILL_USCITE = PatternFill("solid", fgColor="FCE4D6")
FILL_TOTALE = PatternFill("solid", fgColor="DDDDDD")
FILL_DANGER = PatternFill("solid", fgColor="FFC7CE")
EUR_FMT = '#,##0;(#,##0);"-"'

# Additional helpers used internally
_FONT_TITLE = Font(name="Arial", bold=True, size=13)
_FONT_SMALL_GREY = Font(name="Arial", size=9, color="888888")
_FONT_SECTION = Font(name="Arial", bold=True, size=11)
_FONT_BOLD_DANGER = Font(name="Arial", bold=True, size=10, color="CC0000")
_FONT_OK = Font(name="Arial", bold=True, size=10, color="217346")
_FONT_WARN = Font(name="Arial", bold=True, size=10, color="7F6000")
_FILL_WARNING = PatternFill("solid", fgColor="FFEB9C")
_FILL_OK = PatternFill("solid", fgColor="C6EFCE")


def _set_header(ws, row: int, col: int, value, width: float | None = None):
    cell = ws.cell(row, col, value)
    cell.font = FONT_HEADER
    cell.fill = FILL_HEADER
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if width is not None:
        ws.column_dimensions[get_column_letter(col)].width = width
    return cell


def _eur(ws, row: int, col: int, value, font=None):
    cell = ws.cell(row, col, value)
    cell.number_format = EUR_FMT
    if font:
        cell.font = font
    return cell


# ── Sheet 1: Proiezione Cashflow ──────────────────────────────────────────────

def _build_cashflow_sheet(
    wb: Workbook,
    societa: str,
    anno: int,
    cashflow_rows: list[CashflowRow],
    saldi_banca: dict[str, float] | None,
):
    ws = wb.create_sheet("Proiezione Cashflow")

    # Title
    ws.merge_cells("A1:N1")
    ws["A1"] = f"Proiezione Cashflow {societa} — {anno}"
    ws["A1"].font = _FONT_TITLE

    # Saldi banca note
    if saldi_banca:
        note = "Saldi banca: " + " | ".join(
            f"{b}: €{int(v):,}" for b, v in saldi_banca.items()
        )
    else:
        note = ""
    ws.merge_cells("A2:N2")
    ws["A2"] = note
    ws["A2"].font = _FONT_SMALL_GREY

    # ── Column headers ────────────────────────────────────────────────────────
    # Col A = label, B+ = months
    # Determine which months appear in data
    months = sorted({r.mese for r in cashflow_rows})
    n_months = len(months)

    ws.column_dimensions["A"].width = 22
    row = 4

    # Month name sub-headers
    ws.cell(row, 1, "").fill = FILL_HEADER
    for i, mese in enumerate(months):
        col = i + 2
        _set_header(ws, row, col, MESI[mese - 1], width=13)

    # ── Row labels and data ───────────────────────────────────────────────────
    labels = [
        ("Saldo iniziale", None),
        ("+ Entrate", FILL_ENTRATE),
        ("- Uscite PF", FILL_USCITE),
        ("- Fornitori", FILL_USCITE),
        ("Netto mese", None),
        ("SALDO FINE MESE", FILL_TOTALE),
        ("Stato", None),
    ]

    field_map = [
        "saldo_iniziale",
        "entrate",
        "uscite_pf",
        "uscite_fornitori",
        "netto",
        "saldo_fine",
        "stato",
    ]

    # Index cashflow_rows by mese
    cf_by_mese = {r.mese: r for r in cashflow_rows}

    for label_idx, (label, fill) in enumerate(labels):
        r = row + 1 + label_idx
        cell = ws.cell(r, 1, label)

        is_saldo_fine = label == "SALDO FINE MESE"
        is_stato = label == "Stato"

        if is_saldo_fine:
            cell.font = FONT_BOLD
        elif is_stato:
            cell.font = FONT_NORMAL
        else:
            cell.font = FONT_NORMAL

        if fill:
            cell.fill = fill

        for i, mese in enumerate(months):
            col = i + 2
            cf = cf_by_mese.get(mese)
            if cf is None:
                continue

            field = field_map[label_idx]
            value = getattr(cf, field)

            if is_stato:
                data_cell = ws.cell(r, col, value)
                if value == "PERICOLO":
                    data_cell.font = FONT_DANGER
                    data_cell.fill = FILL_DANGER
                elif value == "ATTENZIONE":
                    data_cell.font = _FONT_WARN
                    data_cell.fill = _FILL_WARNING
                else:
                    data_cell.font = _FONT_OK
                    data_cell.fill = _FILL_OK
                data_cell.alignment = Alignment(horizontal="center")
            elif is_saldo_fine:
                if value is not None and value < 0:
                    data_cell = _eur(ws, r, col, value, font=_FONT_BOLD_DANGER)
                    data_cell.fill = FILL_DANGER
                else:
                    data_cell = _eur(ws, r, col, value, font=FONT_BOLD)
                    data_cell.fill = FILL_TOTALE
            else:
                data_cell = _eur(ws, r, col, value, font=FONT_NORMAL)
                if fill:
                    data_cell.fill = fill

    ws.freeze_panes = "B5"
    return ws


# ── Sheet 2: Dettaglio Voci ───────────────────────────────────────────────────

def _build_dettaglio_sheet(
    wb: Workbook,
    societa: str,
    anno: int,
    voci_data: list[dict],
):
    ws = wb.create_sheet("Dettaglio Voci")

    # Title
    ws.merge_cells("A1:AM1")
    ws["A1"] = f"Dettaglio Piano Finanziario {societa} — {anno}"
    ws["A1"].font = _FONT_TITLE

    # ── Build index: voce_id -> {mese -> {previsione, budget, consuntivo}} ────
    # Also preserve order of first appearance of each voce_id
    voce_order: list[str] = []
    voce_meta: dict[str, dict] = {}  # voce_id -> {voce_label, sezione}
    voce_data_index: dict[str, dict[int, dict]] = {}

    for row in voci_data:
        vid = row["voce_id"]
        if vid not in voce_data_index:
            voce_order.append(vid)
            voce_meta[vid] = {
                "voce_label": row.get("voce_label", vid),
                "sezione": row.get("sezione", ""),
            }
            voce_data_index[vid] = {}
        mese = row["mese"]
        voce_data_index[vid][mese] = {
            "previsione": row.get("previsione", 0) or 0,
            "budget": row.get("budget", 0) or 0,
            "consuntivo": row.get("consuntivo", 0) or 0,
        }

    # ── Column headers ────────────────────────────────────────────────────────
    # Col A = Voce, then 3 cols per month (Prev, Budget, Cons)
    HEADER_ROW = 3
    SUB_ROW = 4

    ws.column_dimensions["A"].width = 30

    # Month group headers (merged across 3 sub-cols each)
    for m_idx, mese_name in enumerate(MESI):
        start_col = 2 + m_idx * 3
        end_col = start_col + 2
        start_letter = get_column_letter(start_col)
        end_letter = get_column_letter(end_col)
        ws.merge_cells(f"{start_letter}{HEADER_ROW}:{end_letter}{HEADER_ROW}")
        cell = ws.cell(HEADER_ROW, start_col, mese_name)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center")
        for col in range(start_col, end_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = 11

    # Sub-column headers (Prev / Budget / Cons) × 12
    sub_labels = ["Prev", "Budget", "Cons"]
    for m_idx in range(12):
        for sub_idx, sub_label in enumerate(sub_labels):
            col = 2 + m_idx * 3 + sub_idx
            cell = ws.cell(SUB_ROW, col, sub_label)
            cell.font = Font(name="Arial", bold=True, size=9)
            cell.fill = FILL_HEADER
            cell.alignment = Alignment(horizontal="center")

    # Voce label header
    cell = ws.cell(HEADER_ROW, 1, "Voce")
    cell.font = FONT_HEADER
    cell.fill = FILL_HEADER
    ws.merge_cells(f"A{HEADER_ROW}:A{SUB_ROW}")

    # ── Data rows ──────────────────────────────────────────────────────────────
    data_row = SUB_ROW + 1
    current_sezione = None

    for vid in voce_order:
        meta = voce_meta[vid]
        sezione = meta["sezione"]

        # Section separator row
        if sezione != current_sezione:
            current_sezione = sezione
            fill = FILL_ENTRATE if sezione == "ENTRATE" else FILL_USCITE
            total_cols = 1 + 12 * 3
            ws.merge_cells(f"A{data_row}:{get_column_letter(total_cols)}{data_row}")
            cell = ws.cell(data_row, 1, f"── {sezione} ──")
            cell.font = _FONT_SECTION
            cell.fill = fill
            data_row += 1

        ws.cell(data_row, 1, meta["voce_label"]).font = FONT_NORMAL

        mese_data = voce_data_index[vid]
        for m_idx in range(12):
            mese = m_idx + 1
            md = mese_data.get(mese, {"previsione": 0, "budget": 0, "consuntivo": 0})
            base_col = 2 + m_idx * 3

            prev_cell = _eur(ws, data_row, base_col, md["previsione"] or None, font=FONT_PREVISIONE)
            _eur(ws, data_row, base_col + 1, md["budget"] or None, font=FONT_NORMAL)
            cons_cell = _eur(ws, data_row, base_col + 2, md["consuntivo"] or None, font=FONT_BOLD)
            _ = prev_cell, cons_cell  # used for formatting, referenced above

        data_row += 1

    ws.freeze_panes = "B5"
    return ws


# ── Sheet 3: Fornitori ────────────────────────────────────────────────────────

def _build_fornitori_sheet(wb: Workbook, fornitori: list[dict]):
    ws = wb.create_sheet("Fornitori")

    ws.merge_cells("A1:Z1")
    ws["A1"] = "Scadenzario Fornitori"
    ws["A1"].font = _FONT_TITLE

    if not fornitori:
        return ws

    # Detect month columns from first row
    sample = fornitori[0]
    mese_keys = sorted(
        (k for k in sample if k.startswith("mese_")),
        key=lambda k: int(k.split("_")[1]),
    )

    # Sort by totale descending
    sorted_fornitori = sorted(
        fornitori,
        key=lambda r: r.get("totale", 0) or 0,
        reverse=True,
    )

    # Headers
    HEADER_ROW = 3
    fixed_headers = ["Fornitore", "Totale", "Scaduto"]
    for col, h in enumerate(fixed_headers, 1):
        _set_header(ws, HEADER_ROW, col, h)

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14

    for i, mk in enumerate(mese_keys):
        col = len(fixed_headers) + 1 + i
        try:
            mese_num = int(mk.split("_")[1])
            label = MESI[mese_num - 1] if 1 <= mese_num <= 12 else mk
        except (ValueError, IndexError):
            label = mk
        _set_header(ws, HEADER_ROW, col, label, width=12)

    # Data rows
    for r_idx, forn in enumerate(sorted_fornitori):
        r = HEADER_ROW + 1 + r_idx
        ws.cell(r, 1, forn.get("fornitore", "")).font = FONT_NORMAL

        totale = forn.get("totale", 0) or 0
        scaduto = forn.get("scaduto", 0) or 0

        _eur(ws, r, 2, totale, font=FONT_BOLD)
        scaduto_cell = _eur(ws, r, 3, scaduto, font=FONT_NORMAL)
        if scaduto and scaduto > 0:
            scaduto_cell.font = FONT_DANGER
            scaduto_cell.fill = FILL_DANGER

        for i, mk in enumerate(mese_keys):
            col = len(fixed_headers) + 1 + i
            val = forn.get(mk, 0) or 0
            _eur(ws, r, col, val or None, font=FONT_NORMAL)

    return ws


# ── Public API ────────────────────────────────────────────────────────────────

def generate_tesoreria_excel(
    societa: str,
    anno: int,
    cashflow_rows: list[CashflowRow],
    voci_data: list[dict],
    fornitori: list[dict] | None = None,
    saldi_banca: dict[str, float] | None = None,
) -> BytesIO:
    """Generate a clean tesoreria Excel workbook.

    Args:
        societa: Legal entity (ORTI or INTUR).
        anno: Year (e.g. 2026).
        cashflow_rows: List of CashflowRow from cashflow.project_cashflow().
        voci_data: Flat list of dicts, one per (voce_id, mese) combination.
            Required keys: voce_id, voce_label, sezione, mese (1-12),
            previsione, budget, consuntivo.
        fornitori: Optional list of supplier dicts with keys:
            fornitore, totale, scaduto, mese_1..mese_N.
        saldi_banca: Optional dict mapping banca_id -> saldo.

    Returns:
        BytesIO buffer containing the XLSX file.
    """
    wb = Workbook()
    wb.remove(wb.active)

    _build_cashflow_sheet(wb, societa, anno, cashflow_rows, saldi_banca)
    _build_dettaglio_sheet(wb, societa, anno, voci_data)

    if fornitori:
        _build_fornitori_sheet(wb, fornitori)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
