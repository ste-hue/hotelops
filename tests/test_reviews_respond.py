"""Tests for verticals/reviews/respond.py — bozze di risposta alle recensioni."""

from verticals.reviews.respond import (
    VOICE_PATH,
    build_response_prompt,
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


def test_build_prompt_contiene_regole_verificabili():
    prompt = build_response_prompt("Camera sporca.", "HOTEL", VOICE_FIXTURE)
    # regole non negoziabili, formulate come nella spec
    assert "stessa lingua della recensione" in prompt
    assert "100 parole" in prompt
    assert "almeno un dettaglio presente nella recensione" in prompt
    assert "rispondere a qualcosa scritto dall'ospite" in prompt
    assert "aggiungere un fatto" in prompt
    assert "azione concreta" in prompt
    # fase di pulizia
    assert "copiata sotto una recensione diversa" in prompt
    assert "meno di 40 parole" in prompt
    # voce e firma dal voice file
    assert "Scrivi come una persona della reception." in prompt
    assert "Panorama Team" in prompt
    # il testo della recensione e la BU ci sono
    assert "Camera sporca." in prompt
    assert "HOTEL" in prompt


def test_build_prompt_playbook_solo_bu_giusta():
    p_hotel = build_response_prompt("Hotel datato.", "HOTEL", VOICE_FIXTURE)
    p_res = build_response_prompt("Hotel datato.", "RESIDENCE", VOICE_FIXTURE)
    assert "ristrutturazione" in p_hotel
    assert "ristrutturazione" not in p_res
    # playbook senza restrizione BU entra ovunque
    assert "colazione e' cambiata" in p_hotel
    assert "colazione e' cambiata" in p_res


def test_build_prompt_nota_propagata():
    con_nota = build_response_prompt(
        "Bello.", "CVM", VOICE_FIXTURE, nota="menziona la nuova colazione"
    )
    senza_nota = build_response_prompt("Bello.", "CVM", VOICE_FIXTURE)
    assert "menziona la nuova colazione" in con_nota
    assert "NOTA" in con_nota
    assert "NOTA" not in senza_nota
