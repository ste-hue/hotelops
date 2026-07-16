"""Loader / persister per d_fornitori.csv (schema v2 con societa_id + esclusione)."""

from __future__ import annotations

import csv
from pathlib import Path

from core.config import D_FORNITORI, D_VOCI_PIANO_FINANZIARIO
from core.schemas import FornitoreMapRow

# voce_id PF → label foglio dettaglio. Home canonica (era in app_scadenzario,
# deprecato): mapping fornitore→voce vive qui col loader/persister.
VOCE_LABELS = {
    "USCITE_MATERIE_PRIME": "Materie Prime",
    "USCITE_UTENZE": "Utenze",
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commissioni",
    "USCITE_MUTUI": "Mutui e Finanziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_VARIE_EXT": "Varie ed Eventuali",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
    "USCITE_CANONI": "Canoni diversi",
}


def _to_bool(s) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes")


def load_fornitori(csv_path: Path, societa: str) -> dict[int, FornitoreMapRow]:
    """Read d_fornitori.csv, filtered by societa_id. Returns {codice: row}."""
    result: dict[int, FornitoreMapRow] = {}
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("societa_id") or "").strip().upper() != societa.upper():
                continue
            row = FornitoreMapRow(
                codice_fornitore=int(r["codice_fornitore"]),
                nome_esolver=r.get("nome_esolver", "") or "",
                nome_pf=r.get("nome_pf", "") or "",
                voce_id=r.get("voce_id", "") or "",
                is_intercompany=_to_bool(r.get("is_intercompany", "False")),
                is_excluded=_to_bool(r.get("is_excluded", "False")),
                exclude_reason=r.get("exclude_reason", "") or "",
                societa_id=r["societa_id"],
            )
            result[row.codice_fornitore] = row
    return result


def append_fornitore(
    csv_path: Path,
    *,
    codice_fornitore: int,
    nome_esolver: str,
    nome_pf: str,
    voce_id: str,
    societa_id: str,
    is_excluded: bool = False,
    exclude_reason: str = "",
    is_intercompany: bool = False,
) -> None:
    """Append a new row. Validates via Pydantic before writing."""
    row = FornitoreMapRow(
        codice_fornitore=codice_fornitore,
        nome_esolver=nome_esolver,
        nome_pf=nome_pf,
        voce_id=voce_id,
        is_intercompany=is_intercompany,
        is_excluded=is_excluded,
        exclude_reason=exclude_reason,
        societa_id=societa_id,
    )
    line = (
        ",".join(
            [
                str(row.codice_fornitore),
                row.nome_esolver,
                row.nome_pf,
                row.voce_id,
                str(row.is_intercompany),
                str(row.is_excluded),
                row.exclude_reason,
                row.societa_id,
            ]
        )
        + "\n"
    )
    with Path(csv_path).open("a", encoding="utf-8") as f:
        f.write(line)


# ── BQ-backed (sorgente persistente per app deployata) ────────────────────────
# d_fornitori è una DIMENSIONE (anagrafica/riferimento, non una proiezione) →
# BigQuery è la casa durevole. L'app legge/scrive qui; il CSV diventa seed/export.


def _bq():
    from core.bq.client import get_client

    return get_client()


def load_fornitori_bq(societa: str) -> dict[int, FornitoreMapRow]:
    """Read d_fornitori da BigQuery, filtrato per societa_id. Returns {codice: row}."""
    from google.cloud import bigquery

    sql = f"""
        SELECT codice_fornitore, nome_esolver, nome_pf, voce_id,
               is_intercompany, is_excluded, exclude_reason, societa_id
        FROM `{D_FORNITORI}`
        WHERE societa_id = @soc
    """
    job = _bq().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("soc", "STRING", societa)]
        ),
    )
    result: dict[int, FornitoreMapRow] = {}
    for r in job.result():
        row = FornitoreMapRow(
            codice_fornitore=int(r.codice_fornitore),
            nome_esolver=r.nome_esolver or "",
            nome_pf=r.nome_pf or "",
            voce_id=r.voce_id or "",
            is_intercompany=bool(r.is_intercompany),
            is_excluded=bool(r.is_excluded),
            exclude_reason=r.exclude_reason or "",
            societa_id=r.societa_id,
        )
        result[row.codice_fornitore] = row
    return result


