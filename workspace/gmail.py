from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterator

from googleapiclient.discovery import build

from .auth import gmail_credentials


@dataclass
class GmailMessage:
    id: str
    thread_id: str
    date: str
    subject: str
    sender: str
    recipients: str
    snippet: str
    body_text: str
    raw_payload: dict


@dataclass
class GmailAttachment:
    message_id: str
    filename: str
    mime_type: str
    data: bytes
    size: int


def get_gmail_service(subject: str):
    creds = gmail_credentials(subject)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_messages(service, query: str, max_results: int = 1000) -> Iterator[dict]:
    """Yield message refs ({id, threadId}) matching query, paginated."""
    page_token = None
    fetched = 0
    while True:
        page_size = min(100, max_results - fetched)
        if page_size <= 0:
            return
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=page_size, pageToken=page_token)
            .execute()
        )
        for ref in resp.get("messages", []):
            yield ref
            fetched += 1
            if fetched >= max_results:
                return
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def get_message(service, msg_id: str) -> GmailMessage:
    full = (
        service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    )
    headers = {
        h["name"].lower(): h["value"]
        for h in full.get("payload", {}).get("headers", [])
    }
    return GmailMessage(
        id=full["id"],
        thread_id=full["threadId"],
        date=headers.get("date", ""),
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        recipients=headers.get("to", ""),
        snippet=full.get("snippet", ""),
        body_text=_extract_text(full.get("payload", {})),
        raw_payload=full,
    )


def _extract_text(payload: dict) -> str:
    """Walk MIME tree; prefer text/plain, fall back to text/html as-is."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and "data" in body:
        return base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="replace")
    if mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _extract_text(part)
            if text:
                return text
    if mime == "text/html" and "data" in body:
        return base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="replace")
    return ""


def list_attachments(service, msg: GmailMessage) -> list[GmailAttachment]:
    out: list[GmailAttachment] = []
    _collect_attachments(service, msg.id, msg.raw_payload.get("payload", {}), out)
    return out


def _collect_attachments(
    service, msg_id: str, payload: dict, out: list[GmailAttachment]
) -> None:
    filename = payload.get("filename")
    body = payload.get("body", {})
    if filename and body.get("attachmentId"):
        data = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=body["attachmentId"])
            .execute()
        )
        decoded = base64.urlsafe_b64decode(data["data"])
        out.append(
            GmailAttachment(
                message_id=msg_id,
                filename=filename,
                mime_type=payload.get("mimeType", "application/octet-stream"),
                data=decoded,
                size=int(data.get("size", len(decoded))),
            )
        )
    for part in payload.get("parts", []):
        _collect_attachments(service, msg_id, part, out)
