"""Pagina Ingest — drop → classifica → intake → promote → inbox.

Unica superficie di scrittura del hub (eccezione dichiarata in spec §regole).
Lineage-first: stesse funzioni del CLI, mai parser diretti.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st


def _classifica(tmp_path: Path):
    from core.lineage.source_resolver import load_registry
    from ingest.classify import classify

    res = classify(tmp_path)
    reg = load_registry()
    proposta = None
    if res.category and res.societa:
        sd = reg.resolve(res.category, res.societa)
        proposta = sd.source_name if sd else None
    return res, proposta, sorted(reg.sources)


def _inbox_df():
    from core.bq.client import get_client

    q = """
    SELECT r.file_name_original, r.source_name, v.current_status,
           v.last_event_at, r.raw_object_id
    FROM `hotelops-suite.hotelops.v_raw_objects_current` v
    JOIN `hotelops-suite.hotelops.f_raw_objects` r USING (raw_object_id)
    WHERE v.current_status != 'PROMOTED'
    ORDER BY v.last_event_at DESC
    LIMIT 50
    """
    return get_client().query(q).result().to_dataframe(create_bqstorage_client=False)


def render():
    st.title("📥 Ingest")
    st.caption(
        "File → classifica → intake (GCS + f_raw_objects) → promote. Lineage-first."
    )

    files = st.file_uploader(
        "Trascina i file (xlsx, csv, txt)",
        accept_multiple_files=True,
        type=["xlsx", "csv", "txt"],
    )

    for up in files or []:
        st.divider()
        st.subheader(up.name)
        tmp_dir = Path(tempfile.mkdtemp(prefix="hub_ingest_"))
        tmp_path = tmp_dir / up.name  # nome originale: serve a detection e GCS
        tmp_path.write_bytes(up.getbuffer())

        res, proposta, tutti = _classifica(tmp_path)
        st.write(
            f"Rilevato: `{res.file_type}` (categoria `{res.category}`, "
            f"società `{res.societa}`, confidenza {res.confidence:.0%})"
        )
        if proposta is None:
            st.warning(
                "Nessun source nel registry per questa detection — se è un tipo "
                "nuovo va definito prima (skill hotelops-ingest). "
                "Puoi comunque forzare un source esistente qui sotto."
            )
        source = st.selectbox(
            "Source",
            options=tutti,
            index=tutti.index(proposta) if proposta in tutti else None,
            key=f"src_{up.name}",
        )

        if st.button("Intake", key=f"intake_{up.name}", disabled=source is None):
            from ingest.intake import intake_file

            risultato = intake_file(tmp_path, source_name=source, actor="hub")
            if risultato.deduped:
                st.info(f"Già registrato (dedup): `{risultato.raw_object_id}`")
            else:
                st.success(f"Registrato: `{risultato.raw_object_id}`")
            st.session_state[f"ro_{up.name}"] = risultato.raw_object_id

        ro_id = st.session_state.get(f"ro_{up.name}")
        if ro_id and st.button("Promote", key=f"promote_{up.name}"):
            from ingest.promotion import promote_raw_object

            esito = promote_raw_object(ro_id, actor="hub")
            if esito.status == "PROMOTED":
                st.success(f"PROMOTED — {esito.rows_written} righe scritte")
            else:
                st.error(f"{esito.status}: {esito.reason}")  # VALIDATE_FAIL in chiaro

    st.divider()
    st.subheader("Inbox — raw objects non promossi")
    try:
        df = _inbox_df()
        if df.empty:
            st.success("Coda vuota: tutto promosso.")
        else:
            st.dataframe(df, hide_index=True)
    except Exception as e:
        st.error(f"Inbox non disponibile (BigQuery): {e}")
