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

from verticals.condges.pf_rotate.excel_model import periodo, periodo_anno_mese
from verticals.condges.pf_rotate.fornitori_map import (
    VOCE_LABELS,
    export_fornitori_to_csv,
    load_fornitori_bq,
    load_voci_pf_bq,
    upsert_fornitore_bq,
)
from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy
from verticals.condges.scadenze_parse import parse_scadenze

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


def unmapped_suppliers(
    scad_df: pd.DataFrame, known_codici: set[int]
) -> list[dict[str, object]]:
    """Fornitori dello scadenziario assenti dalla mappa d_fornitori (funzione pura).

    Ritorna [{codice, nome, totale}] deduplicato, per codici non in known_codici.
    """
    out: list[dict[str, object]] = []
    seen: set[int] = set()
    for _, r in scad_df.iterrows():
        cod = int(r["codice_fornitore"])
        if cod in known_codici or cod in seen:
            continue
        seen.add(cod)
        out.append(
            {
                "codice": cod,
                "nome": str(r.get("nome", "")),
                "totale": float(r.get("totale", 0) or 0),
            }
        )
    return out


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
            "Ultimo mese con saldi banca certificati",
            min_value=1,
            max_value=12,
            value=max(1, today.month - 1),
            help="Il mese di cui hai i saldi banca reali (cutover). Il PF proietta dal "
            "mese SUCCESSIVO in avanti. Es: saldi al 30/04 → metti 4 → PF di maggio.",
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

    scad_df, bucket_periodi = parse_scadenze(
        BytesIO(up_scad.getvalue()), primo_mese_aperto=primo_aperto
    )
    st.subheader("Scadenziario")
    st.write(
        f"{len(scad_df)} fornitori · mesi forward: "
        + ", ".join(
            f"{MESI[periodo_anno_mese(p)[1]]} {periodo_anno_mese(p)[0]}"
            for p in bucket_periodi
        )
    )

    # Fornitori non mappati → mappali qui (persiste su BQ d_fornitori: ricordato i mesi dopo)
    known = set(load_fornitori_bq(societa).keys())
    nuovi = unmapped_suppliers(scad_df, known)

    # Voci PF selezionabili: dalla dimensione canonica BQ; fallback statico se offline.
    try:
        voci_labels = load_voci_pf_bq(societa)
    except Exception:  # noqa: BLE001 — BQ assente in dev/offline è non-fatale
        voci_labels = VOCE_LABELS

    if nuovi:
        st.subheader(f"⚠️ {len(nuovi)} fornitori da mappare")
        st.caption(
            "Assegna ognuno alla sua voce: si salva su BQ (d_fornitori) e i prossimi "
            "mesi finisce da solo al posto giusto. 'Escludi sempre' = permanente "
            "(strutturale, raro); per saltarlo solo questo mese usa la sezione esclusioni."
        )
        try:
            from verticals.condges.pf_rotate.interactive_map import (
                suggest_voci_from_fatture,
            )

            sugg = suggest_voci_from_fatture([n["codice"] for n in nuovi], societa)
        except Exception:  # noqa: BLE001 — suggerimenti BQ best-effort
            sugg = {}
        voci_ids = list(voci_labels.keys())
        ESCLUDI = "__escludi__"
        opzioni = voci_ids + [ESCLUDI]
        with st.form("map_fornitori"):
            scelte: dict[int, tuple[str, str, bool]] = {}
            for n in nuovi:
                cod = int(n["codice"])
                suggested = sugg.get(cod, (None,))[0]
                default = suggested if suggested in voci_ids else (
                    "USCITE_VARIE_EXT" if "USCITE_VARIE_EXT" in voci_ids else (voci_ids[0] if voci_ids else ESCLUDI)
                )
                c_voce, c_ic = st.columns([4, 1])
                with c_voce:
                    sel = st.selectbox(
                        f"{cod} · {str(n['nome'])[:40]} (€ {n['totale']:,.2f})",
                        options=opzioni,
                        index=opzioni.index(default),
                        format_func=lambda v: "— escludi SEMPRE (permanente) —"
                        if v == ESCLUDI
                        else voci_labels[v],
                        key=f"map_{cod}",
                    )
                with c_ic:
                    inter = st.checkbox(
                        "intercompany",
                        key=f"ic_{cod}",
                        help="Movimento di cassa REALE tra società del gruppo (es. fitto "
                        "ORTI→INTUR): tracciato nella cassa del singolo, netta solo nel "
                        "consolidato. Diverso da 'escludi'.",
                    )
                scelte[cod] = (sel, str(n["nome"]), inter)
            if st.form_submit_button("💾 Salva mapping"):
                for cod, (voce, nome, inter) in scelte.items():
                    if voce == ESCLUDI:
                        upsert_fornitore_bq(
                            codice_fornitore=cod,
                            nome_esolver=nome,
                            nome_pf=nome,
                            voce_id="",
                            societa_id=societa,
                            is_excluded=True,
                            exclude_reason="escluso da app cashflow",
                        )
                    else:
                        upsert_fornitore_bq(
                            codice_fornitore=cod,
                            nome_esolver=nome,
                            nome_pf=nome.title() if nome.isupper() else nome,
                            voce_id=voce,
                            societa_id=societa,
                            is_intercompany=inter,
                        )
                st.success(f"{len(scelte)} fornitori salvati.")
                st.rerun()
        st.caption(
            "Puoi anche procedere senza mappare: i non mappati restano 'da mappare' "
            "(policy skip) e non entrano nelle voci."
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

    # Esclusioni SOLO per questa rotation (transienti, NON salvate): il mese dopo il
    # fornitore torna incluso. Per escludere sempre → "escludi sempre" in mappatura.
    st.subheader("Escludi da questa rotation (solo questo mese)")
    st.caption(
        "Esclusione temporanea, NON salvata: il prossimo mese tornano inclusi. "
        "Per un'esclusione permanente usa 'escludi sempre' nella mappatura sopra."
    )
    nome_by_cod = {
        int(r["codice_fornitore"]): str(r.get("nome", "")) for _, r in scad_df.iterrows()
    }
    extra_excluded = set(
        st.multiselect(
            "Fornitori da escludere questo mese",
            options=sorted(nome_by_cod),
            format_func=lambda c: f"{c} · {nome_by_cod[c][:40]}",
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
        # dump d_fornitori da BQ → CSV temp: l'engine resta CSV-based ma legge la
        # mappatura PERSISTENTE (BQ), incluse le mappe appena salvate sopra.
        forn_csv = Path(tmp) / "d_fornitori.csv"
        export_fornitori_to_csv(forn_csv)
        try:
            result = rotate(
                pf_path=pf_path,
                scad_df=scad_df,
                bucket_periodi=bucket_periodi,
                societa=societa,
                periodo_chiuso=periodo(anno, mese_chiuso),
                data_saldo=data_saldo,
                saldi={k: v for k, v in saldi.items() if v != 0} or None,
                fornitori_csv=forn_csv,
                out_dir=Path(tmp),
                unmapped_policy=policy,
                extra_excluded=extra_excluded or None,
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

    oltre = (result.scadenzario_summary or {}).get("oltre_orizzonte") or {}
    if oltre:
        tot_oltre = sum(oltre.values())
        st.warning(
            f"⚠️ Oltre orizzonte (senza colonna nel PF): {len(oltre)} fornitori, "
            f"{tot_oltre:,.2f} € NON scritti"
        )

    summ = scad_summary(scad_df, bucket_periodi)
    st.metric("Scaduto (roll-forward)", f"€ {summ['scaduto_totale']:,.2f}")
    st.metric("Totale partite aperte", f"€ {summ['totale_partite_aperte']:,.2f}")
    forward = summ["forward_buckets"]
    if forward:
        st.write("Progressivo forward:")
        st.table(
            {
                f"{MESI[periodo_anno_mese(p)[1]]} {periodo_anno_mese(p)[0]}": f"€ {v:,.2f}"
                for p, v in sorted(forward.items())
            }
        )

    # Nome canonico dell'engine: <societa>_PF_<YYYY-MM>_post-rotate_<timestamp>.xlsx
    # — ha il mese (primo proiettato) + il timestamp. Mostrato nel bottone per verifica.
    nome_download = result.out_path.name
    st.download_button(
        f"⬇️ Scarica {nome_download}",
        data=out_bytes,
        file_name=nome_download,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
