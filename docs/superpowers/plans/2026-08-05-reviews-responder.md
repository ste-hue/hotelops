# Reviews Responder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `hotelops reviews --rispondi` genera bozze di risposta alle recensioni, voice-driven e anti-omologazione, draft-only (pubblicazione manuale sulla OTA).

**Architecture:** Tutta la personalità sta in `verticals/reviews/voice.md` (vincoli, temi, playbook, firma); `verticals/reviews/respond.py` resta quasi stupido: carica il file, assembla un prompt a 3 fasi (temi → bozza → pulizia), una sola chiamata Claude, stampa su stdout. Nessuna tabella BQ, nessuno stato.

**Tech Stack:** Python ≥3.11, argparse (CLI esistente `hotelops reviews`), SDK `anthropic` (già in uso in `classify.py`), pytest con mock del client.

**Spec:** `docs/superpowers/specs/2026-08-05-reviews-responder-design.md` (rev.2 — leggila prima di iniziare).

## Global Constraints

- Worktree `.worktrees/reviews-responder`, branch `feat/reviews-responder`. **Mai `pip install -e` da dentro il worktree** (CLAUDE.md).
- Modello bozze: `RESPONDER_MODEL = "claude-sonnet-5"` in `verticals/reviews/config.py`. Il classificatore resta su `NLP_MODEL` (Haiku) — non toccarlo.
- Regole prompt NON negoziabili (dalla spec): lingua della recensione; max 100 parole senza minimo; ringraziamento che cita ≥1 dettaglio della recensione; ogni frase risponde all'ospite / aggiunge un fatto / descrive un'azione concreta, altrimenti si elimina; critiche → azione concreta solo se credibile (da playbook o nota), altrimenti solo riconoscimento; fase di pulizia finale; firma da voice.md.
- Output CLI: SOLO la bozza su stdout (pipe-friendly, `| pbcopy`). Errori e warning su stderr.
- BU valide: `HOTEL`, `RESIDENCE`, `CVM`.
- Stile: match del codice esistente del vertical (import lazy dentro le funzioni CLI, `raise SystemExit("...")` per gli errori utente). `ruff check .` pulito.

## File Structure

- Create: `verticals/reviews/voice.md` — la voce (vincoli, temi, playbook, firma). Editabile da Stefano, zero codice.
- Create: `verticals/reviews/respond.py` — `load_voice`, `split_sections`, `parse_playbooks`, `build_response_prompt`, `generate_response`.
- Create: `tests/test_reviews_respond.py` — tutti i test del modulo.
- Modify: `verticals/reviews/config.py` — aggiungi `RESPONDER_MODEL`.
- Modify: `verticals/reviews/cli_commands.py` — dispatch `--rispondi` + `_cmd_rispondi`.
- Modify: `cli.py` (~riga 1176, dentro il blocco `# reviews`) — 4 argomenti nuovi.

---

### Task 1: voice.md + parsing (load_voice, split_sections, parse_playbooks)

**Files:**
- Create: `verticals/reviews/voice.md`
- Create: `verticals/reviews/respond.py`
- Modify: `verticals/reviews/config.py` (in coda al file)
- Test: `tests/test_reviews_respond.py`

**Interfaces:**
- Produces: `load_voice(path: Path | None = None) -> str` (markdown grezzo);
  `split_sections(voice_text: str) -> dict[str, str]` (sezioni h2 `## Nome` → contenuto);
  `parse_playbooks(voice_text: str) -> dict[str, dict]` con shape `{"STRUTTURA": {"bu": {"HOTEL"} | None, "testo": str}}` — heading `### TEMA (BU1,BU2)` limita alle BU indicate, senza parentesi vale per tutte;
  `VOICE_PATH`, `VALID_BU = {"HOTEL", "RESIDENCE", "CVM"}`, `MAX_PAROLE = 100`;
  `config.RESPONDER_MODEL = "claude-sonnet-5"`.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `tests/test_reviews_respond.py`:

```python
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
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.reviews.respond'`

