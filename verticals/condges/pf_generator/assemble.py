"""Orchestratore del generatore PF: sorgenti -> workbook + report."""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd

from verticals.condges.pf_generator.blocchi import (
    blocco_a_per_voce,
    rettifica_doppio_conteggio,
)
from verticals.condges.pf_generator.costanti import (
    PRIMA_RIGA_BLOCCO_A,
    VOCE_SHEET_NAME,
)
from verticals.condges.pf_generator.previsioni import estrai_previsioni
from verticals.condges.pf_generator.template import (
    scrivi_controlli,
    scrivi_da_mappare,
    scrivi_foglio_voce,
    scrivi_riepilogo,
)


def _check_codice_nome(wb: openpyxl.Workbook, fornitori: dict[int, dict]) -> dict:
    """Legge le righe blocco-A dai fogli voce e verifica che ogni
    (codice, nome) coincida con fornitori[codice]['nome_pf'].
    Esito OK solo se tutti corrispondono — non è un rubber stamp.
    """
    mismatches: list[str] = []
    for voce_id, sheet_name in VOCE_SHEET_NAME.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        # Le righe blocco-A vanno da PRIMA_RIGA_BLOCCO_A fino alla riga
        # di intestazione sezione B (prima riga vuota o etichetta di sezione).
        for r in range(PRIMA_RIGA_BLOCCO_A, ws.max_row + 1):
            codice = ws.cell(row=r, column=1).value
            if not isinstance(codice, int):
                break  # fine blocco A (riga vuota o sezione B)
            nome = ws.cell(row=r, column=2).value or ""
            entry = fornitori.get(codice)
            if entry is None:
                continue  # stub non in CSV: non verificabile
            atteso = entry.get("nome_pf") or str(codice)
            if nome != atteso:
                mismatches.append(f"{codice}: got '{nome}' want '{atteso}'")
    if not mismatches:
        return {
            "check": "codice↔nome vs CSV",
            "esito": "OK",
            "dettaglio": f"{sum(1 for s in wb.sheetnames if s in VOCE_SHEET_NAME.values())} fogli verificati",
        }
    return {
        "check": "codice↔nome vs CSV",
        "esito": "ERR",
        "dettaglio": f"{len(mismatches)} mismatch; primo: {mismatches[0]}",
    }


def _check_quadratura(scad_df: pd.DataFrame, per_voce, unmapped) -> dict:
    """|somma scritta blocchi A + DA MAPPARE| == |somma partite export|."""
    scritto = sum(
        v for righe in per_voce.values() for r in righe for v in r["mesi"].values()
    )
    scritto += sum(v for r in unmapped for v in r["mesi"].values())
    atteso = float(scad_df["totale"].abs().sum())
    delta = round(abs(scritto) - atteso, 2)
    return {
        "check": "quadratura blocchi A vs export partite",
        "esito": "OK" if abs(delta) < 0.01 else "ERR",
        "dettaglio": f"scritto={scritto:.2f} atteso={atteso:.2f} delta={delta}",
    }


def genera_pf(
    *,
    pf_prev_bytes: bytes,
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    fornitori: dict[int, dict],
    societa: str,
    anno: int,
    primo_mese_aperto: int,
    entrate: list[dict] | None = None,
) -> tuple[bytes, dict]:
    per_voce, unmapped = blocco_a_per_voce(
        scad_df,
        bucket_months,
        fornitori,
        primo_mese_aperto=primo_mese_aperto,
    )
    codici_partite = {int(c) for c in scad_df["codice_fornitore"]}
    estratto = estrai_previsioni(
        pf_prev_bytes,
        codici_partite=codici_partite,
        primo_mese_aperto=primo_mese_aperto,
    )

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    controlli: list[dict] = []
    fornitori_scritti = 0
    voci_attive: list[str] = []
    for voce_id in VOCE_SHEET_NAME:
        blocco_a = per_voce.get(voce_id, [])
        prev = estratto.get(voce_id, {}).get("previsioni", [])
        cons = estratto.get(voce_id, {}).get("consuntivi", {})

        # Fornitori con SOLO storico chiuso (no partita aperta): aggiungi stub row
        # così scrivi_foglio_voce può mergiare i loro consuntivi. Codici non in
        # fornitori (non mappati con storico) vengono ignorati — limitazione v1.
        codici_in_blocco_a = {r["codice"] for r in blocco_a}
        for codice, _ in cons.items():
            if codice in codici_in_blocco_a:
                continue
            entry = fornitori.get(codice)
            if entry is None or entry.get("voce_id") != voce_id:
                continue
            nome_pf = entry.get("nome_pf") or str(codice)
            blocco_a.append({"codice": codice, "nome": nome_pf, "mesi": {}})
        # Ordine deterministico (idempotenza)
        blocco_a.sort(key=lambda r: (r["nome"].lower(), r["codice"]))

        if not blocco_a and not prev and not cons:
            continue
        rett = rettifica_doppio_conteggio(blocco_a, prev)
        scrivi_foglio_voce(
            wb,
            voce_id=voce_id,
            blocco_a=blocco_a,
            previsioni=prev,
            consuntivi=cons,
            rettifica=rett,
            primo_mese_aperto=primo_mese_aperto,
        )
        fornitori_scritti += len(blocco_a)
        voci_attive.append(voce_id)

    # Ordine fogli: scrivi_riepilogo PRIMA di scrivi_controlli.
    # Entrambe inseriscono a index 0; riepilogo-poi-controlli => Controlli in cima.
    scrivi_riepilogo(
        wb,
        societa=societa,
        anno=anno,
        entrate=entrate or [],
        voci_attive=voci_attive,
        primo_mese_aperto=primo_mese_aperto,
    )
    scrivi_da_mappare(wb, unmapped)

    controlli.append(_check_quadratura(scad_df, per_voce, unmapped))
    controlli.append(_check_codice_nome(wb, fornitori))
    controlli.append(
        {
            "check": "fornitori non mappati",
            "esito": "OK" if not unmapped else "WARN",
            "dettaglio": f"{len(unmapped)} nel foglio DA MAPPARE",
        }
    )
    scrivi_controlli(wb, controlli)

    buf = BytesIO()
    wb.save(buf)
    report = {
        "fornitori_scritti": fornitori_scritti,
        "unmapped": sorted(r["codice"] for r in unmapped),
        "voci": voci_attive,
        "controlli": controlli,
    }
    return buf.getvalue(), report
