"""Livello B del cashflow consuntivo — dati puri, zero import Streamlit.

Spec: docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md.
I trasferimenti interni si neutralizzano SOLO al consolidato di società (Livello B);
il Livello A (v_cash_position) resta sui lordi per conto.
"""

from __future__ import annotations

import re

_PATTERN_GIRO = re.compile(
    r"GIROCONTO|ASS\.? ?CIRCOLAR|ASSEGNO CIRCOLARE|VERSAMENTO NS", re.IGNORECASE
)


def detect_trasferimenti_interni(
    movimenti: list[dict], window_days: int = 3
) -> list[dict]:
    """Tagga i trasferimenti interni fra conti della stessa società.

    Ritorna gli stessi dict con transfer_status ('AUTO'|'CANDIDATE'|None)
    e transfer_group (int|None). Deterministic-first: solo coppie univoche
    diventano AUTO; ambiguità → CANDIDATE, mai neutralizzate.
    """
    out = [dict(m, transfer_status=None, transfer_group=None) for m in movimenti]

    def compatibile(a: dict, b: dict) -> bool:
        if abs(abs(a["importo_netto"]) - abs(b["importo_netto"])) > 0.01:
            return False
        if (a["importo_netto"] > 0) == (b["importo_netto"] > 0):
            return False
        if abs((a["data_operazione"] - b["data_operazione"]).days) > window_days:
            return False
        if a["banca_id"] == b["banca_id"]:
            # stessa banca: solo con pattern causale su almeno una gamba
            return bool(
                _PATTERN_GIRO.search(a["descrizione"] or "")
                or _PATTERN_GIRO.search(b["descrizione"] or "")
            )
        return True

    # candidati per ogni movimento
    candidates: dict[int, list[int]] = {i: [] for i in range(len(out))}
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if compatibile(out[i], out[j]):
                candidates[i].append(j)
                candidates[j].append(i)

    # coppie univoche → AUTO (greedy per distanza data crescente)
    pairs = []
    for i, cands in candidates.items():
        if len(cands) == 1 and len(candidates[cands[0]]) == 1 and i < cands[0]:
            dist = abs(
                (out[i]["data_operazione"] - out[cands[0]]["data_operazione"]).days
            )
            pairs.append((dist, i, cands[0]))

    group = 0
    for _, i, j in sorted(pairs):
        group += 1
        for k in (i, j):
            out[k]["transfer_status"] = "AUTO"
            out[k]["transfer_group"] = group

    # ambigui → CANDIDATE
    for i, cands in candidates.items():
        if out[i]["transfer_status"] is None and cands:
            out[i]["transfer_status"] = "CANDIDATE"

    return out


def consolidato_societa(movimenti_tagged: list[dict]) -> dict:
    """Livello B: flussi esterni con trasferimenti interni (AUTO) neutralizzati.

    I CANDIDATE restano nei flussi esterni ma sono quantificati a parte:
    verranno risolti dalla review queue (C.2), mai neutralizzati in silenzio.
    """
    incassi = pagamenti = trasferimenti = candidati = 0.0
    for m in movimenti_tagged:
        imp = m["importo_netto"]
        if m["transfer_status"] == "AUTO":
            trasferimenti += abs(imp)
            continue
        if m["transfer_status"] == "CANDIDATE":
            candidati += abs(imp)
        if imp > 0:
            incassi += imp
        else:
            pagamenti += abs(imp)
    return {
        "incassi_esterni": round(incassi, 2),
        "pagamenti_esterni": round(pagamenti, 2),
        "trasferimenti_interni": round(trasferimenti, 2),
        "candidati_trasferimento": round(candidati, 2),
        "variazione_netta": round(incassi - pagamenti, 2),
    }


def fetch_movimenti_mese(societa_id: str, anno: int, mese: int) -> list[dict]:
    """Movimenti banca del mese, nel formato atteso da detect_trasferimenti_interni."""
    from google.cloud import bigquery

    from core.bq.client import get_client
    from core.config import F_BANCHE_MOVIMENTI

    client = get_client()
    sql = f"""
    SELECT id_movimento, banca_id, data_operazione,
           CAST(importo_netto AS FLOAT64) AS importo_netto, descrizione
    FROM `{F_BANCHE_MOVIMENTI}`
    WHERE societa_id = @societa
      AND DATE_TRUNC(data_operazione, MONTH) = DATE(@anno, @mese, 1)
      AND descrizione IS NOT NULL
      AND descrizione NOT IN ('Totale (€)', 'TOTALE')
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa_id),
                bigquery.ScalarQueryParameter("anno", "INT64", anno),
                bigquery.ScalarQueryParameter("mese", "INT64", mese),
            ]
        ),
    )
    return [dict(r) for r in job.result()]
