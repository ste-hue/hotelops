#!/usr/bin/env python3
"""Ingest Moolty F&B bar spiaggia (xlsx) → f_spiaggia_fb_ordini.

Un report Moolty = un foglio "Report", un ordine per riga. Bar spiaggia = INTUR.
Lifecycle APPEND (dedup hash_riga).

Parser_module della source MOOLTY_FBSPIAGGIA_INTUR_APPEND, invocato
da `hotelops promote`:
    python -m ingest.flussi.ingest_spiaggia_fb --file X.xlsx --raw-object-id Y
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import openpyxl

from core.config import F_SPIAGGIA_FB_ORDINI
from core.schemas import SpiaggiaFbOrdineRow, make_hash, validate_batch

log = logging.getLogger("ingest.spiaggia_fb")

SOCIETA = "INTUR"
BUSINESS_UNIT = "LIDO"
LOCATION = "LIDO"

_ORDINE_RE = re.compile(r"#\s*(\d+)")
_MESE_REPORT_RE = re.compile(r"Report\s+(\d{2}/\d{4})", re.IGNORECASE)


def to_float(v: Any) -> Optional[float]:
    """Cella numerica → float. None/''/'–' → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "–"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_str(v: Any) -> Optional[str]:
    """Cella → str strip. None/'' → None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def parse_dt(cell: Any) -> Optional[datetime]:
    """Cella data Moolty → datetime (tz-naive).

    Accetta:
    - datetime (openpyxl): restituita as-is (tz-naive preservata).
    - str "dd/mm/yyyy HH:MM": parsata con strptime.
    - Altro: None.
    """
    if isinstance(cell, datetime):
        # Già datetime — rimuovi tzinfo se presente per uniformità
        return cell.replace(tzinfo=None)
    if isinstance(cell, str):
        s = cell.strip()
        try:
            return datetime.strptime(s, "%d/%m/%Y %H:%M")
        except ValueError:
            return None
    return None


def parse_ordine_id(descrizione: Optional[str]) -> Optional[str]:
    """Estrae il numero ordine da stringhe tipo '# 104 del 01/06/2025 0...'."""
    if not descrizione:
        return None
    m = _ORDINE_RE.search(descrizione)
    return m.group(1) if m else None


def parse_mese_report(ws) -> Optional[str]:
    """Legge 'Report MM/YYYY' dalla cella A1 del foglio."""
    cell_value = ws.cell(row=1, column=1).value
    if not cell_value:
        return None
    m = _MESE_REPORT_RE.search(str(cell_value))
    return m.group(1) if m else None


def valida_export_moolty(path: Path) -> tuple[bool, str]:
    """Guardiano per il drop dell'export Moolty dalla pagina Spiaggia.

    Il dedup BQ (hash_riga) protegge dai RICARICAMENTI, non dai duplicati
    INTERNI a un export (righe ripetute — trappola storica "×2,4"): quelli
    vanno fermati PRIMA di toccare la tabella. Controlla: foglio 'Report'
    con titolo 'Report MM/YYYY', almeno un ordine, nessuna tripla
    (data_ora, descrizione, entrata) ripetuta. Ritorna (ok, motivo).
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if "Report" not in wb.sheetnames:
            return False, "non sembra un report Moolty: manca il foglio 'Report'"
        ws = wb["Report"]
        # firma del layout = header di riga 2 (la testa può essere
        # 'Report MM/YYYY' o 'Report DD/MM/YYYY' — il parser tollera entrambe)
        header = set()
        for i, row in enumerate(ws.iter_rows(min_row=2, max_row=2, values_only=True)):
            header = {str(c).strip().lower() for c in row if c is not None}
        if not {"data", "entrata", "descrizione"} <= header:
            return False, (
                "non sembra un report Moolty: header senza "
                "Data/Entrata/Descrizione"
            )
        viste: dict = {}
        n = 0
        for row in ws.iter_rows(min_row=3, values_only=True):
            if not row:
                continue
            dt = parse_dt(row[0] if len(row) > 0 else None)
            if dt is None:
                continue
            n += 1
            chiave = (
                dt.isoformat(),
                to_str(row[7] if len(row) > 7 else None),
                to_float(row[4] if len(row) > 4 else None),
            )
            viste[chiave] = viste.get(chiave, 0) + 1
    finally:
        wb.close()
    if n == 0:
        return False, "nessun ordine nel report (export venuto male: rifallo)"
    doppioni = sum(c - 1 for c in viste.values() if c > 1)
    if doppioni:
        return False, (
            f"{doppioni} righe duplicate DENTRO l'export (stessa data/"
            "descrizione/importo): copie non byte-identiche non si puliscono "
            "a valle — rifai l'export pulito da Moolty"
        )
    return True, ""


