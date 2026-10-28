"""Ingest HotelCube «Stampa Cassa» → f_stampa_cassa (ORTI, una struttura per file).

Layout standard = export del 2026-10-28, raggruppato per sezione e modalità:
riga 1 intestazione (Data, Ora, Operatore, Camera, Ospite, Pagante, Numero Doc.,
Importo, Totale); sezioni con totale dichiarato in colonna H; sotto-intestazioni
«CODICE-NOME» per modalità di pagamento; righe documento; chiusura
«TOTALE GENERALE: € x». Il tracciato per documento di luglio 2026 (colonne
Pagato/Pos/Sospesi/Caparra) è un altro report: rifiutato con messaggio.

Quadrature fail-loud: somma degli importi di ogni sezione = totale dichiarato;
somma delle sezioni = TOTALE GENERALE. BU per file dal prefisso camera (H/R/C),
unico per export; le righe senza camera (acconti) ereditano la BU del file.
Lifecycle APPEND (dedup hash_riga).

Usage:
    python -m ingest.flussi.ingest_stampa_cassa --file X.xlsx --raw-object-id Y [--societa ORTI] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openpyxl

from core.config import F_STAMPA_CASSA
from core.schemas import StampaCassaRow, make_hash, validate_batch

log = logging.getLogger("ingest_stampa_cassa")

SOCIETA = "ORTI"
HEADER = (
    "Data",
    "Ora",
    "Operatore",
    "Camera",
    "Ospite",
    "Pagante",
    "Numero Doc.",
    "Importo",
    "Totale",
)
SEZIONI = {
    "documenti pagati e caparre incassate/restituite": "PAGATI",
    "documenti totalmente incassati con caparra": "INCASSATI_CON_CAPARRA",
    "rientri del sospeso": "RIENTRI_SOSPESO",
    "documenti sospesi": "SOSPESI",
}
BU_PREFISSO = {"H": "HOTEL", "R": "RESIDENCE", "C": "CVM"}
_DATA_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})$")
_DOC_RE = re.compile(r"^(\d{4})\s+([A-Z])\s+(\d+)\s*([A-Z]*)$")
_EUR_RE = re.compile(r"€\s*([\d.]+,\d{2})")
_TOL = 0.011


class StampaCassaLayoutError(ValueError):
    """Il file non è una Stampa Cassa nel layout standard, o non quadra."""


def parse_numero_doc(
    s: str | None,
) -> tuple[Optional[int], Optional[str], Optional[int], Optional[str]]:
    m = _DOC_RE.match(str(s or "").strip())
    if not m:
        return None, None, None, None
    return int(m.group(1)), m.group(2), int(m.group(3)), m.group(4) or None


def _eur(s) -> Optional[float]:
    m = _EUR_RE.search(str(s or ""))
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


def _str(v) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    return s or None


def build_rows(
    ws, file_name: str, raw_object_id: Optional[str], now: datetime
) -> list[StampaCassaRow]:
    rows = list(ws.iter_rows(values_only=True))
    header = tuple(_str(v) for v in (list(rows[0]) + [None] * 9)[:9]) if rows else ()
    if header != HEADER:
        raise StampaCassaLayoutError(
            f"{file_name}: intestazione inattesa {header!r}; atteso il layout Stampa Cassa "
            f"raggruppato per sezione (2026-10-28), non il tracciato per documento"
        )

    parsed: list[dict] = []
    dichiarati: dict[str, float] = {}
    sezione = metodo = None
    totale_generale = None
    for r in rows[1:]:
        c = (list(r) + [None] * 9)[:9]
        v0 = _str(c[0])
        if v0 and _DATA_RE.match(v0):
            if sezione is None:
                raise StampaCassaLayoutError(
                    f"{file_name}: riga documento prima di ogni sezione"
                )
            d, mth, y = _DATA_RE.match(v0).groups()
            data = datetime(2000 + int(y), int(mth), int(d)).date()
            ora = _str(c[1])
            try:
                data_ora = (
                    datetime.strptime(f"{data.isoformat()} {ora}", "%Y-%m-%d %H:%M")
                    if ora
                    else None
                )
            except ValueError:
                data_ora = None
            importo = float(c[7]) if c[7] not in (None, "") else None
            if importo is None:
                raise StampaCassaLayoutError(
                    f"{file_name}: importo mancante sul documento {c[6]!r} del {v0}"
                )
            parsed.append(
                dict(
                    data=data,
                    ora=ora,
                    data_ora=data_ora,
                    operatore=_str(c[2]),
                    camera=_str(c[3]),
                    ospite=_str(c[4]),
                    pagante=_str(c[5]),
                    numero_doc=_str(c[6]) or "",
                    importo=importo,
                    totale_doc=float(c[8]) if c[8] not in (None, "") else None,
                    sezione=sezione,
                    metodo_pagamento=metodo,
                )
            )
            continue
        tot_gen = str(c[7] or "")
        if tot_gen.upper().startswith("TOTALE GENERALE"):
            totale_generale = _eur(tot_gen)
            continue
        if v0 and _eur(c[7]) is not None:
            key = v0.lower()
            if key in SEZIONI:
                sezione = SEZIONI[key]
                metodo = None
                dichiarati[sezione] = _eur(c[7])
            elif v0.startswith("***"):
                metodo = None
            else:
                metodo = v0.split("-", 1)[0].strip()
            continue
    if totale_generale is None:
        raise StampaCassaLayoutError(f"{file_name}: manca la riga TOTALE GENERALE")

    # Quadrature: sezioni dichiarate vs somme, poi totale generale.
    somme: dict[str, float] = {}
    for p in parsed:
        somme[p["sezione"]] = somme.get(p["sezione"], 0.0) + p["importo"]
    for sez, dich in dichiarati.items():
        if abs(somme.get(sez, 0.0) - dich) > _TOL:
            raise StampaCassaLayoutError(
                f"{file_name}: sezione {sez} non quadra: somma {somme.get(sez, 0.0):.2f} vs dichiarato {dich:.2f}"
            )
    if abs(sum(dichiarati.values()) - totale_generale) > _TOL:
        raise StampaCassaLayoutError(
            f"{file_name}: TOTALE GENERALE {totale_generale:.2f} ≠ somma sezioni {sum(dichiarati.values()):.2f}"
        )

    # BU per file: prefisso camera unico.
    prefissi = {p["camera"][0].upper() for p in parsed if p["camera"]}
    if len(prefissi) != 1 or next(iter(prefissi)) not in BU_PREFISSO:
        raise StampaCassaLayoutError(
            f"{file_name}: prefissi camera {sorted(prefissi)}: serve un prefisso unico tra "
            f"{sorted(BU_PREFISSO)} (export per struttura)"
        )
    bu = BU_PREFISSO[next(iter(prefissi))]

    out: list[StampaCassaRow] = []
    visti: dict[tuple, int] = {}
    for p in parsed:
        anno_doc, serie, numero, _ = parse_numero_doc(p["numero_doc"])
        is_acconto = "acconto" in (p["ospite"] or "").lower()
        chiave = (
            bu,
            p["data"].isoformat(),
            p["ora"] or "",
            p["numero_doc"],
            p["pagante"] or "",
            p["sezione"],
            p["metodo_pagamento"] or "",
            f"{p['importo']:.2f}",
        )
        visti[chiave] = visti.get(chiave, 0) + 1
        hash_riga = make_hash("stampa_cassa", *chiave, str(visti[chiave]))
        out.append(
            StampaCassaRow(
                societa_id=SOCIETA,
                business_unit_id=bu,
                anno_doc=anno_doc,
                serie_doc=serie,
                numero=numero,
                is_acconto=is_acconto,
                occorrenza=visti[chiave],
                raw_object_id=raw_object_id,
                file_sorgente=file_name,
                hash_riga=hash_riga,
                data_caricamento=now,
                **p,
            )
        )
    return out


def ingest_file(
    path: Path, raw_object_id: Optional[str] = None, dry_run: bool = False
) -> dict[str, int]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    now = datetime.now(timezone.utc)
    rows = build_rows(ws, path.name, raw_object_id, now)
    wb.close()
    validate_batch(
        [r.model_dump() for r in rows],
        StampaCassaRow,
        context=f"stampa_cassa {path.name}",
    )
    if dry_run:
        log.info("[DRY-RUN] stampa_cassa → %s : %d righe", F_STAMPA_CASSA, len(rows))
        return {"stampa_cassa": len(rows)}

    from core.bq.dedup import filter_new_rows_by_hash
    from core.bq.write import bq_write_validated

    new_rows = filter_new_rows_by_hash(F_STAMPA_CASSA, rows, "hash_riga")
    if not new_rows:
        log.info("Tutte le righe già presenti — niente da scrivere (%s)", path.name)
        return {"stampa_cassa": 0}
    bq_write_validated(F_STAMPA_CASSA, new_rows, mode="append")
    log.info(
        "OK stampa_cassa → %s : %d righe nuove (su %d)",
        F_STAMPA_CASSA,
        len(new_rows),
        len(rows),
    )
    return {"stampa_cassa": len(new_rows)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest HotelCube Stampa Cassa → BQ")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--raw-object-id", default=None)
    ap.add_argument(
        "--societa", default=None, help="Deve essere ORTI (export per struttura ORTI)."
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.societa and args.societa != SOCIETA:
        raise SystemExit(f"--societa {args.societa}: la Stampa Cassa è solo {SOCIETA}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    counts = ingest_file(
        args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run
    )
    log.info("Totale: %s", counts)


if __name__ == "__main__":
    main()
