# Keplero Conversation Mining → FAQ candidate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minare le conversazioni dump Keplero (ospite ↔ bot) per produrre candidati FAQ `question⟶answer` (bozza+evidenza) che colmano i gap della knowledge base del chatbot.

**Architecture:** Due fasi. **Fase 1 (landing)**: dump `.tsv` → `hotelops intake` → GCS + `f_raw_objects` → `hotelops promote` invoca il parser → `f_keplero_messaggi` (BQ, APPEND, dedup `hash_riga`). **Fase 2 (mining)** — processo a stadi nel vertical `verticals/keplero/`: **[1] analisi NLP** (classify per conversazione, Sonnet) → **[2] considerazioni** (sintesi ragionata Claude sull'aggregato → `considerazioni.md`) → **[3] candidati** (cluster domande-gap, dedup vs baseline, bozza+evidenza → `keplero_faq_candidates.tsv`) → **GATE UMANO** (revisione/edit) → **[4] merge** (baseline + approvati → `keplero_faq_updated.tsv`, il deliverable da ricaricare in Keplero).

**Tech Stack:** Python 3.11, Pydantic (schemi), google-cloud-bigquery (`bq_write_validated`), `anthropic` SDK (Claude Sonnet `claude-sonnet-4-6`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-keplero-conversation-mining-faq-design.md`

**Deviazione dallo spec (ratificata in planning):** la source NON è `RAW_ONLY` ma `promotion_policy: AUTO` con `loop_targets: [keplero_faq]`. Motivo: `RAW_ONLY` blocca la promozione canonica (`policy_gate`), quindi `f_keplero_messaggi` non si popolerebbe via `promote`. `loop_targets` è lista libera (non set chiuso): `keplero_faq` è il loop che questa fonte alimenta. L'invariante `loop_targets==[] ⇔ RAW_ONLY` resta soddisfatta.

---

## File Structure

**Fase 1 — landing**
- `core/config.py` (modify) — aggiunge `F_KEPLERO_MESSAGGI`.
- `core/schemas.py` (modify) — aggiunge `KepleroMessaggioRow`.
- `core/source_registry.yaml` (modify) — aggiunge source `KEPLERO_CONVERSATIONS_PANORAMA_DUMP`.
- `ingest/flussi/ingest_keplero_conversazioni.py` (create) — parser TSV → `f_keplero_messaggi`. Eseguibile standalone (`--file --dry-run`) e via `promote` (`--raw-object-id`). Stessa forma di `ingest/flussi/ingest_ricavi_fb.py`.
- `tests/test_ingest_keplero.py` (create) — parser: parsing, dedup, takeover umano, file malformato.

**Fase 2 — mining** (`verticals/keplero/`)
- `verticals/keplero/__init__.py` (create) — vuoto.
- `verticals/keplero/config.py` (create) — `NLP_MODEL`, path di default.
- `verticals/keplero/faq_baseline.py` (create) — carica la FAQ esistente (TSV 2 colonne).
- `verticals/keplero/load_conversazioni.py` (create) — legge `f_keplero_messaggi` da BQ, raggruppa per `conversation_id`.
- `verticals/keplero/classify.py` (create) — classifica una conversazione con Claude Sonnet.
- `verticals/keplero/distill_faq.py` (create) — [stadio 3] cluster domande-gap, dedup vs baseline, bozza risposta → candidati TSV.
- `verticals/keplero/considerazioni.py` (create) — [stadio 2] sintesi ragionata Claude sull'aggregato → `considerazioni.md`.
- `verticals/keplero/merge_faq.py` (create) — [stadio 4] merge baseline + candidati approvati → `keplero_faq_updated.tsv` (post gate umano).
- `verticals/keplero/mine.py` (create) — orchestratore Fase 2 stadi [1]→[3] (CLI).
- `tests/test_keplero_faq_baseline.py` (create)
- `tests/test_keplero_classify.py` (create)
- `tests/test_keplero_distill.py` (create)
- `tests/test_keplero_considerazioni.py` (create)
- `tests/test_keplero_merge.py` (create)

---

## Task 1: Schema `KepleroMessaggioRow` + config

**Files:**
- Modify: `core/config.py` (zona fact tables, dopo `F_PROGETTO_EVENTI`)
- Modify: `core/schemas.py` (in fondo, dopo `PipelineRunRow`, prima di `def validate_batch`)
- Test: `tests/test_ingest_keplero.py`

- [ ] **Step 1: Write the failing test**

Crea `tests/test_ingest_keplero.py`:

```python
from core.schemas import KepleroMessaggioRow


def test_keplero_messaggio_row_minimal():
    row = KepleroMessaggioRow(
        hash_riga="abc123",
        conversation_id="001d6919-7e74-4ec9-a880-f28d56d28163",
        seq=0,
        sender="user",
        operator="",
        message="Buonasera, volevo un preventivo",
        ts="2026-04-25 15:25:36.017+00",
        data_ingest="2026-06-13T10:00:00",
        raw_object_id="raw_xyz",
    )
    assert row.conversation_id.startswith("001d6919")
    assert row.sender == "user"


def test_keplero_messaggio_row_rejects_empty_hash():
    import pytest
    with pytest.raises(Exception):
        KepleroMessaggioRow(
            hash_riga="",
            conversation_id="c",
            seq=0,
            sender="user",
            operator="",
            message="ciao",
            ts="2026-04-25 15:25:36+00",
            data_ingest="2026-06-13T10:00:00",
            raw_object_id="raw_xyz",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_keplero.py -v`
Expected: FAIL con `ImportError: cannot import name 'KepleroMessaggioRow'`.

- [ ] **Step 3: Add the schema**

In `core/schemas.py`, dopo la classe `PipelineRunRow` (prima di `def validate_batch`), aggiungi:

```python
class KepleroMessaggioRow(BaseModel):
    """Schema for f_keplero_messaggi — un turno di conversazione Keplero (ospite ↔ bot).

    Source: dump TSV console Keplero (1 file = 1 conversazione, filename = UUID).
    Pattern: APPEND + hash_riga dedup. Niente 5 dimensioni canoniche (non è un
    fatto finanziario; precedente: f_reviews porta solo societa/business_unit).
    """

    hash_riga: str
    conversation_id: str
    seq: int
    sender: str
    operator: str
    message: str
    ts: str
    data_ingest: str  # ISO timestamp
    raw_object_id: str

    @field_validator("hash_riga")
    @classmethod
    def hash_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("hash_riga vuoto")
        return v.strip()
```

- [ ] **Step 4: Add the config table id**

In `core/config.py`, dopo la riga `F_PROGETTO_EVENTI             = _t("f_progetto_eventi")` aggiungi:

```python
F_KEPLERO_MESSAGGI          = _t("f_keplero_messaggi")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ingest_keplero.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add core/schemas.py core/config.py tests/test_ingest_keplero.py
git commit -m "feat(keplero): schema KepleroMessaggioRow + config F_KEPLERO_MESSAGGI"
```

---

## Task 2: TSV parser → rows (parse + build)

**Files:**
- Create: `ingest/flussi/ingest_keplero_conversazioni.py`
- Test: `tests/test_ingest_keplero.py`

Il parser TSV ha header `sender <TAB> operator <TAB> message <TAB> timestamp`. Una riga per turno. `conversation_id` = stem del filename meno il prefisso `conversation_`.

- [ ] **Step 1: Write the failing tests**

Aggiungi a `tests/test_ingest_keplero.py`:

```python
from pathlib import Path
from ingest.flussi.ingest_keplero_conversazioni import (
    conversation_id_from_path,
    parse_tsv,
    build_rows,
)

SAMPLE_TSV = (
    "sender\toperator\tmessage\ttimestamp\n"
    "user\t\tBuonasera, volevo un preventivo\t2026-04-25 15:25:36.017+00\n"
    "assistant\tkeplero\tGrazie! Per quale struttura?\t2026-04-25 15:25:36.018+00\n"
    "assistant\tinfo@panoramagroup.it\tLe rispondo io, ecco il preventivo\t2026-04-25 15:30:00.000+00\n"
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_conversation_id_from_path(tmp_path):
    p = tmp_path / "conversation_001d6919-7e74-4ec9-a880-f28d56d28163.tsv"
    assert conversation_id_from_path(p) == "001d6919-7e74-4ec9-a880-f28d56d28163"


def test_parse_tsv_turns(tmp_path):
    p = _write(tmp_path, "conversation_abc.tsv", SAMPLE_TSV)
    turns = parse_tsv(p)
    assert len(turns) == 3
    assert turns[0] == ("user", "", "Buonasera, volevo un preventivo", "2026-04-25 15:25:36.017+00")
    # takeover umano riconoscibile dall'operator
    assert turns[2][1] == "info@panoramagroup.it"


def test_parse_tsv_skips_malformed_rows(tmp_path):
    bad = "sender\toperator\tmessage\ttimestamp\n" "user\tincompleta\n"
    p = _write(tmp_path, "conversation_bad.tsv", bad)
    assert parse_tsv(p) == []


def test_build_rows_dedup_and_seq(tmp_path):
    p = _write(tmp_path, "conversation_abc.tsv", SAMPLE_TSV)
    rows = build_rows(p, raw_object_id="raw_1", data_ingest="2026-06-13T10:00:00")
    assert len(rows) == 3
    assert [r.seq for r in rows] == [0, 1, 2]
    assert all(r.conversation_id == "abc" for r in rows)
    # hash_riga unico per turno
    assert len({r.hash_riga for r in rows}) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_keplero.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ingest.flussi.ingest_keplero_conversazioni'`.

- [ ] **Step 3: Implement parse + build**

Crea `ingest/flussi/ingest_keplero_conversazioni.py`:

```python
"""Parser dump conversazioni Keplero → f_keplero_messaggi.

1 file TSV = 1 conversazione (filename: conversation_<UUID>.tsv).
Header: sender <TAB> operator <TAB> message <TAB> timestamp. Una riga per turno.

Lifecycle: APPEND, dedup hash_riga. Eseguibile standalone (--file --dry-run) e
via `hotelops promote` (riceve --raw-object-id). Stessa forma di
ingest/flussi/ingest_ricavi_fb.py.
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.config import F_KEPLERO_MESSAGGI
from core.schemas import KepleroMessaggioRow, make_hash, validate_batch

log = logging.getLogger(__name__)

EXPECTED_HEADER = ["sender", "operator", "message", "timestamp"]


def conversation_id_from_path(path: Path) -> str:
    """`conversation_<UUID>.tsv` → `<UUID>`."""
    stem = path.stem
    return stem[len("conversation_"):] if stem.startswith("conversation_") else stem


def parse_tsv(path: Path) -> list[tuple[str, str, str, str]]:
    """Legge il TSV → lista di turni (sender, operator, message, timestamp).

    Righe senza i 4 campi vengono saltate con warning (non bloccano).
    """
    turns: list[tuple[str, str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        rows = list(reader)
    if not rows:
        return turns
    start = 1 if rows[0][:4] == EXPECTED_HEADER else 0
    for r in rows[start:]:
        if len(r) < 4:
            log.warning("%s: riga malformata saltata: %r", path.name, r)
            continue
        turns.append((r[0], r[1], r[2], r[3]))
    return turns


def build_rows(
    path: Path, raw_object_id: str, data_ingest: str | None = None
) -> list[KepleroMessaggioRow]:
    """Turni del file → righe Pydantic validate."""
    if data_ingest is None:
        data_ingest = datetime.now(timezone.utc).isoformat()
    conv_id = conversation_id_from_path(path)
    out: list[KepleroMessaggioRow] = []
    for seq, (sender, operator, message, ts) in enumerate(parse_tsv(path)):
        hash_riga = make_hash(conv_id, str(seq), sender, operator, message, ts)
        out.append(
            KepleroMessaggioRow(
                hash_riga=hash_riga,
                conversation_id=conv_id,
                seq=seq,
                sender=sender,
                operator=operator,
                message=message,
                ts=ts,
                data_ingest=data_ingest,
                raw_object_id=raw_object_id,
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_keplero.py -v`
Expected: PASS (tutti i test del file).

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_keplero_conversazioni.py tests/test_ingest_keplero.py
git commit -m "feat(keplero): parser TSV conversazioni (parse + build_rows)"
```

---

## Task 3: `ingest_file` + CLI main (write BQ via lineage)

**Files:**
- Modify: `ingest/flussi/ingest_keplero_conversazioni.py`
- Test: `tests/test_ingest_keplero.py`

`ingest_file` scrive su BQ tramite `bq_write_validated` (mode append). La lineage
(`raw_object_id` già nel row) viene letta dal `PipelineRun` corrente quando girato via promote.

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests/test_ingest_keplero.py` (mock di `bq_write_validated`):

```python
def test_ingest_file_writes_append_after_dedup(tmp_path, monkeypatch):
    import ingest.flussi.ingest_keplero_conversazioni as mod

    captured = {}

    def fake_write(table, rows, mode="append", natural_key=None):
        captured["table"] = table
        captured["rows"] = rows
        captured["mode"] = mode

    # dedup helper: pass-through (nessun duplicato preesistente)
    def fake_filter(table, rows, hash_column):
        captured["dedup_called"] = (table, hash_column)
        return rows

    monkeypatch.setattr("core.bq.write.bq_write_validated", fake_write)
    monkeypatch.setattr("core.bq.dedup.filter_new_rows_by_hash", fake_filter)

    p = tmp_path / "conversation_abc.tsv"
    p.write_text(SAMPLE_TSV, encoding="utf-8")
    n = mod.ingest_file(p, raw_object_id="raw_1", dry_run=False)

    assert n == 3
    assert captured["mode"] == "append"
    assert captured["table"].endswith("f_keplero_messaggi")
    assert captured["dedup_called"][1] == "hash_riga"
    assert len(captured["rows"]) == 3


def test_ingest_file_skips_already_present_rows(tmp_path, monkeypatch):
    import ingest.flussi.ingest_keplero_conversazioni as mod

    written = {}
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append", natural_key=None: written.update(rows=rows),
    )
    # simula che TUTTE le righe sono già in BQ → niente da scrivere
    monkeypatch.setattr(
        "core.bq.dedup.filter_new_rows_by_hash", lambda table, rows, hash_column: []
    )
    p = tmp_path / "conversation_abc.tsv"
    p.write_text(SAMPLE_TSV, encoding="utf-8")
    n = mod.ingest_file(p, raw_object_id="raw_1", dry_run=False)
    assert n == 0  # 0 righe nuove scritte
    assert written.get("rows", []) == [] or "rows" not in written


def test_ingest_file_dry_run_does_not_write(tmp_path, monkeypatch):
    import ingest.flussi.ingest_keplero_conversazioni as mod

    def boom(*a, **k):
        raise AssertionError("non deve scrivere in dry-run")

    monkeypatch.setattr("core.bq.write.bq_write_validated", boom)
    p = tmp_path / "conversation_abc.tsv"
    p.write_text(SAMPLE_TSV, encoding="utf-8")
    assert mod.ingest_file(p, raw_object_id="raw_1", dry_run=True) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_keplero.py::test_ingest_file_writes_append_after_dedup -v`
Expected: FAIL con `AttributeError: module ... has no attribute 'ingest_file'`.

- [ ] **Step 3: Implement ingest_file + main**

Aggiungi in fondo a `ingest/flussi/ingest_keplero_conversazioni.py`:

```python
def ingest_file(path: Path, raw_object_id: str, dry_run: bool = False) -> int:
    """Parse + validate + dedup-by-hash + (se non dry-run) write append.

    Idempotente: re-ingerire lo stesso dump (o dump che si sovrappongono) NON
    crea duplicati — filter_new_rows_by_hash scarta le righe il cui hash_riga è
    già in f_keplero_messaggi (stesso helper di reviews/ristocube).

    Ritorna il numero di righe NUOVE scritte (0 se tutto già presente).
    """
    rows = build_rows(path, raw_object_id=raw_object_id)
    validate_batch([r.model_dump() for r in rows], KepleroMessaggioRow, context=path.name)
    if dry_run:
        log.info("[dry-run] %s → %d turni (non scritti)", path.name, len(rows))
        return len(rows)
    from core.bq.dedup import filter_new_rows_by_hash
    from core.bq.write import bq_write_validated

    new_rows = filter_new_rows_by_hash(F_KEPLERO_MESSAGGI, rows, "hash_riga")
    if not new_rows:
        log.info("%s -> 0 turni nuovi (tutti gia' in BQ)", path.name)
        return 0
    bq_write_validated(F_KEPLERO_MESSAGGI, new_rows, mode="append")
    log.info("%s -> %d turni nuovi scritti su f_keplero_messaggi", path.name, len(new_rows))
    return len(new_rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest dump conversazioni Keplero → f_keplero_messaggi"
    )
    ap.add_argument("--file", required=True, type=Path, help="file conversation_<UUID>.tsv")
    ap.add_argument(
        "--raw-object-id",
        default="standalone",
        help="FK lineage (passato da `hotelops promote`); 'standalone' se eseguito a mano",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest_keplero.py -v`
Expected: PASS (tutti).

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_keplero_conversazioni.py tests/test_ingest_keplero.py
git commit -m "feat(keplero): ingest_file + CLI main (dedup-by-hash + append BQ via lineage)"
```

---

## Task 4: Registra la source lineage

**Files:**
- Modify: `core/source_registry.yaml`

- [ ] **Step 1: Add the source block**

In `core/source_registry.yaml`, in fondo alla sezione delle sources, aggiungi (indentazione 2 spazi, coerente con le altre voci):

```yaml
  # ── Conversazioni Keplero (dump TSV) — AUTO, loop keplero_faq ──────────────
  KEPLERO_CONVERSATIONS_PANORAMA_DUMP:
    system: KEPLERO
    dataset: CONVERSATIONS
    dataset_label: "Dump conversazioni chatbot Keplero (ospite ↔ bot Emma)"
    societa: PANORAMA
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_keplero_messaggi
    parser_module: ingest.flussi.ingest_keplero_conversazioni
    hash_basis: hash_riga
    loop_targets: [keplero_faq]
    promotion_policy: AUTO
    detector_category: keplero_conversations
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "keplero/conversations/PANORAMA"
    notes: |
      Dump TSV esportati dalla console Keplero (1 file = 1 conversazione,
      filename conversation_<UUID>.tsv). Alimentano il loop keplero_faq:
      mining → candidati FAQ. Dedup a livello oggetto per conversation_id;
      dedup riga via hash_riga nel parser.
```

- [ ] **Step 2: Verify the registry loads (invariant gate at boot)**

Run:
```bash
python -c "from core.lineage.source_resolver import load_source_registry; r = load_source_registry(); print('OK', 'KEPLERO_CONVERSATIONS_PANORAMA_DUMP' in r)"
```
Expected: stampa `OK True`. (Se il nome della funzione differisce, ispeziona `core/lineage/source_resolver.py` per l'API di load — l'obiettivo è che il boot validi l'invariante `loop_targets ⇔ policy` senza errori.)

- [ ] **Step 3: Verify the naming grammar (4 parti)**

Il `source_name` deve avere 4 parti `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`:
`KEPLERO` / `CONVERSATIONS` / `PANORAMA` / `DUMP`. Confermato dal nome.

- [ ] **Step 4: Commit**

```bash
git add core/source_registry.yaml
git commit -m "feat(keplero): source lineage KEPLERO_CONVERSATIONS_PANORAMA_DUMP (AUTO, loop keplero_faq)"
```

---

## Task 5: FAQ baseline loader

**Files:**
- Create: `verticals/keplero/__init__.py`
- Create: `verticals/keplero/config.py`
- Create: `verticals/keplero/faq_baseline.py`
- Test: `tests/test_keplero_faq_baseline.py`

La FAQ esistente è un file 2 colonne `question <TAB> answer` (può avere righe multilinea
nelle risposte; il loader le tratta come TSV con quoting standard, fallback a split su TAB).

- [ ] **Step 1: Write the failing test**

Crea `tests/test_keplero_faq_baseline.py`:

```python
from verticals.keplero.faq_baseline import load_faq_baseline, FaqEntry


def test_load_faq_baseline(tmp_path):
    content = (
        "question\tanswer\n"
        "Wi-fi\tIl servizio Wi-Fi è gratuito.\n"
        "Colazione\tLa colazione a buffet è inclusa.\n"
    )
    p = tmp_path / "faq.tsv"
    p.write_text(content, encoding="utf-8")
    entries = load_faq_baseline(p)
    assert len(entries) == 2
    assert isinstance(entries[0], FaqEntry)
    assert entries[0].question == "Wi-fi"
    assert "gratuito" in entries[0].answer


def test_load_faq_baseline_skips_blank_and_header(tmp_path):
    content = "question\tanswer\n\nWi-fi\tGratuito.\n"
    p = tmp_path / "faq.tsv"
    p.write_text(content, encoding="utf-8")
    entries = load_faq_baseline(p)
    assert [e.question for e in entries] == ["Wi-fi"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keplero_faq_baseline.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.keplero'`.

- [ ] **Step 3: Implement**

Crea `verticals/keplero/__init__.py` vuoto.

Crea `verticals/keplero/config.py`:

```python
"""Config del vertical Keplero (mining conversazioni → FAQ)."""

# Modello Claude per classificazione NLP (deciso in design: Sonnet)
NLP_MODEL = "claude-sonnet-4-6"

# Path di default per gli output (override via CLI)
DEFAULT_OUT_DIR = "~/Desktop/keplero_mining"
```

Crea `verticals/keplero/faq_baseline.py`:

```python
"""Carica la FAQ baseline esistente di Keplero (2 colonne question/answer)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FaqEntry:
    question: str
    answer: str


def load_faq_baseline(path: Path) -> list[FaqEntry]:
    """TSV 2 colonne → lista FaqEntry. Salta header e righe vuote."""
    entries: list[FaqEntry] = []
    with Path(path).expanduser().open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for r in reader:
            if len(r) < 2:
                continue
            q, a = r[0].strip(), r[1].strip()
            if not q or q.lower() == "question":
                continue
            entries.append(FaqEntry(question=q, answer=a))
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keplero_faq_baseline.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add verticals/keplero/__init__.py verticals/keplero/config.py verticals/keplero/faq_baseline.py tests/test_keplero_faq_baseline.py
git commit -m "feat(keplero): vertical scaffold + FAQ baseline loader"
```

---

## Task 6: Classificazione conversazione (Claude Sonnet)

**Files:**
- Create: `verticals/keplero/classify.py`
- Test: `tests/test_keplero_classify.py`

`classify.py` espone: `build_prompt(conversation)`, `parse_classification(text)` (puro,
testabile), e `classify_conversation(conversation, client)` (chiama Claude). La conversazione
è un dict `{"conversation_id": str, "turns": [{"sender","operator","message"}...]}`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_keplero_classify.py`:

```python
import json
from verticals.keplero.classify import build_prompt, parse_classification, classify_conversation

CONV = {
    "conversation_id": "abc",
    "turns": [
        {"sender": "user", "operator": "", "message": "Avete il parcheggio per camper?"},
        {"sender": "assistant", "operator": "keplero", "message": "Le consiglio di contattare info@panoramagroup.it"},
        {"sender": "assistant", "operator": "info@panoramagroup.it", "message": "No, non accettiamo camper."},
    ],
}


def test_build_prompt_includes_turns_and_ids():
    prompt = build_prompt(CONV)
    assert "Avete il parcheggio per camper?" in prompt
    assert "abc" in prompt


def test_parse_classification_valid_json():
    raw = json.dumps({
        "intent": "info_servizi",
        "sentiment": "neutro",
        "struttura": "HOTEL",
        "domande_estratte": ["Accettate camper nel parcheggio?"],
        "esito": "handoff_umano",
        "flag_gap": True,
    })
    out = parse_classification(raw)
    assert out["esito"] == "handoff_umano"
    assert out["flag_gap"] is True
    assert out["domande_estratte"] == ["Accettate camper nel parcheggio?"]


def test_parse_classification_strips_markdown_fence():
    raw = "```json\n{\"intent\": \"x\", \"sentiment\": \"neutro\", \"struttura\": \"n.d.\", \"domande_estratte\": [], \"esito\": \"abbandonata\", \"flag_gap\": false}\n```"
    out = parse_classification(raw)
    assert out["intent"] == "x"


def test_classify_conversation_uses_client():
    class FakeMsg:
        def __init__(self, text): self.content = [type("C", (), {"text": text})()]

    class FakeClient:
        def __init__(self): self.messages = self
        def create(self, **kwargs):
            return FakeMsg(json.dumps({
                "intent": "info_servizi", "sentiment": "neutro", "struttura": "HOTEL",
                "domande_estratte": ["Accettate camper?"], "esito": "handoff_umano", "flag_gap": True,
            }))

    out = classify_conversation(CONV, client=FakeClient())
    assert out["conversation_id"] == "abc"
    assert out["flag_gap"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keplero_classify.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.keplero.classify'`.

- [ ] **Step 3: Implement**

Crea `verticals/keplero/classify.py`:

```python
"""Classificazione NLP di una conversazione Keplero via Claude Sonnet.

Pattern mutuato da verticals/reviews/classify.py: client anthropic.Anthropic(),
messages.create, risposta JSON strutturata.
"""

from __future__ import annotations

import json
import logging
import re

from verticals.keplero.config import NLP_MODEL

log = logging.getLogger(__name__)

_PROMPT_HEADER = """Sei un analista del servizio ospiti di un gruppo alberghiero (Hotel Panorama,
Angelina Residence, Casa Vacanza Maiori, Lido). Classifica la conversazione tra un OSPITE
e il chatbot (operator=keplero) o un operatore umano (operator=info@panoramagroup.it).

Rispondi SOLO con un JSON con questi campi:
- intent: categoria della richiesta (es: preventivo, info_servizi, prenotazione, modifica_prenotazione, reclamo, altro)
- sentiment: uno tra positivo / neutro / negativo
- struttura: HOTEL / RESIDENCE / CVM / LIDO / n.d.
- domande_estratte: lista delle domande concrete poste dall'ospite, riformulate in forma-domanda naturale e autocontenuta
- esito: uno tra risolto_da_bot / handoff_umano / abbandonata
- flag_gap: true se l'ospite ha chiesto qualcosa che il bot NON ha saputo rispondere
  (ha deviato su "contatta info@panoramagroup.it"), oppure è intervenuto un operatore umano

Conversazione:
"""


def build_prompt(conversation: dict) -> str:
    lines = [f"[conversation_id: {conversation['conversation_id']}]"]
    for t in conversation["turns"]:
        who = "OSPITE" if t["sender"] == "user" else f"BOT/{t.get('operator') or 'keplero'}"
        lines.append(f"{who}: {t['message']}")
    return _PROMPT_HEADER + "\n".join(lines)


def parse_classification(text: str) -> dict:
    """Estrae il JSON dalla risposta (tollera fence markdown)."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def classify_conversation(conversation: dict, client) -> dict:
    """Classifica una conversazione. Ritorna il dict NLP + conversation_id.

    In caso di errore (API o JSON) ritorna un record con esito='errore_classificazione'.
    """
    prompt = build_prompt(conversation)
    try:
        resp = client.messages.create(
            model=NLP_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        out = parse_classification(resp.content[0].text)
    except Exception:
        log.exception("classificazione fallita per %s", conversation["conversation_id"])
        out = {
            "intent": "n.d.", "sentiment": "neutro", "struttura": "n.d.",
            "domande_estratte": [], "esito": "errore_classificazione", "flag_gap": False,
        }
    out["conversation_id"] = conversation["conversation_id"]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keplero_classify.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add verticals/keplero/classify.py tests/test_keplero_classify.py
git commit -m "feat(keplero): classificazione conversazione via Claude Sonnet"
```

---

## Task 7: Carica conversazioni da BQ (raggruppa messaggi)

**Files:**
- Create: `verticals/keplero/load_conversazioni.py`
- Test: `tests/test_keplero_classify.py` (riusa il file — funzione pura di grouping)

`group_messaggi(rows)` è puro e testabile: prende righe `f_keplero_messaggi` (dict) e le
raggruppa per `conversation_id`, ordinando per `seq`. `load_conversazioni(limit)` interroga BQ
(non unit-testata, smoke manuale).

- [ ] **Step 1: Write the failing test**

Aggiungi a `tests/test_keplero_classify.py`:

```python
from verticals.keplero.load_conversazioni import group_messaggi


def test_group_messaggi_orders_by_seq():
    rows = [
        {"conversation_id": "a", "seq": 1, "sender": "assistant", "operator": "keplero", "message": "B"},
        {"conversation_id": "a", "seq": 0, "sender": "user", "operator": "", "message": "A"},
        {"conversation_id": "b", "seq": 0, "sender": "user", "operator": "", "message": "C"},
    ]
    convs = group_messaggi(rows)
    assert len(convs) == 2
    conv_a = next(c for c in convs if c["conversation_id"] == "a")
    assert [t["message"] for t in conv_a["turns"]] == ["A", "B"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keplero_classify.py::test_group_messaggi_orders_by_seq -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.keplero.load_conversazioni'`.

- [ ] **Step 3: Implement**

Crea `verticals/keplero/load_conversazioni.py`:

```python
"""Legge f_keplero_messaggi da BQ e raggruppa per conversazione."""

from __future__ import annotations

from collections import defaultdict

from core.config import F_KEPLERO_MESSAGGI


def group_messaggi(rows: list[dict]) -> list[dict]:
    """Righe messaggio → lista conversazioni {conversation_id, turns[ordinati per seq]}."""
    by_conv: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_conv[r["conversation_id"]].append(r)
    convs = []
    for conv_id, msgs in by_conv.items():
        msgs_sorted = sorted(msgs, key=lambda m: m["seq"])
        turns = [
            {"sender": m["sender"], "operator": m["operator"], "message": m["message"]}
            for m in msgs_sorted
        ]
        convs.append({"conversation_id": conv_id, "turns": turns})
    return convs


def load_conversazioni(limit: int | None = None) -> list[dict]:
    """Query f_keplero_messaggi → conversazioni raggruppate. Smoke-tested a mano."""
    from core.bq.client import get_client

    sql = f"SELECT conversation_id, seq, sender, operator, message FROM `{F_KEPLERO_MESSAGGI}`"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in get_client().query(sql).result()]
    return group_messaggi(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keplero_classify.py::test_group_messaggi_orders_by_seq -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verticals/keplero/load_conversazioni.py tests/test_keplero_classify.py
git commit -m "feat(keplero): load_conversazioni — raggruppa f_keplero_messaggi per conversazione"
```

---

## Task 8: Distillazione FAQ (dedup baseline, bozza, output)

**Files:**
- Create: `verticals/keplero/distill_faq.py`
- Test: `tests/test_keplero_distill.py`

La parte pura e testabile: `dedup_against_baseline`, `assemble_candidate`, `write_candidates_tsv`.
Il clustering semantico delle domande (`cluster_questions`) usa Claude e viene iniettato come
funzione (mockato nei test). La sintesi ragionata (considerazioni) è un modulo separato (Task 9).

- [ ] **Step 1: Write the failing test**

Crea `tests/test_keplero_distill.py`:

```python
from pathlib import Path
from verticals.keplero.faq_baseline import FaqEntry
from verticals.keplero.distill_faq import (
    dedup_against_baseline,
    assemble_candidate,
    write_candidates_tsv,
)


def test_dedup_against_baseline_drops_covered():
    baseline = [FaqEntry(question="Avete il wifi?", answer="Sì, gratuito.")]
    clusters = [
        {"question": "C'è il wi-fi?", "members": ["a"]},          # coperto (overlap forte)
        {"question": "Accettate camper?", "members": ["b", "c"]},  # nuovo
    ]
    fresh = dedup_against_baseline(clusters, baseline)
    qs = [c["question"] for c in fresh]
    assert "Accettate camper?" in qs
    assert "C'è il wi-fi?" not in qs


def test_assemble_candidate_marks_da_compilare_without_evidence_answer():
    cluster = {"question": "Accettate camper?", "members": ["b", "c"]}
    # nessuna risposta fattuale nell'evidenza (solo deviazioni del bot)
    evidence = {
        "b": {"turns": [{"sender": "assistant", "operator": "keplero", "message": "contatti info@panoramagroup.it"}]},
        "c": {"turns": [{"sender": "user", "operator": "", "message": "camper?"}]},
    }
    cand = assemble_candidate(cluster, evidence)
    assert cand["answer"] == "[DA COMPILARE]"
    assert cand["support_count"] == 2
    assert set(cand["evidence_conversation_ids"].split(",")) == {"b", "c"}


def test_assemble_candidate_uses_human_takeover_answer():
    cluster = {"question": "Accettate camper?", "members": ["b"]}
    evidence = {
        "b": {"turns": [
            {"sender": "user", "operator": "", "message": "camper?"},
            {"sender": "assistant", "operator": "info@panoramagroup.it", "message": "No, non accettiamo camper."},
        ]},
    }
    cand = assemble_candidate(cluster, evidence)
    assert "camper" in cand["answer"].lower()
    assert cand["answer"] != "[DA COMPILARE]"


def test_write_candidates_tsv(tmp_path):
    cands = [
        {"question": "Accettate camper?", "answer": "No.", "support_count": 2, "evidence_conversation_ids": "b,c"},
    ]
    out = tmp_path / "cand.tsv"
    write_candidates_tsv(cands, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "question\tanswer\tsupport_count\tevidence_conversation_ids"
    assert lines[1].startswith("Accettate camper?\tNo.\t2\t")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keplero_distill.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.keplero.distill_faq'`.

- [ ] **Step 3: Implement**

Crea `verticals/keplero/distill_faq.py`:

```python
"""Distillazione: cluster di domande-gap → candidati FAQ (bozza+evidenza).

Pure functions + un punto Claude (cluster_questions) iniettabile per il test.
"""

from __future__ import annotations

import csv
import logging
from difflib import SequenceMatcher
from pathlib import Path

from verticals.keplero.faq_baseline import FaqEntry

log = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.6  # overlap domanda candidata vs baseline → considerata coperta


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def dedup_against_baseline(
    clusters: list[dict], baseline: list[FaqEntry]
) -> list[dict]:
    """Scarta i cluster la cui domanda è già coperta da una voce baseline."""
    fresh = []
    for c in clusters:
        covered = any(_similar(c["question"], e.question) >= _SIMILARITY_THRESHOLD for e in baseline)
        if not covered:
            fresh.append(c)
    return fresh


def assemble_candidate(cluster: dict, evidence: dict[str, dict]) -> dict:
    """Bozza risposta da takeover umano / buone risposte bot; altrimenti [DA COMPILARE].

    evidence: {conversation_id: {"turns": [...]}}.
    """
    members = cluster["members"]
    answer = "[DA COMPILARE]"
    # priorità 1: risposta di operatore umano (gold)
    for cid in members:
        for t in evidence.get(cid, {}).get("turns", []):
            if t["sender"] == "assistant" and t.get("operator") == "info@panoramagroup.it":
                answer = t["message"].strip()
                break
        if answer != "[DA COMPILARE]":
            break
    # priorità 2: risposta bot non-deviante (non contiene "info@panoramagroup.it")
    if answer == "[DA COMPILARE]":
        for cid in members:
            for t in evidence.get(cid, {}).get("turns", []):
                if (
                    t["sender"] == "assistant"
                    and t.get("operator") == "keplero"
                    and "info@panoramagroup.it" not in t["message"]
                ):
                    answer = t["message"].strip()
                    break
            if answer != "[DA COMPILARE]":
                break
    return {
        "question": cluster["question"],
        "answer": answer,
        "support_count": len(members),
        "evidence_conversation_ids": ",".join(members),
    }


def write_candidates_tsv(candidates: list[dict], out_path: Path) -> None:
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["question", "answer", "support_count", "evidence_conversation_ids"])
        for c in sorted(candidates, key=lambda x: x["support_count"], reverse=True):
            w.writerow([c["question"], c["answer"], c["support_count"], c["evidence_conversation_ids"]])


def write_gap_report(classified: list[dict], candidates: list[dict], out_path: Path) -> None:
    """Report markdown: intent frequenti, handoff, top domande non coperte."""
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from collections import Counter

    intents = Counter(c.get("intent", "n.d.") for c in classified)
    handoff = sum(1 for c in classified if c.get("esito") == "handoff_umano")
    gaps = sum(1 for c in classified if c.get("flag_gap"))
    lines = [
        "# Keplero — Gap Report",
        "",
        f"- Conversazioni analizzate: {len(classified)}",
        f"- Con gap (flag_gap): {gaps}",
        f"- Takeover umano (handoff): {handoff}",
        f"- Candidati FAQ nuovi: {len(candidates)}",
        "",
        "## Intent più frequenti",
        "",
    ]
    for intent, n in intents.most_common():
        lines.append(f"- {intent}: {n}")
    lines += ["", "## Top domande non coperte (per support_count)", ""]
    for c in sorted(candidates, key=lambda x: x["support_count"], reverse=True)[:30]:
        flag = " ⚠️ [DA COMPILARE]" if c["answer"] == "[DA COMPILARE]" else ""
        lines.append(f"- ({c['support_count']}) {c['question']}{flag}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cluster_questions(gap_questions: list[dict], client) -> list[dict]:
    """Raggruppa domande-gap semanticamente equivalenti via Claude.

    gap_questions: [{"conversation_id": str, "question": str}].
    Ritorna [{"question": <canonica>, "members": [conversation_id, ...]}].

    Implementazione: invia la lista numerata a Claude e chiedi i gruppi in JSON.
    Per volumi grandi, batcha a ~80 domande per chiamata e fondi i gruppi simili
    a posteriori con _similar() >= _SIMILARITY_THRESHOLD.
    """
    import json

    if not gap_questions:
        return []
    numbered = "\n".join(f"{i}: {g['question']}" for i, g in enumerate(gap_questions))
    prompt = (
        "Raggruppa le seguenti domande di ospiti in cluster semanticamente equivalenti. "
        "Per ogni cluster scegli una domanda canonica chiara in forma-domanda naturale. "
        'Rispondi SOLO JSON: {"clusters": [{"question": "...", "indici": [0,3]}]}.\n\n'
        + numbered
    )
    resp = client.messages.create(
        model=NLP_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    import re as _re
    text = _re.sub(r"^```(?:json)?|```$", "", resp.content[0].text.strip(), flags=_re.MULTILINE).strip()
    data = json.loads(text)
    out = []
    for cl in data["clusters"]:
        members = [gap_questions[i]["conversation_id"] for i in cl["indici"] if 0 <= i < len(gap_questions)]
        out.append({"question": cl["question"], "members": members})
    return out
```

Nota: `cluster_questions` referenzia `NLP_MODEL` — aggiungi l'import in cima al file:
`from verticals.keplero.config import NLP_MODEL`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keplero_distill.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add verticals/keplero/distill_faq.py tests/test_keplero_distill.py
git commit -m "feat(keplero): distillazione FAQ (dedup baseline, bozza+evidenza, output)"
```

---

## Task 9: Orchestratore Fase 2 (`mine.py`) + smoke

**Files:**
- Create: `verticals/keplero/mine.py`

Lega insieme: load_conversazioni (BQ) → classify (Sonnet) → raccogli gap → cluster → dedup
baseline → assemble candidates → scrivi TSV + report.

- [ ] **Step 1: Implement orchestrator**

Crea `verticals/keplero/mine.py`:

```python
"""Orchestratore Fase 2: f_keplero_messaggi → candidati FAQ + gap report.

Uso:
    python -m verticals.keplero.mine --faq-baseline ~/faq.tsv --out-dir ~/Desktop/keplero_mining
    python -m verticals.keplero.mine --faq-baseline ~/faq.tsv --limit 200   # smoke su sottoinsieme
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from verticals.keplero.config import DEFAULT_OUT_DIR
from verticals.keplero.faq_baseline import load_faq_baseline
from verticals.keplero.load_conversazioni import load_conversazioni
from verticals.keplero.classify import classify_conversation
from verticals.keplero.distill_faq import (
    cluster_questions,
    dedup_against_baseline,
    assemble_candidate,
    write_candidates_tsv,
    write_gap_report,
)

log = logging.getLogger(__name__)


def run(faq_baseline: Path, out_dir: Path, limit: int | None = None) -> None:
    import anthropic

    client = anthropic.Anthropic()
    out_dir = Path(out_dir).expanduser()

    baseline = load_faq_baseline(faq_baseline)
    convs = load_conversazioni(limit=limit)
    log.info("conversazioni: %d, baseline FAQ: %d", len(convs), len(baseline))

    classified = [classify_conversation(c, client=client) for c in convs]
    evidence = {c["conversation_id"]: c for c in convs}

    gap_questions = [
        {"conversation_id": cl["conversation_id"], "question": q}
        for cl in classified if cl.get("flag_gap")
        for q in cl.get("domande_estratte", [])
    ]
    clusters = cluster_questions(gap_questions, client=client)
    fresh = dedup_against_baseline(clusters, baseline)
    candidates = [assemble_candidate(c, evidence) for c in fresh]

    write_candidates_tsv(candidates, out_dir / "keplero_faq_candidates.tsv")
    write_gap_report(classified, candidates, out_dir / "gap_report.md")
    log.info("scritti %d candidati in %s", len(candidates), out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Keplero mining → FAQ candidate")
    ap.add_argument("--faq-baseline", required=True, type=Path, help="TSV FAQ esistente (2 colonne)")
    ap.add_argument("--out-dir", type=Path, default=Path(DEFAULT_OUT_DIR))
    ap.add_argument("--limit", type=int, default=None, help="limita le righe lette da BQ (smoke)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    run(args.faq_baseline, args.out_dir, limit=args.limit)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports (no syntax/wiring errors)**

Run: `python -c "import verticals.keplero.mine"`
Expected: nessun output, exit 0.

- [ ] **Step 3: Run the full test suite for the vertical**

Run: `pytest tests/test_ingest_keplero.py tests/test_keplero_faq_baseline.py tests/test_keplero_classify.py tests/test_keplero_distill.py -v`
Expected: tutti PASS.

- [ ] **Step 4: Lint**

Run: `ruff check ingest/flussi/ingest_keplero_conversazioni.py verticals/keplero/`
Expected: nessun errore (fix eventuali import inutilizzati).

- [ ] **Step 5: Commit**

```bash
git add verticals/keplero/mine.py
git commit -m "feat(keplero): orchestratore Fase 2 mine.py (BQ → classify → distill → output)"
```

---

## Task 10: Smoke end-to-end (manuale, gated dall'utente)

**Files:** nessuno (validazione). Richiede credenziali GCP + Anthropic + accesso al dump e al FAQ baseline.

> Questo task NON è automatizzabile: richiede dati reali e scrive su BQ/GCS. Eseguire con l'utente.

- [ ] **Step 1: Intake di un sottoinsieme (es. 5 file)**

```bash
hotelops intake "/Users/stefanodellapietra/Downloads/conversations 2/conversazioni_keplero/conversation_001d6919-7e74-4ec9-a880-f28d56d28163.tsv" \
  --source-name KEPLERO_CONVERSATIONS_PANORAMA_DUMP
```
Expected: stampa un `raw_object_id`; l'oggetto compare in `f_raw_objects`.

- [ ] **Step 2: Promote (AUTO invoca il parser)**

```bash
hotelops promote --raw-object-id <id_dallo_step_1>
```
Expected: il parser scrive N turni su `f_keplero_messaggi`. Verifica:
```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `hotelops-suite.hotelops.f_keplero_messaggi`'
```

- [ ] **Step 3: Mining su limit ristretto**

```bash
python -m verticals.keplero.mine --faq-baseline <faq.tsv> --limit 200 --out-dir ~/Desktop/keplero_mining
```
Expected: `~/Desktop/keplero_mining/keplero_faq_candidates.tsv` + `gap_report.md` generati; ispezione visiva dei candidati.

- [ ] **Step 4: Batch completo** (dopo OK sullo smoke)

Intake dell'intera cartella (loop sui 2172 file) — vedi Open item #3 nello spec: confermare/implementare il wrapper batch sull'`intake` per-file. Poi `promote` di tutti i raw object PROMOTABLE e `mine` senza `--limit`.

---

## Open items (dal design, da chiudere con l'utente)

1. **FAQ baseline file**: l'utente deve fornire il TSV (~70 voci). Senza, Task 10 step 3/4 non gira.
2. **Wrapper batch intake** (Task 10 step 4): l'`intake` è per-file; ingerire 2172 file richiede un loop/wrapper. Decidere se script ad hoc o estensione di `cmd_intake`.
3. **Clustering a volumi reali**: `cluster_questions` batcha a ~80 domande; valutare la qualità/costo sul volume vero e l'eventuale fusione post-batch.
4. **Dump Drive vecchi**: quando scaricati in locale, si aggiungono come secondo batch (dedup per conversation_id li fonde).
