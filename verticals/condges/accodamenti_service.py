from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from google.cloud import bigquery

from verticals.condges.cassa_giornaliera import (
    _STRUTTURA_DISPLAY,
    _STRUTTURA_FT_SUFFIX,
    _day_to_row,
    _new_day,
    _sort_key_date,
    classify_payment_account,
    run_accodamenti_to_excel,
    write_excel,
)
from core.bq.client import get_client
from ingest.banca.ingest_accodamenti import BQ_TABLE, parse_and_transform, write_to_bq

_BU_TO_STRUTTURA = {"HOTEL": "hotel", "RESIDENCE": "residence", "CVM": "cvm"}

logger = logging.getLogger(__name__)


@dataclass
class BatchPreview:
    input_dir: Path
    txt_files: int
    parsed_rows: int
    candidate_hashes: int
    existing_hashes: int
    new_rows: int
    min_date: str | None
    max_date: str | None


def _collect_txt_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.rglob("*.txt")) + sorted(input_dir.rglob("*.TXT"))


def parse_rows_from_folder(input_dir: Path, societa: str = "INTUR") -> list[dict]:
    rows: list[dict] = []
    for filepath in _collect_txt_files(input_dir):
        rel_path = str(filepath.relative_to(input_dir))
        rows.extend(
            parse_and_transform(
                path=filepath,
                societa=societa,
                logger=logger,
                rel_path=rel_path,
            )
        )
    return rows


