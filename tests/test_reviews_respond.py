"""Tests for verticals/reviews/respond.py — bozze di risposta alle recensioni."""

from verticals.reviews.respond import (
    VOICE_PATH,
    load_voice,
    parse_playbooks,
    split_sections,
)

VOICE_FIXTURE = """# Voce — risposte alle recensioni

## Voce
Scrivi come una persona della reception.
Frasi corte.

## Temi
PULIZIA, COLAZIONE, STRUTTURA

## Playbook

### STRUTTURA (HOTEL)
L'hotel e' in fase di ristrutturazione.

### COLAZIONE
La colazione e' cambiata a giugno.

## Firma
Panorama Team
"""


def test_load_voice_reads_repo_file():
    text = load_voice()
    assert VOICE_PATH.name == "voice.md"
    assert "## Voce" in text
    assert "## Playbook" in text
    assert "## Firma" in text


def test_split_sections():
    sections = split_sections(VOICE_FIXTURE)
    assert "Scrivi come una persona della reception." in sections["Voce"]
    assert sections["Firma"] == "Panorama Team"
    assert "PULIZIA" in sections["Temi"]


def test_parse_playbooks_bu_restriction():
    playbooks = parse_playbooks(VOICE_FIXTURE)
    assert playbooks["STRUTTURA"]["bu"] == {"HOTEL"}
    assert "ristrutturazione" in playbooks["STRUTTURA"]["testo"]
    assert playbooks["COLAZIONE"]["bu"] is None  # vale per tutte le BU
    assert playbooks["COLAZIONE"]["testo"] == "La colazione e' cambiata a giugno."


def test_repo_voice_has_strutturazione_playbook_hotel_only():
    playbooks = parse_playbooks(load_voice())
    assert playbooks["STRUTTURA"]["bu"] == {"HOTEL"}
    assert "ristrutturazione" in playbooks["STRUTTURA"]["testo"].lower()
