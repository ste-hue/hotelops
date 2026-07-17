"""Digest CEO: cosa è successo sulle 4 caselle, azionabile prima del rumore.

Checkpoint tecnico su f_pec_digest_runs (default finestra: dall'ultimo
SUCCESS). Il markdown su AMM_CEO/_digest/ è output umano. Spec 2026-07-17.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from core.config import (
    F_PEC_ALLEGATI,
    F_PEC_DIGEST_RUNS,
    F_PEC_MESSAGES,
    F_PEC_PANEL_PROJECTIONS,
    PANEL_ROOT,
    PROJECT,
)
from core.schemas import PecDigestRunRow, validate_batch

log = logging.getLogger("ingest.pec.digest")

EPOCA_CORPUS = datetime(2018, 1, 1)
_V_CORRENTE = f"{PROJECT}.hotelops.v_pec_classificazione_corrente"


def _percorso_file(giorno: datetime) -> Path:
    return (
        Path(PANEL_ROOT) / "_digest" / f"{giorno:%Y}" / f"{giorno:%m}"
        / f"{giorno:%Y-%m-%d}.md"
    )


def _ultimo_success(client) -> datetime | None:
    sql = (
        f"SELECT MAX(to_ts) AS t FROM `{F_PEC_DIGEST_RUNS}` "
        f"WHERE status = 'SUCCESS'"
    )
    try:
        rows = list(client.query(sql).result())
        return rows[0].t if rows and rows[0].t else None
    except Exception:
        return None  # tabella assente: primo run


def _run_aperto(client) -> bool:
    """Esiste un run_id la cui ULTIMA riga (per COALESCE(finished_at, started_at))
    è RUNNING? f_pec_digest_runs è APPEND-only: lo stato di un run è l'ultima
    riga per run_id (RUNNING poi SUCCESS/FAILED)."""
    sql = f"""
    SELECT 1 FROM (
      SELECT run_id, ARRAY_AGG(status ORDER BY COALESCE(finished_at, started_at) DESC
             LIMIT 1)[OFFSET(0)] AS ultimo
      FROM `{F_PEC_DIGEST_RUNS}` GROUP BY run_id
    ) WHERE ultimo = 'RUNNING' LIMIT 1
    """
    try:
        return any(client.query(sql).result())
    except Exception:
        return False


def _q(client, sql: str, **params):
    from google.cloud import bigquery

    qp = [
        bigquery.ScalarQueryParameter(
            k, "DATETIME" if isinstance(v, datetime) else "STRING", v
        )
        for k, v in params.items()
    ]
    return [dict(r) for r in client.query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=qp)
    ).result()]


def _raccogli(client, da: datetime, a: datetime,
              casella: str | None, entity: str | None) -> dict:
    filtro = "AND m.data_caricamento > @da AND m.data_caricamento <= @a"
    extra = {}
    if casella:
        filtro += " AND m.casella = @casella"
        extra["casella"] = casella
    if entity:
        filtro += " AND m.entity_id = @entity"
        extra["entity"] = entity
    base = dict(da=da, a=a, **extra)

    importanti = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente, c.primary_category,
               EXISTS(SELECT 1 FROM `{F_PEC_PANEL_PROJECTIONS}` p
                      WHERE p.msgid = m.msgid AND p.status='COPIED') AS proiettato
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.importance = 'ALTA' {filtro} ORDER BY m.data_evento DESC""", **base)
    anomalie = _q(client, f"""
        SELECT m.entity_id, m.subject, m.tipo FROM `{F_PEC_MESSAGES}` m
        WHERE m.tipo = 'ANOMALIA' {filtro}""", **base)
    errori = _q(client, f"""
        SELECT m.entity_id, m.subject, m.parse_warning FROM `{F_PEC_MESSAGES}` m
        WHERE m.parse_warning IS NOT NULL {filtro}""", **base)
    non_sync = _q(client, f"""
        SELECT m.entity_id, a.nome_file, a.gcs_uri, a.size_bytes
        FROM `{F_PEC_ALLEGATI}` a JOIN `{F_PEC_MESSAGES}` m USING (msgid)
        JOIN `{_V_CORRENTE}` c USING (msgid)
        LEFT JOIN `{F_PEC_PANEL_PROJECTIONS}` p
          ON p.msgid = a.msgid AND p.sha256 = a.sha256 AND p.status = 'COPIED'
        WHERE c.importance = 'ALTA' AND p.projection_key IS NULL
          AND m.entity_id IN ('INTUR','ORTI','VIGNA') {filtro}""", **base)
    ambigui = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.stato = 'AMBIGUO' {filtro}""", **base)
    non_class = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.stato IN ('NON_CLASSIFICATO','ERRORE_CLASSIFICAZIONE') {filtro}""",
        **base)
    risolti = _q(client, f"""
        SELECT c.msgid, c.primary_category, c.override_note
        FROM `{_V_CORRENTE}` c
        WHERE c.override_source = 'HUMAN'
          AND c.classified_at > @da AND c.classified_at <= @a""", da=da, a=a)
    totali = _q(client, f"""
        SELECT m.casella, COUNT(*) AS n FROM `{F_PEC_MESSAGES}` m
        WHERE TRUE {filtro} GROUP BY 1""", **base)

    return {
        "finestra": (da, a), "importanti": importanti,
        "anomalie_ricevute": anomalie, "errori_parsing": errori,
        "non_sincronizzati": non_sync, "ambigui": ambigui,
        "non_classificati": non_class, "risolti": risolti,
        "totali_per_casella": {r["casella"]: r["n"] for r in totali},
    }


