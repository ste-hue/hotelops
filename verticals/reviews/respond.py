"""Bozze di risposta alle recensioni — draft-only, voice-driven.

La personalità sta tutta in voice.md; qui solo caricamento, parsing
e assemblaggio prompt. Spec: docs/superpowers/specs/2026-08-05-reviews-responder-design.md.
"""

from __future__ import annotations

import re
from pathlib import Path

VOICE_PATH = Path(__file__).parent / "voice.md"
VALID_BU = {"HOTEL", "RESIDENCE", "CVM"}
MAX_PAROLE = 100


def load_voice(path: Path | None = None) -> str:
    """Read voice.md (markdown grezzo)."""
    return (path or VOICE_PATH).read_text(encoding="utf-8")


def split_sections(voice_text: str) -> dict[str, str]:
    """Split del markdown in sezioni h2: {nome: contenuto strippato}."""
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in voice_text.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = m.group(1).strip()
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def parse_playbooks(voice_text: str) -> dict[str, dict]:
    """Playbook per tema dalla sezione '## Playbook'.

    Heading `### TEMA (BU1,BU2)` limita il playbook a quelle BU;
    senza parentesi vale per tutte (bu=None).
    """
    body = split_sections(voice_text).get("Playbook", "")
    playbooks: dict[str, dict] = {}
    current: str | None = None
    for line in body.splitlines():
        m = re.match(r"^### (\w+)(?:\s*\(([^)]*)\))?\s*$", line)
        if m:
            current = m.group(1).upper()
            bu = (
                {b.strip().upper() for b in m.group(2).split(",")}
                if m.group(2)
                else None
            )
            playbooks[current] = {"bu": bu, "testo": ""}
        elif current is not None:
            playbooks[current]["testo"] += line + "\n"
    for p in playbooks.values():
        p["testo"] = p["testo"].strip()
    return playbooks
