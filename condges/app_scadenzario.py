#!/usr/bin/env python3
"""Scadenzario → PF Updater (Streamlit).

Drop the Esolver 'Situazione sintetica scadenze' Excel,
preview the match vs Piano Finanziario, and write amounts
into the PF Excel (Materie Prime sheet) by codice fornitore.

Usage:
    streamlit run condges/app_scadenzario.py
"""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_MATERIE = "Materie Prime-Consumo "

MONTH_NAMES_IT = {
    "GENNAIO": 1, "FEBBRAIO": 2, "MARZO": 3, "APRILE": 4,
    "MAGGIO": 5, "GIUGNO": 6, "LUGLIO": 7, "AGOSTO": 8,
    "SETTEMBRE": 9, "OTTOBRE": 10, "NOVEMBRE": 11, "DICEMBRE": 12,
}

MESI_NOMI = [
    "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
    "Lug", "Ago", "Set", "Ott", "Nov", "Dic",
]


# ── Parse scadenze ────────────────────────────────────────────────────────────


def parse_scadenze(file_bytes: BytesIO) -> tuple[pd.DataFrame, list[int]]:
    """Parse Esolver sintetica scadenze, return (df, bucket_months)."""
    wb = openpyxl.load_workbook(file_bytes, data_only=True)
    ws = wb.active

    # Detect month buckets from header row
    bucket_cols: dict[int, int] = {}  # col -> month
    for col in range(4, ws.max_column + 1):
        header = ws.cell(row=1, column=col).value
        if not header:
            continue
        h = str(header).lower()
        if "scadenza" not in h or "oltre" in h:
            continue
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(header))
        if m:
            bucket_cols[col] = int(m.group(2))

    rows = []
    for row_idx in range(2, ws.max_row + 1):
        cell_a = ws.cell(row=row_idx, column=1).value
        if not cell_a:
            continue
        m = re.match(r"^(\d+)\s+(.+)$", str(cell_a).strip())
        if not m:
            continue
        codice = int(m.group(1))
        nome = m.group(2).strip()
        totale = float(ws.cell(row=row_idx, column=2).value or 0)
        scaduto = float(ws.cell(row=row_idx, column=3).value or 0)
        row_data = {
            "codice_fornitore": codice,
            "nome": nome,
            "totale": totale,
            "scaduto": scaduto,
        }
        for col, month in bucket_cols.items():
            val = ws.cell(row=row_idx, column=col).value
            row_data[f"mese_{month}"] = float(val) if val else 0.0
        rows.append(row_data)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["codice_fornitore", "nome", "totale", "scaduto"])
    bucket_months = sorted(bucket_cols.values())
    return df, bucket_months


# ── Read PF Excel ─────────────────────────────────────────────────────────────


def read_pf_materie(pf_path: Path) -> tuple[pd.DataFrame, dict[int, int]]:
    """Read the Materie Prime sheet from file path."""
    wb = openpyxl.load_workbook(str(pf_path), data_only=True)
    return _parse_pf_materie(wb)


def read_pf_materie_from_bytes(pf_bytes: bytes) -> tuple[pd.DataFrame, dict[int, int]]:
    """Read the Materie Prime sheet from bytes."""
    wb = openpyxl.load_workbook(BytesIO(pf_bytes), data_only=True)
    return _parse_pf_materie(wb)


def _parse_pf_materie(wb) -> tuple[pd.DataFrame, dict[int, int]]:
    """Read the Materie Prime sheet: codice, nome, month columns.

    Returns (df, month_col_map) where month_col_map = {calendar_month: excel_col}.
    """
    ws = wb[SHEET_MATERIE]

    # Build month -> column map from row 2
    month_col: dict[int, int] = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=2, column=col).value
        if val and str(val).strip().upper() in MONTH_NAMES_IT:
            month = MONTH_NAMES_IT[str(val).strip().upper()]
            # Take rightmost occurrence (2026 for duplicated months)
            if month not in month_col or col > month_col[month]:
                month_col[month] = col

    rows = []
    for r in range(5, ws.max_row + 1):
        codice = ws.cell(row=r, column=1).value
        nome = ws.cell(row=r, column=2).value
        if not codice or not isinstance(codice, (int, float)):
            continue
        row_data = {"codice_fornitore": int(codice), "nome_pf": str(nome or ""), "pf_row": r}
        for month, col in month_col.items():
            val = ws.cell(row=r, column=col).value
            row_data[f"pf_mese_{month}"] = float(val) if isinstance(val, (int, float)) else 0.0
        rows.append(row_data)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["codice_fornitore", "nome_pf", "pf_row"])
    return df, month_col


# ── Write back to PF ─────────────────────────────────────────────────────────


