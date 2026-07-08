"""Census read-only del Workspace per il dossier societario.

Fase 1 della spec: raccoglie, deduplica, classifica; NON scrive su Drive
(l'unico output e' il jsonl locale + l'indice xlsx caricato dal runner).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..config import SKIP_ATTACHMENT_EXTS
from ..drive import get_drive_reader
from ..gmail import get_gmail_service, get_thread, list_attachments, search_messages
from .dossier_classify import classify, extract_text


def item_key(item: dict) -> str:
    if item.get("source") == "drive":
        return f"drive:{item['file_id']}"
    return f"hash:{item['attachment_sha256']}"


def dedupe_items(items: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for it in items:
        key = item_key(it)
        if key in seen:
            for h in it.get("holders", []):
                if h not in seen[key]["holders"]:
                    seen[key]["holders"].append(h)
        else:
            it = dict(it)
            it["key"] = key
            it["holders"] = list(it.get("holders", []))
            seen[key] = it
    return list(seen.values())


def load_ledger(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        if line.strip():
            keys.add(json.loads(line)["key"])
    return keys


def append_ledger(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for k in keys:
            f.write(json.dumps({"key": k}) + "\n")


MAX_CONTENT_BYTES = 15 * 1024 * 1024
CLASSIFIABLE_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
GOOGLE_EXPORT_AS_PDF = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
}


def drive_query(phrase: str) -> str:
    escaped = phrase.replace("\\", "\\\\").replace("'", "\\'")
    return f"fullText contains '{escaped}' and trashed = false"


def gmail_query(terms: list[str]) -> str:
    return " OR ".join(f"({t})" for t in terms)


def _drive_file_bytes(svc, file_meta: dict) -> bytes | None:
    """Contenuto per la classificazione (None se non classificabile)."""
    mime = file_meta.get("mimeType", "")
    size = int(file_meta.get("size") or 0)
    try:
        if mime in GOOGLE_EXPORT_AS_PDF:
            return (
                svc.files()
                .export(fileId=file_meta["id"], mimeType="application/pdf")
                .execute()
            )
        if mime in CLASSIFIABLE_MIMES and 0 < size <= MAX_CONTENT_BYTES:
            return (
                svc.files()
                .get_media(fileId=file_meta["id"], supportsAllDrives=True)
                .execute()
            )
    except Exception:
        return None
    return None


def census_drive_user(
    user_email: str, phrases: list[str], max_files: int = 500
) -> list[dict]:
    svc = get_drive_reader(user_email)
    found: dict[str, dict] = {}
    for phrase in phrases:
        token = None
        while len(found) < max_files:
            resp = (
                svc.files()
                .list(
                    q=drive_query(phrase),
                    corpora="user",
                    pageToken=token,
                    pageSize=100,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields=(
                        "nextPageToken, files(id, name, mimeType, size, owners, "
                        "modifiedTime, webViewLink)"
                    ),
                )
                .execute()
            )
            for f in resp.get("files", []):
                if f["id"] in found:
                    continue
                data = _drive_file_bytes(svc, f)
                mime = (
                    "application/pdf"
                    if f["mimeType"] in GOOGLE_EXPORT_AS_PDF
                    else f["mimeType"]
                )
                text = extract_text(f["name"], data, mime) if data else ""
                category, confidence = classify(text)
                owners = [o.get("emailAddress", "") for o in f.get("owners", [])]
                found[f["id"]] = {
                    "source": "drive",
                    "file_id": f["id"],
                    "name": f["name"],
                    "mime_type": f["mimeType"],
                    "size": int(f.get("size") or 0),
                    "owner": owners[0] if owners else "",
                    "holders": [user_email],
                    "link": f.get("webViewLink", ""),
                    "modified": f.get("modifiedTime", ""),
                    "category": category,
                    "confidence": round(confidence, 2),
                }
            token = resp.get("nextPageToken")
            if not token:
                break
    return list(found.values())


def census_gmail_user(
    user_email: str, terms: list[str], max_threads: int = 200
) -> list[dict]:
    svc = get_gmail_service(user_email)
    items: list[dict] = []
    seen_threads: set[str] = set()
    for msg_ref in search_messages(
        svc, gmail_query(terms), max_results=max_threads * 4
    ):
        tid = msg_ref.get("threadId")
        if not tid or tid in seen_threads:
            continue
        seen_threads.add(tid)
        if len(seen_threads) > max_threads:
            break
        for msg in get_thread(svc, tid):
            for att in list_attachments(svc, msg):
                ext = (
                    "." + att.filename.rsplit(".", 1)[-1].lower()
                    if "." in att.filename
                    else ""
                )
                if ext in SKIP_ATTACHMENT_EXTS or not att.data:
                    continue
                sha = hashlib.sha256(att.data).hexdigest()
                text = extract_text(att.filename, att.data, att.mime_type)
                category, confidence = classify(text)
                items.append(
                    {
                        "source": "gmail",
                        "attachment_sha256": sha,
                        "name": att.filename,
                        "mime_type": att.mime_type,
                        "size": att.size,
                        "owner": msg.sender,
                        "holders": [user_email],
                        "link": f"https://mail.google.com/mail/u/0/#all/{msg.id}",
                        "modified": msg.date,
                        "message_id": msg.id,
                        "thread_id": msg.thread_id,
                        "thread_subject": msg.subject,
                        "category": category,
                        "confidence": round(confidence, 2),
                    }
                )
        time.sleep(0.2)
    return items


def census_company_folder(
    company_folder_id: str, reader_subject: str, max_files: int = 500
) -> list[dict]:
    """Classifica i file GIA' presenti nella cartella società (spec: 'stesso giro').

    Stessa forma-item di census_drive_user; esclude le sottocartelle della tassonomia
    e gli indici (_INDICE_*) per l'idempotenza dei run successivi.
    """
    svc = get_drive_reader(reader_subject)
    out: list[dict] = []
    token = None
    while len(out) < max_files:
        resp = (
            svc.files()
            .list(
                q=f"'{company_folder_id}' in parents and trashed = false",
                pageToken=token,
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields=(
                    "nextPageToken, files(id, name, mimeType, size, owners, "
                    "modifiedTime, webViewLink)"
                ),
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                continue
            if f["name"].startswith("_INDICE_DOSSIER_"):
                continue
            data = _drive_file_bytes(svc, f)
            mime = (
                "application/pdf"
                if f["mimeType"] in GOOGLE_EXPORT_AS_PDF
                else f["mimeType"]
            )
            text = extract_text(f["name"], data, mime) if data else ""
            category, confidence = classify(text)
            owners = [o.get("emailAddress", "") for o in f.get("owners", [])]
            out.append(
                {
                    "source": "drive",
                    "file_id": f["id"],
                    "name": f["name"],
                    "mime_type": f["mimeType"],
                    "size": int(f.get("size") or 0),
                    "owner": owners[0] if owners else "",
                    "holders": [reader_subject],
                    "link": f.get("webViewLink", ""),
                    "modified": f.get("modifiedTime", ""),
                    "category": category,
                    "confidence": round(confidence, 2),
                }
            )
        token = resp.get("nextPageToken")
        if not token:
            break
    return out
