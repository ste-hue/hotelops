#!/usr/bin/env python3
"""Scadenzario -> PF Updater (Streamlit).

Drop the Esolver 'Situazione sintetica scadenze' Excel,
preview the match vs Piano Finanziario, and write amounts
into ALL PF detail sheets by codice fornitore and voce_id.

Usage:
    streamlit run condges/app_scadenzario.py
"""

from __future__ import annotations

import csv
import re
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import streamlit as st

# -- Config --------------------------------------------------------------------

FORNITORI_CSV = Path(__file__).parent.parent / "core" / "bq" / "dimensioni" / "d_fornitori.csv"

VOCE_TO_SHEET = {
    "USCITE_MATERIE_PRIME": "Materie Prime-Consumo ",
    "USCITE_UTENZE": "Utenze",
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commisisoni Portali",
    "USCITE_MUTUI": "Mutui e Finaziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_VARIE_EXT": " Varie ed Eventuali",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
}

VOCE_LABELS = {
    "USCITE_MATERIE_PRIME": "Materie Prime",
    "USCITE_UTENZE": "Utenze",
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commissioni",
    "USCITE_MUTUI": "Mutui e Finanziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_VARIE_EXT": "Varie ed Eventuali",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
}

MONTH_NAMES_IT = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}

MESI_NOMI = [
    "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
    "Lug", "Ago", "Set", "Ott", "Nov", "Dic",
]


# -- Fornitori map -------------------------------------------------------------


def load_fornitori_map() -> dict[int, dict]:
    """Load d_fornitori CSV -> {codice_fornitore: {voce_id, nome_pf}}."""
    result = {}
    with open(FORNITORI_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[int(row["codice_fornitore"])] = {
                "voce_id": row["voce_id"],
                "nome_pf": row.get("nome_pf", "").strip(),
            }
    return result


# -- Parse scadenze ------------------------------------------------------------


def parse_scadenze(file_bytes: BytesIO) -> tuple[pd.DataFrame, list[int]]:
    """Parse Esolver 'Situazione partite sintetica per fornitori'.

    Each row is an individual invoice with:
      col 11: codice_fornitore, col 12: nome, col 20: importo, col 23: data_scadenza.

    Returns (df, bucket_months) where df has one row per supplier with columns:
      codice_fornitore, nome, totale, scaduto, mese_4, mese_5, ...
    Invoices with scadenza before current month are aggregated into 'scaduto'.
    """
    wb = openpyxl.load_workbook(file_bytes, data_only=True)
    ws = wb.active

    current_month = date.today().month
    current_year = date.today().year

    # Read all invoices
    invoices: list[dict] = []
    for row_idx in range(1, ws.max_row + 1):
        codice = ws.cell(row=row_idx, column=11).value
        if not codice or not isinstance(codice, (int, float)):
            continue
        nome = ws.cell(row=row_idx, column=12).value or ""
        importo = ws.cell(row=row_idx, column=20).value or 0
        scad = ws.cell(row=row_idx, column=23).value
        if not scad:
            continue
        invoices.append({
            "codice": int(codice),
            "nome": str(nome).strip(),
            "importo": float(importo),
            "scad_month": scad.month,
            "scad_year": scad.year,
        })

    if not invoices:
        return pd.DataFrame(columns=["codice_fornitore", "nome", "totale", "scaduto"]), []

    # Aggregate by supplier + month
    from collections import defaultdict
    supplier_data: dict[int, dict] = {}  # codice -> {nome, scaduto, mese_X, totale}
    all_months: set[int] = set()

    for inv in invoices:
        cod = inv["codice"]
        if cod not in supplier_data:
            supplier_data[cod] = {"nome": inv["nome"], "scaduto": 0.0, "totale": 0.0}
        amt = inv["importo"]  # negative = debt
        supplier_data[cod]["totale"] += amt

        # Past due (before current month) → scaduto
        if inv["scad_year"] < current_year or (
            inv["scad_year"] == current_year and inv["scad_month"] < current_month
        ):
            supplier_data[cod]["scaduto"] += amt
        else:
            m = inv["scad_month"]
            all_months.add(m)
            key = f"mese_{m}"
            supplier_data[cod][key] = supplier_data[cod].get(key, 0.0) + amt

    # Build DataFrame
    rows = []
    for cod, data in supplier_data.items():
        row = {
            "codice_fornitore": cod,
            "nome": data["nome"],
            "totale": data["totale"],
            "scaduto": data["scaduto"],
        }
        for m in all_months:
            row[f"mese_{m}"] = data.get(f"mese_{m}", 0.0)
        rows.append(row)

    df = pd.DataFrame(rows)
    bucket_months = sorted(all_months)
    return df, bucket_months


# -- Read PF sheet -------------------------------------------------------------


def _build_month_col_map(ws) -> dict[int, int]:
    """Scan row 2 of a detail sheet, return {calendar_month: column}."""
    col_map: dict[int, int] = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=2, column=col).value
        if val and str(val).strip().upper() in MONTH_NAMES_IT:
            month = MONTH_NAMES_IT[str(val).strip().upper()]
            if month not in col_map or col > col_map[month]:
                col_map[month] = col
    return col_map


