#!/usr/bin/env python3
"""Generate Tesoreria Excel from PF (+ optional scadenzario); mirrors Streamlit tesoreria app.

Run from repo root (``pip install -e .`` or ``PYTHONPATH=.``).

Senza scadenzario::

    python -m condges.gen_tesoreria_xlsx \\
      --pf ~/Downloads/ORTI\\ Piano\\ Finanziario\\ 2026.xlsx \\
      --out ~/Downloads/Tesoreria_ORTI_2026.xlsx

Con scadenzario (scegli ``--scad-tipo`` in base al file Esolver)::

    python -m condges.gen_tesoreria_xlsx \\
      --pf ~/Downloads/ORTI\\ Piano\\ Finanziario\\ 2026.xlsx \\
      --out ~/Downloads/Tesoreria_ORTI_2026.xlsx \\
      --scad ~/Downloads/situazione_scadenze.xlsx \\
      --scad-tipo sintetica

Valori ``--scad-tipo``: ``riepilogo`` (tabella con intestazioni mese),
``partite`` (righe fattura colonne fisse), ``sintetica`` (col. A ``codice nome``).

Pass ``--verbose`` per vedere anche il warning opzionale BigQuery Storage API.

"""

from __future__ import annotations

import argparse
import warnings
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd

from verticals.condges.bq_tesoreria_core import fetch_consuntivo_df, fetch_voci_df
from verticals.condges.cashflow import project_cashflow
from verticals.condges.export_excel import generate_tesoreria_excel
from verticals.condges.parse_pf import PFData, ScadenzarioData, parse_pf, parse_scadenzario
from verticals.condges.scadenze_parse import (
    parse_scadenze,
    partite_df_to_scadenzario_data,
    sintetica_list_to_scadenzario_data,
)
from verticals.condges.scadenzario_excel import parse_sintetica_scadenze

BANKS_BY_SOCIETA: dict[str, list[str]] = {
    "ORTI": ["MPS", "Intesa", "MPS_KROSS"],
    "INTUR": ["Sella", "MPS", "Intesa", "BCP"],
}


def _match_banca_saldo(pf_saldi: dict[str, float], bank_name: str) -> float:
    bank_words = set(bank_name.lower().replace("_", " ").split())
    for label, amount in pf_saldi.items():
        label_words = set(label.lower().split())
        if bank_words <= label_words:
            return amount
    return 0.0


def assemble_voci_data(
    pf_data: PFData,
    societa: str,
    anno: int,
    df_voci: pd.DataFrame,
) -> list[dict]:
    try:
        df_consuntivo = fetch_consuntivo_df(societa, anno)
    except Exception:
        df_consuntivo = pd.DataFrame(columns=["voce_id", "mese", "importo_consuntivo"])

    cons_index: dict[tuple[str, int], float] = {}
    for _, row in df_consuntivo.iterrows():
        cons_index[(str(row["voce_id"]), int(row["mese"]))] = float(row["importo_consuntivo"])

    df_filtered = df_voci[
        df_voci["societa_id"].isna() | (df_voci["societa_id"] == societa)
    ].copy()
    df_filtered = df_filtered.sort_values("ord")

    voci_data: list[dict] = []
    for _, voce_row in df_filtered.iterrows():
        voce_id = voce_row["voce_id"]
        voce_label = voce_row.get("voce_label", voce_id)
        sezione = voce_row.get("sezione", "")
        categoria = voce_row.get("categoria", "")
        ord_val = voce_row.get("ord", 0)
        for mese in range(1, 13):
            prev = (
                pf_data.voci[voce_id].importi.get(mese, 0.0)
                if voce_id in pf_data.voci
                else 0.0
            )
            cons = cons_index.get((voce_id, mese), 0.0)
            voci_data.append(
                {
                    "voce_id": voce_id,
                    "voce_label": voce_label,
                    "sezione": sezione,
                    "categoria": categoria,
                    "ord": ord_val,
                    "mese": mese,
                    "previsione": prev,
                    "consuntivo": cons,
                }
            )
    return voci_data


def parse_scad_file(raw: bytes, tipo: str) -> ScadenzarioData:
    if tipo == "riepilogo":
        return parse_scadenzario(raw)
    if tipo == "partite":
        df_scad, bucket_months = parse_scadenze(BytesIO(raw))
        return partite_df_to_scadenzario_data(df_scad, bucket_months)
    suppliers, bucket_months = parse_sintetica_scadenze(BytesIO(raw))
    return sintetica_list_to_scadenzario_data(suppliers, bucket_months)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export Tesoreria Excel from PF (+ optional scadenzario).")
    ap.add_argument("--pf", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scad", type=Path, default=None)
    ap.add_argument(
        "--scad-tipo",
        choices=("riepilogo", "partite", "sintetica"),
        default="riepilogo",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Show Streamlit cache / BigQuery Storage warnings (default is quiet).",
    )
    args = ap.parse_args()

    if not args.verbose:
        warnings.filterwarnings("ignore", message="BigQuery Storage module not found")

    pf_data = parse_pf(args.pf.read_bytes())
    societa = pf_data.societa if pf_data.societa in ("ORTI", "INTUR") else "ORTI"
    anno = int(pf_data.anno)

    banks = BANKS_BY_SOCIETA[societa]
    saldi_banca = {b: _match_banca_saldo(pf_data.saldi_banca, b) for b in banks}

    df_voci = fetch_voci_df()
    voci_data = assemble_voci_data(pf_data, societa, anno, df_voci)

    entrate_per_mese: dict[int, float] = {}
    uscite_per_mese: dict[int, float] = {}
    for row in voci_data:
        m = row["mese"]
        if row["sezione"] == "ENTRATE":
            entrate_per_mese[m] = entrate_per_mese.get(m, 0.0) + row["previsione"]
        else:
            uscite_per_mese[m] = uscite_per_mese.get(m, 0.0) + row["previsione"]

    scad_data: ScadenzarioData | None = None
    if args.scad is not None:
        scad_data = parse_scad_file(args.scad.read_bytes(), args.scad_tipo)

    fornitori_per_mese = scad_data.totale_per_mese if scad_data else {}

    saldo_iniziale = sum(saldi_banca.values())
    mese_corrente = date.today().month
    cashflow_rows = project_cashflow(
        saldo_iniziale=saldo_iniziale,
        mese_inizio=mese_corrente,
        entrate_per_mese=entrate_per_mese,
        uscite_per_mese=uscite_per_mese,
        fornitori_per_mese=fornitori_per_mese,
        mese_fine=12,
    )

    fornitori_list = scad_data.fornitori if scad_data else None
    buf = generate_tesoreria_excel(
        societa=societa,
        anno=anno,
        cashflow_rows=cashflow_rows,
        voci_data=voci_data,
        fornitori=fornitori_list,
        saldi_banca=saldi_banca,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(buf.getvalue())
    print(f"Wrote {args.out.resolve()}")


if __name__ == "__main__":
    main()
