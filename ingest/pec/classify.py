"""Classificatore PEC a ruleset versionato → f_pec_classificazioni.

Tre dimensioni separate (category / importance / document_type), tutti i match
conservati, primary per priorità esplicita. Stati: CLASSIFICATO,
NON_CLASSIFICATO, AMBIGUO, ERRORE_CLASSIFICAZIONE. Spec 2026-07-17, I-PEC-8.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from core.config import F_PEC_CLASSIFICAZIONI, F_PEC_MESSAGES, F_PEC_ALLEGATI
from core.schemas import PecClassificazioneRow, make_hash, validate_batch

log = logging.getLogger("ingest.pec.classify")

RULESET_PATH = Path(__file__).resolve().parents[2] / "core" / "pec_ruleset.yaml"


@dataclass(frozen=True)
class Rule:
    id: str
    priority: int
    match: dict
    assign: dict


@dataclass(frozen=True)
class Ruleset:
    version: str
    rules: list[Rule] = field(default_factory=list)


def load_ruleset(path: Path | None = None) -> Ruleset:
    data = yaml.safe_load((path or RULESET_PATH).read_text())
    rules = [Rule(**r) for r in data["rules"]]
    if len({r.id for r in rules}) != len(rules):
        raise ValueError("id regola duplicati nel ruleset")
    return Ruleset(version=str(data["version"]), rules=rules)


def _rule_matches(rule: Rule, mittente: str, subject: str, nomi: list[str]) -> bool:
    m = rule.match
    if "mittente_domain" in m:
        dominio = mittente.rsplit("@", 1)[-1].lower() if "@" in mittente else ""
        if dominio not in [d.lower() for d in m["mittente_domain"]]:
            return False
    if "subject_regex" in m and not re.search(m["subject_regex"], subject or ""):
        return False
    if "allegato_regex" in m and not any(
        re.search(m["allegato_regex"], n or "") for n in nomi
    ):
        return False
    return True


_IMPORTANCE_ORD = {"DA_RIVEDERE": 0, "NORMALE": 1, "ALTA": 2}


def classify_message(
    mittente: str | None, subject: str | None, nomi_allegati: list[str],
    ruleset: Ruleset,
) -> dict:
    out = {
        "stato": "NON_CLASSIFICATO", "primary_category": None,
        "importance": "DA_RIVEDERE", "document_type": None, "matches": [],
    }
    try:
        matched = [
            r for r in ruleset.rules
            if _rule_matches(r, mittente or "", subject or "", nomi_allegati)
        ]
    except re.error as e:
        log.warning("regex rotta nel ruleset: %s", e)
        return {**out, "stato": "ERRORE_CLASSIFICAZIONE"}

    if not matched:
        return out
    out["matches"] = [r.id for r in matched]

    # category: vince la priorità più alta; pari priorità con categorie
    # diverse al vertice → AMBIGUO (si conservano comunque tutti i match).
    con_cat = sorted(
        (r for r in matched if r.assign.get("category")),
        key=lambda r: -r.priority,
    )
    if con_cat:
        top = [r for r in con_cat if r.priority == con_cat[0].priority]
        categorie_top = {r.assign["category"] for r in top}
        if len(categorie_top) > 1:
            return {**out, "stato": "AMBIGUO"}
        out["primary_category"] = con_cat[0].assign["category"]
        out["stato"] = "CLASSIFICATO"

    # importance: la massima tra tutti i match (default NORMALE se classificato)
    livelli = [r.assign["importance"] for r in matched if r.assign.get("importance")]
    if livelli:
        out["importance"] = max(livelli, key=_IMPORTANCE_ORD.__getitem__)
    elif out["stato"] == "CLASSIFICATO":
        out["importance"] = "NORMALE"

    # document_type: preferisce un tipo specifico (da allegato/oggetto) al
    # generico ALTRO di una regola di categoria anche se quest'ultima ha
    # priority più alta — la priority ordina la category, non il document_type;
    # a parità di specificità vince comunque la priority più alta.
    con_tipo = sorted(
        (r for r in matched if r.assign.get("document_type")),
        key=lambda r: (r.assign["document_type"] == "ALTRO", -r.priority),
    )
    if con_tipo:
        out["document_type"] = con_tipo[0].assign["document_type"]

    if out["stato"] == "NON_CLASSIFICATO" and out["matches"]:
        # match solo di document_type: comunque materiale classificato
        out["stato"] = "CLASSIFICATO"
    return out


def run_classify(dry_run: bool = False) -> dict:
    """Classifica su BQ i messaggi privi di riga alla versione corrente."""
    from core.bq.client import get_client

    rs = load_ruleset()
    client = get_client()
    sql = f"""
    SELECT m.msgid, m.entity_id, m.mittente, m.subject,
           ARRAY_AGG(a.nome_file IGNORE NULLS) AS nomi
    FROM `{F_PEC_MESSAGES}` m
    LEFT JOIN `{F_PEC_ALLEGATI}` a USING (msgid)
    LEFT JOIN `{F_PEC_CLASSIFICAZIONI}` c
      ON c.msgid = m.msgid AND c.ruleset_version = @v
    WHERE c.msgid IS NULL AND m.entity_id IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """
    from google.cloud import bigquery

    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("v", "STRING", rs.version)]
    ))
    now = datetime.now()
    rows, per_stato = [], {}
    for r in job.result():
        esito = classify_message(r.mittente, r.subject, list(r.nomi or []), rs)
        per_stato[esito["stato"]] = per_stato.get(esito["stato"], 0) + 1
        rows.append({
            "msgid": r.msgid, "entity_id": r.entity_id, "stato": esito["stato"],
            "primary_category": esito["primary_category"],
            "importance": esito["importance"],
            "document_type": esito["document_type"],
            "matches": json.dumps(esito["matches"]),
            "ruleset_version": rs.version, "classified_at": now,
            "override_source": None, "override_note": None,
            "hash_riga": make_hash(r.msgid, rs.version, ""),
            "data_caricamento": now,
        })
    validate_batch(rows, PecClassificazioneRow, context="f_pec_classificazioni")
    if not dry_run and rows:
        from core.bq.write import bq_write_validated

        bq_write_validated(
            F_PEC_CLASSIFICAZIONI,
            [PecClassificazioneRow(**r) for r in rows], mode="append",
        )
    report = {"ruleset_version": rs.version, "classificati": len(rows),
              "per_stato": per_stato, "dry_run": dry_run}
    log.info("classify: %s", report)
    return report