def _find_previsionale_row(ws, max_row: int = 200) -> int | None:
    """Find the PREVISIONALE row (col B contains 'PREVISIONALE')."""
    for r in range(3, min(ws.max_row + 1, max_row)):
        val = ws.cell(row=r, column=2).value
        if val and "previsional" in str(val).strip().lower():
            return r
    return None


def _find_total_row_and_range(
    ws, month_col: dict[int, int], max_row: int = 10,
) -> tuple[int | None, int, int]:
    """Find the total row with a vertical SUM formula in a month column.

    Returns (total_row, sum_start_row, sum_end_row).
    """
    # Check month columns for vertical SUM formulas like =SUM(L5:L180)
    for r in range(3, min(ws.max_row + 1, max_row)):
        for month, col in month_col.items():
            val = ws.cell(row=r, column=col).value
            if not val or not isinstance(val, str):
                continue
            m = re.search(r"SUM\([A-Z]+(\d+):[A-Z]+(\d+)\)", val)
            if m:
                start = int(m.group(1))
                end = int(m.group(2))
                if end - start > 5:  # vertical SUM spans many rows
                    return r, start, end
    return None, 0, 0


def _find_supplier_row_by_name(ws, nome_pf: str, max_row: int = 200) -> int | None:
    """Find row in detail sheet where column B matches nome_pf.

    Tries exact match first, then containment in either direction
    (PF name contains search term, or search term contains PF name).
    """
    if not nome_pf or not nome_pf.strip():
        return None
    target = nome_pf.strip().lower()
    # Exact match first
    for r in range(3, min(ws.max_row + 1, max_row)):
        val = ws.cell(row=r, column=2).value
        if val and str(val).strip().lower() == target:
            return r
    # Containment match: either direction, min 4 chars to avoid false positives
    if len(target) >= 4:
        for r in range(3, min(ws.max_row + 1, max_row)):
            val = ws.cell(row=r, column=2).value
            if not val:
                continue
            pf_name = str(val).strip().lower()
            if len(pf_name) < 4:
                continue
            if target in pf_name or pf_name in target:
                return r
    return None


def _find_supplier_row_by_codice(ws, codice: int, max_row: int = 200) -> int | None:
    """Find row in detail sheet where column A matches codice_fornitore."""
    for r in range(3, min(ws.max_row + 1, max_row)):
        val = ws.cell(row=r, column=1).value
        if val and isinstance(val, (int, float)) and int(val) == codice:
            return r
    return None


