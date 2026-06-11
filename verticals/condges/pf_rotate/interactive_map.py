"""Risoluzione interattiva dei fornitori non mappati (UnmappedPolicy.INTERACTIVE).

Il pezzo "buono" della Streamlit portato nel CLI: per ogni fornitore nuovo nello
scadenzario chiede la voce PF (con suggerimento derivato dai conti delle sue
fatture in f_fatture_righe, best-effort) e persiste la scelta in d_fornitori.csv
via append_fornitore. Dopo la risoluzione il caller prosegue con policy FAIL.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from verticals.condges.app_scadenzario import VOCE_LABELS
from verticals.condges.pf_rotate.fornitori_map import append_fornitore, load_fornitori

log = logging.getLogger(__name__)

# Classe conto Esolver (primi 2 caratteri) -> voce PF suggerita
CLASSE_TO_VOCE = {
    "55": "USCITE_MATERIE_PRIME",
    "57": "USCITE_SERVIZI_PRODUZIONE",
    "59": "USCITE_SERVIZI_PRODUZIONE",
    "61": "USCITE_CONSULENZE",
    "63": "USCITE_VARIE_EXT",
    "65": "USCITE_CANONE_PASSIVO",
    "67": "USCITE_SALARI",
    "05": "USCITE_VARIE_EXT",
    "15": "USCITE_VARIE_EXT",
    "71": "USCITE_VARIE_EXT",
    "75": "USCITE_VARIE_EXT",
}

VOCI_MENU = list(VOCE_LABELS.keys())


def suggest_voci_from_fatture(
    codici: list[int], societa: str
) -> dict[int, tuple[str, str]]:
    """Best-effort: {codice: (voce_id, motivo)} dalla classe conto più frequente
    nelle fatture del fornitore. Vuoto se BQ non disponibile."""
    if not codici:
        return {}
    try:
        from core.bq.client import get_client
        from core.config import F_FATTURE_RIGHE

        sql = f"""
        SELECT cod_clifor, SUBSTR(cod_conto,1,2) classe,
               ANY_VALUE(des_conto) des_conto, COUNT(*) n
        FROM `{F_FATTURE_RIGHE}`
        WHERE societa_id = @societa AND tipo_registro = 'ACQUISTO'
          AND cod_clifor IN UNNEST(@codici)
        GROUP BY cod_clifor, classe
        QUALIFY ROW_NUMBER() OVER (PARTITION BY cod_clifor ORDER BY n DESC) = 1
        """
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa),
                bigquery.ArrayQueryParameter(
                    "codici", "STRING", [str(c) for c in codici]
                ),
            ]
        )
        out: dict[int, tuple[str, str]] = {}
        for row in get_client().query(sql, job_config=job_config).result():
            voce = CLASSE_TO_VOCE.get(row.classe)
            if voce:
                out[int(row.cod_clifor)] = (
                    voce,
                    f"dalle fatture: classe {row.classe} '{row.des_conto}' ({row.n} righe)",
                )
        return out
    except Exception as e:  # BQ assente/offline: il prompt funziona senza suggerimenti
        log.warning("Suggerimenti da f_fatture_righe non disponibili: %s", e)
        return {}


def resolve_unmapped_interactive(
    scad_df: pd.DataFrame,
    fornitori_csv: Path,
    societa: str,
    *,
    input_fn=input,
    print_fn=print,
    suggestions: dict[int, tuple[str, str]] | None = None,
) -> list[int]:
    """Prompt per ogni fornitore dello scadenzario assente da d_fornitori.csv.

    Scelte: numero voce / invio = suggerimento / 'e' = escludi / 's' = salta
    (resta unmapped). Persiste subito ogni scelta. Ritorna i codici risolti.
    """
    known = set(load_fornitori(fornitori_csv, societa=societa).keys())
    scad_codici = {int(c) for c in scad_df["codice_fornitore"]}
    unmapped = sorted(scad_codici - known)
    if not unmapped:
        return []

    if suggestions is None:
        suggestions = suggest_voci_from_fatture(unmapped, societa)

    print_fn(f"\n{len(unmapped)} fornitori nuovi da mappare ({societa}):\n")
    for i, (voce, label) in enumerate(VOCE_LABELS.items(), 1):
        print_fn(f"  [{i}] {label} ({voce})")
    print_fn("  [e] escludi dal PF   [s] salta per questo giro\n")

    resolved: list[int] = []
    for cod in unmapped:
        sub = scad_df[scad_df["codice_fornitore"] == cod]
        nome = str(sub["nome"].iloc[0])
        totale = float(sub["totale"].iloc[0])
        sugg = suggestions.get(cod)
        sugg_txt = f" [invio = {VOCE_LABELS[sugg[0]]} — {sugg[1]}]" if sugg else ""
        while True:
            answer = (
                input_fn(f"  {cod} {nome} (tot {totale:,.2f}) → voce?{sugg_txt} ")
                .strip()
                .lower()
            )
            if answer == "" and sugg:
                voce_id = sugg[0]
            elif answer == "s":
                voce_id = None
            elif answer == "e":
                append_fornitore(
                    fornitori_csv,
                    codice_fornitore=cod,
                    nome_esolver=nome,
                    nome_pf=nome,
                    voce_id="",
                    societa_id=societa,
                    is_excluded=True,
                    exclude_reason="escluso da prompt pf-rotate",
                )
                resolved.append(cod)
                break
            elif answer.isdigit() and 1 <= int(answer) <= len(VOCI_MENU):
                voce_id = VOCI_MENU[int(answer) - 1]
            else:
                print_fn("    scelta non valida — numero voce, invio, 'e' o 's'")
                continue

            if voce_id is None:
                break  # salta: resta unmapped
            append_fornitore(
                fornitori_csv,
                codice_fornitore=cod,
                nome_esolver=nome,
                nome_pf=nome.title() if nome.isupper() else nome,
                voce_id=voce_id,
                societa_id=societa,
            )
            resolved.append(cod)
            break

    return resolved