def write_pf(
    pf_source: Path | bytes,
    matches: pd.DataFrame,
    bucket_months: list[int],
    month_col: dict[int, int],
    cascade_scaduto: bool = True,
) -> bytes:
    """Write scadenze amounts into PF Excel, return bytes of updated file.

    Logic: scaduto goes to current_month (April). Future buckets go to their
    respective months. All amounts are written — scaduto is not optional,
    it's debt already due.
    """
    if isinstance(pf_source, bytes):
        wb = openpyxl.load_workbook(BytesIO(pf_source))
    else:
        wb = openpyxl.load_workbook(str(pf_source))
    ws = wb[SHEET_MATERIE]

    current_month = date.today().month

    for _, row in matches.iterrows():
        pf_row = int(row["pf_row"])

        # Collect all amounts per month: scaduto → current month, buckets → their months
        amounts: dict[int, float] = {}
        scaduto = float(row.get("scaduto", 0) or 0)
        if scaduto:
            amounts[current_month] = amounts.get(current_month, 0) + scaduto

        for month in bucket_months:
            val = float(row.get(f"mese_{month}", 0) or 0)
            if val:
                amounts[month] = amounts.get(month, 0) + val

        # Write all amounts (overwrite, not accumulate)
        # Flip sign: scadenze are negative (debito), PF wants positive (uscita)
        for month, amount in amounts.items():
            col = month_col.get(month)
            if col:
                ws.cell(row=pf_row, column=col, value=round(abs(amount), 2))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Streamlit App ─────────────────────────────────────────────────────────────


def main():
    st.set_page_config(page_title="Scadenzario → PF", page_icon="📋", layout="wide")
    st.title("Scadenzario → Piano Finanziario")

    col_up1, col_up2 = st.columns(2)

    with col_up1:
        uploaded_pf = st.file_uploader(
            "Carica il **Piano Finanziario** (Excel con codici fornitori)",
            type=["xlsx"],
            key="pf",
        )

    with col_up2:
        uploaded_scad = st.file_uploader(
            "Carica il file **Situazione sintetica scadenze** (Esolver export)",
            type=["xlsx"],
            key="scad",
        )

    if not uploaded_pf or not uploaded_scad:
        st.info("Carica entrambi i file: PF Excel e Scadenze Esolver")
        return

    # Store PF bytes for later write-back
    pf_bytes = uploaded_pf.getvalue()

    # Parse both files
    scad_df, bucket_months = parse_scadenze(BytesIO(uploaded_scad.getvalue()))
    pf_df, month_col = read_pf_materie_from_bytes(pf_bytes)

    st.subheader("Scadenze caricate")
    st.metric("Fornitori nel file", len(scad_df))

    # Join on codice_fornitore
    merged = scad_df.merge(pf_df, on="codice_fornitore", how="outer", indicator=True)

    matched = merged[merged["_merge"] == "both"].copy()
    only_scad = merged[merged["_merge"] == "left_only"].copy()
    only_pf = merged[merged["_merge"] == "right_only"].copy()

    col1, col2, col3 = st.columns(3)
    col1.metric("Match", len(matched), help="Presenti in scadenze E nel PF")
    col2.metric("Solo scadenze (no PF)", len(only_scad), help="Nel file ma non nel foglio Materie Prime")
    col3.metric("Solo PF (no scadenze)", len(only_pf), help="Nel PF ma senza scadenze")

    # Preview matched
    st.subheader("Preview: cosa verrà scritto nel PF")

    month_cols_scad = [f"mese_{m}" for m in bucket_months]
    month_labels = [MESI_NOMI[m - 1] for m in bucket_months]

    display_cols = ["codice_fornitore", "nome", "scaduto"] + month_cols_scad + ["totale"]
    display_df = matched[display_cols].copy()
    display_df.columns = ["Cod", "Fornitore", "Scaduto"] + month_labels + ["Totale"]

    # Format numbers
    num_cols = ["Scaduto"] + month_labels + ["Totale"]
    for c in num_cols:
        display_df[c] = display_df[c].apply(
            lambda v: f"{v:,.0f}" if pd.notna(v) and v != 0 else ""
        )

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Show unmatched from scadenze
    if len(only_scad) > 0:
        with st.expander(f"Fornitori solo in scadenze ({len(only_scad)}) — non nel foglio Materie Prime"):
            st.dataframe(
                only_scad[["codice_fornitore", "nome", "totale"]].rename(
                    columns={"codice_fornitore": "Cod", "nome": "Fornitore", "totale": "Totale"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    # Gap analysis
    st.subheader("Gap: PF attuale vs Scadenze")
    gap_rows = []
    for month in bucket_months:
        scad_tot = matched[f"mese_{month}"].sum()
        pf_tot = matched[f"pf_mese_{month}"].sum() if f"pf_mese_{month}" in matched.columns else 0
        gap_rows.append({
            "Mese": MESI_NOMI[month - 1],
            "PF Rosa": round(pf_tot),
            "Scadenzario": round(scad_tot),
            "Delta": round(pf_tot - scad_tot),
        })
    gap_df = pd.DataFrame(gap_rows)
    st.dataframe(gap_df, use_container_width=True, hide_index=True)

    # Action
    st.divider()
    st.caption(f"Lo scaduto viene riversato in **{MESI_NOMI[date.today().month - 1]}** (mese corrente)")

    if st.button("Aggiorna PF Excel", type="primary"):
        updated_bytes = write_pf(pf_bytes, matched, bucket_months, month_col)

        st.success(f"Aggiornati {len(matched)} fornitori nel foglio Materie Prime")

        st.download_button(
            label="Scarica PF aggiornato",
            data=updated_bytes,
            file_name=f"ORTI_PF_2026_scadenzario_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