def read_pf_sheet(
    wb_values, wb_formulas, sheet_name: str,
) -> tuple[pd.DataFrame, dict[int, int], int | None, bool]:
    """Read a PF detail sheet.

    Returns: (df, month_col, previsionale_row, prev_in_sum)
    """
    ws = wb_values[sheet_name]
    ws_cod = wb_formulas[sheet_name]

    month_col = _build_month_col_map(ws)
    prev_row = _find_previsionale_row(ws)
    month_col_form = _build_month_col_map(ws_cod)
    total_row, sum_start, sum_end = _find_total_row_and_range(ws_cod, month_col_form)

    prev_in_sum = False
    if prev_row and total_row:
        prev_in_sum = sum_start <= prev_row <= sum_end

    # Read supplier rows (match by codice in col 1 or name in col 2)
    rows = []
    for r in range(3, ws.max_row + 1):
        codice = ws_cod.cell(row=r, column=1).value
        nome = ws.cell(row=r, column=2).value
        if r == prev_row or r == total_row:
            continue
        if not nome:
            continue
        row_data = {"nome_pf": str(nome).strip(), "pf_row": r}
        if codice and isinstance(codice, (int, float)):
            row_data["codice_fornitore"] = int(codice)
        for month, col in month_col.items():
            val = ws.cell(row=r, column=col).value
            row_data[f"pf_mese_{month}"] = float(val) if isinstance(val, (int, float)) else 0.0
        rows.append(row_data)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["codice_fornitore", "nome_pf", "pf_row"])
    return df, month_col, prev_row, prev_in_sum


# -- Write back to PF ---------------------------------------------------------


