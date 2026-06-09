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
import sys
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

# Streamlit Cloud runs this script directly, so the repo root isn't on sys.path
# and `from condges.X import …` fails. Inject it before the first such import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import openpyxl
import pandas as pd
import streamlit as st

from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq, write_saldi_banca
from verticals.condges.pf_rotate.step2_azzera import azzera_mese
from verticals.condges.pf_rotate.step5_controlli import CheckOutcome, verifica_controlli
from verticals.condges.scadenze_parse import parse_scadenze

# -- Config --------------------------------------------------------------------

FORNITORI_CSV = (
    Path(__file__).parent.parent.parent
    / "core"
    / "bq"
    / "dimensioni"
    / "d_fornitori.csv"
)


MESI_NOMI = [
    "Gen",
    "Feb",
    "Mar",
    "Apr",
    "Mag",
    "Giu",
    "Lug",
    "Ago",
    "Set",
    "Ott",
    "Nov",
    "Dic",
]


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

    # Detect società from PF (cell A1 of "Piano Finanziario" sheet)
    pf_wb_peek = openpyxl.load_workbook(
        BytesIO(pf_bytes), data_only=True, read_only=True
    )
    societa = ""
    if "Piano Finanziario" in pf_wb_peek.sheetnames:
        a1 = pf_wb_peek["Piano Finanziario"].cell(row=1, column=1).value
        if a1:
            societa = (
                str(a1).strip().replace(" S.R.L.", "").replace(" s.r.l.", "").upper()
            )
    pf_wb_peek.close()

    if societa:
        st.subheader(f"Scadenzario {societa}")
    else:
        st.subheader("Scadenze caricate")

    # === Sezione Chiudi mese precedente (step 1 + 2) ===========================
    with st.expander("📅 Chiudi mese precedente (step 1 + 2)", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            mese_chiuso = st.selectbox(
                "Mese chiuso",
                list(range(1, 13)),
                index=max(0, date.today().month - 2),
                format_func=lambda m: [
                    "GEN",
                    "FEB",
                    "MAR",
                    "APR",
                    "MAG",
                    "GIU",
                    "LUG",
                    "AGO",
                    "SET",
                    "OTT",
                    "NOV",
                    "DIC",
                ][m - 1],
            )
        with col_b:
            data_saldo_input = st.date_input(
                "Data saldo",
                value=date.today().replace(day=1) - timedelta(days=1),
            )

        # Try BQ for saldi pre-fill
        try:
            bq_saldi = fetch_saldi_da_bq(societa, data_saldo_input) if societa else {}
        except Exception:
            bq_saldi = {}

        st.caption("Saldi banca al cutover (precompilati da BQ se disponibili)")
        saldi_input: dict[str, float] = {}
        default_banche = list(bq_saldi.keys()) or (
            ["MPS", "Intesa", "MPS_KROSS"]
            if societa == "ORTI"
            else ["MPS", "Intesa", "Sella", "BCP"]
        )
        cols_b = st.columns(min(4, max(2, len(default_banche))))
        for i, banca in enumerate(default_banche):
            with cols_b[i % len(cols_b)]:
                saldi_input[banca] = float(
                    st.number_input(
                        f"Saldo {banca}",
                        value=float(bq_saldi.get(banca, 0.0)),
                        step=1000.0,
                        format="%.2f",
                        key=f"saldo_{banca}",
                    )
                )

        if st.button("Applica step 1+2 (rolla + azzera)", type="secondary"):
            wb_pre = openpyxl.load_workbook(BytesIO(pf_bytes))
            write_saldi_banca(
                wb_pre,
                mese_chiuso=mese_chiuso,
                data_saldo=data_saldo_input,
                saldi={k: v for k, v in saldi_input.items() if v != 0},
            )
            azzera_mese(wb_pre, mese_chiuso=mese_chiuso)
            report = verifica_controlli(wb_pre, mese_chiuso=mese_chiuso)
            buf = BytesIO()
            wb_pre.save(buf)
            st.session_state["pf_bytes_post_step12"] = buf.getvalue()
            st.session_state["pf_controlli_report"] = report
            st.success(
                f"Step 1+2 applicati. Controlli: OK={report.n_ok} "
                f"ERR={report.n_err} INDET={report.n_indet}"
            )

        # Use post-step12 bytes for subsequent sections
        if "pf_bytes_post_step12" in st.session_state:
            pf_bytes = st.session_state["pf_bytes_post_step12"]
            st.info("Usando il PF post step 1+2 per lo scadenzario.")

    # ===========================================================================

    # Parse scadenzario
    scad_df, bucket_months = parse_scadenze(BytesIO(uploaded_scad.getvalue()))
    fornitori_map = load_fornitori_map()

    st.metric("Fornitori nel file", len(scad_df))

    # Map scadenzario to voci
    mapped_rows = []
    unmapped_rows = []
    for _, row in scad_df.iterrows():
        codice = int(row["codice_fornitore"])
        info = fornitori_map.get(codice)
        if info:
            mapped_rows.append(
                {
                    **row.to_dict(),
                    "voce_id": info["voce_id"],
                    "nome_pf": info["nome_pf"],
                }
            )
        else:
            unmapped_rows.append(row.to_dict())

    mapped_df = pd.DataFrame(mapped_rows)
    unmapped_df = pd.DataFrame(unmapped_rows)

    col1, col2 = st.columns(2)
    col1.metric("Mappati (in d_fornitori)", len(mapped_df))
    col2.metric(
        "Non mappati", len(unmapped_df), help="Fornitori non in d_fornitori.csv"
    )

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

            with st.expander(
                f"{voce_label} ({len(voce_df)} fornitori) -> foglio '{sheet_name}'"
            ):
                for _, row in voce_df.iterrows():
                    codice = int(row["codice_fornitore"])
                    nome = row["nome"]
                    totale = row.get("totale", 0)
                    is_excluded = codice in st.session_state.excluded_suppliers
                    cols = st.columns([0.5, 3, 2] + [2] * len(month_cols_scad) + [2])
                    exclude = cols[0].checkbox(
                        "x",
                        value=is_excluded,
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
                mapped_rows.append(
                    {**row.to_dict(), "voce_id": voce_id, "nome_pf": nome}
                )
                fornitori_map[codice] = {"voce_id": voce_id, "nome_pf": nome}
            else:
                still_unmapped.append(row.to_dict())
        mapped_df = pd.DataFrame(mapped_rows)
        unmapped_df = pd.DataFrame(still_unmapped)

    if len(unmapped_df) > 0:
        voce_options = ["-- non assegnato --"] + sorted(VOCE_LABELS.keys())
        voce_display = {k: VOCE_LABELS[k] for k in VOCE_LABELS}
        voce_display["-- non assegnato --"] = "-- non assegnato --"

        with st.expander(
            f"Fornitori non mappati ({len(unmapped_df)}) — assegna voce", expanded=True
        ):
            st.caption(
                "Scegli la voce PF per ogni fornitore. Clicca 'Conferma' per includerli nella scrittura."
            )

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
                    choice = st.session_state.get(
                        f"voce_{codice}", "-- non assegnato --"
                    )
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
        active_df = mapped_df[
            ~mapped_df["codice_fornitore"].isin(
                st.session_state.get("excluded_suppliers", set())
            )
        ]
        # Scaduto total -> current month
        scaduto_total = abs(active_df["scaduto"].sum())
        gap_rows.append(
            {
                "Mese": MESI_NOMI[current_month - 1] + " (scaduto)",
                "Scadenzario": f"{scaduto_total:,.0f}",
            }
        )
        for month in bucket_months:
            col = f"mese_{month}"
            if col in active_df.columns:
                total = abs(active_df[col].sum())
                gap_rows.append(
                    {
                        "Mese": MESI_NOMI[month - 1],
                        "Scadenzario": f"{total:,.0f}",
                    }
                )
        st.dataframe(pd.DataFrame(gap_rows), use_container_width=True, hide_index=True)

    # Action
    st.divider()
    st.caption(
        f"Lo scaduto viene riversato in **{MESI_NOMI[date.today().month - 1]}** (mese corrente). "
        "Il PREVISIONALE viene aggiustato per evitare doppio conteggio nel totale."
    )

    unmapped_remaining = len(unmapped_df)
    disable_btn = unmapped_remaining > 0
    if st.button(
        "Aggiorna PF Excel",
        type="primary",
        disabled=disable_btn,
        help=(
            "Disabilitato finché tutti i fornitori non mappati hanno una scelta"
            if disable_btn
            else None
        ),
    ):
        excluded = st.session_state.get("excluded_suppliers", set())
        updated_bytes, write_summary = write_pf(
            pf_bytes, scad_df, bucket_months, fornitori_map, excluded
        )

        total_written = sum(len(v) for v in write_summary.values())
        st.success(
            f"Aggiornati {total_written} fornitori in {len(write_summary)} fogli"
        )

        for voce_label, entries in write_summary.items():
            st.caption(f"**{voce_label}**: {len(entries)} fornitori")

        st.download_button(
            label="Scarica PF aggiornato",
            data=updated_bytes,
            file_name=f"{societa + ' ' if societa else ''}PF Scadenzario {date.today().strftime('%b %-d %Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        if st.session_state.get("pf_controlli_report"):
            rep = st.session_state["pf_controlli_report"]
            st.subheader("Controlli")
            for r in rep.results:
                icon = (
                    "✅"
                    if r.outcome == CheckOutcome.OK
                    else ("❌" if r.outcome == CheckOutcome.ERR else "⚠️")
                )
                st.text(f"{icon} {r.check_id} — {r.title}  {r.detail}")


if __name__ == "__main__":
    main()