- [ ] **Step 3: Crea `verticals/reviews/voice.md`**

```markdown
# Voce — risposte alle recensioni

Questo file È la personalità del responder. Modificarlo cambia le bozze
senza toccare codice. La blacklist è viva: quando vedi un tic ricorrente
nelle bozze, aggiungi la frase qui.

## Voce
Scrivi come una persona della reception.
Frasi corte.
Niente linguaggio da marketing.
Mai dire:
- "Siamo lieti"
- "La soddisfazione dell'ospite..."
- "Speriamo di riaverla presto"
Ringrazia solo per qualcosa di concreto.
Se una frase potrebbe andare bene sotto qualsiasi recensione, cancellala.
Non usare più di un aggettivo nella stessa frase.
Non descrivere l'hotel.
Rispondi all'ospite.

## Temi
PULIZIA, COLAZIONE, PERSONALE, POSIZIONE, RUMORE, PARCHEGGIO, CAMERA, STRUTTURA, RISTORANTE, SPIAGGIA

## Playbook

### STRUTTURA (HOTEL)
L'hotel è in fase di ristrutturazione. Citala come fatto, non come promessa vaga.

## Firma
Panorama Team
```

- [ ] **Step 4: Crea `verticals/reviews/respond.py` (solo parsing)**

```python
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
```

- [ ] **Step 5: Aggiungi in coda a `verticals/reviews/config.py`**

```python
# Claude API model for review response drafts (responder module)
RESPONDER_MODEL = "claude-sonnet-5"
```

- [ ] **Step 6: Verifica che i test passino**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: 4 PASS

- [ ] **Step 7: Lint + commit**

```bash
ruff check verticals/reviews/respond.py tests/test_reviews_respond.py && ruff format --check verticals/reviews/respond.py tests/test_reviews_respond.py
git add verticals/reviews/voice.md verticals/reviews/respond.py verticals/reviews/config.py tests/test_reviews_respond.py
git commit -m "feat(reviews): voice.md + parsing playbook per il responder"
```

---

### Task 2: build_response_prompt

**Files:**
- Modify: `verticals/reviews/respond.py`
- Test: `tests/test_reviews_respond.py`

**Interfaces:**
- Consumes: `load_voice`, `split_sections`, `parse_playbooks` (Task 1).
- Produces: `build_response_prompt(testo: str, bu: str, voice_text: str, nota: str | None = None) -> str` — prompt completo a 3 fasi. I playbook entrano nel prompt SOLO se `bu` è tra le loro BU (o bu=None); la nota entra solo se presente.

- [ ] **Step 1: Scrivi i test che falliscono**

Aggiungi a `tests/test_reviews_respond.py` (import: aggiungi `build_response_prompt` all'import da `verticals.reviews.respond`):

```python
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
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: i 3 test nuovi FAIL con `ImportError: cannot import name 'build_response_prompt'`

- [ ] **Step 3: Implementa in `respond.py`**

Aggiungi dopo `parse_playbooks`:

```python
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
        "- Sulle critiche: se e' credibile, cita un'azione concreta presa o pianificata,",
        "  presa SOLO dai PLAYBOOK o dalla NOTA qui sotto. Se non puoi citarne una,",
        "  riconosci il problema senza inventare interventi. Mai promesse non supportate da fatti.",
        "- Applica i PLAYBOOK solo se il loro tema e' tra quelli trovati in FASE 1.",
    ]

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
```

- [ ] **Step 4: Verifica che passino**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: 7 PASS

- [ ] **Step 5: Lint + commit**

```bash
ruff check verticals/reviews/respond.py tests/test_reviews_respond.py
git add verticals/reviews/respond.py tests/test_reviews_respond.py
git commit -m "feat(reviews): build_response_prompt a 3 fasi (temi/bozza/pulizia)"
```

---

### Task 3: generate_response (chiamata Claude + validazioni)

**Files:**
- Modify: `verticals/reviews/respond.py`
- Test: `tests/test_reviews_respond.py`

**Interfaces:**
- Consumes: `build_response_prompt`, `load_voice` (Task 1-2), `config.RESPONDER_MODEL`.
- Produces: `generate_response(testo: str, bu: str, nota: str | None = None) -> str` — valida input (ValueError su testo vuoto / BU sconosciuta PRIMA di chiamare l'API), una chiamata `anthropic.Anthropic().messages.create`, warning su stderr se la bozza supera `MAX_PAROLE`, eccezioni API propagate al chiamante.

- [ ] **Step 1: Scrivi i test che falliscano**

Aggiungi a `tests/test_reviews_respond.py`:

```python
import pytest


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
    from verticals.reviews.respond import generate_response
    from verticals.reviews.config import RESPONDER_MODEL

    fake = _patch_client(monkeypatch, "Grazie per la nota sulla colazione.\nPanorama Team")
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
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: i 4 test nuovi FAIL con `ImportError: cannot import name 'generate_response'`

