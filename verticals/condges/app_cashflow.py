#!/usr/bin/env python3
"""Cashflow vertical — guscio Streamlit sul motore canonico pf-rotate.

Monta `render()` nel hub. Stateless: upload PF + scadenziario + saldi → genera il
PF del mese successivo (rotation completa) scaricabile. L'authority è l'engine
pf_rotate + i saldi VERI letti da BQ (f_saldi_banca_chiusura_mensile); il PF è
tutto PROIEZIONE (tranne i saldi iniziali) e NON viene riscritto nel pool fatti.
"""

from __future__ import annotations

import tempfile
from calendar import monthrange
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy
from verticals.condges.scadenze_parse import parse_scadenze

FORNITORI_CSV = Path("core/bq/dimensioni/d_fornitori.csv")
MESI = {
    1: "gennaio",
    2: "febbraio",
    3: "marzo",
    4: "aprile",
    5: "maggio",
    6: "giugno",
    7: "luglio",
    8: "agosto",
    9: "settembre",
    10: "ottobre",
    11: "novembre",
    12: "dicembre",
}


def scad_summary(
    scad_df: pd.DataFrame, bucket_months: list[int]
) -> dict[str, object]:
    """Cifre di display dallo scadenziario: scaduto (roll-forward) + buckets forward.

    Funzione pura, solo per la UI. Niente persistenza (il PF è proiezione).
    """
    scaduto = float(scad_df["scaduto"].sum()) if "scaduto" in scad_df.columns else 0.0
    totale = float(scad_df["totale"].sum()) if "totale" in scad_df.columns else 0.0
    buckets = {
        m: float(scad_df[f"mese_{m}"].sum())
        for m in bucket_months
        if f"mese_{m}" in scad_df.columns
    }
    return {
        "scaduto_totale": scaduto,
        "totale_partite_aperte": totale,
        "forward_buckets": buckets,
    }


def render() -> None:
    st.title("💸 Cashflow — Piano Finanziario")
    st.caption(
        "Previsione di cassa: carica il PF del mese da chiudere + lo scadenziario, "
        "conferma i saldi, genera il PF del mese successivo."
    )

    societa = st.selectbox("Società", ["ORTI", "INTUR"])
    col1, col2 = st.columns(2)
    with col1:
        up_pf = st.file_uploader(
            "PF del mese da chiudere (.xlsx)", type=["xlsx"], key="pf"
        )
    with col2:
        up_scad = st.file_uploader(
            "Scadenziario fornitori (.xlsx)", type=["xlsx"], key="scad"
        )

    today = date.today()
    mese_chiuso = int(
        st.number_input(
            "Mese da chiudere", min_value=1, max_value=12, value=max(1, today.month - 1)
        )
    )
    anno = int(
        st.number_input("Anno", min_value=2020, max_value=2100, value=today.year)
    )

    if not up_pf or not up_scad:
        st.info("Carica PF e scadenziario per continuare.")
        return

    # cutover = ultimo giorno del mese chiuso; primo mese aperto = mese successivo
    data_saldo = date(anno, mese_chiuso, monthrange(anno, mese_chiuso)[1])
    primo_aperto = (anno + 1, 1) if mese_chiuso == 12 else (anno, mese_chiuso + 1)

    scad_df, bucket_months = parse_scadenze(
        BytesIO(up_scad.getvalue()), primo_mese_aperto=primo_aperto
    )
    st.subheader("Scadenziario")
    st.write(
        f"{len(scad_df)} fornitori · mesi forward: "
        f"{', '.join(MESI[m] for m in bucket_months)}"
    )

    # Saldi: pre-fill da BQ, editabili
    try:
        bq_saldi = fetch_saldi_da_bq(societa, data_saldo)
    except Exception as e:  # noqa: BLE001 — BQ assente in dev/cloud è non-fatale
        bq_saldi = {}
        st.warning(f"Saldi BQ non disponibili ({e}); inseriscili a mano.")
    st.subheader("Saldi banca al cutover")
    st.caption(
        f"Cutover: {data_saldo.isoformat()} (pre-compilati da BQ se disponibili)"
    )
    default_banche = list(bq_saldi.keys()) or (
        ["MPS", "Intesa", "MPS_KROSS"]
        if societa == "ORTI"
        else ["MPS", "Intesa", "Sella", "BCP"]
    )
    saldi: dict[str, float] = {}
    for banca in default_banche:
        saldi[banca] = float(
            st.number_input(
                f"Saldo {banca}",
                value=float(bq_saldi.get(banca, 0.0)),
                step=1000.0,
                format="%.2f",
                key=f"saldo_{banca}",
            )
        )

    policy_label = st.radio(
        "Fornitori non mappati", ["skip (procedi con warning)", "fail (blocca)"]
    )
    policy = (
        UnmappedPolicy.SKIP if policy_label.startswith("skip") else UnmappedPolicy.FAIL
    )

    if not st.button("Genera PF mese successivo", type="primary"):
        return

    with tempfile.TemporaryDirectory() as tmp:
        pf_path = Path(tmp) / up_pf.name
        pf_path.write_bytes(up_pf.getvalue())
        try:
            result = rotate(
                pf_path=pf_path,
                scad_df=scad_df,
                bucket_months=bucket_months,
                societa=societa,
                mese_chiuso=mese_chiuso,
                data_saldo=data_saldo,
                saldi={k: v for k, v in saldi.items() if v != 0} or None,
                fornitori_csv=FORNITORI_CSV,
                out_dir=Path(tmp),
                unmapped_policy=policy,
            )
        except Exception as e:  # noqa: BLE001 — surfacing engine error to UI
            st.error(f"Rotation fallita: {e}")
            return

        out_bytes = result.out_path.read_bytes()

    # Esiti
    if result.n_controlli_err:
        st.error(
            f"Controlli: {result.n_controlli_ok} OK · {result.n_controlli_err} ERR · "
            f"{result.n_controlli_indet} INDET — ERR sotto investigazione (vedi spec §4)."
        )
    else:
        st.success(
            f"Controlli: {result.n_controlli_ok} OK · 0 ERR · "
            f"{result.n_controlli_indet} INDET"
        )

    summ = scad_summary(scad_df, bucket_months)
    st.metric("Scaduto (roll-forward)", f"€ {summ['scaduto_totale']:,.2f}")
    st.metric("Totale partite aperte", f"€ {summ['totale_partite_aperte']:,.2f}")
    forward = summ["forward_buckets"]
    if forward:
        st.write("Progressivo forward:")
        st.table({MESI[m]: f"€ {v:,.2f}" for m, v in sorted(forward.items())})

    st.download_button(
        "⬇️ Scarica nuovo PF",
        data=out_bytes,
        file_name=result.out_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
