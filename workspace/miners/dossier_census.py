"""Census read-only del Workspace per il dossier societario.

Fase 1 della spec: raccoglie, deduplica, classifica; NON scrive su Drive
(l'unico output e' il jsonl locale + l'indice xlsx caricato dal runner).
"""

from __future__ import annotations

import json
from pathlib import Path


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
            it.setdefault("holders", [])
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
