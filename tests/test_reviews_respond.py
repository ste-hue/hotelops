"""Tests for verticals/reviews/respond.py — bozze di risposta alle recensioni."""

import argparse
import io

import pytest

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

VOICE_FIXTURE_HOTEL_ONLY = """# Voce — risposte alle recensioni

## Voce
Scrivi come una persona della reception.
Frasi corte.

## Temi
PULIZIA, STRUTTURA

## Playbook

### STRUTTURA (HOTEL)
L'hotel e' in fase di ristrutturazione.

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


def test_build_prompt_guardrail_sempre_presente():
    # Regression: guardrail vs allucinazioni deve esserci ANCHE quando
    # non ci sono playbook applicabili (es. RESIDENCE con fixture che ha solo HOTEL playbook)
    # e nessuna nota.
    prompt_senza_playbook = build_response_prompt(
        "Camera datata.", "RESIDENCE", VOICE_FIXTURE_HOTEL_ONLY
    )
    # Il guardrail è la frase fondamentale per bloccare allucinazioni
    assert "senza inventare interventi" in prompt_senza_playbook
    # La regola "Sulle critiche" dev'esserci
    assert "Sulle critiche" in prompt_senza_playbook
    # Non deve dire "PLAYBOOK" se nessuno è applicabile (solo HOTEL playbook,
    # ma stiamo chiedendo per RESIDENCE = niente riferimento a playbook)
    assert "Applica i PLAYBOOK" not in prompt_senza_playbook


# Fake client helpers for testing generate_response


class _FakeContent:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeContent(text)]


class _FakeMessages:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.reply)


class _FakeClient:
    def __init__(self, reply):
        self.messages = _FakeMessages(reply)


def _patch_client(monkeypatch, reply):
    import anthropic

    fake = _FakeClient(reply)
    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake)
    return fake


def test_generate_response_happy_path(monkeypatch):
    from verticals.reviews.config import RESPONDER_MODEL
    from verticals.reviews.respond import generate_response

    fake = _patch_client(
        monkeypatch, "Grazie per la nota sulla colazione.\nPanorama Team"
    )
    bozza = generate_response("Colazione ottima.", "HOTEL")
    assert bozza == "Grazie per la nota sulla colazione.\nPanorama Team"
    (call,) = fake.messages.calls
    assert call["model"] == RESPONDER_MODEL
    assert "Colazione ottima." in call["messages"][0]["content"]


def test_generate_response_testo_vuoto(monkeypatch):
    from verticals.reviews.respond import generate_response

    fake = _patch_client(monkeypatch, "irrilevante")
    with pytest.raises(ValueError, match="vuoto"):
        generate_response("   ", "HOTEL")
    assert fake.messages.calls == []  # mai chiamata l'API


def test_generate_response_bu_sconosciuta(monkeypatch):
    from verticals.reviews.respond import generate_response

    fake = _patch_client(monkeypatch, "irrilevante")
    with pytest.raises(ValueError, match="BU"):
        generate_response("Bello.", "LIDO")
    assert fake.messages.calls == []


def test_generate_response_warning_oltre_100_parole(monkeypatch, capsys):
    from verticals.reviews.respond import generate_response

    _patch_client(monkeypatch, "parola " * 120)
    bozza = generate_response("Testo.", "CVM")
    assert len(bozza.split()) > 100
    err = capsys.readouterr().err
    assert "100 parole" in err


# CLI --rispondi


def _args(**kw):
    base = dict(rispondi=True, bu=None, file=None, nota=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_rispondi_stdin(monkeypatch, capsys):
    from verticals.reviews import cli_commands

    monkeypatch.setattr(
        "verticals.reviews.respond.generate_response",
        lambda testo, bu, nota=None: f"BOZZA[{bu}|{nota}]: {testo.strip()}",
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("Camera sporca.\n"))
    cli_commands._cmd_rispondi(_args(bu="HOTEL", nota="tono asciutto"))
    out = capsys.readouterr().out
    assert out.strip() == "BOZZA[HOTEL|tono asciutto]: Camera sporca."


def test_cmd_rispondi_file(monkeypatch, tmp_path, capsys):
    from verticals.reviews import cli_commands

    monkeypatch.setattr(
        "verticals.reviews.respond.generate_response",
        lambda testo, bu, nota=None: f"BOZZA: {testo.strip()}",
    )
    f = tmp_path / "rec.txt"
    f.write_text("Ottima posizione.", encoding="utf-8")
    cli_commands._cmd_rispondi(_args(bu="CVM", file=str(f)))
    assert capsys.readouterr().out.strip() == "BOZZA: Ottima posizione."


def test_cmd_rispondi_senza_bu(monkeypatch):
    from verticals.reviews import cli_commands

    with pytest.raises(SystemExit, match="--bu"):
        cli_commands._cmd_rispondi(_args(bu=None))


def test_cmd_rispondi_errore_input_pulito(monkeypatch):
    from verticals.reviews import cli_commands

    monkeypatch.setattr("sys.stdin", io.StringIO("   "))
    with pytest.raises(SystemExit, match="vuoto"):
        cli_commands._cmd_rispondi(_args(bu="HOTEL"))


def test_cli_end_to_end_parser_e_dispatch(monkeypatch):
    """Parser + dispatch reali: stdin vuoto deve dare SystemExit 'vuoto'
    PRIMA di qualsiasi chiamata API (nessuna key richiesta)."""
    import cli

    monkeypatch.setattr(
        "sys.argv", ["hotelops", "reviews", "--rispondi", "--bu", "HOTEL"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit, match="vuoto"):
        cli.main()
