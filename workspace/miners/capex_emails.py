"""CapEx email miner — Gmail API.

Strategy (adapted from old GWS dump miner):
  Pass 1 (strict)   — q='<project_code> OR <project keywords>' → primary matches
  Pass 2 (thread)   — for each Pass 1 thread, fetch ALL messages (Gmail's
                      threads.get returns full conversation) → context replies
  Pass 3 (fuzzy)    — optional second query with generic keywords (preventivo,
                      offerta, capitolato), scored by sender overlap with Pass 1.
                      Off by default — high noise.

Output (Drive):
  <run_folder>/
    <mailbox_slug>/
      _Certo/<thread_folder>/   ← Pass 1 + Pass 2 (project-specific)
      _DaRivedere/<thread_folder>/  ← Pass 3 (manual review)
      index.csv
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime

from ..config import SKIP_ATTACHMENT_EXTS
from ..drive import ensure_subfolder, get_drive_writer, upload_bytes
from ..gmail import (
    GmailAttachment,
    GmailMessage,
    get_gmail_service,
    get_thread,
    list_attachments,
    search_messages,
)


# Defaults for HPAN25PIANO1 (Camere Primo Piano)
HPAN25PIANO1_KEYWORDS = [
    "HPAN25PIANO1",
    "primo piano",
    "camere primo piano",
]

GENERIC_CAPEX_KEYWORDS = ["preventivo", "offerta", "capitolato"]


def build_query(keywords: list[str], extra: str = "") -> str:
    parts = [f'"{k}"' if " " in k else k for k in keywords]
    clause = "(" + " OR ".join(parts) + ")"
    return f"{clause} {extra}".strip() if extra else clause


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text or "")
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:max_len] or "no_subject"


def _date_iso(rfc_date: str) -> str:
    try:
        dt = parsedate_to_datetime(rfc_date or "")
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return "unknown"


def _sender_addr(msg: GmailMessage) -> str:
    _, addr = parseaddr(msg.sender)
    return (addr or "").lower()


def _filter_attachments(
    atts: list[GmailAttachment], skip_exts: set[str] = SKIP_ATTACHMENT_EXTS
) -> list[GmailAttachment]:
    out = []
    for a in atts:
        ext = ("." + a.filename.rsplit(".", 1)[-1]).lower() if "." in a.filename else ""
        if ext in skip_exts:
            continue
        out.append(a)
    return out


def _persist_thread(
    drive,
    parent_folder_id: str,
    thread_messages: list[GmailMessage],
    primary_msg_ids: set[str],
    gmail_svc,
) -> tuple[str, int]:
    """Write thread.json + attachments to a new subfolder. Returns (folder_name, n_attachments)."""
    primary = sorted(thread_messages, key=lambda m: m.date or "")[0]
    date_str = _date_iso(primary.date)
    slug = _slugify(primary.subject or "no_subject")
    folder_name = f"{date_str}__{slug}__{primary.thread_id[:8]}"
    thread_folder_id = ensure_subfolder(drive, parent_folder_id, folder_name)

    thread_data = {
        "thread_id": primary.thread_id,
        "messages": [
            {
                "id": m.id,
                "is_primary_match": m.id in primary_msg_ids,
                "date": m.date,
                "from": m.sender,
                "to": m.recipients,
                "subject": m.subject,
                "snippet": m.snippet,
                "body_text": m.body_text,
            }
            for m in thread_messages
        ],
    }
    upload_bytes(
        drive,
        thread_folder_id,
        "thread.json",
        json.dumps(thread_data, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json",
    )

    n_attachments = 0
    seen_md5: set[str] = set()
    for m in thread_messages:
        atts = _filter_attachments(list_attachments(gmail_svc, m))
        for a in atts:
            import hashlib

            md5 = hashlib.md5(a.data).hexdigest()
            if md5 in seen_md5:
                continue
            seen_md5.add(md5)
            msg_date = _date_iso(m.date)
            fname = f"{msg_date}__{a.filename}"
            upload_bytes(drive, thread_folder_id, fname, a.data, a.mime_type)
            n_attachments += 1
    return folder_name, n_attachments


def mine_mailbox(
    mailbox: str,
    project_keywords: list[str],
    drive_run_folder_id: str,
    extra_filters: str = "",
    fuzzy_keywords: list[str] | None = None,
    max_threads: int = 1000,
    dry_run: bool = False,
) -> dict:
    """Mine one mailbox; return summary dict."""
    print(f"\n  ── {mailbox} ──")
    gmail = get_gmail_service(mailbox)

    # ── Pass 1: strict project-keyword search ──
    p1_query = build_query(project_keywords, extra_filters)
    print(f"  [Pass 1] q={p1_query}")
    p1_refs = list(search_messages(gmail, p1_query, max_results=max_threads * 5))
    p1_thread_ids = {r["threadId"] for r in p1_refs}
    p1_msg_ids = {r["id"] for r in p1_refs}
    print(f"  [Pass 1] {len(p1_refs)} messages → {len(p1_thread_ids)} threads")

    # ── Pass 2: thread expansion (fetch full thread for each Pass 1 hit) ──
    threads_certo: list[list[GmailMessage]] = []
    seed_senders: set[str] = set()
    for tid in p1_thread_ids:
        msgs = get_thread(gmail, tid)
        threads_certo.append(msgs)
        for m in msgs:
            seed_senders.add(_sender_addr(m))
    print(f"  [Pass 2] Expanded to full threads. Seed senders: {len(seed_senders)}")

    # ── Pass 3: fuzzy keyword search (optional, scored) ──
    threads_rivedere: list[tuple[list[GmailMessage], int]] = []
    if fuzzy_keywords:
        p3_query = build_query(fuzzy_keywords, extra_filters)
        print(f"  [Pass 3] q={p3_query}")
        p3_refs = list(search_messages(gmail, p3_query, max_results=max_threads * 5))
        p3_thread_ids = {r["threadId"] for r in p3_refs} - p1_thread_ids
        print(f"  [Pass 3] {len(p3_thread_ids)} new threads (after Pass 1 dedup)")
        for tid in p3_thread_ids:
            msgs = get_thread(gmail, tid)
            score = 1
            for m in msgs:
                if _sender_addr(m) in seed_senders:
                    score += 3
                    break
            for kw in project_keywords:
                if any(kw.lower() in (m.body_text or "").lower() for m in msgs):
                    score += 2
                    break
            threads_rivedere.append((msgs, score))
        threads_rivedere.sort(key=lambda x: -x[1])

    if dry_run:
        return {
            "mailbox": mailbox,
            "pass1_messages": len(p1_refs),
            "pass1_threads": len(p1_thread_ids),
            "pass3_threads": len(threads_rivedere),
            "dry_run": True,
        }

    # ── Persist to Drive ──
    drive = get_drive_writer()
    mailbox_slug = mailbox.split("@")[0]
    mb_folder_id = ensure_subfolder(drive, drive_run_folder_id, mailbox_slug)
    certo_id = ensure_subfolder(drive, mb_folder_id, "_Certo")
    rivedere_id = (
        ensure_subfolder(drive, mb_folder_id, "_DaRivedere")
        if threads_rivedere
        else None
    )

    index_rows: list[dict] = []
    n_att_total = 0

    for msgs in threads_certo:
        folder_name, n_att = _persist_thread(
            drive, certo_id, msgs, p1_msg_ids, gmail
        )
        n_att_total += n_att
        primary = sorted(msgs, key=lambda m: m.date or "")[0]
        index_rows.append(
            {
                "pass": "1+2",
                "score": "",
                "thread_id": primary.thread_id,
                "first_date": _date_iso(primary.date),
                "first_subject": primary.subject,
                "first_from": primary.sender,
                "n_messages": len(msgs),
                "n_attachments": n_att,
                "drive_folder": f"_Certo/{folder_name}",
            }
        )
        print(f"    ✓ Certo: {folder_name} ({len(msgs)} msg, {n_att} att)")

    for msgs, score in threads_rivedere:
        folder_name, n_att = _persist_thread(
            drive, rivedere_id, msgs, set(), gmail
        )
        n_att_total += n_att
        primary = sorted(msgs, key=lambda m: m.date or "")[0]
        index_rows.append(
            {
                "pass": "3",
                "score": score,
                "thread_id": primary.thread_id,
                "first_date": _date_iso(primary.date),
                "first_subject": primary.subject,
                "first_from": primary.sender,
                "n_messages": len(msgs),
                "n_attachments": n_att,
                "drive_folder": f"_DaRivedere/{folder_name}",
            }
        )
        print(f"    · Rivedere (score={score}): {folder_name} ({len(msgs)} msg)")

    if index_rows:
        csv_buf = io.StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=list(index_rows[0].keys()))
        writer.writeheader()
        writer.writerows(index_rows)
        upload_bytes(
            drive,
            mb_folder_id,
            "index.csv",
            csv_buf.getvalue().encode("utf-8"),
            "text/csv",
        )

    return {
        "mailbox": mailbox,
        "pass1_threads": len(threads_certo),
        "pass3_threads": len(threads_rivedere),
        "attachments": n_att_total,
        "drive_folder_id": mb_folder_id,
    }


def mine_capex_project(
    project_code: str,
    mailboxes: list[str],
    drive_parent_id: str,
    project_keywords: list[str] | None = None,
    fuzzy_keywords: list[str] | None = None,
    extra_filters: str = "",
    dry_run: bool = False,
) -> dict:
    """Run capex mine across multiple mailboxes."""
    if project_keywords is None:
        project_keywords = (
            HPAN25PIANO1_KEYWORDS if project_code == "HPAN25PIANO1" else [project_code]
        )

    drive = get_drive_writer()
    run_folder_name = f"{project_code}__extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_folder_id = ensure_subfolder(drive, drive_parent_id, run_folder_name)
    print(f"  Run folder: {run_folder_name}")

    results = []
    for mb in mailboxes:
        results.append(
            mine_mailbox(
                mailbox=mb,
                project_keywords=project_keywords,
                drive_run_folder_id=run_folder_id,
                extra_filters=extra_filters,
                fuzzy_keywords=fuzzy_keywords,
                dry_run=dry_run,
            )
        )

    # Write top-level README
    if not dry_run:
        readme = _build_readme(project_code, project_keywords, fuzzy_keywords, results)
        upload_bytes(
            drive,
            run_folder_id,
            "README.md",
            readme.encode("utf-8"),
            "text/markdown",
        )

    return {
        "project_code": project_code,
        "run_folder_id": run_folder_id,
        "run_folder_name": run_folder_name,
        "mailboxes": results,
    }


def _build_readme(
    project_code: str,
    project_keywords: list[str],
    fuzzy_keywords: list[str] | None,
    results: list[dict],
) -> str:
    lines = [
        f"# CapEx email mine — {project_code}",
        f"\nGenerated: {datetime.now().isoformat(timespec='seconds')}",
        f"\nProject keywords: {', '.join(project_keywords)}",
    ]
    if fuzzy_keywords:
        lines.append(f"Fuzzy keywords (Pass 3): {', '.join(fuzzy_keywords)}")
    lines.append("\n## Folders")
    lines.append("- `_Certo/` — Pass 1 (strict project-keyword match) + Pass 2 (thread expansion)")
    if fuzzy_keywords:
        lines.append("- `_DaRivedere/` — Pass 3 (fuzzy keyword), scored. Manual review needed.")
    lines.append("\n## Per-mailbox summary")
    for r in results:
        lines.append(
            f"- **{r['mailbox']}**: {r.get('pass1_threads', 0)} certo threads, "
            f"{r.get('pass3_threads', 0)} rivedere threads, "
            f"{r.get('attachments', 0)} attachments"
        )
    return "\n".join(lines) + "\n"