def write_pf(
    pf_bytes: bytes,
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    fornitori_map: dict[int, dict],
    excluded: set[int] | None = None,
) -> tuple[bytes, dict[str, list]]:
    """Write scadenze into ALL PF detail sheets, return (bytes, summary).

    Handles the PREVISIONALE adjustment: if the PREVISIONALE row is inside
    the SUM range of the total row, reduce it by the scadenzario total so
    the overall SUM stays correct (= MAX(previsionale, scadenzario)).
    """
    wb = openpyxl.load_workbook(BytesIO(pf_bytes))
    wb_values = openpyxl.load_workbook(BytesIO(pf_bytes), data_only=True)
    wb_formulas = openpyxl.load_workbook(BytesIO(pf_bytes), data_only=False)

    current_month = date.today().month
    summary: dict[str, list] = {}

    # Group scadenzario suppliers by voce_id
    excluded = excluded or set()
    scad_by_voce: dict[str, list[dict]] = {}
    for _, row in scad_df.iterrows():
        codice = int(row["codice_fornitore"])
        if codice in excluded:
            continue
        info = fornitori_map.get(codice)
        if not info:
            continue
        voce_id = info["voce_id"]
        nome_pf = info["nome_pf"]
        scad_by_voce.setdefault(voce_id, []).append({
            "codice_fornitore": codice,
            "nome": row["nome"],
            "nome_pf": nome_pf,
            "scaduto": float(row.get("scaduto", 0) or 0),
            **{f"mese_{m}": float(row.get(f"mese_{m}", 0) or 0) for m in bucket_months},
        })

    for voce_id, suppliers in scad_by_voce.items():
        sheet_name = VOCE_TO_SHEET.get(voce_id)
        if not sheet_name or sheet_name not in wb.sheetnames:
            continue

        ws = wb[sheet_name]
        ws_vals = wb_values[sheet_name]
        ws_form = wb_formulas[sheet_name]

        month_col = _build_month_col_map(ws_vals)
        prev_row = _find_previsionale_row(ws_vals)
        month_col_form = _build_month_col_map(ws_form)
        total_row, sum_start, sum_end = _find_total_row_and_range(ws_form, month_col_form)
        prev_in_sum = False
        if prev_row and total_row:
            prev_in_sum = sum_start <= prev_row <= sum_end

        voce_label = VOCE_LABELS.get(voce_id, voce_id)
        written: list[dict] = []
        # Track total scadenzario written per month for PREVISIONALE adjustment
        scad_totals: dict[int, float] = {}

        # Find empty rows inside SUM range for new suppliers (avoid insert_rows
        # which corrupts formulas and creates circular references)
        empty_rows: list[int] = []
        search_start = sum_start if sum_start else 4
        search_end = (prev_row or total_row or ws.max_row) - 1
        for r in range(search_start, search_end + 1):
            a = ws_vals.cell(row=r, column=1).value
            b = ws_vals.cell(row=r, column=2).value
            if not a and not b:
                empty_rows.append(r)
        empty_row_idx = 0

        for s in suppliers:
            # Find the supplier row: try codice first, then name
            pf_row = _find_supplier_row_by_codice(ws_vals, s["codice_fornitore"])
            if pf_row is None and s["nome_pf"]:
                pf_row = _find_supplier_row_by_name(ws_vals, s["nome_pf"])
            if pf_row is None:
                pf_row = _find_supplier_row_by_name(ws_vals, s["nome"])
            if pf_row is None and empty_row_idx < len(empty_rows):
                # Use an existing empty row instead of inserting
                pf_row = empty_rows[empty_row_idx]
                empty_row_idx += 1
                ws.cell(row=pf_row, column=1, value=s["codice_fornitore"])
                ws.cell(row=pf_row, column=2, value=s["nome_pf"] or s["nome"])
            if pf_row is None:
                continue

            # Collect amounts: scaduto -> current month, buckets -> their months
            amounts: dict[int, float] = {}
            scaduto = s["scaduto"]
            if scaduto:
                amounts[current_month] = amounts.get(current_month, 0) + scaduto

            for month in bucket_months:
                val = s[f"mese_{month}"]
                if val:
                    amounts[month] = amounts.get(month, 0) + val

            # Write: flip sign (scadenze negative = debito, PF positive = uscita)
            months_written: dict[int, float] = {}
            for month, amount in amounts.items():
                col = month_col.get(month)
                if col:
                    pf_val = round(abs(amount), 2)
                    ws.cell(row=pf_row, column=col, value=pf_val)
                    months_written[month] = pf_val
                    scad_totals[month] = scad_totals.get(month, 0) + pf_val

            if months_written:
                written.append({
                    "codice": s["codice_fornitore"],
                    "nome": s["nome_pf"] or s["nome"],
                    "months": months_written,
                })

        # Adjust PREVISIONALE if it's inside the SUM range.
        # After writing supplier cells, compute the total of ALL non-prev
        # rows in the SUM range, then set PREVISIONALE so that:
        #   SUM = MAX(orig_previsionale, supplier_total)
        if prev_in_sum and prev_row and scad_totals:
            for month in scad_totals:
                col = month_col.get(month)
                if not col:
                    continue
                orig_prev = ws_vals.cell(row=prev_row, column=col).value
                if not orig_prev or not isinstance(orig_prev, (int, float)):
                    continue
                orig_prev_f = float(orig_prev)
                # Sum all non-previsionale rows in the SUM range
                supplier_total = 0.0
                for r in range(sum_start, sum_end + 1):
                    if r == prev_row:
                        continue
                    v = ws.cell(row=r, column=col).value
                    if v and isinstance(v, (int, float)):
                        supplier_total += float(v)
                # Set PREV so SUM = MAX(orig_prev, supplier_total)
                new_prev = max(0.0, orig_prev_f - supplier_total)
                ws.cell(row=prev_row, column=col, value=round(new_prev, 2))

        if written:
            summary[voce_label] = written

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), summary


# -- Streamlit App -------------------------------------------------------------


