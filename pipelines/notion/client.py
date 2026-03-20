"""Notion API client — thin wrapper around the REST API."""
import os
import requests
from datetime import date
from typing import Iterator

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "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")
JOURNAL_DB_ID = "098f483264474490af92b5358b973a23"
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def _get(url: str, **kwargs) -> dict:
    r = requests.get(url, headers=HEADERS, **kwargs)
    r.raise_for_status()
    return r.json()


def _post(url: str, body: dict) -> dict:
    r = requests.post(url, headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json()


def iter_journal_entries(from_date: date, to_date: date) -> Iterator[dict]:
    """Yield all journal DB pages in [from_date, to_date], newest first."""
    cursor = None
    while True:
        body = {
            "filter": {
                "and": [
                    {"property": "data", "date": {"on_or_after": from_date.isoformat()}},
                    {"property": "data", "date": {"on_or_before": to_date.isoformat()}},
                ]
            },
            "sorts": [{"property": "data", "direction": "descending"}],
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor

        data = _post(f"https://api.notion.com/v1/databases/{JOURNAL_DB_ID}/query", body)
        yield from data["results"]

        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]


def get_page_blocks(page_id: str) -> list[dict]:
    """Return all blocks for a page (no nested recursion for now)."""
    blocks = []
    cursor = None
    while True:
        params = {}
        if cursor:
            params["start_cursor"] = cursor
        data = _get(f"https://api.notion.com/v1/blocks/{page_id}/children", params=params)
        blocks.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return blocks


def blocks_to_markdown(blocks: list[dict]) -> str:
    """Convert Notion blocks to clean markdown."""
    lines = []
    for b in blocks:
        t = b["type"]
        content = b.get(t, {})
        rt = content.get("rich_text", [])
        text = "".join(x.get("plain_text", "") for x in rt)

        if t == "heading_1":
            lines.append(f"# {text}")
        elif t == "heading_2":
            lines.append(f"## {text}")
        elif t == "heading_3":
            lines.append(f"### {text}")
        elif t == "bulleted_list_item":
            lines.append(f"- {text}")
        elif t == "numbered_list_item":
            lines.append(f"1. {text}")
        elif t == "to_do":
            checked = content.get("checked", False)
            box = "[x]" if checked else "[ ]"
            lines.append(f"- {box} {text}")
        elif t == "callout":
            icon_obj = content.get("icon") or {}
            icon = icon_obj.get("emoji", "⚠️")
            lines.append(f"> {icon} {text}")
        elif t == "quote":
            lines.append(f"> {text}")
        elif t == "divider":
            lines.append("---")
        elif t == "paragraph" and text:
            lines.append(text)
        elif t == "code":
            lang = content.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")

    return "\n".join(lines)
