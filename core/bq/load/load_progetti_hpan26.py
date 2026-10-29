#!/usr/bin/env python3
"""Loader HPAN26PIANO3 — anagrafica progetto, voci di scope, impegno firmato.

Idempotente: prima DELETE su progetto_id, poi INSERT. Stesso schema del seed
Step 1 (``seed_progetti_step1.py``), di cui questo e' il fratello per il 2026.

Cosa carica:
- 1 riga in ``d_progetti``
- 10 righe in ``f_progetto_voci`` (le voci del Budget Cost 01/09, terzo piano)
- 1 riga in ``f_progetto_eventi``: IMPEGNO 482.000, contratto AMCN Rev9 firmato

Cosa NON carica, deliberatamente: i pagamenti ipotizzati. Un'ipotesi dentro una
tabella di fatti diventa un fatto al primo che la legge. Il calendario dei
pagamenti vive nel D1 dell'app CdG (decisione Stefano 28/10: BigQuery = fatti,
scenari = D1 dell'app che li produce).

Usage:
    python -m core.bq.load.load_progetti_hpan26 --dry-run
    python -m core.bq.load.load_progetti_hpan26
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI
from core.schemas import ImpegnoMeta, Progetto, ProgettoEvento, ProgettoVoce

PROGETTO_ID = "HPAN26PIANO3"
NOW_ISO = datetime.now(timezone.utc).isoformat()

log = logging.getLogger("load.progetti_hpan26")

# ── Anagrafica ─────────────────────────────────────────────────────────────
# budget_cap_eur: il tetto REALISTICO (Stefano, 28/10) — xlsx "Budget interno
# terzo piano: realistico vs banca", foglio Confronto, netto IVA, del 04/09/2026.
# Regia ne dichiara anche un secondo, budget_banca 2.016.260,50 (BP MPS,
# rielaborazione 06/10): il campo e' singolo e NOT NULL, quindi l'altro tetto
# resta solo in Regia. Differenza fra i due: 283.962,02.
#
# data_fine_prevista: la PREVISIONE (app di cantiere), non il termine
# contrattuale. Il termine 2027-03-20 dell'art. 12 vive nell'IMPEGNO, dove un
# termine ha senso. Quattro date circolano e divergono fino a 31 giorni:
#   contratto art.12  2027-03-20 | cronoprogramma Rev02  2027-04-03
#   app di cantiere   2027-04-14 | obiettivo apertura    2027-04-20
PROGETTI = [
    Progetto(
        progetto_id=PROGETTO_ID,
        nome="Terzo piano — 20 camere, Hotel Panorama",
        societa_owner_id="INTUR",
        business_unit_id="HOTEL",
        struttura="Hotel Panorama",
        budget_cap_eur=Decimal("1732298.48"),
        data_inizio=date(2026, 10, 19),
        data_fine_prevista=date(2027, 4, 14),
        stato="IN_CORSO",
        owner="Amalia Pisacane",
        drive_root_url="HPAN26PIANO3/",
    )
]

# ── Voci di scope ──────────────────────────────────────────────────────────
# Importi dal Budget Cost 01/09/2026, sezione Riepilogo Generale, PIANO TERZO.
# fornitore_id = codice_fornitore vero di d_anagrafica_fornitori dove esiste;
# None dove il fornitore NON e' in anagrafica (AMCN compreso, pur avendo un
# contratto firmato da 482.000: va aperta la sua anagrafica).
# Ascensori (150.000) e garage (15.000): RINVIATI al 2028, fuori dallo scope.
_VOCI: list[tuple[str, str, str, str | None, str]] = [
    # (seq, descrizione, categoria, fornitore_id, importo a memoria nelle note)
    ("001", "Lavori edili e di finitura", "EDILE", None, "AMCN · 470.000 a budget, 482.000 a contratto"),
    ("002", "Fit out e FF&E camere", "FFE", None, "479.406 · 14 fornitori nel dettaglio del budget"),
    ("003", "Impianti elettrici e speciali", "IMPIANTI_EL", None, "STE · 180.000 · 20 camere x 9.000"),
    ("004", "Impianti termoidraulici e meccanici", "IMPIANTI_TM", "121", "Santelia Luigi · 180.000"),
    ("005", "Sistema di gestione e apertura camere", "IMPIANTI_SP", None, "VDA · 18.000 · 20 x 900"),
    ("006", "Progetto architettonico, sicurezza, DL", "TECNICHE", "351", "Ing. Pisacane Amalia · 40.000"),
    ("007", "Progetto VVFF", "TECNICHE", None, "Studio Delta · 27.000"),
    ("008", "Progetto acustica", "TECNICHE", None, "2.000"),
    ("009", "Tecnico di cantiere", "TECNICHE", None, "17.500"),
    ("010", "Disegni interior esecutivi e project monitoring", "TECNICHE", "1091", "Hospitality Project · 34.000"),
]
VOCI = [
    ProgettoVoce(
        voce_id=f"{PROGETTO_ID}.{seq}",
        progetto_id=PROGETTO_ID,
        codice_interno=seq,
        descrizione=desc,
        categoria=cat,
        fornitore_id=forn,
        societa_pagante_id="INTUR",
        note=note,
    )
    for seq, desc, cat, forn, note in _VOCI
]

# ── Eventi: solo fatti ─────────────────────────────────────────────────────
# L'unico impegno bilaterale documentato: contratto d'appalto AMCN Rev9,
# firmato il 15/10/2026, art. 5 "a misura", 482.000 inclusi 15.000 di
# sicurezza, reverse charge. rate=[] perche' i SAL non sono un calendario
# pattuito: maturano ogni 60.000 di lavori eseguiti (art. 6), quindi le date
# non esistono finche' i lavori non avanzano.
EVENTI = [
    ProgettoEvento(
        evento_id="evt-hpan26p3-amcn-impegno",
        voce_id=f"{PROGETTO_ID}.001",
        progetto_id=PROGETTO_ID,
        tipo_evento="IMPEGNO",
        data_evento=date(2026, 10, 15),
        data_registrazione=NOW_ISO,
        importo_eur=Decimal("482000.00"),
        fornitore_id=None,
        metadata=ImpegnoMeta(
            data_firma=date(2026, 10, 15),
            numero_contratto="Rev09",
            rate=[],
            stato_commitment="IN_CORSO",
        ),
        file_sorgente="2026-10-15_AMCN_Contratto-appalto_Piano3_Rev09_FIRMATO_Scansione.pdf",
    )
]


def _riga(m) -> dict:
    d = m.model_dump(mode="json")
    d["data_caricamento"] = NOW_ISO
    return d


def _riga_evento(e: ProgettoEvento) -> dict:
    d = e.model_dump(mode="json")
    d["metadata"] = json.dumps(d["metadata"])
    return d


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    righe = {
        D_PROGETTI: [_riga(x) for x in PROGETTI],
        F_PROGETTO_VOCI: [_riga(x) for x in VOCI],
        F_PROGETTO_EVENTI: [_riga_evento(x) for x in EVENTI],
    }
    for tab, rr in righe.items():
        log.info("%-42s %d righe", tab.split(".")[-1], len(rr))

    if args.dry_run:
        log.info("[DRY-RUN] nessuna scrittura")
        log.info("progetto  %s · tetto %s · %s → %s",
                 PROGETTI[0].progetto_id, PROGETTI[0].budget_cap_eur,
                 PROGETTI[0].data_inizio, PROGETTI[0].data_fine_prevista)
        for v in VOCI:
            log.info("  voce %s  %-48s %-13s forn=%s", v.codice_interno,
                     v.descrizione[:48], v.categoria, v.fornitore_id or "—")
        for e in EVENTI:
            log.info("  evento %s  %s  %s €", e.tipo_evento, e.data_evento, e.importo_eur)
        return 0

    client = get_client()
    for tab, key in ((D_PROGETTI, "progetto_id"),
                     (F_PROGETTO_VOCI, "progetto_id"),
                     (F_PROGETTO_EVENTI, "progetto_id")):
        q = f"DELETE FROM `{tab}` WHERE {key} = @pid"
        from google.cloud import bigquery
        job = client.query(q, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("pid", "STRING", PROGETTO_ID)]))
        job.result()
        log.info("DELETE %-42s %s righe", tab.split(".")[-1], job.num_dml_affected_rows)

    for tab, rr in righe.items():
        err = client.insert_rows_json(tab, rr)
        if err:
            log.error("INSERT %s: %s", tab, err)
            return 1
        log.info("INSERT %-42s %d righe", tab.split(".")[-1], len(rr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