def _sezione(titolo: str, righe: list[dict], fmt_riga) -> list[str]:
    out = [f"## {titolo}", ""]
    out += [f"- {fmt_riga(r)}" for r in righe] if righe else ["_niente_"]
    out.append("")
    return out


def _render_markdown(dati: dict, solo_anomalie: bool) -> str:
    da, a = dati["finestra"]
    out = [f"# Digest PEC — {a:%Y-%m-%d}", "",
           f"Finestra: {da:%Y-%m-%d %H:%M} → {a:%Y-%m-%d %H:%M}", ""]
    if not solo_anomalie:
        out += _sezione(
            "Messaggi importanti", dati["importanti"],
            lambda r: f"**{r['entity_id']}** [{r['primary_category']}] "
                      f"{r['subject']} — da {r['mittente']}"
                      f"{' → nel pannello' if r['proiettato'] else ' (non proiettato)'}",
        )
    out += _sezione("Ricevute anomale", dati["anomalie_ricevute"],
                    lambda r: f"**{r['entity_id']}** {r['subject']} ({r['tipo']})")
    out += _sezione("Errori di parsing", dati["errori_parsing"],
                    lambda r: f"**{r['entity_id']}** {r['subject']}: {r['parse_warning']}")
    out += _sezione("Allegati importanti non sincronizzati", dati["non_sincronizzati"],
                    lambda r: f"**{r['entity_id']}** {r['nome_file']} — {r['gcs_uri']}")
    if not solo_anomalie:
        out += _sezione("Classificazioni ambigue", dati["ambigui"],
                        lambda r: f"**{r['entity_id']}** {r['subject']} — {r['mittente']}")
        out += _sezione("Da rivedere (non classificati)", dati["non_classificati"],
                        lambda r: f"**{r['entity_id']}** {r['subject']} — {r['mittente']}")
        out += _sezione("Risolti dall'ultimo digest", dati["risolti"],
                        lambda r: f"{r['msgid']} → {r['primary_category']} ({r['override_note'] or 'override'})")
        out += ["## Totali nuovi messaggi", ""]
        out += [f"- {c}: {n}" for c, n in dati["totali_per_casella"].items()] or ["_niente_"]
        out.append("")
    return "\n".join(out)


def run_digest(da: datetime | None = None, a: datetime | None = None,
               casella: str | None = None, entity: str | None = None,
               solo_anomalie: bool = False, fmt: str = "markdown",
               dry_run: bool = False) -> str:
    from core.bq.client import get_client
    from core.bq.write import bq_write_validated

    client = get_client()
    if _run_aperto(client):
        raise RuntimeError("un digest è già RUNNING: attendere o marcarlo FAILED")

    a = a or datetime.now()
    da = da or _ultimo_success(client) or EPOCA_CORPUS
    run_id = f"digest-{uuid.uuid4().hex[:12]}"
    started = datetime.now()
    params = json.dumps({"casella": casella, "entity": entity,
                         "solo_anomalie": solo_anomalie, "format": fmt})

    def _checkpoint(status: str, finished: datetime | None) -> None:
        if dry_run:
            return
        row = {"run_id": run_id, "started_at": started, "finished_at": finished,
               "status": status, "from_ts": da, "to_ts": a, "params": params}
        validate_batch([row], PecDigestRunRow, context="f_pec_digest_runs")
        bq_write_validated(F_PEC_DIGEST_RUNS, [PecDigestRunRow(**row)], mode="append")

    _checkpoint("RUNNING", None)
    try:
        dati = _raccogli(client, da, a, casella, entity)
        if fmt == "json":
            reso = json.dumps(dati, default=str, ensure_ascii=False, indent=2)
        else:
            reso = _render_markdown(dati, solo_anomalie)
            if not dry_run:
                dest = _percorso_file(a)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(reso)
                (Path(PANEL_ROOT) / "_digest" / "latest.md").write_text(reso)
    except Exception:
        _checkpoint("FAILED", datetime.now())
        raise
    _checkpoint("SUCCESS", datetime.now())
    return reso