def main():
    st.set_page_config(page_title="Scadenzario -> PF", page_icon="", layout="wide")
    st.title("Scadenzario -> Piano Finanziario")

    col_up1, col_up2 = st.columns(2)

    with col_up1:
        uploaded_pf = st.file_uploader(
            "Carica il **Piano Finanziario** (Excel)",
            type=["xlsx"],
            key="pf",
        )

    with col_up2:
        uploaded_scad = st.file_uploader(
            "Carica il file **Situazione fornitori** (Esolver export)",
            type=["xlsx"],
            key="scad",
        )

    if not uploaded_pf or not uploaded_scad:
        st.info("Carica entrambi i file: PF Excel e Scadenze Esolver")
        return

    pf_bytes = uploaded_pf.getvalue()

    # Parse scadenzario
    scad_df, bucket_months = parse_scadenze(BytesIO(uploaded_scad.getvalue()))
    fornitori_map = load_fornitori_map()

    st.subheader("Scadenze caricate")
    st.metric("Fornitori nel file", len(scad_df))

    # Map scadenzario to voci
    mapped_rows = []
    unmapped_rows = []
    for _, row in scad_df.iterrows():
        codice = int(row["codice_fornitore"])
        info = fornitori_map.get(codice)
        if info:
            mapped_rows.append({**row.to_dict(), "voce_id": info["voce_id"], "nome_pf": info["nome_pf"]})
        else:
            unmapped_rows.append(row.to_dict())

    mapped_df = pd.DataFrame(mapped_rows)
    unmapped_df = pd.DataFrame(unmapped_rows)

    col1, col2 = st.columns(2)
    col1.metric("Mappati (in d_fornitori)", len(mapped_df))
    col2.metric("Non mappati", len(unmapped_df), help="Fornitori non in d_fornitori.csv")

    # Preview per voce — with exclude checkboxes
    if "excluded_suppliers" not in st.session_state:
        st.session_state.excluded_suppliers = set()

    if not mapped_df.empty:
        st.subheader("Preview per voce PF")

        month_cols_scad = [f"mese_{m}" for m in bucket_months]

        for voce_id in sorted(mapped_df["voce_id"].unique()):
            voce_label = VOCE_LABELS.get(voce_id, voce_id)
            sheet_name = VOCE_TO_SHEET.get(voce_id, "?")
            voce_df = mapped_df[mapped_df["voce_id"] == voce_id]

            with st.expander(f"{voce_label} ({len(voce_df)} fornitori) -> foglio '{sheet_name}'"):
                for _, row in voce_df.iterrows():
                    codice = int(row["codice_fornitore"])
                    nome = row["nome"]
                    totale = row.get("totale", 0)
                    is_excluded = codice in st.session_state.excluded_suppliers
                    cols = st.columns([0.5, 3, 2] + [2] * len(month_cols_scad) + [2])
                    exclude = cols[0].checkbox(
                        "x", value=is_excluded,
                        key=f"excl_{codice}",
                        label_visibility="collapsed",
                    )
                    if exclude:
                        st.session_state.excluded_suppliers.add(codice)
                    elif codice in st.session_state.excluded_suppliers:
                        st.session_state.excluded_suppliers.discard(codice)
                    label = f"~~{nome}~~" if exclude else nome
                    cols[1].markdown(f"**{codice}** {label}")
                    col_idx = 2
                    scad_val = row.get("scaduto", 0)
                    cols[col_idx].text(f"{scad_val:,.0f}" if scad_val else "")
                    col_idx += 1
                    for mc in month_cols_scad:
                        v = row.get(mc, 0)
                        cols[col_idx].text(f"{v:,.0f}" if v else "")
                        col_idx += 1
                    cols[col_idx].text(f"{totale:,.0f}" if totale else "")

    # Unmapped — let user assign voce from the UI
    # Persist assignments in session_state so they survive reruns
    if "voce_assignments" not in st.session_state:
        st.session_state.voce_assignments = {}

    # Apply previous session assignments: move from unmapped to mapped
    if st.session_state.voce_assignments and not unmapped_df.empty:
        still_unmapped = []
        for _, row in unmapped_df.iterrows():
            codice = int(row["codice_fornitore"])
            if codice in st.session_state.voce_assignments:
                voce_id = st.session_state.voce_assignments[codice]
                nome = str(row.get("nome", "")).strip()
                mapped_rows.append({**row.to_dict(), "voce_id": voce_id, "nome_pf": nome})
                fornitori_map[codice] = {"voce_id": voce_id, "nome_pf": nome}
            else:
                still_unmapped.append(row.to_dict())
        mapped_df = pd.DataFrame(mapped_rows)
        unmapped_df = pd.DataFrame(still_unmapped)

    if len(unmapped_df) > 0:
        voce_options = ["-- non assegnato --"] + sorted(VOCE_LABELS.keys())
        voce_display = {k: VOCE_LABELS[k] for k in VOCE_LABELS}
        voce_display["-- non assegnato --"] = "-- non assegnato --"

        with st.expander(f"Fornitori non mappati ({len(unmapped_df)}) — assegna voce", expanded=True):
            st.caption("Scegli la voce PF per ogni fornitore. Clicca 'Conferma' per includerli nella scrittura.")

            for idx, row in unmapped_df.iterrows():
                cols = st.columns([1, 4, 2, 4])
                cols[0].text(str(int(row["codice_fornitore"])))
                cols[1].text(row["nome"])
                cols[2].text(f"{row['totale']:,.0f}" if pd.notna(row["totale"]) else "")
                cols[3].selectbox(
                    "Voce",
                    voce_options,
                    format_func=lambda x: voce_display.get(x, x),
                    key=f"voce_{int(row['codice_fornitore'])}",
                    label_visibility="collapsed",
                )

            if st.button("Conferma assegnazioni", type="secondary"):
                new_assignments = {}
                for _, row in unmapped_df.iterrows():
                    codice = int(row["codice_fornitore"])
                    choice = st.session_state.get(f"voce_{codice}", "-- non assegnato --")
                    if choice != "-- non assegnato --":
                        new_assignments[codice] = choice
                if new_assignments:
                    st.session_state.voce_assignments.update(new_assignments)
                    st.rerun()

    # Gap analysis
    if not mapped_df.empty:
        st.subheader("Riepilogo per mese")
        current_month = date.today().month
        gap_rows = []
        # Filter out excluded suppliers for the summary
        active_df = mapped_df[~mapped_df["codice_fornitore"].isin(st.session_state.get("excluded_suppliers", set()))]
        # Scaduto total -> current month
        scaduto_total = abs(active_df["scaduto"].sum())
        gap_rows.append({
            "Mese": MESI_NOMI[current_month - 1] + " (scaduto)",
            "Scadenzario": f"{scaduto_total:,.0f}",
        })
        for month in bucket_months:
            col = f"mese_{month}"
            if col in active_df.columns:
                total = abs(active_df[col].sum())
                gap_rows.append({
                    "Mese": MESI_NOMI[month - 1],
                    "Scadenzario": f"{total:,.0f}",
                })
        st.dataframe(pd.DataFrame(gap_rows), use_container_width=True, hide_index=True)

    # Action
    st.divider()
    st.caption(
        f"Lo scaduto viene riversato in **{MESI_NOMI[date.today().month - 1]}** (mese corrente). "
        "Il PREVISIONALE viene aggiustato per evitare doppio conteggio nel totale."
    )

    if st.button("Aggiorna PF Excel", type="primary"):
        excluded = st.session_state.get("excluded_suppliers", set())
        updated_bytes, write_summary = write_pf(pf_bytes, scad_df, bucket_months, fornitori_map, excluded)

        total_written = sum(len(v) for v in write_summary.values())
        st.success(f"Aggiornati {total_written} fornitori in {len(write_summary)} fogli")

        for voce_label, entries in write_summary.items():
            st.caption(f"**{voce_label}**: {len(entries)} fornitori")

        st.download_button(
            label="Scarica PF aggiornato",
            data=updated_bytes,
            file_name=f"PF Scadenzario {date.today().strftime('%b %-d %Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
