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

from verticals.condges.accodamenti_service import (  # noqa: E402
    current_watermark,
    generate_cumulative_excel_from_bq,
    ingest_rows,
    preview_folder,
)


def _init_state() -> None:
    st.session_state.setdefault("acc_preview_new_rows", None)
    st.session_state.setdefault("acc_preview_stats", None)
    st.session_state.setdefault("acc_uploaded_input_dir", None)
    st.session_state.setdefault("acc_uploaded_count", 0)
    st.session_state.setdefault("acc_excel_bytes", None)
    st.session_state.setdefault("acc_excel_name", "RACCOLTAACCODAMENTI.xlsx")


def _materialize_uploaded_files(uploaded_files: list) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="accodamenti_drop_"))
    for f in uploaded_files:
        # Browser folder-drop often preserves relative path in name.
        rel_name = str(f.name).lstrip("/").replace("\\", "/")
        target = tmp_dir / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f.getbuffer())
    return tmp_dir


def _cumulative_excel_bytes(start_date: date) -> tuple[dict, bytes | None]:
    """Genera l'Excel cumulativo Gaia su un tempfile e ne ritorna i bytes.

    Cloud-Run-safe: nessun path utente, il download avviene dai bytes in memoria.
    """
    out = Path(tempfile.mkdtemp(prefix="accodamenti_xlsx_")) / "RACCOLTAACCODAMENTI.xlsx"
    result = generate_cumulative_excel_from_bq(start_date, out)
    data = out.read_bytes() if out.exists() else None
    return result, data


def render() -> None:
    """Pagina montabile (hub): drop → dedup → aggiorna f_accodamenti → Excel Gaia.

    Niente ``set_page_config`` qui: lo imposta il guscio (``main`` o l'hub).
    """
    _init_state()

    st.title("📒 Raccolta Accodamenti")
    st.caption(
        "Workflow: drop TXT → anteprima/dedup → ingest nuove righe → Excel cumulativo da BQ"
    )

    watermark = current_watermark()
    st.info(f"Watermark corrente f_accodamenti: `{watermark or 'N/A'}`")

    societa = "ORTI"
    dropped_files = st.file_uploader(
        "Trascina i file accodamenti (.txt)",
        accept_multiple_files=True,
        type=["txt"],
        help="Società fissa per accodamenti: ORTI.",
    )
    start_date = st.date_input("Data inizio cumulativo (BQ)", value=date(2026, 4, 3))

    with st.expander("Cartella locale (solo dev, ignorata su Cloud Run)", expanded=False):
        local_dir = st.text_input("Path cartella .txt", value="").strip()

    if dropped_files:
        uploaded_dir = _materialize_uploaded_files(dropped_files)
        st.session_state.acc_uploaded_input_dir = str(uploaded_dir)
        st.session_state.acc_uploaded_count = len(dropped_files)
        st.success(f"Drop ricevuto: {len(dropped_files)} file")

    effective_input_dir = st.session_state.acc_uploaded_input_dir or (local_dir or None)
    if effective_input_dir:
        st.caption(f"Input effettivo: `{effective_input_dir}`")

    action_col, reset_col = st.columns([4, 1])
    with action_col:
        run_all = st.button(
            "Esegui workflow cumulativo (standard)",
            type="primary",
            disabled=effective_input_dir is None,
            help="Anteprima overlap, ingest solo nuove righe, rigenera Excel cumulativo da BQ",
        )
    with reset_col:
        if st.button("Reset drop"):
            st.session_state.acc_uploaded_input_dir = None
            st.session_state.acc_uploaded_count = 0
            st.session_state.acc_preview_new_rows = None
            st.session_state.acc_preview_stats = None
            st.rerun()

    if run_all and effective_input_dir:
        input_dir = Path(effective_input_dir).expanduser()
        if not input_dir.exists():
            st.error(f"Cartella non trovata: {input_dir}")
        else:
            with st.spinner("Parsing → dedup → ingest → Excel..."):
                stats, _rows, new_rows = preview_folder(input_dir, societa=societa)
                written = ingest_rows(new_rows)
                result, data = _cumulative_excel_bytes(start_date)
            st.session_state.acc_preview_new_rows = new_rows
            st.session_state.acc_preview_stats = stats
            st.session_state.acc_excel_bytes = data
            st.success(
                f"Completato. Nuove righe ingestite: {written} | "
                f"Righe Excel cumulativo: {result['rows']}"
            )
            st.info(f"Watermark aggiornato: `{current_watermark() or 'N/A'}`")

    stats = st.session_state.acc_preview_stats
    if stats:
        st.subheader("Preview batch")
        c1, c2, c3 = st.columns(3)
        c1.metric("TXT trovati", stats.txt_files)
        c2.metric("Righe parsate", stats.parsed_rows)
        c3.metric("Nuove righe", stats.new_rows)

        c4, c5, c6 = st.columns(3)
        c4.metric("Hash candidati", stats.candidate_hashes)
        c5.metric("Hash già presenti", stats.existing_hashes)
        c6.metric("Range date", f"{stats.min_date or '-'} → {stats.max_date or '-'}")

    with st.expander("Azioni avanzate (opzionali)", expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("Solo anteprima overlap", disabled=effective_input_dir is None):
                input_dir = Path(effective_input_dir).expanduser()
                if not input_dir.exists():
                    st.error(f"Cartella non trovata: {input_dir}")
                else:
                    with st.spinner("Parsing + dedup preview su BQ..."):
                        stats, _rows, new_rows = preview_folder(input_dir, societa=societa)
                    st.session_state.acc_preview_new_rows = new_rows
                    st.session_state.acc_preview_stats = stats
        with a2:
            if st.button("Solo ingest nuove righe"):
                if not st.session_state.acc_preview_new_rows or not st.session_state.acc_preview_stats:
                    st.warning("Esegui prima 'Solo anteprima overlap'.")
                else:
                    with st.spinner("Scrittura su BigQuery in corso..."):
                        written = ingest_rows(st.session_state.acc_preview_new_rows)
                    st.success(f"Ingest completato: {written} nuove righe.")
                    st.info(f"Nuovo watermark: `{current_watermark() or 'N/A'}`")
        with a3:
            if st.button("Excel cumulativo da BQ"):
                with st.spinner("Export cumulativo da BigQuery..."):
                    result, data = _cumulative_excel_bytes(start_date)
                st.session_state.acc_excel_bytes = data
                st.success(
                    f"Excel cumulativo generato: {result['rows']} righe "
                    f"da {result['start_date']}"
                )

        st.caption(
            "Nota: il percorso standard produce sempre il cumulativo da BigQuery. "
            "Usa i pulsanti qui solo per debug o operazioni isolate."
        )

    if st.session_state.acc_excel_bytes:
        st.download_button(
            "⬇ Scarica Excel cumulativo (Gaia)",
            data=st.session_state.acc_excel_bytes,
            file_name=st.session_state.acc_excel_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def main() -> None:
    st.set_page_config(page_title="Raccolta Accodamenti", layout="wide")
    render()


if __name__ == "__main__":
    main()
