# Motore di identificazione content-first — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** far riconoscere a `hotelops capture` gli 11 report Power BI che oggi non sa identificare, leggendo firme dichiarative da `core/registry.yaml` invece di scrivere 11 funzioni Python.

**Architecture:** un valutatore di firme (`ingest/signatures.py`) gira **davanti** al loop `DETECTORS` di `ingest/classify.py`. Se una firma matcha, il risultato si costruisce derivando `lifecycle`/società/parser da `core/source_registry.yaml` tramite `detector_category`. Se nessuna matcha, i detector Python restano la rete, invariati.

**Tech Stack:** Python ≥3.11, `pyyaml`, `openpyxl`, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-08-03-motore-identificazione-content-first-design.md`

## Global Constraints

- **Nessun detector Python viene modificato o cancellato.** Le 11 funzioni in `ingest/classify.py` restano bit-per-bit come sono. L'unica modifica a quel file è l'aggiunta di un ramo in `classify()` e di una funzione nuova.
- **Il valutatore supporta solo `sheets` e `structure.header_prefix`.** Ogni entry che usa `columns`, `filename`, `content` o `structure.header_0_2` viene **saltata**. È così che «nessuna migrazione in questo giro» diventa una proprietà del codice: `ricavi_fb` usa `header_0_2`, quindi il valutatore non può matcharla nemmeno volendo.
- **Le entry nuove in `core/registry.yaml` portano solo `formats` e `signatures`.** Niente `lifecycle`, `bq_table`, `pipeline`, `dest_folder`, `split_by_societa`: vivono già in `core/source_registry.yaml` sotto lo stesso `detector_category`.
- **Nessuna dipendenza nuova.** `pyyaml` e `openpyxl` sono già dipendenze core.
- **Nessuna scrittura su BigQuery.** Questo lavoro identifica file, non scrive righe. L'invariante `loop_targets == [] ⇔ RAW_ONLY` non viene toccata.
- **Due entry che matchano lo stesso file sono un errore esplicito** (`AmbiguousSignature`), mai un tie-break silenzioso.
- Dopo ogni task: `ruff check .` e `ruff format .` devono passare puliti.

---

## File Structure

| File | Responsabilità |
|---|---|
| `ingest/signatures.py` *(nuovo)* | Carica `core/registry.yaml`, valuta le firme di una entry contro un file, restituisce la `detector_category`. Non conosce `ClassificationResult` né BigQuery. |
| `tests/test_signatures.py` *(nuovo)* | Unit test del valutatore con `file_types` iniettati. Nessuna dipendenza dal registry reale. |
| `core/registry.yaml` *(modificato)* | +11 entry, solo `formats` + `signatures`. |
| `tests/test_registry_signatures.py` *(nuovo)* | Test di **configurazione**: nessuna ambiguità nel registry reale, ogni categoria firmata risolve a una source. |
| `ingest/classify.py` *(modificato)* | +`_classify_by_signature()`, +3 righe in `classify()`. Il resto invariato. |
| `tests/test_classify.py` *(modificato)* | +2 test: il percorso YAML vince su un Power BI, un file legacy va ancora al suo detector Python. |

Il confine è netto: `signatures.py` risponde *«che report è»* e non sa niente di società, tabelle o pipeline; `classify.py` traduce quella risposta in un `ClassificationResult` interrogando il source registry.

---

### Task 1: Valutatore di firme

**Files:**
- Create: `ingest/signatures.py`
- Test: `tests/test_signatures.py`

**Interfaces:**
- Consumes: `ingest.classify._read_xlsx_sample(path, sheet_name=None, max_rows=10) -> tuple[list[list], str]` (import **locale dentro la funzione** — `classify.py` importerà questo modulo, quindi un import a livello di modulo creerebbe un ciclo).
- Produces:
  - `identify(path: Path, file_types: dict | None = None) -> str | None`
  - `matches(path: Path, entry: dict, _cache: dict | None = None) -> bool`
  - `load_file_types(path: Path | None = None) -> dict`
  - `AmbiguousSignature(Exception)`
  - `_entry_is_supported(entry: dict) -> bool` (usato da `tests/test_registry_signatures.py`)

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `tests/test_signatures.py`:

```python
"""Test del valutatore di firme dichiarative (ingest.signatures).

Le fixture sono xlsx sintetici: nome foglio + sola riga d'header, che è
esattamente ciò che una firma legge. Nessun file di produzione nel repo.
"""

