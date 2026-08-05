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


def build_response_prompt(
    testo: str, bu: str, voice_text: str, nota: str | None = None
) -> str:
    """Assembla il prompt a 3 fasi (temi -> bozza -> pulizia)."""
    sections = split_sections(voice_text)
    playbooks = parse_playbooks(voice_text)
    applicabili = {
        tema: p["testo"]
        for tema, p in playbooks.items()
        if p["bu"] is None or bu in p["bu"]
    }

    parts = [
        "Sei l'addetto alla reception che risponde a una recensione online.",
        "",
        "VOCE (vincoli di scrittura, non negoziabili):",
        sections.get("Voce", ""),
        "",
        "Procedi in tre fasi.",
        "",
        "FASE 1 — TEMI: individua quali di questi temi sono presenti nella recensione:",
        sections.get("Temi", ""),
        "Considera solo i temi davvero menzionati dall'ospite.",
        "",
        "FASE 2 — BOZZA: scrivi la risposta rispettando TUTTE queste regole:",
        "- Rispondi nella stessa lingua della recensione.",
        "- Massimo 100 parole. Nessun minimo: non aggiungere testo per arrivare a una lunghezza.",
        "- Il ringraziamento deve citare almeno un dettaglio presente nella recensione.",
        "- Ogni frase deve fare almeno una di queste tre cose, altrimenti eliminala:",
        "  1. rispondere a qualcosa scritto dall'ospite;",
        "  2. aggiungere un fatto;",
        "  3. descrivere un'azione concreta.",
    ]

    # Build the playbook/nota reference string conditionally
    playbook_nota_refs = []
    if applicabili or nota:
        playbook_nota_refs = [
            "- Sulle critiche: se e' credibile, cita un'azione concreta presa o pianificata,",
        ]
        if applicabili and nota:
            playbook_nota_refs.append(
                "  presa SOLO dai PLAYBOOK o dalla NOTA qui sotto. Se non puoi citarne una,"
            )
        elif applicabili:
            playbook_nota_refs.append(
                "  presa SOLO dai PLAYBOOK qui sotto. Se non puoi citarne una,"
            )
        elif nota:
            playbook_nota_refs.append(
                "  presa SOLO dalla NOTA qui sotto. Se non puoi citarne una,"
            )
        playbook_nota_refs += [
            "  riconosci il problema senza inventare interventi. Mai promesse non supportate da fatti.",
        ]

    parts.extend(playbook_nota_refs)
    parts.append(
        "- Applica i PLAYBOOK solo se il loro tema e' tra quelli trovati in FASE 1."
    )

    if applicabili:
        parts += ["", "PLAYBOOK (fatti citabili, per tema):"]
        for tema, testo_pb in sorted(applicabili.items()):
            parts.append(f"- {tema}: {testo_pb}")

    if nota:
        parts += ["", f"NOTA di Stefano per questa risposta: {nota}"]

    parts += [
        "",
        "FASE 3 — PULIZIA: rileggi il testo.",
        "Elimina ogni frase che potrebbe essere copiata sotto una recensione diversa.",
        "Se restano meno di 40 parole va bene.",
        "Non aggiungere testo per arrivare a una certa lunghezza.",
        "",
        f"Chiudi con la firma: {sections.get('Firma', 'Panorama Team')}",
        "",
        f"Recensione (struttura: {bu}):",
        testo,
        "",
        "Rispondi SOLO con la bozza finale, senza spiegazioni ne' fasi intermedie.",
    ]
    return "\n".join(parts)
