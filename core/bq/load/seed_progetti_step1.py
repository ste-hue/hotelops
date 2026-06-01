#!/usr/bin/env python3
"""
Seed loader Step 1 — popola HPAN25PIANO1 + SPIAGGIA_LOTTO7 con dati inline.

Idempotente: prima DELETE, poi INSERT (per i due progetti del seed).

Carica:
- 2 righe in d_progetti
- 10 righe in f_progetto_voci (5 HPAN + 5 SPIAGGIA)
- 19 righe in f_progetto_eventi (11 HPAN + 8 SPIAGGIA)

Usage:
    python -m core.bq.load.seed_progetti_step1
    python -m core.bq.load.seed_progetti_step1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal

from google.cloud.bigquery import LoadJobConfig, WriteDisposition

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI
from core.schemas import (
    Progetto,
    ProgettoEvento,
    ProgettoVoce,
)

NOW_ISO = datetime.utcnow().isoformat()
SEED_PROGETTI_IDS = ("HPAN25PIANO1", "SPIAGGIA_LOTTO7")


def build_progetti() -> list[Progetto]:
    return [
        Progetto(
            progetto_id="HPAN25PIANO1",
            nome="Camere Primo Piano - Hotel Panorama",
            societa_owner_id="INTUR",
            business_unit_id="HOTEL",
            struttura="Hotel Panorama",
            budget_cap_eur=Decimal("1200000.00"),
            data_inizio=date(2026, 2, 1),
            stato="IN_CORSO",
            owner="Stefano Della Pietra Jr",
            drive_root_url="investimenti2026/HPAN25PIANO1/",
        ),
        Progetto(
            progetto_id="SPIAGGIA_LOTTO7",
            nome="Spiaggia Lotto 7 Maiori",
            societa_owner_id="INTUR",
            business_unit_id="LIDO",
            struttura="Stabilimento Lido 7",
            budget_cap_eur=Decimal("490000.00"),
            data_inizio=date(2025, 3, 1),
            stato="PIANIFICATO",
            owner="Stefano Della Pietra Jr",
            drive_root_url=None,
        ),
    ]


def build_voci() -> list[ProgettoVoce]:
    return [
        # ── HPAN25PIANO1 (5 voci) ──
        ProgettoVoce(voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1", codice_interno="001",
            descrizione="Opere murarie strutturali piano 1 (AMCN)", categoria="EDILE",
            societa_pagante_id="INTUR", fornitore_id="anag-amcn-001"),
        ProgettoVoce(voce_id="HPAN25PIANO1.002", progetto_id="HPAN25PIANO1", codice_interno="002",
            descrizione="Impianti elettrici (STE)", categoria="IMPIANTI_EL",
            societa_pagante_id="INTUR", fornitore_id="anag-ste-002"),
        ProgettoVoce(voce_id="HPAN25PIANO1.008", progetto_id="HPAN25PIANO1", codice_interno="008",
            descrizione="Direzione lavori (Amalia Pisacane)", categoria="CONSULENZA",
            societa_pagante_id="INTUR", fornitore_id=None),
        ProgettoVoce(voce_id="HPAN25PIANO1.010", progetto_id="HPAN25PIANO1", codice_interno="010",
            descrizione="Project Management (Hospitality Project)", categoria="CONSULENZA",
            societa_pagante_id="ORTI", fornitore_id=None),
        ProgettoVoce(voce_id="HPAN25PIANO1.013", progetto_id="HPAN25PIANO1", codice_interno="013",
            descrizione="Falegnameria armadi (Rino Cuomo)", categoria="ARREDI_CUSTOM",
            societa_pagante_id="INTUR", fornitore_id=None,
            note="Stima da Excel; nessun preventivo ricevuto"),
        # ── SPIAGGIA_LOTTO7 (5 voci) ──
        ProgettoVoce(voce_id="SPIAGGIA_LOTTO7.001", progetto_id="SPIAGGIA_LOTTO7", codice_interno="001",
            descrizione="Ombrelloni Pagoda 164pz", categoria="OMBRELLONI",
            qta=Decimal("164"), unita="pz",
            societa_pagante_id="INTUR", fornitore_id=None),
        ProgettoVoce(voce_id="SPIAGGIA_LOTTO7.002", progetto_id="SPIAGGIA_LOTTO7", codice_interno="002",
            descrizione="Arredo Ethimo (cabane+sedie+tavolini+lampade)", categoria="ARREDI",
            societa_pagante_id="INTUR", fornitore_id=None),
        ProgettoVoce(voce_id="SPIAGGIA_LOTTO7.005", progetto_id="SPIAGGIA_LOTTO7", codice_interno="005",
            descrizione="Giochi da spiaggia (Kompan)", categoria="GIOCHI",
            societa_pagante_id="INTUR", fornitore_id=None),
        ProgettoVoce(voce_id="SPIAGGIA_LOTTO7.011", progetto_id="SPIAGGIA_LOTTO7", codice_interno="011",
            descrizione="Vela motorizzata (Similis)", categoria="STRUTTURA",
            societa_pagante_id="INTUR", fornitore_id=None),
        ProgettoVoce(voce_id="SPIAGGIA_LOTTO7.012", progetto_id="SPIAGGIA_LOTTO7", codice_interno="012",
            descrizione="Buvette", categoria="STRUTTURA",
            societa_pagante_id="INTUR", fornitore_id=None,
            note="Da definire fornitore"),
    ]


def build_eventi() -> list[ProgettoEvento]:
    return [
        # ── HPAN25PIANO1.001 AMCN: PREV → 2 IMPEGNI (overrun) → 3 FATT ──
        ProgettoEvento(evento_id="evt-h001-prev", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO", data_evento=date(2026, 1, 15), data_registrazione=NOW_ISO,
            importo_eur=Decimal("375389.25"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "PREVENTIVO", "articolo": "Opere murarie strutturali piano 1",
                "stato_preventivo": "ACCETTATO", "note": "OFFERTA FIRMATA HOTEL PANORAMA.pdf"}),
        ProgettoEvento(evento_id="evt-h001-imp1", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO", data_evento=date(2026, 2, 27), data_registrazione=NOW_ISO,
            importo_eur=Decimal("375389.25"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "IMPEGNO", "from_preventivo_evento_id": "evt-h001-prev",
                "data_firma": "2026-02-27", "rate": [], "stato_commitment": "FIRMATO"}),
        ProgettoEvento(evento_id="evt-h001-imp2", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO", data_evento=date(2026, 3, 26), data_registrazione=NOW_ISO,
            importo_eur=Decimal("412928.18"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "IMPEGNO", "data_firma": "2026-02-27", "rate": [],
                "stato_commitment": "IN_CORSO",
                "motivo_variazione": "Overrun amianto - Ft 02-26 INTUR Saldo_AMIANTO"}),
        ProgettoEvento(evento_id="evt-h001-fatt1", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA", data_evento=date(2026, 3, 14), data_registrazione=NOW_ISO,
            importo_eur=Decimal("44000.00"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "FATTURA", "numero_fattura": "FPR 23/26", "data_emissione": "2026-03-14",
                "tipo_doc": "FT-RC", "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30", "copre_rate": []}),
        ProgettoEvento(evento_id="evt-h001-fatt2", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA", data_evento=date(2026, 3, 14), data_registrazione=NOW_ISO,
            importo_eur=Decimal("56732.02"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "FATTURA", "numero_fattura": "FPR 24/26", "data_emissione": "2026-03-14",
                "tipo_doc": "FT-RC", "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30", "copre_rate": []}),
        ProgettoEvento(evento_id="evt-h001-fatt3", voce_id="HPAN25PIANO1.001", progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA", data_evento=date(2026, 3, 26), data_registrazione=NOW_ISO,
            importo_eur=Decimal("60157.92"), fornitore_id="anag-amcn-001",
            metadata={"tipo": "FATTURA", "numero_fattura": "FPR 31/26", "data_emissione": "2026-03-26",
                "tipo_doc": "FT-RC", "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30", "copre_rate": []}),
        # ── HPAN25PIANO1.002 STE: PREV → IMPEGNO → 1 FATT ──
        ProgettoEvento(evento_id="evt-h002-prev", voce_id="HPAN25PIANO1.002", progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO", data_evento=date(2026, 1, 20), data_registrazione=NOW_ISO,
            importo_eur=Decimal("101705.84"), fornitore_id="anag-ste-002",
            metadata={"tipo": "PREVENTIVO", "articolo": "Impianti elettrici e speciali",
                "stato_preventivo": "ACCETTATO", "note": "imp_elettrico_e_speciali_COMPUTO METRICO"}),
        ProgettoEvento(evento_id="evt-h002-imp", voce_id="HPAN25PIANO1.002", progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO", data_evento=date(2026, 2, 27), data_registrazione=NOW_ISO,
            importo_eur=Decimal("106791.13"), fornitore_id="anag-ste-002",
            metadata={"tipo": "IMPEGNO", "from_preventivo_evento_id": "evt-h002-prev",
                "data_firma": "2026-02-27", "rate": [], "stato_commitment": "IN_CORSO"}),
        ProgettoEvento(evento_id="evt-h002-fatt", voce_id="HPAN25PIANO1.002", progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA", data_evento=date(2026, 3, 31), data_registrazione=NOW_ISO,
            importo_eur=Decimal("30000.00"), fornitore_id="anag-ste-002",
            metadata={"tipo": "FATTURA", "numero_fattura": "STE-FT-001", "data_emissione": "2026-03-31",
                "tipo_doc": "FT", "condizioni_pagamento": "Bonifico 60gg DF", "copre_rate": []}),
        # ── HPAN25PIANO1.008 Pisacane: 1 PREV ──
        ProgettoEvento(evento_id="evt-h008-prev", voce_id="HPAN25PIANO1.008", progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO", data_evento=date(2026, 1, 25), data_registrazione=NOW_ISO,
            importo_eur=None, fornitore_id=None,
            metadata={"tipo": "PREVENTIVO", "articolo": "Direzione lavori ingegneria",
                "stato_preventivo": "RICEVUTO", "note": "Importo da chiarire - PREVENTIVO_PENDING"}),
        # ── HPAN25PIANO1.010 Hospitality Project: 1 PREV (società ORTI) ──
        ProgettoEvento(evento_id="evt-h010-prev", voce_id="HPAN25PIANO1.010", progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO", data_evento=date(2026, 1, 30), data_registrazione=NOW_ISO,
            importo_eur=None, fornitore_id=None,
            metadata={"tipo": "PREVENTIVO", "articolo": "Project Management",
                "stato_preventivo": "RICEVUTO",
                "note": "PM fee - società pagante ORTI (unico opex del progetto)"}),
        # ── HPAN25PIANO1.013 Rino Cuomo: 0 eventi ──
        # ── SPIAGGIA_LOTTO7.001 Pagoda: 4 PREVENTIVO ──
        ProgettoEvento(evento_id="evt-s001-prev-armagi", voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 17), data_registrazione=NOW_ISO,
            importo_eur=Decimal("31324.00"), fornitore_id="anag-armagi-001",
            metadata={"tipo": "PREVENTIVO", "articolo": "Pagoda 164pz (82 Ø220 + 82 Ø240)",
                "stato_preventivo": "RICEVUTO"}),
        ProgettoEvento(evento_id="evt-s001-prev-magnani", voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 17), data_registrazione=NOW_ISO,
            importo_eur=Decimal("35620.80"), fornitore_id="anag-magnani-001",
            metadata={"tipo": "PREVENTIVO", "articolo": "Pagoda 164pz",
                "stato_preventivo": "RICEVUTO", "note": "Sconto 20% applicato"}),
        ProgettoEvento(evento_id="evt-s001-prev-maffei", voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 20), data_registrazione=NOW_ISO,
            importo_eur=Decimal("37556.00"), fornitore_id="anag-maffei-001",
            metadata={"tipo": "PREVENTIVO", "articolo": "Pagoda 220+240",
                "stato_preventivo": "RICEVUTO", "note": "Porto franco"}),
        ProgettoEvento(evento_id="evt-s001-prev-azzolini", voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 3), data_registrazione=NOW_ISO,
            importo_eur=Decimal("122098.00"), fornitore_id="anag-azzolini-001",
            metadata={"tipo": "PREVENTIVO", "numero_preventivo": "25/00392",
                "data_preventivo": "2025-03-03",
                "articolo": "Ombrellone Pagoda 220 + 240 + Lettini Rail (bundle)",
                "stato_preventivo": "RICEVUTO",
                "note": "Non competitivo (bundle, vs alternatives)"}),
        # ── SPIAGGIA_LOTTO7.002 Ethimo: 1 PREVENTIVO + 1 DOCUMENTO ──
        ProgettoEvento(evento_id="evt-s002-prev-ethimo", voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 10), data_registrazione=NOW_ISO,
            importo_eur=Decimal("84851.40"), fornitore_id="anag-ethimo-001",
            metadata={"tipo": "PREVENTIVO", "data_preventivo": "2025-03-10",
                "articolo": "Arredo esterno (KILT, KNIT, GAIA, ALLAPERTO)",
                "stato_preventivo": "RICEVUTO"}),
        ProgettoEvento(evento_id="evt-s002-doc-ethimo", voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="DOCUMENTO",
            data_evento=date(2025, 3, 10), data_registrazione=NOW_ISO,
            metadata={"tipo": "DOCUMENTO", "tipo_doc": "PREVENTIVO",
                "drive_url": "https://drive.google.com/open?id=1gutGg76LwglxG5dCbHQ3CLwRMzVwO-Pi",
                "file_name": "Preventivo_Ethimo.pdf",
                "file_hash_md5": "ethimo-pdf-hash-placeholder",
                "correlato_evento_id": "evt-s002-prev-ethimo"},
            file_sorgente="https://drive.google.com/open?id=1gutGg76LwglxG5dCbHQ3CLwRMzVwO-Pi"),
        # ── SPIAGGIA_LOTTO7.005 Kompan: 1 PREVENTIVO ──
        ProgettoEvento(evento_id="evt-s005-prev-kompan", voce_id="SPIAGGIA_LOTTO7.005",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 10), data_registrazione=NOW_ISO,
            importo_eur=Decimal("13550.00"), fornitore_id="anag-kompan-001",
            metadata={"tipo": "PREVENTIVO", "numero_preventivo": "SQ221807-2",
                "data_preventivo": "2025-03-10", "validita_fino_a": "2025-06-10",
                "articolo": "Sand Desk + Delfino + Capanna + Ape (giochi spiaggia)",
                "stato_preventivo": "RICEVUTO",
                "note": "Pagamento 50% conferma + 50% a 30gg"}),
        # ── SPIAGGIA_LOTTO7.011 Vela Similis: 1 PREVENTIVO ──
        ProgettoEvento(evento_id="evt-s011-prev-similis", voce_id="SPIAGGIA_LOTTO7.011",
            progetto_id="SPIAGGIA_LOTTO7", tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 5), data_registrazione=NOW_ISO,
            importo_eur=Decimal("26101.39"), fornitore_id="anag-similis-001",
            metadata={"tipo": "PREVENTIVO", "numero_preventivo": "P25-00125",
                "data_preventivo": "2025-03-05",
                "articolo": "Vela motorizzata SunSquare SQK-I",
                "stato_preventivo": "RICEVUTO"}),
        # ── SPIAGGIA_LOTTO7.012 Buvette: 0 eventi ──
    ]


def progetto_to_row(p: Progetto) -> dict:
    d = p.model_dump(mode="json")
    d["data_caricamento"] = NOW_ISO
    return d


def voce_to_row(v: ProgettoVoce) -> dict:
    d = v.model_dump(mode="json")
    d["data_caricamento"] = NOW_ISO
    return d


def evento_to_row(e: ProgettoEvento) -> dict:
    d = e.model_dump(mode="json")
    # BQ JSON column: serialize metadata dict → JSON string
    d["metadata"] = json.dumps(d["metadata"])
    return d


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Skip BQ writes, print counts")
    args = p.parse_args()

    log = logging.getLogger("seed_progetti_step1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    progetti = build_progetti()
    voci = build_voci()
    eventi = build_eventi()

    log.info(f"Built: {len(progetti)} progetti, {len(voci)} voci, {len(eventi)} eventi")
    assert len(progetti) == 2, "Expected 2 progetti"
    assert len(voci) == 10, "Expected 10 voci"
    assert len(eventi) == 19, "Expected 19 eventi"

    if args.dry_run:
        log.info("--dry-run: skipping BQ writes")
        return 0

    client = get_client()

    # 1. DELETE existing rows for the seed progetti (idempotency)
    seed_ids_sql = ",".join(f"'{pid}'" for pid in SEED_PROGETTI_IDS)
    for table, key in [
        (D_PROGETTI, "progetto_id"),
        (F_PROGETTO_VOCI, "progetto_id"),
        (F_PROGETTO_EVENTI, "progetto_id"),
    ]:
        log.info(f"DELETE FROM {table} WHERE {key} IN ({SEED_PROGETTI_IDS})")
        client.query(f"DELETE FROM `{table}` WHERE {key} IN ({seed_ids_sql})").result()

    # 2. INSERT via batch load (not streaming insert — avoids streaming buffer restriction
    #    that would block the DELETE on subsequent idempotent re-runs)
    job_cfg = LoadJobConfig(write_disposition=WriteDisposition.WRITE_APPEND)

    def batch_insert(table_id: str, rows: list[dict], label: str) -> int:
        log.info(f"INSERT {len(rows)} rows into {table_id}")
        job = client.load_table_from_json(rows, table_id, job_config=job_cfg)
        job.result()  # wait for completion
        if job.errors:
            log.error(f"{label} errors: {job.errors}")
            return 1
        return 0

    if batch_insert(D_PROGETTI, [progetto_to_row(p) for p in progetti], "d_progetti"):
        return 1
    if batch_insert(F_PROGETTO_VOCI, [voce_to_row(v) for v in voci], "f_progetto_voci"):
        return 1
    if batch_insert(F_PROGETTO_EVENTI, [evento_to_row(e) for e in eventi], "f_progetto_eventi"):
        return 1

    log.info("Seed Step 1 completato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