from pathlib import Path

import pytest

from ingest.signatures import (
    AmbiguousSignature,
    _entry_is_supported,
    identify,
    matches,
)


def _xlsx(path: Path, sheet: str, header: list[str]) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    wb.save(path)
    return path


FT = {
    "numero_camera_clienti": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {
                "type": "structure",
                "header_prefix": ["Camera", "Volte", "ARB", "Infant"],
            },
        ],
    },
    "occupazione_pms": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {
                "type": "structure",
                "header_prefix": ["Data", "Cam. Totali", "OOO", "Cam. Vendibili"],
            },
        ],
    },
    "legacy_da_saltare": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {"type": "structure", "header_0_2": ["Camera", "Volte", "ARB"]},
        ],
    },
}


def test_identifica_dal_prefisso_header(tmp_path):
    f = _xlsx(
        tmp_path / "data.xlsx",
        "Export",
        ["Camera", "Volte", "ARB", "Infant", "ADR"],
    )
    assert identify(f, FT) == "numero_camera_clienti"


def test_foglio_sbagliato_non_matcha(tmp_path):
    f = _xlsx(
        tmp_path / "data.xlsx",
        "Foglio1",
        ["Camera", "Volte", "ARB", "Infant"],
    )
    assert identify(f, FT) is None


def test_header_diverso_non_matcha(tmp_path):
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Giorno", "Camere", "ARB"])
    assert identify(f, FT) is None


def test_entry_con_grammatica_legacy_viene_saltata():
    assert _entry_is_supported(FT["numero_camera_clienti"]) is True
    assert _entry_is_supported(FT["legacy_da_saltare"]) is False


def test_grammatica_legacy_non_matcha_mai(tmp_path):
    """Un file che soddisfa header_0_2 non viene identificato: resta ai detector."""
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Camera", "Volte", "ARB"])
    assert identify(f, {"legacy_da_saltare": FT["legacy_da_saltare"]}) is None


