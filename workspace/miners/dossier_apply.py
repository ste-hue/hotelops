"""Fase apply del dossier: scorciatoie per i file Drive, upload per gli
allegati Gmail, nelle cartelle di categoria del dossier.

Per i file Drive non condivisi con WRITE_AS la scorciatoia sarebbe un link
morto: prima dello shortcut si tenta una condivisione reader silenziosa via
DWD impersonando owner/holder interno al dominio (best-effort; owner esterni
finiscono in `not_shared` per la gap list).

Idempotente via ledger; mai move/delete degli originali.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..dossier_config import (
    CONFIDENCE_THRESHOLD,
    DOMAIN,
    DOSSIER_STATE_DIR,
    DossierCompany,
    TAXONOMY,
    WRITE_AS,
)
from ..drive import (
    create_shortcut,
    ensure_shared_with,
    ensure_subfolder,
    get_drive_reader,
    get_drive_writer,
    upload_bytes,
)
from ..gmail import get_gmail_service, get_thread, list_attachments
from .dossier_census import GOOGLE_EXPORT_AS_PDF


def plan_apply(items: list[dict], ledger_keys: set[str], threshold: float) -> list[dict]:
    plan = []
    for it in items:
        if it["key"] in ledger_keys:
            continue
        it = dict(it)
        it["target_category"] = (
            it["category"] if it.get("confidence", 0) >= threshold else "_DaRivedere"
        )
        plan.append(it)
    return plan


def _grant_subject(item: dict) -> str | None:
    """Utente del dominio da impersonare per il grant (owner, poi holders)."""
    suffix = f"@{DOMAIN}"
    owner = item.get("owner") or ""
    if owner.endswith(suffix):
        return owner
    for h in item.get("holders", []):
        if h.endswith(suffix):
            return h
    return None


def _fetch_bytes(item: dict) -> bytes | None:
    holder = item["holders"][0]
    if item["source"] == "drive":
        svc = get_drive_reader(holder)
        if item["mime_type"] in GOOGLE_EXPORT_AS_PDF:
            return svc.files().export(
                fileId=item["file_id"], mimeType="application/pdf").execute()
        return svc.files().get_media(
            fileId=item["file_id"], supportsAllDrives=True).execute()
    svc = get_gmail_service(holder)
    # rifetch: trova nel thread l'allegato con lo stesso sha256
    for msg in get_thread(svc, item["thread_id"]):
        for att in list_attachments(svc, msg):
            if att.data and hashlib.sha256(att.data).hexdigest() == item["attachment_sha256"]:
                return att.data
    return None


def apply_census(company: DossierCompany, census_path: Path, dry_run: bool = False) -> dict:
    from .dossier_census import append_ledger, load_ledger

    items = [json.loads(line) for line in Path(census_path).read_text().splitlines() if line.strip()]
    ledger_path = DOSSIER_STATE_DIR / f"applied_{company.company_id}.jsonl"
    plan = plan_apply(items, load_ledger(ledger_path), CONFIDENCE_THRESHOLD)
    if dry_run:
        for p in plan:
            print(f"  [{p['target_category']}] {p['name']}  ({p['key']})")
        return {"applied": 0, "skipped": len(items) - len(plan), "failed": [],
                "planned": len(plan), "not_shared": []}

    writer = get_drive_writer(WRITE_AS)
    folder_ids = {cat: ensure_subfolder(writer, company.drive_folder_id, cat)
                  for cat in TAXONOMY}
    applied, failed, not_shared = [], [], []
    for p in plan:
        try:
            if p["source"] == "drive":
                # condivisione silenziosa best-effort: senza accesso per
                # WRITE_AS la scorciatoia sarebbe un link morto.
                subject = _grant_subject(p)
                shared = bool(subject) and ensure_shared_with(
                    subject, p["file_id"], WRITE_AS
                )
                create_shortcut(
                    writer, folder_ids[p["target_category"]], p["name"], p["file_id"]
                )
                # solo dopo che la scorciatoia esiste: se non condivisa, gap list.
                if not shared:
                    not_shared.append(p["key"])
            else:
                data = _fetch_bytes(p)
                if data is None:
                    raise RuntimeError("contenuto non recuperabile")
                name = p["name"]
                if p["mime_type"] in GOOGLE_EXPORT_AS_PDF and not name.lower().endswith(".pdf"):
                    name += ".pdf"
                mime = "application/pdf" if p["mime_type"] in GOOGLE_EXPORT_AS_PDF else p["mime_type"]
                upload_bytes(writer, folder_ids[p["target_category"]], name, data, mime)
            append_ledger(ledger_path, [p["key"]])
            applied.append(p["key"])
        except Exception as e:
            failed.append({"key": p["key"], "name": p.get("name"), "error": str(e)})
    return {"applied": len(applied), "skipped": len(items) - len(plan),
            "failed": failed, "planned": len(plan), "not_shared": not_shared}
