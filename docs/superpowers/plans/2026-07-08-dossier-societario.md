# Dossier Societario ORTI/INTUR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Miner Workspace che censisce Drive+Gmail di tutti gli utenti panoramagroup.it per ORTI srl / INTUR srl, classifica content-only nella tassonomia CEO, e (dopo review) copia i documenti nelle cartelle Drive societarie con indice e gap list; più subcomando per i documenti ufficiali via openapi-ita.

**Architecture:** Due fasi — census read-only (jsonl ledger + indice xlsx su Drive) e apply idempotente (copie via impersonation, mai move/delete). Moduli nuovi sotto `workspace/` sul pattern del miner CapEx; classificazione content-only pura e testabile; I/O Google in wrapper sottili.

**Tech Stack:** Python (hotelops), google-api-python-client (delegated SA `workspace-controller`), pdfplumber, openpyxl, `openapi_ita` (già installato editable in `hotelops_core`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-08-dossier-societario-design.md` (stesso worktree).
- Worktree: `/Users/stefanodellapietra/dev/Projects/hotelops/.worktrees/dossier-societario`, branch `feat/dossier-societario`. Tutti i comandi si eseguono da lì.
- Python/test runner: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/<file> -v` · lint: `~/.virtualenvs/hotelops_core/bin/python -m ruff check <paths>`.
- Classificazione **content-only**: mai decidere sul nome file (mandato esistente).
- ORTI **mai** cercato come parola nuda: solo `"ORTI S.R.L."`, `"ORTI SRL"`, `04391390657`.
- Nessuna scrittura BigQuery. Nessun move/delete su Drive: solo copie.
- Ogni chiamata openapi-ita a pagamento richiede flag esplicito (`--order`, `--yes`).
- Scope SA disponibili: `gmail.readonly`, `drive.readonly`, `drive.file`, `admin.directory.user.readonly` (client 114389181117717185714, già autorizzati).
- Identità: lettura impersonando il singolo utente; scrittura sempre impersonando `stefano@panoramagroup.it`.
- Costanti reali: ORTI CF/PIVA `04391390657` (Maiori), folder `1jtik538_t4udzOM033KHXa88PaY-o53S`; INTUR CF/PIVA `00553430653`, folder `1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG`; dominio `panoramagroup.it`.

---

### Task 1: Config società e tassonomia

**Files:**
- Create: `workspace/dossier_config.py`
- Test: `tests/test_dossier_config.py`

**Interfaces:**
- Produces: `DossierCompany` (dataclass: `company_id, display_name, search_phrases: list[str], gmail_terms: list[str], tax_code: str, drive_folder_id: str`), `COMPANIES: dict[str, DossierCompany]` (chiavi `"ORTI"`, `"INTUR"`), `TAXONOMY: list[str]` (9 voci, ultima `_DaRivedere`), `CONFIDENCE_THRESHOLD: float = 0.6`, `DOSSIER_STATE_DIR: Path`, `WRITE_AS = "stefano@panoramagroup.it"`, `DIRECTORY_SUBJECT = "stefano@panoramagroup.it"`, `DOMAIN = "panoramagroup.it"` (riusa `workspace.config.DOMAIN`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dossier_config.py
from workspace.dossier_config import (
    COMPANIES,
    CONFIDENCE_THRESHOLD,
    TAXONOMY,
)


def test_companies_have_real_identifiers():
    orti = COMPANIES["ORTI"]
    intur = COMPANIES["INTUR"]
    assert orti.tax_code == "04391390657"
    assert intur.tax_code == "00553430653"
    assert orti.drive_folder_id == "1jtik538_t4udzOM033KHXa88PaY-o53S"
    assert intur.drive_folder_id == "1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG"


def test_orti_never_searched_as_bare_word():
    orti = COMPANIES["ORTI"]
    for phrase in orti.search_phrases + orti.gmail_terms:
        assert phrase.strip().upper() != "ORTI", f"bare ORTI in {phrase!r}"


def test_taxonomy_shape():
    assert TAXONOMY[0] == "01_Societario"
    assert TAXONOMY[-1] == "_DaRivedere"
    assert len(TAXONOMY) == 9
    assert 0 < CONFIDENCE_THRESHOLD < 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/test_dossier_config.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'workspace.dossier_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# workspace/dossier_config.py
"""Config del dossier societario ORTI/INTUR (fronte dossier-societario)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import DOMAIN  # noqa: F401  (riesportato per i miner)

WRITE_AS = "stefano@panoramagroup.it"
DIRECTORY_SUBJECT = "stefano@panoramagroup.it"

DOSSIER_STATE_DIR = Path.home() / ".config" / "hotelops" / "dossier"

CONFIDENCE_THRESHOLD = 0.6

TAXONOMY = [
    "01_Societario",
    "02_Fiscale",
    "03_Bilanci",
    "04_Banche_Finanza",
    "05_Immobili_Catasto",
    "06_Personale",
    "07_Legale_Ispezioni",
    "08_Contratti",
    "_DaRivedere",
]


@dataclass(frozen=True)
class DossierCompany:
    company_id: str
    display_name: str
    search_phrases: list[str] = field(default_factory=list)  # Drive fullText
    gmail_terms: list[str] = field(default_factory=list)     # Gmail q
    tax_code: str = ""
    drive_folder_id: str = ""


COMPANIES: dict[str, DossierCompany] = {
    # "orti" e' una parola comune: MAI il termine nudo, solo frasi esatte + CF.
    "ORTI": DossierCompany(
        company_id="ORTI",
        display_name="ORTI S.R.L.",
        search_phrases=['"ORTI S.R.L."', '"ORTI SRL"', "04391390657"],
        gmail_terms=['"ORTI S.R.L." OR "ORTI SRL" OR 04391390657'],
        tax_code="04391390657",
        drive_folder_id="1jtik538_t4udzOM033KHXa88PaY-o53S",
    ),
    "INTUR": DossierCompany(
        company_id="INTUR",
        display_name="INTUR S.R.L.",
        search_phrases=["INTUR", "00553430653"],
        gmail_terms=["INTUR OR 00553430653"],
        tax_code="00553430653",
        drive_folder_id="1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG",
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/test_dossier_config.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add workspace/dossier_config.py tests/test_dossier_config.py
git commit -m "feat(dossier): config societa' ORTI/INTUR + tassonomia CEO"
```

---

### Task 2: Enumerazione utenti dominio (Directory API)

**Files:**
- Modify: `workspace/config.py` (aggiungi scope)
- Modify: `workspace/auth.py` (credenziali directory)
- Create: `workspace/directory.py`
- Test: `tests/test_dossier_directory.py`

**Interfaces:**
- Consumes: `workspace.auth` pattern `service_account.Credentials...with_subject`.
- Produces: `directory_credentials(subject: str)` in auth; in `workspace/directory.py`: `users_from_response(resp: dict) -> list[dict]` (puro; dict con chiavi `email, full_name, suspended, is_admin`) e `enumerate_domain_users(subject: str, include_suspended: bool = True) -> list[dict]` (chiama Admin SDK `users().list(domain=..., orderBy="email")` con paginazione `pageToken`).

- [ ] **Step 1: Write the failing test** (solo la parte pura)

```python
# tests/test_dossier_directory.py
from workspace.directory import users_from_response


def test_users_from_response_maps_fields():
    resp = {
        "users": [
            {"primaryEmail": "a@panoramagroup.it",
             "name": {"fullName": "A B"}, "suspended": False, "isAdmin": True},
            {"primaryEmail": "am@panoramagroup.it",
             "name": {"fullName": "AM"}, "suspended": True},
        ]
    }
    users = users_from_response(resp)
    assert users[0] == {
        "email": "a@panoramagroup.it", "full_name": "A B",
        "suspended": False, "is_admin": True,
    }
    assert users[1]["suspended"] is True
    assert users[1]["is_admin"] is False


def test_users_from_response_empty():
    assert users_from_response({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/test_dossier_directory.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'workspace.directory'`

- [ ] **Step 3: Write implementation**

In `workspace/config.py` aggiungi dopo `SCOPE_DRIVE_FILE`:

```python
SCOPE_ADMIN_DIRECTORY_RO = "https://www.googleapis.com/auth/admin.directory.user.readonly"
```

In `workspace/auth.py` aggiungi (stesso pattern delle altre):

```python
def directory_credentials(subject: str):
    """Delegated credentials per Admin SDK Directory (lista utenti dominio)."""
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=[SCOPE_ADMIN_DIRECTORY_RO],
    )
    return creds.with_subject(subject)
```

(e importa `SCOPE_ADMIN_DIRECTORY_RO` nel blocco import da `.config`).

```python
# workspace/directory.py
"""Enumerazione utenti del dominio via Admin SDK Directory API."""

from __future__ import annotations

from googleapiclient.discovery import build

from .auth import directory_credentials
from .config import DOMAIN


def users_from_response(resp: dict) -> list[dict]:
    """Mappa la risposta users().list in dict piatti (puro, testabile)."""
    out = []
    for u in resp.get("users", []) or []:
        out.append({
            "email": u.get("primaryEmail", ""),
            "full_name": (u.get("name") or {}).get("fullName", ""),
            "suspended": bool(u.get("suspended", False)),
            "is_admin": bool(u.get("isAdmin", False)),
        })
    return out


def enumerate_domain_users(subject: str, include_suspended: bool = True) -> list[dict]:
    svc = build("admin", "directory_v1",
                credentials=directory_credentials(subject), cache_discovery=False)
    users: list[dict] = []
    token = None
    while True:
        resp = svc.users().list(
            domain=DOMAIN, orderBy="email", maxResults=100, pageToken=token,
        ).execute()
        users.extend(users_from_response(resp))
        token = resp.get("nextPageToken")
        if not token:
            break
    if not include_suspended:
        users = [u for u in users if not u["suspended"]]
    return users
```

- [ ] **Step 4: Run tests**

Run: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/test_dossier_directory.py -v`
Expected: 2 PASS

- [ ] **Step 5: Verifica live (read-only, gratis)**

```bash
~/.virtualenvs/hotelops_core/bin/python -c "
from workspace.directory import enumerate_domain_users
us = enumerate_domain_users('stefano@panoramagroup.it')
print(len(us), 'utenti'); [print(u['email'], u['suspended']) for u in us]"
```
Expected: 12 utenti, `am@` suspended True.

- [ ] **Step 6: Commit**

```bash
git add workspace/config.py workspace/auth.py workspace/directory.py tests/test_dossier_directory.py
git commit -m "feat(dossier): enumerazione utenti dominio via Directory API"
```

---

### Task 3: Estrazione testo content-only

**Files:**
- Create: `workspace/miners/dossier_classify.py` (prima metà: estrazione)
- Test: `tests/test_dossier_classify.py`

**Interfaces:**
- Produces: `extract_text(filename: str, data: bytes, mime_type: str) -> str` — pdf via pdfplumber, docx via zipfile (strip XML), xlsx via openpyxl (celle stringhe), text/* decodificato; altrimenti `""`. Mai eccezioni: su errore ritorna `""`.
- Nota: reportlab è disponibile nel venv (dipendenza di openapi-ita) — usalo nei test per generare PDF.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dossier_classify.py
import io
import zipfile

import openpyxl
from reportlab.pdfgen import canvas

from workspace.miners.dossier_classify import extract_text


def _pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.save()
    return buf.getvalue()


def _docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    doc_xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def _xlsx_bytes(text: str) -> bytes:
    wb = openpyxl.Workbook()
    wb.active["A1"] = text
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_pdf():
    assert "VERBALE DI ASSEMBLEA" in extract_text(
        "x.pdf", _pdf_bytes("VERBALE DI ASSEMBLEA"), "application/pdf")


def test_extract_docx():
    got = extract_text(
        "x.docx", _docx_bytes("destinazione del TFR"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "destinazione del TFR" in got


def test_extract_xlsx():
    got = extract_text(
        "x.xlsx", _xlsx_bytes("Richiesta Antimafia"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "Richiesta Antimafia" in got


def test_extract_plain_and_unknown():
    assert extract_text("x.txt", b"ciao F24", "text/plain") == "ciao F24"
    assert extract_text("x.bin", b"\x00\x01", "application/octet-stream") == ""


def test_extract_corrupt_returns_empty():
    assert extract_text("x.pdf", b"not a pdf", "application/pdf") == ""
```

- [ ] **Step 2: Run to verify FAIL** (`ModuleNotFoundError`)

Run: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/test_dossier_classify.py -v`

- [ ] **Step 3: Implementation**

```python
# workspace/miners/dossier_classify.py
"""Classificazione content-only per il dossier societario.

Mandato: MAI decidere sul nome file — sempre sul contenuto.
"""

from __future__ import annotations

import io
import re
import zipfile

MAX_TEXT_CHARS = 200_000


def extract_text(filename: str, data: bytes, mime_type: str) -> str:
    """Estrae testo da pdf/docx/xlsx/text. Su errore o tipo ignoto: stringa vuota."""
    try:
        if mime_type == "application/pdf":
            return _pdf_text(data)
        if mime_type.endswith("wordprocessingml.document"):
            return _docx_text(data)
        if mime_type.endswith("spreadsheetml.sheet"):
            return _xlsx_text(data)
        if mime_type.startswith("text/"):
            return data.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
    except Exception:
        return ""
    return ""


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:20]:
            out.append(page.extract_text() or "")
            if sum(len(t) for t in out) > MAX_TEXT_CHARS:
                break
    return "\n".join(out)[:MAX_TEXT_CHARS]


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    return re.sub(r"<[^>]+>", " ", xml)[:MAX_TEXT_CHARS]


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=200, values_only=True):
            out.extend(str(c) for c in row if isinstance(c, str))
        if sum(len(t) for t in out) > MAX_TEXT_CHARS:
            break
    return "\n".join(out)[:MAX_TEXT_CHARS]
```

- [ ] **Step 4: Run tests** — Expected: 5 PASS
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_classify.py tests/test_dossier_classify.py
git commit -m "feat(dossier): estrazione testo content-only (pdf/docx/xlsx/txt)"
```

---

### Task 4: Classificatore per categoria

**Files:**
- Modify: `workspace/miners/dossier_classify.py` (seconda metà)
- Test: `tests/test_dossier_classify.py` (append)

**Interfaces:**
- Produces: `classify(text: str) -> tuple[str, float]` — ritorna (categoria della TAXONOMY, confidenza 0..1). Testo vuoto o nessun match ⇒ `("_DaRivedere", 0.0)`. Regole = `CATEGORY_RULES: list[tuple[str, list[str]]]` (categoria, regex case-insensitive); confidenza = frazione di pattern della categoria vincente che matchano, con minimo 0.7 se matcha un pattern "forte" (primo della lista).

- [ ] **Step 1: Append failing tests**

```python
from workspace.miners.dossier_classify import classify


def test_classify_f24_fiscale():
    cat, conf = classify("Modello F24 - codice tributo 4001 - scadenza 16.10.26")
    assert cat == "02_Fiscale" and conf >= 0.6


def test_classify_verbale_societario():
    cat, _ = classify("VERBALE DI ASSEMBLEA ORDINARIA dei soci della societa'")
    assert cat == "01_Societario"


def test_classify_gdf_legale():
    cat, _ = classify("Richiesta di esibizione documenti - Guardia di Finanza nucleo")
    assert cat == "07_Legale_Ispezioni"


def test_classify_catasto():
    cat, _ = classify("visura catastale foglio 12 particella 345 subalterno 6")
    assert cat == "05_Immobili_Catasto"


def test_classify_bilancio():
    cat, _ = classify("bilancio di esercizio al 31/12/2025 stato patrimoniale")
    assert cat == "03_Bilanci"


def test_classify_unknown_goes_review():
    assert classify("") == ("_DaRivedere", 0.0)
    assert classify("testo qualunque senza segnali")[0] == "_DaRivedere"
```

- [ ] **Step 2: Run to verify FAIL** (`ImportError: cannot import name 'classify'`)

- [ ] **Step 3: Implementation** (append al modulo)

```python
# Regole per categoria: (categoria, [regex]) — il PRIMO pattern e' quello "forte".
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("07_Legale_Ispezioni", [
        r"guardia di finanza", r"antimafia", r"procura della repubblica",
        r"diffida", r"contenzioso", r"atto di citazione", r"ricorso",
    ]),
    ("05_Immobili_Catasto", [
        r"visura catastale", r"\bparticella\b", r"\bsubalterno\b",
        r"\bfoglio\s+\d+", r"planimetri", r"categoria catastale",
    ]),
    ("02_Fiscale", [
        r"\bF24\b", r"codice tributo", r"agenzia delle entrate",
        r"dichiarazione dei redditi", r"\bIVA\b.*versamento", r"cartella di pagamento",
    ]),
    ("03_Bilanci", [
        r"bilancio (di esercizio|d'esercizio|al \d)", r"stato patrimoniale",
        r"conto economico", r"nota integrativa", r"bilancino",
    ]),
    ("01_Societario", [
        r"verbale di assemblea", r"\bstatuto\b", r"camera di commercio",
        r"visura (ordinaria|storica)", r"consiglio di amministrazione",
        r"nomina (amministratore|del liquidatore)", r"convocazione.*assemblea",
    ]),
    ("04_Banche_Finanza", [
        r"contratto di (conto corrente|mutuo|leasing)", r"piano di ammortamento",
        r"\bfido\b", r"garanzia fideiussoria", r"fideiussione",
    ]),
    ("06_Personale", [
        r"\bTFR\b", r"contratto di (lavoro|assunzione)", r"busta paga",
        r"neoassunt", r"previdenza complementare", r"\bINPS\b",
    ]),
    ("08_Contratti", [
        r"contratto di sviluppo", r"capitolato", r"concessione demaniale",
        r"contratto di (fornitura|appalto|servizio)", r"condizioni generali di contratto",
    ]),
]


def classify(text: str) -> tuple[str, float]:
    """Categoria + confidenza dal solo contenuto. Nessun match -> _DaRivedere."""
    if not text or not text.strip():
        return ("_DaRivedere", 0.0)
    best = ("_DaRivedere", 0.0)
    for category, patterns in CATEGORY_RULES:
        hits = [bool(re.search(p, text, re.IGNORECASE)) for p in patterns]
        if not any(hits):
            continue
        conf = sum(hits) / len(hits)
        if hits[0]:
            conf = max(conf, 0.7)
        if conf > best[1]:
            best = (category, conf)
    return best
```

- [ ] **Step 4: Run ALL classify tests** — Expected: 11 PASS
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_classify.py tests/test_dossier_classify.py
git commit -m "feat(dossier): classificatore content-only per tassonomia CEO"
```

---

### Task 5: Dedup e ledger

**Files:**
- Create: `workspace/miners/dossier_census.py` (parte pura)
- Test: `tests/test_dossier_census.py`

**Interfaces:**
- Produces: `item_key(item: dict) -> str` (`"drive:<fileId>"` se `source=="drive"`, altrimenti `"hash:<sha256>"`); `dedupe_items(items: list[dict]) -> list[dict]` (merge: mantiene il primo, accumula `holders` unione ordinata); `load_ledger(path: Path) -> set[str]` e `append_ledger(path: Path, keys: list[str])` (jsonl, una riga `{"key": ...}` per voce; file/dir creati se mancanti).
- Item census (contratto usato da Task 6-8): dict con chiavi `source` ("drive"|"gmail"), `key`, `name`, `mime_type`, `holders: list[str]`, `owner`, `link`, `modified`, `size`, `category`, `confidence`, e per gmail anche `message_id`, `attachment_sha256`, `thread_subject`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dossier_census.py
from workspace.miners.dossier_census import (
    append_ledger,
    dedupe_items,
    item_key,
    load_ledger,
)


def test_item_key_drive_vs_gmail():
    assert item_key({"source": "drive", "file_id": "abc"}) == "drive:abc"
    assert item_key({"source": "gmail", "attachment_sha256": "ff00"}) == "hash:ff00"


def test_dedupe_merges_holders():
    items = [
        {"source": "drive", "file_id": "abc", "holders": ["a@x.it"], "name": "doc"},
        {"source": "drive", "file_id": "abc", "holders": ["b@x.it"], "name": "doc"},
        {"source": "gmail", "attachment_sha256": "ff00", "holders": ["c@x.it"]},
    ]
    out = dedupe_items(items)
    assert len(out) == 2
    assert out[0]["holders"] == ["a@x.it", "b@x.it"]


def test_ledger_roundtrip(tmp_path):
    p = tmp_path / "sub" / "ledger.jsonl"
    assert load_ledger(p) == set()
    append_ledger(p, ["drive:abc", "hash:ff00"])
    append_ledger(p, ["drive:xyz"])
    assert load_ledger(p) == {"drive:abc", "hash:ff00", "drive:xyz"}
```

- [ ] **Step 2: Run to verify FAIL** (`ModuleNotFoundError`)

- [ ] **Step 3: Implementation**

```python
# workspace/miners/dossier_census.py
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
```

- [ ] **Step 4: Run tests** — Expected: 3 PASS
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_census.py tests/test_dossier_census.py
git commit -m "feat(dossier): dedup per file-id/hash + ledger jsonl"
```

---

### Task 6: Collector Drive e Gmail per utente

**Files:**
- Modify: `workspace/miners/dossier_census.py`
- Test: `tests/test_dossier_census.py` (append: solo query builder)

**Interfaces:**
- Consumes: `workspace.drive.get_drive_reader(subject)`, `workspace.gmail.get_gmail_service/search_messages/get_thread/list_attachments`, `extract_text/classify` da `dossier_classify`, `SKIP_ATTACHMENT_EXTS` da `workspace.config`.
- Produces: `drive_query(phrase: str) -> str`; `gmail_query(terms: list[str]) -> str`; `census_drive_user(user_email: str, phrases: list[str], max_files: int = 500) -> list[dict]`; `census_gmail_user(user_email: str, terms: list[str], max_threads: int = 200) -> list[dict]`; `census_company_folder(company_folder_id: str, reader_subject: str, max_files: int = 500) -> list[dict]` (classifica i file già presenti nella cartella società, saltando sottocartelle tassonomia e `_INDICE_DOSSIER_*`). Entrambi i collector ritornano item nel contratto di Task 5 (classificati; per Drive scaricano il contenuto per la classificazione solo se mime classificabile e size ≤ 15MB; Google Docs nativi esportati come pdf per l'estrazione testo).

- [ ] **Step 1: Append failing tests (query builder, puri)**

```python
from workspace.miners.dossier_census import drive_query, gmail_query


def test_drive_query_escapes_and_wraps():
    q = drive_query('"ORTI SRL"')
    assert q == "fullText contains '\"ORTI SRL\"' and trashed = false"


def test_gmail_query_joins_terms():
    assert gmail_query(["INTUR OR 00553430653"]) == "(INTUR OR 00553430653)"
    assert gmail_query(["a", "b"]) == "(a) OR (b)"
```

- [ ] **Step 2: Run to verify FAIL**

- [ ] **Step 3: Implementation** (append al modulo)

```python
import hashlib
import time

from ..config import SKIP_ATTACHMENT_EXTS
from ..drive import get_drive_reader
from ..gmail import get_gmail_service, get_thread, list_attachments, search_messages
from .dossier_classify import classify, extract_text

MAX_CONTENT_BYTES = 15 * 1024 * 1024
CLASSIFIABLE_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
GOOGLE_EXPORT_AS_PDF = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
}


def drive_query(phrase: str) -> str:
    escaped = phrase.replace("\\", "\\\\").replace("'", "\\'")
    return f"fullText contains '{escaped}' and trashed = false"


def gmail_query(terms: list[str]) -> str:
    return " OR ".join(f"({t})" for t in terms)


def _drive_file_bytes(svc, file_meta: dict) -> bytes | None:
    """Contenuto per la classificazione (None se non classificabile)."""
    mime = file_meta.get("mimeType", "")
    size = int(file_meta.get("size") or 0)
    try:
        if mime in GOOGLE_EXPORT_AS_PDF:
            return svc.files().export(
                fileId=file_meta["id"], mimeType="application/pdf").execute()
        if mime in CLASSIFIABLE_MIMES and 0 < size <= MAX_CONTENT_BYTES:
            return svc.files().get_media(
                fileId=file_meta["id"], supportsAllDrives=True).execute()
    except Exception:
        return None
    return None


def census_drive_user(user_email: str, phrases: list[str], max_files: int = 500) -> list[dict]:
    svc = get_drive_reader(user_email)
    found: dict[str, dict] = {}
    for phrase in phrases:
        token = None
        while len(found) < max_files:
            resp = svc.files().list(
                q=drive_query(phrase), corpora="user", pageToken=token, pageSize=100,
                includeItemsFromAllDrives=True, supportsAllDrives=True,
                fields=("nextPageToken, files(id, name, mimeType, size, owners, "
                        "modifiedTime, webViewLink)"),
            ).execute()
            for f in resp.get("files", []):
                if f["id"] in found:
                    continue
                data = _drive_file_bytes(svc, f)
                mime = "application/pdf" if f["mimeType"] in GOOGLE_EXPORT_AS_PDF else f["mimeType"]
                text = extract_text(f["name"], data, mime) if data else ""
                category, confidence = classify(text)
                owners = [o.get("emailAddress", "") for o in f.get("owners", [])]
                found[f["id"]] = {
                    "source": "drive", "file_id": f["id"], "name": f["name"],
                    "mime_type": f["mimeType"], "size": int(f.get("size") or 0),
                    "owner": owners[0] if owners else "", "holders": [user_email],
                    "link": f.get("webViewLink", ""), "modified": f.get("modifiedTime", ""),
                    "category": category, "confidence": round(confidence, 2),
                }
            token = resp.get("nextPageToken")
            if not token:
                break
    return list(found.values())


def census_gmail_user(user_email: str, terms: list[str], max_threads: int = 200) -> list[dict]:
    svc = get_gmail_service(user_email)
    items: list[dict] = []
    seen_threads: set[str] = set()
    for msg_ref in search_messages(svc, gmail_query(terms), max_results=max_threads * 4):
        tid = msg_ref.get("threadId")
        if not tid or tid in seen_threads:
            continue
        seen_threads.add(tid)
        if len(seen_threads) > max_threads:
            break
        for msg in get_thread(svc, tid):
            for att in list_attachments(svc, msg):
                ext = "." + att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
                if ext in SKIP_ATTACHMENT_EXTS or not att.data:
                    continue
                sha = hashlib.sha256(att.data).hexdigest()
                text = extract_text(att.filename, att.data, att.mime_type)
                category, confidence = classify(text)
                items.append({
                    "source": "gmail", "attachment_sha256": sha, "name": att.filename,
                    "mime_type": att.mime_type, "size": att.size,
                    "owner": msg.sender, "holders": [user_email],
                    "link": f"https://mail.google.com/mail/u/0/#all/{msg.id}",
                    "modified": msg.date, "message_id": msg.id,
                    "thread_id": msg.thread_id, "thread_subject": msg.subject,
                    "category": category, "confidence": round(confidence, 2),
                })
        time.sleep(0.2)
    return items


def census_company_folder(company_folder_id: str, reader_subject: str,
                          max_files: int = 500) -> list[dict]:
    """Classifica i file GIA' presenti nella cartella società (spec: 'stesso giro').

    Stessa forma-item di census_drive_user; esclude le sottocartelle della tassonomia
    e gli indici (_INDICE_*) per l'idempotenza dei run successivi.
    """
    svc = get_drive_reader(reader_subject)
    out: list[dict] = []
    token = None
    while len(out) < max_files:
        resp = svc.files().list(
            q=f"'{company_folder_id}' in parents and trashed = false",
            pageToken=token, pageSize=100, supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields=("nextPageToken, files(id, name, mimeType, size, owners, "
                    "modifiedTime, webViewLink)"),
        ).execute()
        for f in resp.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                continue
            if f["name"].startswith("_INDICE_DOSSIER_"):
                continue
            data = _drive_file_bytes(svc, f)
            mime = "application/pdf" if f["mimeType"] in GOOGLE_EXPORT_AS_PDF else f["mimeType"]
            text = extract_text(f["name"], data, mime) if data else ""
            category, confidence = classify(text)
            owners = [o.get("emailAddress", "") for o in f.get("owners", [])]
            out.append({
                "source": "drive", "file_id": f["id"], "name": f["name"],
                "mime_type": f["mimeType"], "size": int(f.get("size") or 0),
                "owner": owners[0] if owners else "", "holders": [reader_subject],
                "link": f.get("webViewLink", ""), "modified": f.get("modifiedTime", ""),
                "category": category, "confidence": round(confidence, 2),
            })
        token = resp.get("nextPageToken")
        if not token:
            break
    return out
```

- [ ] **Step 4: Run tests** — Expected: query builder PASS, ruff pulito su `workspace/miners/dossier_census.py`.
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_census.py tests/test_dossier_census.py
git commit -m "feat(dossier): collector Drive+Gmail per utente con classificazione"
```

---

### Task 7: Runner census + indice xlsx

**Files:**
- Modify: `workspace/miners/dossier_census.py` (runner)
- Create: `workspace/miners/dossier_index.py`
- Test: `tests/test_dossier_index.py`, `tests/test_dossier_census.py` (append runner con collector iniettati)

**Interfaces:**
- Consumes: Task 1-6.
- Produces:
  - `run_census(company: DossierCompany, users: list[dict], out_dir: Path, drive_collector=census_drive_user, gmail_collector=census_gmail_user, folder_collector=census_company_folder) -> dict` — prima classifica i file già nella cartella società (folder_collector; nel test iniettare `None`/fake), poi per ogni utente non sospeso chiama i collector (utenti sospesi/erroranti → lista `inaccessible`), deduplica, scrive `out_dir/census_<company_id>.jsonl` (un item per riga) e ritorna `{"census_path", "items", "inaccessible", "by_category"}`.
  - In `dossier_index.py`: `GAP_CHECKLIST: list[tuple[str, str]]` (categoria, voce) e `build_index_xlsx(items: list[dict], inaccessible: list[str]) -> bytes` — foglio "Indice" (colonne: Categoria, Confidenza, Nome, Fonte, Owner, Detentori, Modificato, Link) ordinato per categoria, foglio "GapList" con checklist auto-spuntata (`✔` se esiste item della categoria con confidenza ≥ soglia il cui testo-match copre la voce — match semplice: voce presente se la categoria ha ≥1 documento) + righe "Account non accessibile: <email>".
  - `upload_index(company: DossierCompany, xlsx_bytes: bytes) -> str` — carica `_INDICE_DOSSIER_<company_id>_<YYYY-MM-DD>.xlsx` nella cartella società via `get_drive_writer(WRITE_AS)` + `upload_bytes`, ritorna fileId.

- [ ] **Step 1: Failing tests**

```python
# tests/test_dossier_index.py
import io

import openpyxl

from workspace.miners.dossier_index import build_index_xlsx


def _items():
    return [
        {"key": "drive:a", "source": "drive", "name": "verbale.pdf",
         "category": "01_Societario", "confidence": 0.9, "owner": "x@p.it",
         "holders": ["x@p.it"], "link": "http://l", "modified": "2026-01-01",
         "mime_type": "application/pdf", "size": 1},
        {"key": "hash:ff", "source": "gmail", "name": "f24.pdf",
         "category": "02_Fiscale", "confidence": 0.8, "owner": "y@p.it",
         "holders": ["y@p.it", "z@p.it"], "link": "http://m", "modified": "2026-02-02",
         "mime_type": "application/pdf", "size": 2},
    ]


def test_build_index_has_rows_and_gaplist():
    data = build_index_xlsx(_items(), inaccessible=["am@panoramagroup.it"])
    wb = openpyxl.load_workbook(io.BytesIO(data))
    idx = wb["Indice"]
    rows = list(idx.iter_rows(values_only=True))
    assert rows[0][0] == "Categoria"
    assert len(rows) == 3  # header + 2 item
    gap = wb["GapList"]
    gap_text = "\n".join(str(c) for row in gap.iter_rows(values_only=True) for c in row)
    assert "am@panoramagroup.it" in gap_text
    assert "statuto" in gap_text.lower()
```

E in `tests/test_dossier_census.py` (append):

```python
from pathlib import Path

from workspace.dossier_config import COMPANIES
from workspace.miners.dossier_census import run_census


def test_run_census_with_injected_collectors(tmp_path):
    users = [
        {"email": "a@p.it", "suspended": False},
        {"email": "am@p.it", "suspended": True},
    ]

    def fake_drive(email, phrases, max_files=500):
        return [{"source": "drive", "file_id": "f1", "name": "doc.pdf",
                 "mime_type": "application/pdf", "size": 1, "owner": email,
                 "holders": [email], "link": "", "modified": "",
                 "category": "01_Societario", "confidence": 0.9}]

    def fake_gmail(email, terms, max_threads=200):
        return []

    res = run_census(COMPANIES["INTUR"], users, tmp_path,
                     drive_collector=fake_drive, gmail_collector=fake_gmail,
                     folder_collector=lambda folder_id, subject: [])
    assert Path(res["census_path"]).exists()
    assert len(res["items"]) == 1
    assert res["inaccessible"] == ["am@p.it"]
    assert res["by_category"]["01_Societario"] == 1
```

- [ ] **Step 2: Run to verify FAIL**

- [ ] **Step 3: Implementation**

Append a `dossier_census.py`:

```python
from collections import Counter

from ..dossier_config import DossierCompany


def run_census(company: DossierCompany, users: list[dict], out_dir: Path,
               drive_collector=None, gmail_collector=None,
               folder_collector=census_company_folder) -> dict:
    drive_collector = drive_collector or census_drive_user
    gmail_collector = gmail_collector or census_gmail_user
    raw: list[dict] = []
    inaccessible: list[str] = []
    if folder_collector:
        raw.extend(folder_collector(company.drive_folder_id, WRITE_AS))
    for u in users:
        email = u["email"]
        if u.get("suspended"):
            inaccessible.append(email)
            continue
        try:
            raw.extend(drive_collector(email, company.search_phrases))
            raw.extend(gmail_collector(email, company.gmail_terms))
        except Exception as e:  # impersonation negata, ecc.
            print(f"  ! {email}: {type(e).__name__}: {e}")
            inaccessible.append(email)
    items = dedupe_items(raw)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    census_path = out_dir / f"census_{company.company_id}.jsonl"
    with census_path.open("w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    by_category = Counter(it["category"] for it in items)
    return {"census_path": str(census_path), "items": items,
            "inaccessible": inaccessible, "by_category": dict(by_category)}
```

```python
# workspace/miners/dossier_index.py
"""Indice xlsx + gap list del dossier (caricato nella cartella Drive società)."""

from __future__ import annotations

import io
from datetime import date

import openpyxl

from ..dossier_config import DossierCompany, WRITE_AS
from ..drive import get_drive_writer, upload_bytes

GAP_CHECKLIST: list[tuple[str, str]] = [
    ("01_Societario", "Statuto vigente"),
    ("01_Societario", "Visura camerale aggiornata"),
    ("01_Societario", "Libri sociali (verbali assemblee/CdA)"),
    ("02_Fiscale", "Dichiarazioni redditi ultimi 3 anni"),
    ("02_Fiscale", "F24 / cartelle pendenti"),
    ("03_Bilanci", "Bilanci depositati ultimi 5 anni"),
    ("04_Banche_Finanza", "Contratti conto corrente"),
    ("04_Banche_Finanza", "Contratti mutuo/leasing e piani ammortamento"),
    ("04_Banche_Finanza", "Fidi e garanzie/fideiussioni"),
    ("05_Immobili_Catasto", "Visure catastali immobili"),
    ("05_Immobili_Catasto", "Atti di provenienza"),
    ("06_Personale", "Contratti di lavoro in essere"),
    ("07_Legale_Ispezioni", "Contenziosi/ispezioni in corso"),
    ("08_Contratti", "Contratti fornitori strategici"),
    ("08_Contratti", "Concessioni (demaniali/licenze)"),
]

INDEX_COLUMNS = ["Categoria", "Confidenza", "Nome", "Fonte", "Owner",
                 "Detentori", "Modificato", "Link"]


def build_index_xlsx(items: list[dict], inaccessible: list[str]) -> bytes:
    wb = openpyxl.Workbook()
    idx = wb.active
    idx.title = "Indice"
    idx.append(INDEX_COLUMNS)
    for it in sorted(items, key=lambda x: (x["category"], -x["confidence"])):
        idx.append([it["category"], it["confidence"], it["name"], it["source"],
                    it.get("owner", ""), ", ".join(it.get("holders", [])),
                    it.get("modified", ""), it.get("link", "")])
    gap = wb.create_sheet("GapList")
    gap.append(["Categoria", "Documento", "Trovato"])
    have = {it["category"] for it in items}
    for category, voce in GAP_CHECKLIST:
        gap.append([category, voce, "✔" if category in have else "DA CHIEDERE"])
    for email in inaccessible:
        gap.append(["", f"Account non accessibile: {email}", "VERIFICARE"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_index(company: DossierCompany, xlsx_bytes: bytes) -> str:
    svc = get_drive_writer(WRITE_AS)
    name = f"_INDICE_DOSSIER_{company.company_id}_{date.today().isoformat()}.xlsx"
    return upload_bytes(
        svc, company.drive_folder_id, name, xlsx_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
```

- [ ] **Step 4: Run tests** — Expected: nuovi test PASS.
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_census.py workspace/miners/dossier_index.py tests/test_dossier_census.py tests/test_dossier_index.py
git commit -m "feat(dossier): runner census + indice xlsx con gap list"
```

---

### Task 8: Apply — copia nelle cartelle per tassonomia

**Files:**
- Create: `workspace/miners/dossier_apply.py`
- Test: `tests/test_dossier_apply.py`

**Interfaces:**
- Consumes: `load_ledger/append_ledger/item_key` (Task 5), `ensure_subfolder/get_drive_writer/get_drive_reader/upload_bytes` (workspace.drive), `get_gmail_service/get_thread/list_attachments` (workspace.gmail), `TAXONOMY, CONFIDENCE_THRESHOLD, DOSSIER_STATE_DIR, WRITE_AS`.
- Produces:
  - `plan_apply(items: list[dict], ledger_keys: set[str], threshold: float) -> list[dict]` (puro): filtra già-applicati; sotto soglia → `target_category="_DaRivedere"`, altrimenti la categoria propria.
  - `apply_census(company: DossierCompany, census_path: Path, dry_run: bool = False) -> dict`: crea le 9 sottocartelle (`ensure_subfolder`), per ogni item del piano scarica i bytes (drive: `get_media`/`export` PDF impersonando `holders[0]`; gmail: rifetch allegato via `get_thread` su `holders[0]` + match sha256) e li carica con `upload_bytes` nella sottocartella target; appende al ledger `DOSSIER_STATE_DIR/applied_<company_id>.jsonl`; ritorna `{"applied": n, "skipped": n, "failed": [...]}`. In dry_run stampa il piano e non scrive nulla.

- [ ] **Step 1: Failing test (parte pura)**

```python
# tests/test_dossier_apply.py
from workspace.miners.dossier_apply import plan_apply


def test_plan_apply_filters_ledger_and_applies_threshold():
    items = [
        {"key": "drive:a", "category": "01_Societario", "confidence": 0.9},
        {"key": "drive:b", "category": "02_Fiscale", "confidence": 0.3},
        {"key": "drive:c", "category": "03_Bilanci", "confidence": 0.8},
    ]
    plan = plan_apply(items, ledger_keys={"drive:c"}, threshold=0.6)
    assert [p["key"] for p in plan] == ["drive:a", "drive:b"]
    assert plan[0]["target_category"] == "01_Societario"
    assert plan[1]["target_category"] == "_DaRivedere"
```

- [ ] **Step 2: Run to verify FAIL**

- [ ] **Step 3: Implementation**

```python
# workspace/miners/dossier_apply.py
"""Fase apply del dossier: copia i documenti censiti nelle cartelle Drive.

Idempotente via ledger; mai move/delete degli originali, solo copie.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..dossier_config import (
    CONFIDENCE_THRESHOLD,
    DOSSIER_STATE_DIR,
    DossierCompany,
    TAXONOMY,
    WRITE_AS,
)
from ..drive import ensure_subfolder, get_drive_reader, get_drive_writer, upload_bytes
from ..gmail import get_gmail_service, get_thread, list_attachments
from .dossier_census import GOOGLE_EXPORT_AS_PDF


def plan_apply(items: list[dict], ledger_keys: set[str], threshold: float) -> list[dict]:
    plan = []
    for it in items:
        if it["key"] in ledger_keys:
            continue
        it = dict(it)
        it["target_category"] = (
            it["category"] if it.get("confidence", 0) >= threshold else "_DaRivedere"
        )
        plan.append(it)
    return plan


def _fetch_bytes(item: dict) -> bytes | None:
    holder = item["holders"][0]
    if item["source"] == "drive":
        svc = get_drive_reader(holder)
        if item["mime_type"] in GOOGLE_EXPORT_AS_PDF:
            return svc.files().export(
                fileId=item["file_id"], mimeType="application/pdf").execute()
        return svc.files().get_media(
            fileId=item["file_id"], supportsAllDrives=True).execute()
    svc = get_gmail_service(holder)
    # rifetch: trova nel thread l'allegato con lo stesso sha256
    for msg in get_thread(svc, item["thread_id"]):
        for att in list_attachments(svc, msg):
            if att.data and hashlib.sha256(att.data).hexdigest() == item["attachment_sha256"]:
                return att.data
    return None


def apply_census(company: DossierCompany, census_path: Path, dry_run: bool = False) -> dict:
    from .dossier_census import append_ledger, load_ledger

    items = [json.loads(line) for line in Path(census_path).read_text().splitlines() if line.strip()]
    ledger_path = DOSSIER_STATE_DIR / f"applied_{company.company_id}.jsonl"
    plan = plan_apply(items, load_ledger(ledger_path), CONFIDENCE_THRESHOLD)
    if dry_run:
        for p in plan:
            print(f"  [{p['target_category']}] {p['name']}  ({p['key']})")
        return {"applied": 0, "skipped": len(items) - len(plan), "failed": [], "planned": len(plan)}

    writer = get_drive_writer(WRITE_AS)
    folder_ids = {cat: ensure_subfolder(writer, company.drive_folder_id, cat)
                  for cat in TAXONOMY}
    applied, failed = [], []
    for p in plan:
        try:
            data = _fetch_bytes(p)
            if data is None:
                raise RuntimeError("contenuto non recuperabile")
            name = p["name"]
            if p["mime_type"] in GOOGLE_EXPORT_AS_PDF and not name.lower().endswith(".pdf"):
                name += ".pdf"
            mime = "application/pdf" if p["mime_type"] in GOOGLE_EXPORT_AS_PDF else p["mime_type"]
            upload_bytes(writer, folder_ids[p["target_category"]], name, data, mime)
            applied.append(p["key"])
        except Exception as e:
            failed.append({"key": p["key"], "name": p.get("name"), "error": str(e)})
    if applied:
        append_ledger(ledger_path, applied)
    return {"applied": len(applied), "skipped": len(items) - len(plan),
            "failed": failed, "planned": len(plan)}
```

- [ ] **Step 4: Run tests** — Expected: PASS. Poi suite completa: `~/.virtualenvs/hotelops_core/bin/python -m pytest tests/ -x -q` (baseline verde, nessuna regressione).
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_apply.py tests/test_dossier_apply.py
git commit -m "feat(dossier): apply idempotente con copia per tassonomia"
```

---

### Task 9: CLI `hotelops workspace mine-dossier`

**Files:**
- Modify: `workspace/cli_commands.py`
- Modify: `cli.py` (registrazione argomenti, vicino a riga 1317-1320)
- Test: manuale (step 4)

**Interfaces:**
- Consumes: tutto sopra.
- Produces: `hotelops workspace mine-dossier --company ORTI|INTUR [--census] [--apply] [--dry-run] [--users a@,b@] [--max-files N] [--out DIR]`. `--census` esegue census+indice (default se nessuna azione); `--apply` esegue apply dal census file più recente in `--out` (default `DOSSIER_STATE_DIR`); `--users` limita agli utenti indicati (per prove); `--dry-run` con `--apply` stampa solo il piano.

- [ ] **Step 1: Implementazione dispatch** — in `workspace/cli_commands.py`:

```python
def _mine_dossier(args):
    from pathlib import Path

    from .directory import enumerate_domain_users
    from .dossier_config import COMPANIES, DIRECTORY_SUBJECT, DOSSIER_STATE_DIR
    from .miners.dossier_apply import apply_census
    from .miners.dossier_census import run_census
    from .miners.dossier_index import build_index_xlsx, upload_index

    company = COMPANIES[args.company.upper()]
    out_dir = Path(args.out) if args.out else DOSSIER_STATE_DIR
    census_path = out_dir / f"census_{company.company_id}.jsonl"

    if args.apply:
        result = apply_census(company, census_path, dry_run=args.dry_run)
        print(f"\n  applied={result['applied']} planned={result.get('planned')} "
              f"skipped={result['skipped']} failed={len(result['failed'])}")
        for f in result["failed"]:
            print(f"  FAIL {f['name']}: {f['error']}")
        return

    if args.users:
        users = [{"email": u.strip(), "suspended": False}
                 for u in args.users.split(",") if u.strip()]
    else:
        users = enumerate_domain_users(DIRECTORY_SUBJECT)
    print(f"  Census {company.company_id} su {len(users)} utenti…")
    res = run_census(company, users, out_dir)
    print(f"  {len(res['items'])} documenti unici → {res['census_path']}")
    for cat, n in sorted(res["by_category"].items()):
        print(f"    {cat:<22s} {n}")
    if res["inaccessible"]:
        print(f"  Non accessibili: {', '.join(res['inaccessible'])}")
    xlsx = build_index_xlsx(res["items"], res["inaccessible"])
    file_id = upload_index(company, xlsx)
    print(f"  Indice caricato: https://drive.google.com/file/d/{file_id}/view")
```

e nel dispatcher `cmd_workspace` aggiungi il ramo:

```python
    elif args.workspace_action == "mine-dossier":
        _mine_dossier(args)
```

In `cli.py`, dopo il subparser `mine-capex` esistente (cerca `ws_sub` intorno alla riga 1320):

```python
    p_dossier = ws_sub.add_parser("mine-dossier", help="Census/apply dossier societario ORTI/INTUR")
    p_dossier.add_argument("--company", required=True, choices=["ORTI", "INTUR", "orti", "intur"])
    p_dossier.add_argument("--census", action="store_true", help="fase census (default)")
    p_dossier.add_argument("--apply", action="store_true", help="fase apply dal census esistente")
    p_dossier.add_argument("--dry-run", action="store_true")
    p_dossier.add_argument("--users", default="", help="lista email per limitare il census")
    p_dossier.add_argument("--out", default="", help="dir output census (default ~/.config/hotelops/dossier)")
```

- [ ] **Step 2: Ruff + suite**

Run: `~/.virtualenvs/hotelops_core/bin/python -m ruff check workspace/ cli.py && ~/.virtualenvs/hotelops_core/bin/python -m pytest tests/ -q`
Expected: pulito, suite verde.

- [ ] **Step 3: Commit**

```bash
git add workspace/cli_commands.py cli.py
git commit -m "feat(dossier): CLI workspace mine-dossier (census/apply)"
```

- [ ] **Step 4: Verifica live limitata (read-only)**

```bash
~/.virtualenvs/hotelops_core/bin/python cli.py workspace mine-dossier --company INTUR --census --users stefano@panoramagroup.it
```
Expected: census jsonl scritto, conteggi per categoria stampati, indice xlsx caricato nella cartella INTUR (verificare il link stampato). Questo è il primo test end-to-end reale — su UN solo utente.

---

### Task 10: Documenti ufficiali (openapi-ita)

**Files:**
- Create: `workspace/miners/dossier_official.py`
- Modify: `workspace/cli_commands.py`, `cli.py`
- Test: `tests/test_dossier_official.py` (parte pura)

**Interfaces:**
- Consumes: `openapi_ita` (`CompanyAPI().advanced/shareholders`, `VisureAPI().submit/status/download/is_ready` — endpoint es. `"storica-societa-capitale"`, `"bilancio-ottico"`), `upload_bytes/ensure_subfolder/get_drive_writer`.
- Produces:
  - `ORDER_CATALOG: dict[str, dict]` — chiavi `visura` (endpoint `storica-societa-capitale`, costo 4.95, categoria `01_Societario`), `bilancio` (endpoint `bilancio-ottico`, costo 2.95, categoria `03_Bilanci`), `soci` (endpoint `soci-attivi`, costo 2.30, categoria `01_Societario`).
  - `order_summary(orders: list[str]) -> tuple[list[dict], float]` (puro): valida le chiavi e ritorna (lista ordini, costo totale).
  - `fetch_profile(company: DossierCompany) -> dict` — `CompanyAPI().advanced(tax_code)`, salva json in `DOSSIER_STATE_DIR/profile_<id>.json` (€0.10, gratuito nei 30/mese).
  - `place_orders(company: DossierCompany, orders: list[str], poll_minutes: int = 20) -> list[dict]` — submit, polling `status` ogni 60s fino a `is_ready` o timeout, `download` → upload dei PDF nella sottocartella categoria della cartella società.
  - CLI: `hotelops workspace dossier-official --company X [--profile] [--order visura,bilancio,soci] --yes` — senza `--yes` stampa il riepilogo costi e esce senza ordinare.

- [ ] **Step 1: Failing test**

```python
# tests/test_dossier_official.py
import pytest

from workspace.miners.dossier_official import order_summary


def test_order_summary_costs():
    orders, total = order_summary(["visura", "soci"])
    assert [o["order_id"] for o in orders] == ["visura", "soci"]
    assert total == pytest.approx(4.95 + 2.30)


def test_order_summary_rejects_unknown():
    with pytest.raises(KeyError):
        order_summary(["visura", "ubo"])
```

- [ ] **Step 2: Run to verify FAIL**

- [ ] **Step 3: Implementation**

```python
# workspace/miners/dossier_official.py
"""Documenti ufficiali via openapi-ita. OGNI ordine a pagamento e' esplicito."""

from __future__ import annotations

import json
import time

from ..dossier_config import DOSSIER_STATE_DIR, DossierCompany, WRITE_AS
from ..drive import ensure_subfolder, get_drive_writer, upload_bytes

ORDER_CATALOG: dict[str, dict] = {
    "visura": {"endpoint": "storica-societa-capitale", "cost": 4.95,
               "category": "01_Societario", "label": "Visura storica"},
    "bilancio": {"endpoint": "bilancio-ottico", "cost": 2.95,
                 "category": "03_Bilanci", "label": "Bilancio ottico (ultimo)"},
    "soci": {"endpoint": "soci-attivi", "cost": 2.30,
             "category": "01_Societario", "label": "Elenco soci attivi"},
}


def order_summary(orders: list[str]) -> tuple[list[dict], float]:
    out = []
    for oid in orders:
        entry = dict(ORDER_CATALOG[oid])  # KeyError se sconosciuto
        entry["order_id"] = oid
        out.append(entry)
    return out, round(sum(e["cost"] for e in out), 2)


def fetch_profile(company: DossierCompany) -> dict:
    from openapi_ita import CompanyAPI

    data = CompanyAPI().advanced(company.tax_code)
    DOSSIER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = DOSSIER_STATE_DIR / f"profile_{company.company_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  Profilo salvato: {path}")
    return data


def place_orders(company: DossierCompany, orders: list[str], poll_minutes: int = 20) -> list[dict]:
    from openapi_ita import VisureAPI

    api = VisureAPI()
    writer = get_drive_writer(WRITE_AS)
    results = []
    plan, _ = order_summary(orders)
    for entry in plan:
        req = api.submit(entry["endpoint"], cf_piva_id=company.tax_code)
        req_id = req.get("data", {}).get("id") or req.get("id")
        print(f"  {entry['label']}: richiesta {req_id}, polling…")
        deadline = time.time() + poll_minutes * 60
        while time.time() < deadline:
            st = api.status(entry["endpoint"], req_id)
            if api.is_ready(st):
                break
            time.sleep(60)
        else:
            results.append({"order": entry["order_id"], "status": "timeout", "request_id": req_id})
            continue
        files = api.download(entry["endpoint"], req_id)  # [(filename, bytes), ...]
        folder = ensure_subfolder(writer, company.drive_folder_id, entry["category"])
        for fname, data in files:
            upload_bytes(writer, folder, fname, data, "application/pdf")
        results.append({"order": entry["order_id"], "status": "ok",
                        "files": [f for f, _ in files]})
    return results
```

NOTA per l'implementatore: prima di scrivere `place_orders`, leggi le firme reali in
`/Users/stefanodellapietra/dev/Projects/openapi_ita/src/openapi_ita/visure.py`
(`submit(endpoint, **body)`, `status(endpoint, request_id)`, `download(endpoint, request_id)`,
`is_ready(status_data)`) e adegua nomi dei campi body (`cf_piva_id`) e formato di ritorno di
`download` a quello effettivo del modulo — il blocco sopra assume il contratto documentato lì.

CLI (in `cli.py`, sotto il parser `mine-dossier`):

```python
    p_off = ws_sub.add_parser("dossier-official", help="Documenti ufficiali via openapi-ita (costi vivi)")
    p_off.add_argument("--company", required=True, choices=["ORTI", "INTUR", "orti", "intur"])
    p_off.add_argument("--profile", action="store_true", help="scarica profilo advanced (€0.10)")
    p_off.add_argument("--order", default="", help="comma list: visura,bilancio,soci")
    p_off.add_argument("--yes", action="store_true", help="conferma la spesa")
```

e in `cli_commands.py`:

```python
def _dossier_official(args):
    from .dossier_config import COMPANIES
    from .miners.dossier_official import fetch_profile, order_summary, place_orders

    company = COMPANIES[args.company.upper()]
    if args.profile:
        fetch_profile(company)
    if args.order:
        orders = [o.strip() for o in args.order.split(",") if o.strip()]
        plan, total = order_summary(orders)
        for e in plan:
            print(f"  {e['label']:<28s} €{e['cost']:.2f}")
        print(f"  TOTALE €{total:.2f}")
        if not args.yes:
            print("  Nessun ordine inviato (aggiungi --yes per confermare).")
            return
        for r in place_orders(company, orders):
            print(f"  {r['order']}: {r['status']}")
```

più il ramo `elif args.workspace_action == "dossier-official": _dossier_official(args)`.

- [ ] **Step 4: Run tests + ruff + suite completa** — Expected: verde.
- [ ] **Step 5: Commit**

```bash
git add workspace/miners/dossier_official.py workspace/cli_commands.py cli.py tests/test_dossier_official.py
git commit -m "feat(dossier): documenti ufficiali openapi-ita con conferma costi"
```

---

### Task 11: E2E reale + chiusura fronte

**Files:**
- Modify: hub vault `workstreams/DOSSIER_SOCIETARIO.md` + `STATUS.md` (fuori worktree, repo main checkout)

- [ ] **Step 1: Census completo INTUR** (read-only, tutti gli utenti)

```bash
~/.virtualenvs/hotelops_core/bin/python cli.py workspace mine-dossier --company INTUR --census
```
Expected: 11 utenti attivi processati, `am@` in inaccessible, indice xlsx nella cartella INTUR.

- [ ] **Step 2: Census completo ORTI** (idem, `--company ORTI`)

- [ ] **Step 3: Review indici con Stefano** — STOP: presentare i due indici e i conteggi; Stefano rivede la classificazione su Drive prima dell'apply.

- [ ] **Step 4: Apply dopo approvazione**

```bash
~/.virtualenvs/hotelops_core/bin/python cli.py workspace mine-dossier --company INTUR --apply --dry-run   # piano
~/.virtualenvs/hotelops_core/bin/python cli.py workspace mine-dossier --company INTUR --apply            # esegue
# idem ORTI
```
Expected: cartelle popolate; secondo run `--apply` → `applied=0` (idempotenza dimostrata = DoD).

- [ ] **Step 5: Push branch + PR**

```bash
git push -u origin feat/dossier-societario
gh pr create --title "Dossier societario ORTI/INTUR: miner Workspace + documenti ufficiali" --body "Spec: docs/superpowers/specs/2026-07-08-dossier-societario-design.md ..."
```

- [ ] **Step 6: Aggiorna hub + STATUS** (blocco curato "Dove sono", checkbox DoD) — mai merge autonomo su main.