def test_estensione_non_ammessa_non_matcha(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("Camera,Volte,ARB,Infant\n")
    assert identify(f, FT) is None


def test_due_entry_che_matchano_sollevano(tmp_path):
    doppione = {
        "a": FT["numero_camera_clienti"],
        "b": FT["numero_camera_clienti"],
    }
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Camera", "Volte", "ARB", "Infant"])
    with pytest.raises(AmbiguousSignature):
        identify(f, doppione)
```

- [ ] **Step 2: Esegui il test per verificare che fallisca**

Run: `pytest tests/test_signatures.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ingest.signatures'`

- [ ] **Step 3: Scrivi l'implementazione minima**

Crea `ingest/signatures.py`:

```python
#!/usr/bin/env python3
"""Valutatore di firme dichiarative da core/registry.yaml.

Identifica un file dal contenuto — nome foglio + prefisso della riga d'header —
invece che dal nome, che negli export Power BI è rumore del browser
("data.xlsx", "Data from Power BI (3).xlsx").

Gira DAVANTI ai detector Python di `ingest.classify`: se nessuna firma matcha,
il vecchio percorso resta la rete.

Grammatiche supportate: `sheets` (foglio richiesto) e `structure.header_prefix`
(prefisso esatto della prima riga). Una entry che usa qualsiasi altro tipo —
`columns`, `filename`, `content`, `structure.header_0_2` — viene SALTATA: sono
le categorie legacy, che restano ai loro detector Python finché non migrano.

Spec: docs/superpowers/specs/2026-08-03-motore-identificazione-content-first-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("ingest.signatures")

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "core" / "registry.yaml"

_SUPPORTED_TYPES = {"sheets", "structure"}
_SUPPORTED_STRUCTURE_KEYS = {"header_prefix"}


class AmbiguousSignature(Exception):
    """Due o più entry matchano lo stesso file — il registry è incoerente."""


@dataclass(frozen=True)
class _View:
    """Ciò che una firma può leggere: foglio effettivo + riga d'header."""

    sheet_used: str
    header: tuple[str, ...]


def load_file_types(path: Optional[Path] = None) -> dict:
    """Carica la sezione `file_types` di core/registry.yaml."""
    p = path or REGISTRY_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("file_types") or {}


def _entry_is_supported(entry: dict) -> bool:
    """True se TUTTE le firme della entry usano grammatiche che sappiamo valutare."""
    sigs = entry.get("signatures") or []
    if not sigs:
        return False
    for sig in sigs:
        if sig.get("type") not in _SUPPORTED_TYPES:
            return False
        if sig["type"] == "structure":
            if not (set(sig) - {"type"}) <= _SUPPORTED_STRUCTURE_KEYS:
                return False
    return True


def _required_sheet(entry: dict) -> Optional[str]:
    for sig in entry["signatures"]:
        if sig.get("type") == "sheets":
            required = sig.get("required") or []
            if required:
                return required[0]
    return None


def _read_view(path: Path, sheet: Optional[str]) -> Optional[_View]:
    # Import locale: ingest.classify importa questo modulo, un import a livello
    # di modulo creerebbe un ciclo a import-time.
    from ingest.classify import _read_xlsx_sample

    rows, used = _read_xlsx_sample(path, sheet_name=sheet, max_rows=1)
    if not rows:
        return None
    header = tuple(str(c).strip() if c is not None else "" for c in rows[0])
    return _View(sheet_used=used, header=header)


def matches(path: Path, entry: dict, _cache: Optional[dict] = None) -> bool:
    """True se il file soddisfa TUTTE le firme della entry.

    `_cache` evita di riaprire il file per ogni entry: `identify` ne passa uno
    condiviso, indicizzato per nome foglio richiesto.
    """
    if not _entry_is_supported(entry):
        return False
    formats = entry.get("formats") or []
    if formats and path.suffix.lower() not in [f.lower() for f in formats]:
        return False

    sheet = _required_sheet(entry)
    if _cache is None:
        _cache = {}
    if sheet not in _cache:
        _cache[sheet] = _read_view(path, sheet)
    view = _cache[sheet]
    if view is None:
        return False

    for sig in entry["signatures"]:
        if sig["type"] == "sheets":
            required = sig.get("required") or []
            if required and view.sheet_used != required[0]:
                return False
        elif sig["type"] == "structure":
            prefix = sig["header_prefix"]
            if list(view.header[: len(prefix)]) != list(prefix):
                return False
    return True


def identify(path: Path, file_types: Optional[dict] = None) -> Optional[str]:
    """Ritorna la detector_category che matcha il file, o None.

    Solleva AmbiguousSignature se più di una entry matcha: due report
    indistinguibili sono un errore di configurazione, non un tie-break.
    """
    ft = file_types if file_types is not None else load_file_types()
    cache: dict = {}
    hits = [cat for cat, entry in ft.items() if matches(path, entry, cache)]
    if len(hits) > 1:
        raise AmbiguousSignature(f"{path.name} matcha più categorie: {sorted(hits)}")
    return hits[0] if hits else None
```

- [ ] **Step 4: Esegui i test per verificare che passino**

Run: `pytest tests/test_signatures.py -v`
Expected: 7 PASS

- [ ] **Step 5: Lint**

Run: `ruff format ingest/signatures.py tests/test_signatures.py && ruff check ingest/signatures.py tests/test_signatures.py`
Expected: nessun errore

- [ ] **Step 6: Commit**

```bash
git add ingest/signatures.py tests/test_signatures.py
git commit -m "feat(ingest): valutatore di firme dichiarative da core/registry.yaml

Identifica un file dal contenuto (foglio + prefisso header) invece che dal
nome. Supporta solo sheets + structure.header_prefix: le entry con grammatica
legacy vengono saltate e restano ai detector Python.

Due entry che matchano lo stesso file sollevano AmbiguousSignature."
```

---

### Task 2: Le 11 entry di firma + i test di configurazione

**Files:**
- Modify: `core/registry.yaml` (append in coda a `file_types:`)
- Test: `tests/test_registry_signatures.py`

**Interfaces:**
- Consumes: `ingest.signatures.{load_file_types, identify, _entry_is_supported}` (Task 1); `core.lineage.source_resolver.load_registry() -> SourceRegistry` con `find_all_by_detector_category(cat) -> list[SourceDefinition]`.
- Produces: 11 `detector_category` firmate — `andamento_prenotazioni`, `bookings_tipologia`, `consprev_mensile`, `consprev_pax`, `consumi_powerbi`, `dettaglio_prenotazioni`, `menu_engineering`, `numero_camera_clienti`, `occupazione_pms`, `produzione_pms`, `vendite_fb`.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `tests/test_registry_signatures.py`:

```python
"""Test di CONFIGURAZIONE su core/registry.yaml — non del codice.

Verificano proprietà del registry reale: che nessuna firma sia ambigua, e che
ogni categoria firmata risolva a una source in core/source_registry.yaml.
Il secondo, se fosse esistito, avrebbe mostrato i 4 source_name orfani a maggio.
"""

from pathlib import Path

from core.lineage.source_resolver import load_registry
from ingest.signatures import _entry_is_supported, identify, load_file_types

# Le categorie Power BI che questo giro porta sotto firma dichiarativa.
ATTESE = {
    "andamento_prenotazioni",
    "bookings_tipologia",
    "consprev_mensile",
    "consprev_pax",
    "consumi_powerbi",
    "dettaglio_prenotazioni",
    "menu_engineering",
    "numero_camera_clienti",
    "occupazione_pms",
    "produzione_pms",
    "vendite_fb",
}


def _signed() -> dict:
    return {k: v for k, v in load_file_types().items() if _entry_is_supported(v)}


def _fixture_from_entry(path: Path, entry: dict) -> Path:
    """Costruisce l'xlsx minimo che la entry dichiara di riconoscere."""
    from openpyxl import Workbook

    sheet = "Sheet1"
    header: list[str] = []
    for sig in entry["signatures"]:
        if sig["type"] == "sheets":
            sheet = sig["required"][0]
        elif sig["type"] == "structure":
            header = list(sig["header_prefix"])
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    wb.save(path)
    return path


def test_le_undici_categorie_powerbi_hanno_una_firma():
    assert ATTESE <= set(_signed())


def test_nessuna_firma_e_ambigua(tmp_path):
    """Ogni entry riconosce la propria fixture e nessun'altra.

    identify() solleva AmbiguousSignature se due entry matchano: il test
    fallisce da solo, senza bisogno di asserirlo.
    """
    signed = _signed()
    assert signed, "nessuna entry valutabile — il valutatore non è collegato"
    for cat, entry in signed.items():
        f = _fixture_from_entry(tmp_path / f"{cat}.xlsx", entry)
        assert identify(f, signed) == cat


def test_ogni_categoria_firmata_risolve_a_una_source():
    reg = load_registry()
    for cat in _signed():
        assert reg.find_all_by_detector_category(cat), (
            f"{cat}: firma in core/registry.yaml senza nessuna source "
            f"in core/source_registry.yaml"
        )
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

Run: `pytest tests/test_registry_signatures.py -v`
Expected: `test_le_undici_categorie_powerbi_hanno_una_firma` FAIL (nessuna delle 11 esiste); `test_nessuna_firma_e_ambigua` FAIL sull'assert `"nessuna entry valutabile"`.

- [ ] **Step 3: Aggiungi le 11 entry**

In `core/registry.yaml`, in coda alla sezione `file_types:` (stessa indentazione delle entry esistenti, due spazi):

```yaml
  # ── Report Power BI — firme dichiarative (spec 2026-08-03) ─────────────
  # Portano SOLO formats + signatures: lifecycle, tabella, parser e policy
  # vivono in core/source_registry.yaml sotto lo stesso detector_category.
  # Il prefisso è di 4 colonne perché tre non bastano: consumi_powerbi e
  # vendite_fb condividono le prime tre e divergono alla quarta.

  andamento_prenotazioni:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Giorno", "CodiceHotel", "Tipologia Venduta", "Camere"]

  bookings_tipologia:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Giorno", "Tipologia Venduta", "Camere", "ARB"]

  consprev_mensile:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Anno", "Mese", "Classe", "Categoria"]

  consprev_pax:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Anno", "Mese", "Tipo", "Mese Cons"]

  consumi_powerbi:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Data - Anno", "Data - Mese", "Data - Giorno", "Reparto"]

  dettaglio_prenotazioni:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Giorno", "Camere", "ARB", "Infant"]

  menu_engineering:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["M", "Tipo", "Sala", "Piatto"]

  numero_camera_clienti:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Camera", "Volte", "ARB", "Infant"]

  occupazione_pms:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Data", "Cam. Totali", "OOO", "Cam. Vendibili"]

  produzione_pms:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Classe", "01ROOM", "02FB", "03PARK"]

  vendite_fb:
    formats: [.xlsx]
    signatures:
      - type: sheets
        required: ["Export"]
      - type: structure
        header_prefix: ["Data - Anno", "Data - Mese", "Data - Giorno", "Sala"]
```

- [ ] **Step 4: Esegui i test per verificare che passino**

Run: `pytest tests/test_registry_signatures.py -v`
Expected: 3 PASS

Se `test_ogni_categoria_firmata_risolve_a_una_source` fallisce, la categoria segnalata è scritta diversamente in `core/source_registry.yaml`: correggi il nome nella entry di firma, **non** nel source registry.

- [ ] **Step 5: Lint**

Run: `ruff format tests/test_registry_signatures.py && ruff check tests/test_registry_signatures.py`
Expected: nessun errore

- [ ] **Step 6: Commit**

```bash
git add core/registry.yaml tests/test_registry_signatures.py
git commit -m "feat(ingest): 11 firme dichiarative per i report Power BI

Le entry portano solo formats + signatures: lifecycle, tabella, parser e
policy restano in core/source_registry.yaml sotto lo stesso detector_category.

Due test verificano la CONFIGURAZIONE, non il codice: nessuna firma ambigua,
e ogni categoria firmata risolve a una source. Il secondo avrebbe mostrato i
4 source_name orfani a maggio."
```

---

### Task 3: Innesto in `classify()` e derivazione dal source registry

**Files:**
- Modify: `ingest/classify.py` (aggiunta di `_classify_by_signature`, +3 righe in `classify()`)
- Test: `tests/test_classify.py` (append di 2 test)

**Interfaces:**
- Consumes: `ingest.signatures.{identify, AmbiguousSignature}` (Task 1); le 11 entry (Task 2); `SourceDefinition` con i campi `societa`, `lifecycle`, `parser_module`.
- Produces: `classify(path)` restituisce un `ClassificationResult` con `confidence=0.95` e `details={"matched_by": "registry.yaml signature"}` per i file riconosciuti da firma.

- [ ] **Step 1: Scrivi i test che falliscono**

Appendi a `tests/test_classify.py`:

```python
class TestSignatureFirst:
    """Il valutatore dichiarativo vince sui detector Python; i legacy restano."""

    def test_powerbi_riconosciuto_da_firma(self, tmp_path):
        f = tmp_path / "data.xlsx"
        _write_xlsx_file(
            f,
            ["Camera", "Volte", "ARB", "Infant", "ADR"],
            [["H118", 22, 40, 0, 305.0]],
            sheet_name="Export",
        )
        result = classify(f)
        assert result.category == "numero_camera_clienti"
        assert result.societa == "ORTI"
        assert result.lifecycle == LIFECYCLE_SNAPSHOT
        assert result.confidence == 0.95
        assert result.details["matched_by"] == "registry.yaml signature"

    def test_legacy_resta_al_detector_python(self, tmp_path):
        """ricavi_fb usa header_0_2: il valutatore la salta, vince detect_ricavi_fb."""
        f = tmp_path / "data.xlsx"
        _write_xlsx_file(
            f,
            ["Classe", "Codice", "Descrizione Addebito", "Netto"],
            [["02FB", "BAR", "Bar", 19527.0]],
            sheet_name="Export",
        )
        result = classify(f)
        assert result.category == "ricavi_fb"
        assert "matched_by" not in result.details
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

Run: `pytest tests/test_classify.py::TestSignatureFirst -v`
Expected: `test_powerbi_riconosciuto_da_firma` FAIL con `assert 'unknown' == 'numero_camera_clienti'`; `test_legacy_resta_al_detector_python` PASS già (è la regressione, deve passare da subito).

- [ ] **Step 3: Scrivi l'implementazione minima**

In `ingest/classify.py`, subito **prima** di `def classify(path: Path)`, aggiungi:

```python
def _classify_by_signature(path: Path) -> Optional[ClassificationResult]:
    """Identifica il file dalle firme dichiarative di core/registry.yaml.

    lifecycle, società e parser NON stanno nella entry di firma: si derivano
    da core/source_registry.yaml per detector_category. Se le source della
    categoria discordano su un campo (es. `banca`, 5 source su 2 società),
    quel campo resta None e decide la logica esistente.
    """
    from ingest.signatures import identify

    category = identify(path)  # AmbiguousSignature propaga: è un errore di config
    if not category:
        return None

    from core.lineage.source_resolver import load_registry

    sources = load_registry().find_all_by_detector_category(category)
    if not sources:
        log.warning("Firma %s senza source nel source registry", category)
        return None

    def _unico(attr: str):
        valori = {getattr(s, attr) for s in sources}
        return valori.pop() if len(valori) == 1 else None

    parser = _unico("parser_module")
    return ClassificationResult(
        file_path=path,
        file_type=category,
        category=category,
        lifecycle=_unico("lifecycle") or LIFECYCLE_APPEND,
        societa=_unico("societa"),
        canonical_name=path.name,
        pipeline_cmd=f"python -m {parser} --file {{dest_file}}" if parser else None,
        confidence=0.95,
        details={"matched_by": "registry.yaml signature"},
    )
```

Poi, dentro `classify()`, subito **prima** del `for detector in DETECTORS:`:

```python
    # Firme dichiarative da core/registry.yaml: vincono sui detector Python.
    # Se nessuna matcha, i DETECTORS restano la rete (spec 2026-08-03).
    by_signature = _classify_by_signature(path)
    if by_signature:
        return by_signature
```

- [ ] **Step 4: Esegui i test per verificare che passino**

Run: `pytest tests/test_classify.py -v`
Expected: tutti PASS, inclusi i test preesistenti degli 11 detector legacy. **Se un test legacy si rompe, la rete non regge e il task va fermato**: è la premessa dell'intero design.

- [ ] **Step 5: Esegui la suite intera**

Run: `pytest -q`
Expected: nessun fallimento nuovo rispetto a `main`

- [ ] **Step 6: Lint**

Run: `ruff format ingest/classify.py tests/test_classify.py && ruff check .`
Expected: nessun errore

- [ ] **Step 7: Commit**

```bash
git add ingest/classify.py tests/test_classify.py
git commit -m "feat(ingest): classify() prova le firme dichiarative prima dei detector

Il valutatore YAML gira davanti al loop DETECTORS, che resta invariato come
rete. lifecycle, societa e parser si derivano da source_registry.yaml per
detector_category invece di essere duplicati nella entry di firma.

Un campo su cui le source della categoria discordano resta None."
```

---

### Task 4: Smoke sui file reali

**Files:** nessuno modificato — è un gate di verifica su dati veri.

**Interfaces:**
- Consumes: tutto quanto sopra, tramite `hotelops capture --dry-run`.
- Produces: la prova che il caso che ha aperto la sessione non può più accadere.

- [ ] **Step 1: Scarica un campione per report da GCS**

```bash
D=/tmp/hotelops_smoke && mkdir -p "$D"
gcloud storage cp \
  "gs://hotelops-raw/POWERBI_NUMEROCAMERACLIENTI_ORTI_SNAPSHOT/2026/07/2026_Panorama_Numero Camera Clienti Data.xlsx" \
  "gs://hotelops-raw/POWERBI_OCCUPAZIONE_ORTI_SNAPSHOT/2026/07/CVM_occupazione_20260730.xlsx" \
  "gs://hotelops-raw/POWERBI_PRODUZIONE_ORTI_SNAPSHOT/2026/07/CVM_produzione_20260730.xlsx" \
  "gs://hotelops-raw/POWERBI_BOOKINGSTIPOLOGIA_ORTI_SNAPSHOT/2026/08/PANORAMA_bookings_tipologia_20260801.xlsx" \
  "gs://hotelops-raw/POWERBI_DETTAGLIOPRENOTAZIONI_ORTI_SNAPSHOT/2026/08/PANORAMA_dettaglio_prenotazioni_20260801.xlsx" \
  "gs://hotelops-raw/POWERBI_CONSPREVPAX_ORTI_SNAPSHOT/2026/08/PANORAMA_consprevpax_20260801.xlsx" \
  "gs://hotelops-raw/POWERBI_MENUENGINEERING_ORTI_SNAPSHOT/2026/07/Data from Power BI (3).xlsx" \
  "gs://hotelops-raw/POWERBI_VENDITEFB_ORTI_APPEND/2026/07/Consumi Articoli F&B Data.xlsx" \
  "gs://hotelops-raw/POWERBI_CONSUMI_ORTI_APPEND/2026/07/Consumptions F&B Data.xlsx" \
  "gs://hotelops-raw/POWERBI_ANDAMENTOPRENOTAZIONI_ORTI_SNAPSHOT/2026/08/Andamento Prenotazioni Data.xlsx" \
  "gs://hotelops-raw/POWERBI_CONSPREV_ORTI_SNAPSHOT/2026/08/PANORAMA_consprev_20260801.xlsx" \
  "$D/"
```

- [ ] **Step 2: Rinomina tutto in modo anonimo**

È il punto dell'esercizio: se il riconoscimento dipendesse ancora dal nome, qui si romperebbe.

```bash
cd "$D" && i=0; for f in *.xlsx; do mv "$f" "anon_$((i++)).xlsx"; done; ls
```

- [ ] **Step 3: Classifica ognuno**

```bash
for f in "$D"/anon_*.xlsx; do
  echo "--- $(basename "$f")"
  hotelops capture "$f" --dry-run 2>&1 | grep -E "classify|source"
done
```

Expected: 11 file, 11 categorie **distinte**, nessun `unknown`, nessun `AmbiguousSignature`. Le categorie attese sono quelle in `ATTESE` di `tests/test_registry_signatures.py`.

- [ ] **Step 4: Verifica il caso che ha aperto la sessione**

```bash
hotelops capture ~/Downloads/data.xlsx --dry-run 2>&1 | grep -E "classify|source"
```

Expected: `category=ricavi_fb`, `source: POWERBI_RICAVIFB_ORTI_SNAPSHOT` — invariato rispetto a prima. È la prova che il percorso legacy non è stato disturbato.

- [ ] **Step 5: Pulisci**

```bash
rm -rf /tmp/hotelops_smoke
```

- [ ] **Step 6: Aggiorna STATUS.md e il workstream hub**

In `STATUS.md`, in testa, un blocco che dice: motore di identificazione content-first in produzione, 11 report Power BI riconosciuti dal contenuto, detector Python invariati come rete, `core/registry.yaml` finalmente letto.

In `vault/HotelOps/workstreams/INGEST_CHIUSURE.md`, aggiungi ai thread aperti:

```markdown
- [ ] **Migrare le 11 categorie legacy alle firme dichiarative** — oggi `columns`,
  `filename`, `content`, `structure.header_0_2` fanno saltare la entry e vince il
  detector Python. Migrarne una = scrivere la firma in `header_prefix` e cancellare
  la funzione, due passi reversibili
- [ ] **4 `source_name` orfani in `f_raw_objects`** (`POWERBI_BUDGETFORECAST_ORTI_APPEND`
  6 obj, `POWERBI_BOOKINGS_ORTI_APPEND` 3, `POWERBI_PRODUZIONE_ORTI_APPEND` 3,
  `MANUAL_BUDGET_ORTI_SNAPSHOT` 1) — nomi ritirati a maggio 2026 che sopravvivono
  nei raw object
- [ ] **`ESOLVER_PARTITE_APERTE_*` a colonna 0** in `core/source_registry.yaml`
  invece che dentro `sources:` — config morta, invisibile al resolver (i vivi sono
  `ESOLVER_PARTITE_*_SNAPSHOT`)
```

- [ ] **Step 7: Commit**

```bash
git add STATUS.md
git commit -m "docs(status): motore di identificazione content-first in produzione

11 report Power BI riconosciuti dal contenuto con nomi anonimi; percorso
legacy verificato invariato su ricavi_fb."
```

---

## Note per chi esegue

**Perché il fallback non è provvisorio.** L'opzione scartata era migrare tutte e 11 le categorie legacy in un colpo. Il percorso Python oggi ingerisce gli estratti conto e i mastrini di Rosa — il 3 agosto ha portato 404 movimenti MPS fino al 31/07. Romperlo per un guadagno che il fallback dà comunque sarebbe un cattivo affare. Il fallback è la definizione onesta di «il motore nuovo non ha ancora coperto quel caso».

**Perché i test di configurazione contano più di quelli di codice.** `test_nessuna_firma_e_ambigua` e `test_ogni_categoria_firmata_risolve_a_una_source` non verificano funzioni: verificano `core/registry.yaml`. Falliscono il giorno in cui qualcuno aggiunge un report indistinguibile o sbaglia il nome di una categoria — cioè nei due modi in cui questo sistema può degradare in silenzio.

**Cosa NON fa questo piano.** Non scrive nessun parser. `numero_camera_clienti` qui è una delle undici firme: dopo questo lavoro `hotelops capture` sa *che file è*, ma la source resta `RAW_ONLY` e nessuna riga entra in BigQuery. Il parser `NUMEROCAMERACLIENTI` → `f_ricavi_camera_anno` è il progetto successivo, con le quattro decisioni già prese (rollup annuale; riga senza codice camera tenuta come `NON_ASSEGNATA`; colonna `data_estrazione` derivata dal raw object; loop `season_forecast`).