- [ ] **Step 3: Implementa in `respond.py`**

Aggiungi `import sys` in testa al file (dopo `import re`), poi in coda:

```python
def generate_response(testo: str, bu: str, nota: str | None = None) -> str:
    """Genera la bozza di risposta. ValueError su input invalido, PRIMA dell'API."""
    testo = (testo or "").strip()
    if not testo:
        raise ValueError("testo recensione vuoto")
    bu = bu.upper()
    if bu not in VALID_BU:
        raise ValueError(f"BU sconosciuta: {bu} (valide: {', '.join(sorted(VALID_BU))})")

    import anthropic

    from verticals.reviews.config import RESPONDER_MODEL

    prompt = build_response_prompt(testo, bu, load_voice(), nota)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=RESPONDER_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    bozza = response.content[0].text.strip()

    n_parole = len(bozza.split())
    if n_parole > MAX_PAROLE:
        print(
            f"ATTENZIONE: bozza oltre le {MAX_PAROLE} parole ({n_parole}). Rileggila.",
            file=sys.stderr,
        )
    return bozza
```

- [ ] **Step 4: Verifica che passino**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: 11 PASS

- [ ] **Step 5: Lint + commit**

```bash
ruff check verticals/reviews/respond.py tests/test_reviews_respond.py
git add verticals/reviews/respond.py tests/test_reviews_respond.py
git commit -m "feat(reviews): generate_response con validazioni e warning lunghezza"
```

---

### Task 4: CLI — hotelops reviews --rispondi