def build_fb_rows(
    ws,
    file_name: str,
    raw_object_id: Optional[str],
    now: datetime,
) -> list[SpiaggiaFbOrdineRow]:
    """Costruisce righe SpiaggiaFbOrdineRow da un foglio "Report" Moolty.

    Args:
        ws: openpyxl worksheet (foglio "Report").
        file_name: nome del file sorgente.
        raw_object_id: FK a f_raw_objects.
        now: timestamp di caricamento.
    """
    mese_report = parse_mese_report(ws)
    out: list[SpiaggiaFbOrdineRow] = []

    for row in ws.iter_rows(min_row=3, values_only=True):
        # Colonne: A=Data, B=Pagato, C=Rata, D=Metodo, E=Entrata, F=Uscita, G=Causale, H=Descrizione
        #          idx: 0      1        2       3          4          5         6           7
        if not row or len(row) < 1:
            continue
        raw_data = row[0] if len(row) > 0 else None
        raw_pagato = row[1] if len(row) > 1 else None
        raw_rata = row[2] if len(row) > 2 else None
        raw_metodo = row[3] if len(row) > 3 else None
        raw_entrata = row[4] if len(row) > 4 else None
        raw_uscita = row[5] if len(row) > 5 else None
        raw_causale = row[6] if len(row) > 6 else None
        raw_descrizione = row[7] if len(row) > 7 else None

        data_ora = parse_dt(raw_data)
        if data_ora is None:
            continue

        data = data_ora.date()
        metodo = to_str(raw_metodo)
        entrata = to_float(raw_entrata)
        uscita = to_float(raw_uscita)
        pagato = bool(raw_pagato) if raw_pagato is not None else False
        rata = to_str(raw_rata)
        causale = to_str(raw_causale)
        descrizione = to_str(raw_descrizione)
        ordine_id = parse_ordine_id(descrizione)

        hash_riga = make_hash(
            "fb_ordini",
            data_ora.isoformat(),
            descrizione or "",
            str(entrata),
        )

        out.append(SpiaggiaFbOrdineRow(
            societa_id=SOCIETA,
            business_unit_id=BUSINESS_UNIT,
            location_id=LOCATION,
            oggetto_id=None,
            funzione_id=None,
            data_ora=data_ora,
            data=data,
            metodo=metodo,
            entrata=entrata,
            uscita=uscita,
            pagato=pagato,
            rata=rata,
            causale=causale,
            descrizione=descrizione,
            ordine_id=ordine_id,
            mese_report=mese_report,
            raw_object_id=raw_object_id,
            file_sorgente=file_name,
            hash_riga=hash_riga,
            data_caricamento=now,
        ))

    return out


def ingest_file(
    path: Path, raw_object_id: Optional[str] = None, dry_run: bool = False
) -> dict[str, int]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Report"] if "Report" in wb.sheetnames else wb.active
    now = datetime.now(timezone.utc)
    rows = build_fb_rows(ws, path.name, raw_object_id, now)
    wb.close()

    if rows:
        validate_batch(
            [r.model_dump() for r in rows],
            SpiaggiaFbOrdineRow,
            context=f"spiaggia_fb {path.name}",
        )

    if dry_run:
        log.info("[DRY-RUN] fb_ordini → %s : %d righe", F_SPIAGGIA_FB_ORDINI, len(rows))
        return {"fb_ordini": len(rows)}

    from core.bq.dedup import filter_new_rows_by_hash
    from core.bq.write import bq_write_validated

    new_rows = filter_new_rows_by_hash(F_SPIAGGIA_FB_ORDINI, rows, "hash_riga")
    if not new_rows:
        log.info("Tutte le righe già presenti — niente da scrivere (%s)", path.name)
        return {"fb_ordini": 0}

    bq_write_validated(F_SPIAGGIA_FB_ORDINI, new_rows, mode="append")
    log.info("OK fb_ordini → %s : %d righe nuove (su %d totali)",
             F_SPIAGGIA_FB_ORDINI, len(new_rows), len(rows))
    return {"fb_ordini": len(new_rows)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Moolty F&B bar spiaggia → BQ")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--raw-object-id", default=None)
    ap.add_argument("--societa", default=None, help="Ignorato — sempre INTUR.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    counts = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info("Totale: %s", counts)


if __name__ == "__main__":
    main()
