#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

# Streamlit può avviare lo script senza includere la repo root in sys.path.
# Fallback locale per import affidabili in ambiente dev.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from verticals.condges.accodamenti_service import (
    current_watermark,
    generate_cumulative_excel_from_bq,
    ingest_rows,
    preview_folder,
)

DEFAULT_OUTPUT = Path.home() / "Downloads" / "RACCOLTAACCODAMENTI.xlsx"


def _init_state() -> None:
    if "preview_new_rows" not in st.session_state:
        st.session_state.preview_new_rows = None
    if "preview_stats" not in st.session_state:
        st.session_state.preview_stats = None
    if "preview_input_dir" not in st.session_state:
        st.session_state.preview_input_dir = None
    if "uploaded_input_dir" not in st.session_state:
        st.session_state.uploaded_input_dir = None
    if "uploaded_count" not in st.session_state:
        st.session_state.uploaded_count = 0
    if "last_excel_bytes" not in st.session_state:
        st.session_state.last_excel_bytes = None
    if "last_excel_name" not in st.session_state:
        st.session_state.last_excel_name = "RACCOLTAACCODAMENTI.xlsx"


def _materialize_uploaded_files(uploaded_files: list) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="accodamenti_drop_"))
    for f in uploaded_files:
        # Browser folder-drop often preserves relative path in name.
        rel_name = str(f.name).lstrip("/").replace("\\", "/")
        target = tmp_dir / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f.getbuffer())
    return tmp_dir


def main() -> None:
    st.set_page_config(page_title="Raccolta Accodamenti", layout="wide")
    _init_state()

    st.title("Raccolta Accodamenti")
    st.caption("Workflow standard: drop -> anteprima -> ingest nuove righe -> Excel cumulativo da BQ")

    watermark = current_watermark()
    st.info(f"Watermark corrente f_accodamenti: `{watermark or 'N/A'}`")

    input_dir_raw = st.text_input(
        "Cartella accodamenti (.txt)",
        value="/Users/stefanodellapietra/Downloads/RACCOLTAACCODAMENTI",
    ).strip()
    dropped_files = st.file_uploader(
        "Oppure droppa qui la cartella (seleziona tutti i .txt)",
        accept_multiple_files=True,
        type=["txt"],
        help="Puoi trascinare i file della cartella; useremo questi come input della sessione.",
    )
    societa = "ORTI"
    st.caption("Societa fissa per accodamenti: `ORTI`")
    output_path_raw = st.text_input(
        "Output Excel",
        value=str(DEFAULT_OUTPUT),
    ).strip()
    start_date = st.date_input("Data inizio cumulativo (BQ)", value=date(2026, 4, 3))

    if dropped_files:
        uploaded_dir = _materialize_uploaded_files(dropped_files)
        st.session_state.uploaded_input_dir = str(uploaded_dir)
        st.session_state.uploaded_count = len(dropped_files)
        st.success(
            f"Drop ricevuto: {len(dropped_files)} file in `{uploaded_dir}`"
        )

    effective_input_dir = (
        st.session_state.uploaded_input_dir
        if st.session_state.uploaded_input_dir
        else input_dir_raw
    )
    st.caption(f"Input effettivo: `{effective_input_dir}`")

    action_col, reset_col = st.columns([4, 1])
    with action_col:
        run_all = st.button(
            "Esegui workflow cumulativo (standard)",
            type="primary",
            help="Anteprima overlap, ingest solo nuove righe, rigenera Excel cumulativo",
        )
    with reset_col:
        if st.button("Reset drop"):
            st.session_state.uploaded_input_dir = None
            st.session_state.uploaded_count = 0
            st.session_state.preview_new_rows = None
            st.session_state.preview_stats = None
            st.session_state.preview_input_dir = None
            st.rerun()

    if run_all:
        input_dir = Path(effective_input_dir).expanduser()
        output_path = Path(output_path_raw).expanduser()
        if not input_dir.exists():
            st.error(f"Cartella non trovata: {input_dir}")
        else:
            with st.spinner("Esecuzione workflow completo..."):
                stats, _rows, new_rows = preview_folder(input_dir, societa=societa)
                written = ingest_rows(new_rows)
                result = generate_cumulative_excel_from_bq(start_date, output_path)
            st.session_state.preview_new_rows = new_rows
            st.session_state.preview_stats = stats
            st.session_state.preview_input_dir = str(input_dir)
            st.success(
                f"Completato. Nuove righe ingestite: {written} | Excel: {result['output']}"
            )
            generated_path = Path(result["output"])
            if generated_path.exists():
                st.session_state.last_excel_bytes = generated_path.read_bytes()
                st.session_state.last_excel_name = generated_path.name
            st.info(f"Watermark aggiornato: `{current_watermark() or 'N/A'}`")

    stats = st.session_state.preview_stats
    if stats:
        st.subheader("Preview batch")
        c1, c2, c3 = st.columns(3)
        c1.metric("TXT trovati", stats.txt_files)
        c2.metric("Righe parsate", stats.parsed_rows)
        c3.metric("Nuove righe", stats.new_rows)

        c4, c5, c6 = st.columns(3)
        c4.metric("Hash candidati", stats.candidate_hashes)
        c5.metric("Hash gia presenti", stats.existing_hashes)
        c6.metric("Range date", f"{stats.min_date or '-'} -> {stats.max_date or '-'}")

    with st.expander("Azioni avanzate (opzionali)", expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("Solo anteprima overlap"):
                input_dir = Path(effective_input_dir).expanduser()
                if not input_dir.exists():
                    st.error(f"Cartella non trovata: {input_dir}")
                else:
                    with st.spinner("Parsing + dedup preview su BQ..."):
                        stats, _rows, new_rows = preview_folder(input_dir, societa=societa)
                    st.session_state.preview_new_rows = new_rows
                    st.session_state.preview_stats = stats
                    st.session_state.preview_input_dir = str(input_dir)
        with a2:
            if st.button("Solo ingest nuove righe"):
                if not st.session_state.preview_new_rows or not st.session_state.preview_stats:
                    st.warning("Esegui prima 'Solo anteprima overlap'.")
                else:
                    with st.spinner("Scrittura su BigQuery in corso..."):
                        written = ingest_rows(st.session_state.preview_new_rows)
                    st.success(f"Ingest completato: {written} nuove righe.")
                    st.info(f"Nuovo watermark: `{current_watermark() or 'N/A'}`")
        with a3:
            if st.button("Excel cumulativo da BQ"):
                output_path = Path(output_path_raw).expanduser()
                with st.spinner("Export cumulativo da BigQuery..."):
                    result = generate_cumulative_excel_from_bq(start_date, output_path)
                st.success(f"Excel cumulativo generato: {result['output']}")
                st.write(
                    f"Righe esportate: {result['rows']} | Data inizio: {result['start_date']}"
                )
                generated_path = Path(result["output"])
                if generated_path.exists():
                    st.session_state.last_excel_bytes = generated_path.read_bytes()
                    st.session_state.last_excel_name = generated_path.name

        st.caption(
            "Nota: il percorso standard produce sempre il cumulativo da BigQuery. "
            "Usa i pulsanti qui solo per debug o operazioni isolate."
        )

    if st.session_state.last_excel_bytes:
        st.download_button(
            "Scarica Excel cumulativo",
            data=st.session_state.last_excel_bytes,
            file_name=st.session_state.last_excel_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