def upsert_fornitore_bq(
    *,
    codice_fornitore: int,
    nome_esolver: str,
    nome_pf: str,
    voce_id: str,
    societa_id: str,
    is_excluded: bool = False,
    exclude_reason: str = "",
    is_intercompany: bool = False,
) -> None:
    """UPSERT (MERGE) su d_fornitori per chiave (codice_fornitore, societa_id).

    Sostituisce l'append-CSV: persiste in BQ e niente doppioni (re-mappa = update).
    Valida via Pydantic prima di scrivere.
    """
    from google.cloud import bigquery

    row = FornitoreMapRow(
        codice_fornitore=codice_fornitore,
        nome_esolver=nome_esolver,
        nome_pf=nome_pf,
        voce_id=voce_id,
        is_intercompany=is_intercompany,
        is_excluded=is_excluded,
        exclude_reason=exclude_reason,
        societa_id=societa_id,
    )
    sql = f"""
    MERGE `{D_FORNITORI}` T
    USING (SELECT @cod AS codice_fornitore, @soc AS societa_id) S
    ON T.codice_fornitore = S.codice_fornitore AND T.societa_id = S.societa_id
    WHEN MATCHED THEN UPDATE SET
        nome_esolver=@ne, nome_pf=@np, voce_id=@v,
        is_intercompany=@ic, is_excluded=@ex, exclude_reason=@er
    WHEN NOT MATCHED THEN INSERT
        (codice_fornitore, nome_esolver, nome_pf, voce_id,
         is_intercompany, is_excluded, exclude_reason, societa_id)
        VALUES (@cod, @ne, @np, @v, @ic, @ex, @er, @soc)
    """
    params = [
        bigquery.ScalarQueryParameter("cod", "INT64", row.codice_fornitore),
        bigquery.ScalarQueryParameter("soc", "STRING", row.societa_id),
        bigquery.ScalarQueryParameter("ne", "STRING", row.nome_esolver),
        bigquery.ScalarQueryParameter("np", "STRING", row.nome_pf),
        bigquery.ScalarQueryParameter("v", "STRING", row.voce_id),
        bigquery.ScalarQueryParameter("ic", "BOOL", row.is_intercompany),
        bigquery.ScalarQueryParameter("ex", "BOOL", row.is_excluded),
        bigquery.ScalarQueryParameter("er", "STRING", row.exclude_reason),
    ]
    _bq().query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result()


def load_voci_pf_bq(societa: str) -> dict[str, str]:
    """Carica le voci PF selezionabili da d_voci_piano_finanziario (BQ).

    Filtra sezione='USCITE' + (societa_id uguale a @soc OPPURE globale).
    Ritorna {voce_id: voce_label} ordinato per ord.
    """
    from google.cloud import bigquery

    sql = f"""
        SELECT voce_id, voce_label
        FROM `{D_VOCI_PIANO_FINANZIARIO}`
        WHERE sezione = 'USCITE'
          AND (societa_id = @soc OR societa_id IS NULL OR societa_id = '')
        ORDER BY ord
    """
    job = _bq().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("soc", "STRING", societa)]
        ),
    )
    return {r.voce_id: r.voce_label for r in job.result()}


def export_fornitori_to_csv(csv_path: Path, societa: str | None = None) -> int:
    """Dump d_fornitori da BQ → CSV (input per l'engine + seed git). Ritorna n righe."""
    from google.cloud import bigquery

    where = "WHERE societa_id = @soc" if societa else ""
    sql = f"""
        SELECT codice_fornitore, nome_esolver, nome_pf, voce_id,
               is_intercompany, is_excluded, exclude_reason, societa_id
        FROM `{D_FORNITORI}` {where}
        ORDER BY societa_id, codice_fornitore
    """
    qc = (
        bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("soc", "STRING", societa)]
        )
        if societa
        else None
    )
    rows = list(_bq().query(sql, job_config=qc).result())
    with Path(csv_path).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "codice_fornitore",
                "nome_esolver",
                "nome_pf",
                "voce_id",
                "is_intercompany",
                "is_excluded",
                "exclude_reason",
                "societa_id",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.codice_fornitore,
                    r.nome_esolver or "",
                    r.nome_pf or "",
                    r.voce_id or "",
                    bool(r.is_intercompany),
                    bool(r.is_excluded),
                    r.exclude_reason or "",
                    r.societa_id or "",
                ]
            )
    return len(rows)