**Files:**
- Modify: `cli.py` (blocco `# reviews`, dopo l'argomento `--dry-run` ~riga 1176)
- Modify: `verticals/reviews/cli_commands.py` (dispatch in `cmd_reviews` + nuovo handler)
- Test: `tests/test_reviews_respond.py`

**Interfaces:**
- Consumes: `generate_response(testo, bu, nota)` (Task 3).
- Produces: flag CLI `--rispondi` (store_true), `--bu` (str), `--file` (str), `--nota` (str); handler `_cmd_rispondi(args)` in `cli_commands.py`; dispatch: `--rispondi` ha priorità in `cmd_reviews`.

- [ ] **Step 1: Scrivi i test che falliscano**

Aggiungi a `tests/test_reviews_respond.py`:

```python
import argparse
import io


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
```

(Il parser di `cli.py` vive dentro `main()` — verificato, non esiste `build_parser()` — quindi il test passa da `cli.main()` con argv monkeypatchato.)

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_reviews_respond.py -v`
Expected: i test nuovi FAIL con `AttributeError: ... no attribute '_cmd_rispondi'`

- [ ] **Step 3: Aggiungi gli argomenti in `cli.py`**

Dopo il blocco `--dry-run` del parser reviews (~riga 1176):

```python
    p_reviews.add_argument(
        "--rispondi",
        action="store_true",
        help="Genera bozza di risposta a una recensione (testo da stdin o --file)",
    )
    p_reviews.add_argument(
        "--bu", type=str, help="Business unit della recensione (HOTEL|RESIDENCE|CVM)"
    )
    p_reviews.add_argument(
        "--file", type=str, help="File col testo della recensione (default: stdin)"
    )
    p_reviews.add_argument(
        "--nota", type=str, help="Indicazione una-tantum per questa risposta"
    )
```

- [ ] **Step 4: Dispatch + handler in `cli_commands.py`**

In `cmd_reviews`, primo ramo (la bozza non deve mai finire nel ramo `_cmd_summary`):

```python
def cmd_reviews(args):
    """Main reviews CLI handler — dispatches to sub-actions."""
    if getattr(args, "rispondi", False):
        _cmd_rispondi(args)
    elif args.scrape:
        _cmd_scrape(args)
```

Handler in coda al file (stile del modulo: import lazy, SystemExit per errori utente):

```python
def _cmd_rispondi(args):
    """Genera una bozza di risposta (draft-only, stdout). Testo da stdin o --file."""
    import sys
    from pathlib import Path

    from verticals.reviews import respond

    if not args.bu:
        raise SystemExit("--rispondi richiede --bu (HOTEL|RESIDENCE|CVM)")

    if args.file:
        testo = Path(args.file).read_text(encoding="utf-8")
    else:
        testo = sys.stdin.read()

    try:
        bozza = respond.generate_response(testo, args.bu, nota=args.nota)
    except ValueError as e:
        raise SystemExit(f"Errore: {e}")
    except Exception as e:
        raise SystemExit(f"Errore generazione bozza: {e}")

    print(bozza)
```

(Il monkeypatch dei test su `verticals.reviews.respond.generate_response` funziona perché l'handler risolve `respond.generate_response` all'esecuzione, non all'import.)

- [ ] **Step 5: Verifica che passino + suite intera**

Run: `pytest tests/test_reviews_respond.py -v` → Expected: 16 PASS
Run: `pytest -q` → Expected: tutta la suite verde (nessuna regressione: `cmd_reviews` ha un ramo nuovo davanti)

- [ ] **Step 6: Lint + commit**

```bash
ruff check . && ruff format --check verticals/reviews/ tests/test_reviews_respond.py
git add cli.py verticals/reviews/cli_commands.py tests/test_reviews_respond.py
git commit -m "feat(reviews): CLI --rispondi — bozze di risposta draft-only"
```

---

### Task 5: Verifica reale + push (gate DoD — richiede Stefano)

**Files:** nessuno (verifica manuale).

**Interfaces:**
- Consumes: la CLI completa (Task 4).

- [ ] **Step 1: Genera le 4 bozze del set DoD**

Servono 4 recensioni REALI (chiedile a Stefano o prendile da `hotelops reviews` / BQ `f_reviews`, campo `testo`):
1. una positiva; 2. una "hotel datato"; 3. una in inglese; 4. una molto negativa senza azione citabile.

```bash
hotelops reviews --rispondi --bu HOTEL < rec1.txt
hotelops reviews --rispondi --bu HOTEL < rec2_datato.txt
hotelops reviews --rispondi --bu HOTEL < rec3_english.txt
hotelops reviews --rispondi --bu HOTEL < rec4_negativa.txt
```

- [ ] **Step 2: Checklist DoD su OGNI bozza (con Stefano)**

- nessuna frase generica (= che starebbe sotto un'altra recensione);
- nessuna frase identica in due bozze diverse;
- lingua della recensione (la 3 DEVE uscire in inglese);
- sotto le 100 parole;
- almeno un riferimento concreto alla recensione;
- nessuna promessa non supportata (la 4 NON deve inventare interventi; la 2 DEVE citare la ristrutturazione come fatto).

Se una bozza fallisce → la correzione va PRIMA in `voice.md` (blacklist/vincoli), solo se non basta si tocca il prompt in `respond.py`. Commit di ogni ritocco.

- [ ] **Step 3: Suite + push + presentazione per il merge**

```bash
pytest -q && ruff check .
git push -u origin feat/reviews-responder
```

Presentare a Stefano per il merge. **Mai merge autonomo su main** (skill hotelops-threads).