def _existing_hashes(candidate_hashes: list[str]) -> set[str]:
    if not candidate_hashes:
        return set()

    client = get_client()
    found: set[str] = set()
    chunk_size = 10_000

    for i in range(0, len(candidate_hashes), chunk_size):
        chunk = candidate_hashes[i : i + chunk_size]
        job = client.query(
            f"""
            SELECT hash_riga
            FROM `{BQ_TABLE}`
            WHERE hash_riga IN UNNEST(@hashes)
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("hashes", "STRING", chunk)
                ]
            ),
        )
        found.update(r.hash_riga for r in job.result())
    return found


def preview_folder(input_dir: Path, societa: str = "INTUR") -> tuple[BatchPreview, list[dict], list[dict]]:
    txt_files = _collect_txt_files(input_dir)
    rows = parse_rows_from_folder(input_dir, societa=societa)

    hashes = [r["hash_riga"] for r in rows]
    existing = _existing_hashes(hashes)
    new_rows = [r for r in rows if r["hash_riga"] not in existing]

    dates = [r["data_registrazione"] for r in rows if r.get("data_registrazione")]
    preview = BatchPreview(
        input_dir=input_dir,
        txt_files=len(txt_files),
        parsed_rows=len(rows),
        candidate_hashes=len(set(hashes)),
        existing_hashes=len(existing),
        new_rows=len(new_rows),
        min_date=min(dates) if dates else None,
        max_date=max(dates) if dates else None,
    )
    return preview, rows, new_rows


def ingest_rows(new_rows: list[dict]) -> int:
    if not new_rows:
        return 0
    write_to_bq(new_rows, get_client(), logger)
    return len(new_rows)


def current_watermark() -> str | None:
    client = get_client()
    row = next(
        iter(
            client.query(
                f"SELECT MAX(data_registrazione) AS max_data FROM `{BQ_TABLE}`"
            ).result()
        ),
        None,
    )
    if row is None or row.max_data is None:
        return None
    return row.max_data.strftime("%Y-%m-%d")


def generate_excel_from_folder(input_dir: Path, output_path: Path) -> dict:
    return run_accodamenti_to_excel(input_dir, output_path)


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def generate_gaia_excel_from_bq(output_path: Path) -> dict:
    """Genera l'Excel formato GAIA (cumulativo, 2 sheet) leggendo da f_accodamenti.

    Ricostruisce gli eventi raggruppando le righe per (file_sorgente, riga_sorgente,
    data, bu), poi applica la stessa aggregazione di build_daily_reconciliation /
    build_detail_reconciliation di cassa_giornaliera.

    Limite noto: il record PAR (num_doc_partita) dei giri_caparra non è preservato
    in f_accodamenti, quindi la colonna "di cui ft" risulterà 0 per quei giorni.
    """
    client = get_client()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sql = f"""
    SELECT
      data_registrazione,
      business_unit_id,
      file_sorgente,
      riga_sorgente,
      SPLIT(oggetto_id, '_')[OFFSET(0)] AS conto_esolver,
      importo,
      importo_dare,
      importo_avere,
      documento
    FROM `{BQ_TABLE}`
    ORDER BY data_registrazione, business_unit_id, file_sorgente, riga_sorgente
    """
    bq_rows = list(client.query(sql).result())

    if not bq_rows:
        write_excel([], [], output_path)
        return {"output": str(output_path), "rows": 0}

    events: dict[tuple, list] = defaultdict(list)
    for r in bq_rows:
        if not r.data_registrazione:
            continue
        key = (r.file_sorgente, r.riga_sorgente, r.data_registrazione, r.business_unit_id)
        events[key].append(r)

    days_totale: dict = defaultdict(_new_day)
    days_dettaglio: dict = defaultdict(_new_day)

    for (file_src, _riga, data_iso, bu), event_rows in events.items():
        data_str = data_iso.strftime("%d/%m/%Y")
        struttura = _BU_TO_STRUTTURA.get(bu, "unknown")
        targets = (days_totale[data_str], days_dettaglio[(data_str, struttura)])
        file_lower = (file_src or "").lower()

        if "corrispettivi" in file_lower:
            for r in event_rows:
                importo = _dec(r.importo)
                if importo == Decimal("0"):
                    continue
                tipo = classify_payment_account(r.conto_esolver or "")
                for day in targets:
                    if tipo == "pos":
                        day["corrispettivi_pos"] += importo
                    elif tipo == "cash":
                        day["corrispettivi_contanti"] += importo
                    elif tipo == "caparra":
                        day["corrispettivi_storno_caparra"] += importo

        elif "movimenti" in file_lower:
            has_caparra = any(
                classify_payment_account(r.conto_esolver or "") == "caparra"
                for r in event_rows
            )
            if not has_caparra:
                continue
            has_crediti = any((r.conto_esolver or "") == "110301" for r in event_rows)
            if has_crediti:
                for r in event_rows:
                    if classify_payment_account(r.conto_esolver or "") != "caparra":
                        continue
                    importo = max(_dec(r.importo_dare), _dec(r.importo_avere))
                    if importo > Decimal("0"):
                        for day in targets:
                            day["caparre_evase"] += importo
            else:
                for r in event_rows:
                    importo = max(_dec(r.importo_dare), _dec(r.importo_avere))
                    if importo <= Decimal("0"):
                        continue
                    tipo = classify_payment_account(r.conto_esolver or "")
                    if tipo == "pos":
                        for day in targets:
                            day["caparre_incassate_pos"] += importo
                    elif tipo == "cash":
                        for day in targets:
                            day["caparre_incassate_contanti"] += importo

        elif "fatture" in file_lower:
            for r in event_rows:
                importo = _dec(r.importo)
                if importo <= Decimal("0"):
                    continue
                for day in targets:
                    day["fatture_importo"] += importo
                    if r.documento:
                        suffix = _STRUTTURA_FT_SUFFIX.get(struttura, "")
                        day["fatture_lista"].append(f"F{r.documento}{suffix}")

    riepilogo_rows = [
        _day_to_row(days_totale[d], d)
        for d in sorted(days_totale.keys(), key=_sort_key_date)
    ]
    detail_rows = []
    for key in sorted(
        days_dettaglio.keys(), key=lambda k: (_sort_key_date(k[0]), k[1])
    ):
        d, struttura = key
        display = _STRUTTURA_DISPLAY.get(struttura, struttura)
        detail_rows.append(_day_to_row(days_dettaglio[key], d, display))

    write_excel(riepilogo_rows, detail_rows, output_path)
    return {"output": str(output_path), "rows": len(riepilogo_rows)}
