# Tesoreria App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streamlit app that parses Rosa's PF Excel, crosses it with Esolver consuntivo + budget from BQ, projects cashflow forward, and exports a clean Excel.

**Architecture:** Single Streamlit app (`condges/tesoreria.py`) with a pure-logic parser module (`condges/parse_pf.py`) that's independently testable. BQ is read-only — no writes. No persistent state.

**Tech Stack:** Streamlit, pandas, openpyxl, google-cloud-bigquery, plotly

---

### Task 1: PF Excel Parser

**Files:**
- Create: `condges/parse_pf.py`
- Test: `tests/test_parse_pf.py`

The parser must handle two different formats (ORTI and INTUR have different voce labels, column layouts, and year spans).

- [ ] **Step 1: Create test fixtures**

Create a minimal test Excel file programmatically for ORTI format:

```python
# tests/test_parse_pf.py
import pytest
from openpyxl import Workbook
from io import BytesIO

def make_orti_pf() -> BytesIO:
    """Create minimal ORTI PF Excel matching Rosa's format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Piano Finanziario"
    # Row 1: header
    ws["B1"] = "ULTIMO SALDO"
    ws["C1"] = 2026
    # Row 2: societa + date + month headers
    ws["A2"] = "ORTI"
    from datetime import datetime
    ws["B2"] = datetime(2026, 2, 28)
    months = ["GENNAIO","FEBBRAIO","MARZO","APRILE","MAGGIO","GIUGNO",
              "LUGLIO","AGOSTO","SETTEMBRE","OTTOBRE","NOVEMBRE","DICEMBRE"]
    for i, m in enumerate(months):
        ws.cell(2, 3 + i, m)
    # Row 3: saldo mese precedente
    ws["A3"] = "SALDO MESE PRECED"
    ws.cell(3, 3, 134646.79)  # Gen
    ws.cell(3, 4, -108126.59)  # Feb
    # Entrate (rows 5-10)
    ws["A5"] = "Entrate Hotel"
    ws.cell(5, 9, 700000)  # Lug
    ws["A6"] = "Entrate Residence"
    ws.cell(6, 9, 120000)
    ws["A7"] = "Entrate CVM"
    ws["A8"] = "Entrate Supermercato"
    ws.cell(8, 5, 25620)  # Mar
    ws["A9"] = "Rientro Sospesi"
    ws["A10"] = "Caparre Intur"
    # Row 11: totale entrate
    ws["A11"] = "TOTALE ENTRATE"
    # Separator row 13
    ws["A13"] = "===="
    # Uscite (rows 14-25)
    ws["A14"] = "Salari e Stipendi"
    ws.cell(14, 5, 18142.04)  # Mar
    ws["A15"] = "Utenze"
    ws.cell(15, 5, 14670.52)
    ws["A16"] = "Materie Prime/Consumo"
    ws["A17"] = "Tasse e Imposte"
    ws["A18"] = "Commissioni Portali"
    ws["A19"] = "Mutui e Finaziamenti"  # typo in original
    ws.cell(19, 5, 13662.11)
    ws["A20"] = "Consulenze"
    ws["A21"] = "Godimento Beni di Terzi"
    ws["A22"] = "Varie ed Eventuali"
    ws["A23"] = "Canoni e servizi"
    ws["A24"] = "Deposito Fitto"
    # Row 27: totale uscite
    ws["A27"] = "TOTALE USCITE "
    # Saldi banca (rows 32-33)
    ws["A32"] = "Saldo MPS"
    ws["B32"] = 67724.67
    ws["A33"] = "Saldo Intesa"
    ws["B33"] = 66922.12
    # Row 35: totale banche
    ws["A35"] = "TOTALE BANCHE "
    ws["B35"] = 134646.79

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
```

- [ ] **Step 2: Write failing tests for parse_pf_excel**

```python
# tests/test_parse_pf.py (continued)
from condges.parse_pf import parse_pf_excel, PFData

def test_parse_orti_detects_societa():
    data = parse_pf_excel(make_orti_pf())
    assert data.societa == "ORTI"

def test_parse_orti_reads_saldi_banca():
    data = parse_pf_excel(make_orti_pf())
    assert data.saldi_banca["MPS"] == pytest.approx(67724.67)
    assert data.saldi_banca["Intesa"] == pytest.approx(66922.12)
    assert data.saldo_totale == pytest.approx(134646.79)

def test_parse_orti_reads_voci():
    data = parse_pf_excel(make_orti_pf())
    # Check a voce exists with correct mapping
    hotel = data.voci["ENTRATE_HOTEL"]
    assert hotel.importi[7] == 700000  # Luglio
    salari = data.voci["USCITE_SALARI"]
    assert salari.importi[3] == pytest.approx(18142.04)  # Marzo

def test_parse_orti_reads_data_saldo():
    data = parse_pf_excel(make_orti_pf())
    from datetime import date
    assert data.data_saldo == date(2026, 2, 28)

def test_parse_orti_anno():
    data = parse_pf_excel(make_orti_pf())
    assert data.anno == 2026

def test_unknown_voce_logged_as_warning():
    """Voci not matching any known label are collected in warnings."""
    buf = make_orti_pf()
    # Re-open and add an unknown voce
    from openpyxl import load_workbook
    wb = load_workbook(buf)
    ws = wb["Piano Finanziario"]
    ws["A25"] = "Voce Sconosciuta"
    ws.cell(25, 5, 9999)
    buf2 = BytesIO()
    wb.save(buf2)
    buf2.seek(0)
    data = parse_pf_excel(buf2)
    assert any("Voce Sconosciuta" in w for w in data.warnings)

def test_parse_mutui_typo_matches():
    """'Mutui e Finaziamenti' (Rosa's typo) maps to USCITE_MUTUI."""
    data = parse_pf_excel(make_orti_pf())
    mutui = data.voci["USCITE_MUTUI"]
    assert mutui.importi[3] == pytest.approx(13662.11)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_parse_pf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'condges.parse_pf'`

- [ ] **Step 4: Implement parse_pf.py**

```python
# condges/parse_pf.py
"""Parser for Rosa's Piano Finanziario Excel files."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

from openpyxl import load_workbook

# ── Label → voce_id mapping ────────────────────────────────────────────────
# Rosa's Excel labels (with known typos) → BQ voce_id.
# Normalized: stripped, lowercased.
LABEL_TO_VOCE: dict[str, str] = {
    # ORTI entrate
    "entrate hotel": "ENTRATE_HOTEL",
    "entrate residence": "ENTRATE_RESIDENCE",
    "entrate cvm": "ENTRATE_CVM",
    "entrate supermercato": "ENTRATE_SUPERMERCATO",
    "rientro sospesi": "ENTRATE_RIENTRO_SOSPESI",
    "caparre intur": "ENTRATE_CAPARRE",
    # INTUR entrate
    "fitto hotel": "ENTRATE_AFFITTI_INTUR",
    "fitto ar": "ENTRATE_AFFITTI_INTUR",  # same voce, sub-line
    "ribaltamento costi a orti": "ENTRATE_RIENTRO_SOSPESI",
    "entrate farmacia": "ENTRATE_AFFITTI_MINORI",
    "entrate spiaggia": "ENTRATE_SPIAGGIA",
    # Uscite (shared)
    "salari e stipendi": "USCITE_SALARI",
    "utenze": "USCITE_UTENZE",
    "materie prime/consumo": "USCITE_MATERIE_PRIME",
    "tasse e imposte": "USCITE_TASSE",
    "commissioni portali": "USCITE_COMMISSIONI",
    "mutui e finaziamenti": "USCITE_MUTUI",  # Rosa's typo
    "mutui e finanziamenti": "USCITE_MUTUI",
    "consulenze": "USCITE_CONSULENZE",
    "godimento beni di terzi": "USCITE_GODIMENTO_BENI",
    "godimento benidi terzi": "USCITE_GODIMENTO_BENI",  # INTUR typo
    "varie ed eventuali": "USCITE_VARIE",
    "canoni e servizi": "USCITE_CANONI",
    "deposito fitto": "USCITE_DEPOSITO_FITTO",
    "caparre da girocantare aorti": "ENTRATE_CAPARRE_INTUR",
}

SKIP_LABELS = {
    "totale entrate", "totale uscite", "totale uscite ",
    "====", "======", "saldo mese preced", "saldo mese preced.",
    "cash flow", "totale banche", "totale banche ",
    "saldo di periodo/proiettato", "saldo di periodo/proiettato ",
    "cassa contanti", "totale affidamenti", "totale affidamenti  ",
    "cash flow con affid.", "fin. mps 60 mesi", "fin. mps 60 mesi ",
}


@dataclass
class VoceRow:
    """One PF voce with 12 monthly amounts."""
    voce_id: str
    excel_label: str
    importi: dict[int, float] = field(default_factory=dict)  # {1..12: amount}


@dataclass
class PFData:
    """Parsed Piano Finanziario."""
    societa: str
    anno: int
    data_saldo: date | None
    saldi_banca: dict[str, float]  # {banca_label: saldo}
    saldo_totale: float
    voci: dict[str, VoceRow]  # {voce_id: VoceRow}
    warnings: list[str] = field(default_factory=list)


def _normalize(label: str) -> str:
    return label.strip().lower()


def _detect_month_columns(ws) -> dict[int, int]:
    """Find which columns correspond to which months (1-12).
    Returns {col_number: mese_number}."""
    month_names = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    }
    col_to_mese = {}
    # Scan row 2 for month headers
    for col in range(1, ws.max_column + 1):
        val = ws.cell(2, col).value
        if isinstance(val, str):
            key = val.strip().lower()
            if key in month_names:
                col_to_mese[col] = month_names[key]
    return col_to_mese


def _detect_anno(ws) -> int:
    """Detect anno from header row."""
    for col in range(1, ws.max_column + 1):
        val = ws.cell(1, col).value
        if isinstance(val, (int, float)) and 2020 <= val <= 2030:
            return int(val)
    # Fallback: check row 2
    for col in range(1, ws.max_column + 1):
        val = ws.cell(2, col).value
        if isinstance(val, (int, float)) and 2020 <= val <= 2030:
            return int(val)
    return date.today().year


def _detect_societa(ws) -> str:
    """Detect societa from cells A1 or A2."""
    for row in (1, 2):
        val = ws.cell(row, 1).value
        if isinstance(val, str):
            upper = val.strip().upper()
            if "ORTI" in upper:
                return "ORTI"
            if "INTUR" in upper:
                return "INTUR"
    return "ORTI"  # default


def _read_saldi_banca(ws) -> dict[str, float]:
    """Read saldi banca from rows 30-40 (col A=label, col B=amount)."""
    saldi = {}
    for row in range(30, min(45, ws.max_row + 1)):
        label = ws.cell(row, 1).value
        amount = ws.cell(row, 2).value
        if (
            isinstance(label, str)
            and "saldo" in label.lower()
            and "periodo" not in label.lower()
            and "mese" not in label.lower()
            and isinstance(amount, (int, float))
        ):
            # Extract banca name: "Saldo MPS" -> "MPS"
            banca = label.replace("Saldo", "").replace("saldo", "").strip()
            if banca:
                saldi[banca] = float(amount)
    return saldi


def _read_data_saldo(ws) -> date | None:
    """Read data saldo from cell B2 or C3 (the date reference)."""
    for cell in ("B2", "C3"):
        val = ws[cell].value
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
    return None


def parse_pf_excel(file: BytesIO | str) -> PFData:
    """Parse Rosa's PF Excel into structured data.

    Args:
        file: path or BytesIO of the Excel file.

    Returns:
        PFData with societa, anno, saldi, and 28 voci × 12 months.
    """
    wb = load_workbook(file, data_only=True)
    ws = wb["Piano Finanziario"]

    societa = _detect_societa(ws)
    anno = _detect_anno(ws)
    data_saldo = _read_data_saldo(ws)
    col_to_mese = _detect_month_columns(ws)
    saldi_banca = _read_saldi_banca(ws)
    saldo_totale = sum(saldi_banca.values())

    voci: dict[str, VoceRow] = {}
    warnings: list[str] = []

    # Scan data rows (5 to ~30) for voce labels + amounts
    for row in range(3, min(50, ws.max_row + 1)):
        label_raw = ws.cell(row, 1).value
        if not isinstance(label_raw, str) or not label_raw.strip():
            continue

        label = label_raw.strip()
        norm = _normalize(label)

        # Skip known non-voce rows
        if norm in SKIP_LABELS or norm.startswith("="):
            continue

        voce_id = LABEL_TO_VOCE.get(norm)
        if voce_id is None:
            # Try partial match
            for key, vid in LABEL_TO_VOCE.items():
                if key in norm or norm in key:
                    voce_id = vid
                    break

        if voce_id is None:
            warnings.append(f"Voce non mappata: '{label}' (riga {row})")
            continue

        # Read monthly amounts
        importi: dict[int, float] = {}
        for col, mese in col_to_mese.items():
            val = ws.cell(row, col).value
            if isinstance(val, (int, float)) and val != 0:
                importi[mese] = float(val)

        # If voce_id already exists (e.g. Fitto Hotel + Fitto AR both map to
        # ENTRATE_AFFITTI_INTUR), sum the amounts
        if voce_id in voci:
            existing = voci[voce_id]
            for m, v in importi.items():
                existing.importi[m] = existing.importi.get(m, 0) + v
        else:
            voci[voce_id] = VoceRow(
                voce_id=voce_id,
                excel_label=label,
                importi=importi,
            )

    return PFData(
        societa=societa,
        anno=anno,
        data_saldo=data_saldo,
        saldi_banca=saldi_banca,
        saldo_totale=saldo_totale,
        voci=voci,
        warnings=warnings,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_parse_pf.py -v`
Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add condges/parse_pf.py tests/test_parse_pf.py
git commit -m "feat: add PF Excel parser with voce mapping"
```

---

### Task 2: Scadenzario Fornitori Parser

**Files:**
- Modify: `condges/parse_pf.py` (add `parse_scadenzario`)
- Test: `tests/test_parse_pf.py` (add tests)

- [ ] **Step 1: Write failing test**

```python
# tests/test_parse_pf.py (add)
from condges.parse_pf import parse_scadenzario, ScadenzarioData

def make_scadenzario() -> BytesIO:
    """Minimal scadenzario: 3 suppliers with monthly buckets."""
    wb = Workbook()
    ws = wb.active
    # Header row: columns vary by file, parser reads dynamically
    ws["A1"] = "Fornitore"
    ws["B1"] = "Totale"
    ws["C1"] = "Scaduto"
    ws["D1"] = "apr-26"
    ws["E1"] = "mag-26"
    ws["F1"] = "giu-26"
    ws["G1"] = "Oltre"
    # Data
    ws["A2"] = "Fornitore Uno"
    ws["B2"] = 50000
    ws["C2"] = 5000
    ws["D2"] = 15000
    ws["E2"] = 20000
    ws["F2"] = 10000
    ws["G2"] = 0
    ws["A3"] = "Fornitore Due"
    ws["B3"] = 30000
    ws["C3"] = 0
    ws["D3"] = 10000
    ws["E3"] = 10000
    ws["F3"] = 10000
    ws["G3"] = 0
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

def test_parse_scadenzario_totals():
    data = parse_scadenzario(make_scadenzario())
    assert data.totale_per_mese[4] == 25000  # apr: 15k + 10k
    assert data.totale_per_mese[5] == 30000  # mag: 20k + 10k

def test_parse_scadenzario_suppliers():
    data = parse_scadenzario(make_scadenzario())
    assert len(data.fornitori) == 2
    assert data.fornitori[0]["fornitore"] == "Fornitore Uno"

def test_parse_scadenzario_scaduto():
    data = parse_scadenzario(make_scadenzario())
    assert data.scaduto_totale == 5000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parse_pf.py::test_parse_scadenzario_totals -v`
Expected: FAIL — `ImportError: cannot import name 'parse_scadenzario'`

- [ ] **Step 3: Implement parse_scadenzario**

Add to `condges/parse_pf.py`:

```python
@dataclass
class ScadenzarioData:
    """Parsed scadenzario fornitori."""
    fornitori: list[dict]  # [{fornitore, totale, scaduto, mese_4: x, ...}]
    totale_per_mese: dict[int, float]  # {mese: totale_uscite}
    scaduto_totale: float


def _parse_month_header(header: str) -> int | None:
    """Parse 'apr-26' or 'Aprile' into month number."""
    month_map = {
        "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
        "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
    }
    if not isinstance(header, str):
        return None
    h = header.strip().lower()
    for prefix, num in month_map.items():
        if h.startswith(prefix):
            return num
    return None


def parse_scadenzario(file: BytesIO | str) -> ScadenzarioData:
    """Parse scadenzario fornitori XLSX.

    Expected format: first row is headers with fornitore, totale, scaduto,
    then month columns (e.g. 'apr-26', 'mag-26', ...), then 'Oltre'.
    """
    wb = load_workbook(file, data_only=True)
    ws = wb.active

    # Read headers to find month columns
    headers = []
    col_to_mese: dict[int, int] = {}
    scaduto_col: int | None = None
    totale_col: int | None = None
    fornitore_col: int = 1

    for col in range(1, ws.max_column + 1):
        val = ws.cell(1, col).value
        if not isinstance(val, str):
            continue
        h = val.strip().lower()
        if "fornitore" in h or "ragione" in h:
            fornitore_col = col
        elif h == "totale":
            totale_col = col
        elif "scadut" in h:
            scaduto_col = col
        elif h != "oltre":
            mese = _parse_month_header(val)
            if mese is not None:
                col_to_mese[col] = mese

    # Read data rows
    fornitori = []
    totale_per_mese: dict[int, float] = {}
    scaduto_totale = 0.0

    for row in range(2, ws.max_row + 1):
        nome = ws.cell(row, fornitore_col).value
        if not nome or not isinstance(nome, str) or not nome.strip():
            continue

        entry = {"fornitore": nome.strip()}

        if totale_col:
            v = ws.cell(row, totale_col).value
            entry["totale"] = float(v) if isinstance(v, (int, float)) else 0

        scad = 0.0
        if scaduto_col:
            v = ws.cell(row, scaduto_col).value
            scad = float(v) if isinstance(v, (int, float)) else 0
        entry["scaduto"] = scad
        scaduto_totale += scad

        for col, mese in col_to_mese.items():
            v = ws.cell(row, col).value
            amt = float(v) if isinstance(v, (int, float)) else 0
            entry[f"mese_{mese}"] = amt
            totale_per_mese[mese] = totale_per_mese.get(mese, 0) + amt

        fornitori.append(entry)

    return ScadenzarioData(
        fornitori=fornitori,
        totale_per_mese=totale_per_mese,
        scaduto_totale=scaduto_totale,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parse_pf.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add condges/parse_pf.py tests/test_parse_pf.py
git commit -m "feat: add scadenzario fornitori parser"
```

---

### Task 3: BQ Data Loading

**Files:**
- Create: `condges/bq_data.py`

This module provides cached BQ queries for the tesoreria app. Read-only.

- [ ] **Step 1: Create bq_data.py with consuntivo + budget + voci queries**

```python
# condges/bq_data.py
"""BQ data loading for tesoreria app. Read-only, cached."""
from __future__ import annotations

import streamlit as st
import pandas as pd
from google.cloud import bigquery
from core import config as cfg

BQ_PROJECT = "hotelops-suite"


def _client() -> bigquery.Client:
    return bigquery.Client(project=BQ_PROJECT)


@st.cache_data(ttl=300)
def load_voci() -> pd.DataFrame:
    """Load d_voci_piano_finanziario: voce_id, voce_label, sezione, categoria, ord."""
    sql = f"""
    SELECT voce_id, voce_label, sezione, categoria, ord, societa_id,
           categoria_ce, tipo_costo
    FROM `{cfg.D_VOCI_PIANO_FINANZIARIO}`
    ORDER BY ord
    """
    return _client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_consuntivo(societa: str, anno: int) -> pd.DataFrame:
    """Load consuntivo per voce PF × mese from f_movimenti_contabili.

    Joins movimenti to d_voci via cod_conto_pattern LIKE matching.
    Returns: voce_id, mese, importo_consuntivo.
    """
    sql = f"""
    WITH mov AS (
      SELECT
        REPLACE(codice_conto, '.', '') AS cod,
        EXTRACT(MONTH FROM data_registrazione) AS mese,
        imp_dare,
        imp_avere
      FROM `{cfg.F_MOVIMENTI_CONTABILI}`
      WHERE societa_id = '{societa}'
        AND EXTRACT(YEAR FROM data_registrazione) = {anno}
    ),
    mapped AS (
      SELECT
        v.voce_id,
        v.sezione,
        m.mese,
        m.imp_dare,
        m.imp_avere
      FROM mov m
      JOIN `{cfg.D_VOCI_PIANO_FINANZIARIO}` v
        ON m.cod LIKE v.cod_conto_pattern
      WHERE v.fonte = 'ESOLVER'
        AND (v.societa_id IS NULL OR v.societa_id = '{societa}')
    )
    SELECT
      voce_id,
      mese,
      CASE
        WHEN sezione = 'ENTRATE' THEN ROUND(SUM(imp_avere - imp_dare), 2)
        ELSE ROUND(SUM(imp_dare - imp_avere), 2)
      END AS importo_consuntivo
    FROM mapped
    GROUP BY voce_id, mese, sezione
    ORDER BY voce_id, mese
    """
    return _client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_budget(societa: str, anno: int) -> pd.DataFrame:
    """Load budget per voce PF × mese from f_budget_mensile.

    Returns: voce_id, mese, importo_budget.
    """
    sql = f"""
    WITH budget AS (
      SELECT
        REPLACE(codice_conto, '.', '') AS cod,
        mese,
        SUM(importo) AS importo
      FROM `{cfg.F_BUDGET_MENSILE}`
      WHERE societa_id = '{societa}'
        AND anno = {anno}
      GROUP BY 1, 2
    ),
    mapped AS (
      SELECT
        v.voce_id,
        b.mese,
        b.importo
      FROM budget b
      JOIN `{cfg.D_VOCI_PIANO_FINANZIARIO}` v
        ON b.cod LIKE v.cod_conto_pattern
      WHERE v.fonte = 'ESOLVER'
        AND (v.societa_id IS NULL OR v.societa_id = '{societa}')
    )
    SELECT
      voce_id,
      mese,
      ROUND(SUM(importo), 2) AS importo_budget
    FROM mapped
    GROUP BY voce_id, mese
    ORDER BY voce_id, mese
    """
    return _client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_mapping_detail(societa: str) -> pd.DataFrame:
    """Load d_mapping_piano_finanziario for drill-down detail.

    Returns: voce_id, sotto_voce, tipo, codice_fornitore, cod_conto_pattern.
    """
    sql = f"""
    SELECT voce_id, sotto_voce, tipo, codice_fornitore, cod_conto_pattern, nome_esolver
    FROM `{cfg.D_MAPPING_PIANO_FINANZIARIO}`
    WHERE societa_id = '{societa}'
    ORDER BY voce_id, sotto_voce
    """
    return _client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_consuntivo_detail(societa: str, anno: int) -> pd.DataFrame:
    """Load consuntivo per codice_conto × mese for drill-down.

    Returns: codice_conto, descrizione, mese, importo.
    """
    sql = f"""
    SELECT
      codice_conto,
      descrizione_conto AS descrizione,
      EXTRACT(MONTH FROM data_registrazione) AS mese,
      ROUND(SUM(imp_dare - imp_avere), 2) AS importo
    FROM `{cfg.F_MOVIMENTI_CONTABILI}`
    WHERE societa_id = '{societa}'
      AND EXTRACT(YEAR FROM data_registrazione) = {anno}
    GROUP BY 1, 2, 3
    ORDER BY 1, 3
    """
    return _client().query(sql).to_dataframe()


@st.cache_data(ttl=300)
def load_categorie() -> pd.DataFrame:
    """Load d_categorie_conti for drill-down enrichment."""
    sql = f"""
    SELECT codice_conto, tipo_costo, categoria_ce
    FROM `{cfg.D_CATEGORIE_CONTI}`
    """
    return _client().query(sql).to_dataframe()
```

- [ ] **Step 2: Commit**

```bash
git add condges/bq_data.py
git commit -m "feat: add BQ data loading for tesoreria (read-only)"
```

---

### Task 4: Cashflow Projection Logic

**Files:**
- Create: `condges/cashflow.py`
- Test: `tests/test_cashflow.py`

Pure function: given saldo iniziale + entrate + uscite per mese → proiezione.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cashflow.py
import pytest
from condges.cashflow import project_cashflow, CashflowRow

def test_basic_projection():
    entrate = {4: 100_000, 5: 200_000, 6: 300_000}
    uscite = {4: 150_000, 5: 120_000, 6: 400_000}
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese=entrate,
        uscite_per_mese=uscite,
    )
    assert len(rows) == 3
    # Apr: 50k + 100k - 150k = 0
    assert rows[0].saldo_fine == 0
    # Mag: 0 + 200k - 120k = 80k
    assert rows[1].saldo_fine == 80_000
    # Giu: 80k + 300k - 400k = -20k
    assert rows[2].saldo_fine == -20_000

def test_danger_detection():
    entrate = {4: 10_000}
    uscite = {4: 100_000}
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese=entrate,
        uscite_per_mese=uscite,
    )
    assert rows[0].stato == "PERICOLO"  # -40k

def test_ok_stato():
    entrate = {4: 200_000}
    uscite = {4: 100_000}
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese=entrate,
        uscite_per_mese=uscite,
    )
    assert rows[0].stato == "OK"  # 150k

def test_attenzione_stato():
    entrate = {4: 100_000}
    uscite = {4: 120_000}
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese=entrate,
        uscite_per_mese=uscite,
    )
    assert rows[0].stato == "ATTENZIONE"  # 30k (0 < x < 50k)

def test_fornitori_added_to_uscite():
    entrate = {4: 200_000}
    uscite = {4: 100_000}
    fornitori = {4: 30_000}
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese=entrate,
        uscite_per_mese=uscite,
        fornitori_per_mese=fornitori,
    )
    # 50k + 200k - 100k - 30k = 120k
    assert rows[0].saldo_fine == 120_000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cashflow.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement cashflow.py**

```python
# condges/cashflow.py
"""Cashflow projection logic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CashflowRow:
    """One month of cashflow projection."""
    mese: int
    saldo_iniziale: float
    entrate: float
    uscite_pf: float
    uscite_fornitori: float
    netto: float
    saldo_fine: float
    stato: str  # OK, ATTENZIONE, PERICOLO


def project_cashflow(
    saldo_iniziale: float,
    mese_inizio: int,
    entrate_per_mese: dict[int, float],
    uscite_per_mese: dict[int, float],
    fornitori_per_mese: dict[int, float] | None = None,
    mese_fine: int = 12,
) -> list[CashflowRow]:
    """Project cashflow month by month.

    Args:
        saldo_iniziale: Bank balance at start of mese_inizio.
        mese_inizio: First month to project (1-12).
        entrate_per_mese: {mese: total_entrate} from PF Excel.
        uscite_per_mese: {mese: total_uscite} from PF Excel.
        fornitori_per_mese: {mese: total_fornitori} from scadenzario (optional).
        mese_fine: Last month to project (default 12).

    Returns:
        List of CashflowRow, one per month.
    """
    if fornitori_per_mese is None:
        fornitori_per_mese = {}

    rows = []
    saldo = saldo_iniziale

    for mese in range(mese_inizio, mese_fine + 1):
        entrate = entrate_per_mese.get(mese, 0)
        uscite = uscite_per_mese.get(mese, 0)
        forn = fornitori_per_mese.get(mese, 0)
        netto = entrate - uscite - forn
        saldo_fine = saldo + netto

        if saldo_fine < 0:
            stato = "PERICOLO"
        elif saldo_fine < 50_000:
            stato = "ATTENZIONE"
        else:
            stato = "OK"

        rows.append(CashflowRow(
            mese=mese,
            saldo_iniziale=saldo,
            entrate=entrate,
            uscite_pf=uscite,
            uscite_fornitori=forn,
            netto=netto,
            saldo_fine=saldo_fine,
            stato=stato,
        ))
        saldo = saldo_fine

    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cashflow.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add condges/cashflow.py tests/test_cashflow.py
git commit -m "feat: add cashflow projection logic with semaphore"
```

---

### Task 5: Excel Output Generator

**Files:**
- Create: `condges/export_excel.py`

Reuses style patterns from `condges/genera_excel.py` but produces the new clean format.

- [ ] **Step 1: Create export_excel.py**

```python
# condges/export_excel.py
"""Generate clean Excel output for tesoreria app."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from condges.cashflow import CashflowRow

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
        "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# Clean styles — no yellow
FONT_HEADER = Font(name="Arial", bold=True, size=11)
FONT_NORMAL = Font(name="Arial", size=10)
FONT_BOLD = Font(name="Arial", bold=True, size=10)
FONT_PREVISIONE = Font(name="Arial", size=10, color="0000FF")
FONT_DANGER = Font(name="Arial", bold=True, size=10, color="CC0000")
FILL_HEADER = PatternFill("solid", fgColor="D9E1F2")
FILL_ENTRATE = PatternFill("solid", fgColor="E2EFDA")
FILL_USCITE = PatternFill("solid", fgColor="FCE4D6")
FILL_TOTALE = PatternFill("solid", fgColor="DDDDDD")
FILL_DANGER = PatternFill("solid", fgColor="FFC7CE")
EUR_FMT = '#,##0;(#,##0);"-"'
THIN_BORDER = Border(bottom=Side(style="thin", color="AAAAAA"))


def generate_tesoreria_excel(
    societa: str,
    anno: int,
    cashflow_rows: list[CashflowRow],
    voci_data: list[dict],  # [{voce_id, voce_label, sezione, mese, previsione, budget, consuntivo}]
    fornitori: list[dict] | None = None,
    saldi_banca: dict[str, float] | None = None,
) -> BytesIO:
    """Generate clean Excel workbook.

    Returns BytesIO ready for Streamlit download.
    """
    wb = Workbook()
    wb.remove(wb.active)

    _build_cashflow_sheet(wb, societa, anno, cashflow_rows, saldi_banca)
    _build_dettaglio_sheet(wb, societa, anno, voci_data)
    if fornitori:
        _build_fornitori_sheet(wb, fornitori)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _build_cashflow_sheet(
    wb: Workbook,
    societa: str,
    anno: int,
    rows: list[CashflowRow],
    saldi_banca: dict[str, float] | None,
):
    ws = wb.create_sheet("Proiezione Cashflow")

    # Title
    ws.merge_cells("A1:N1")
    ws["A1"] = f"Proiezione Cashflow {societa} — {anno}"
    ws["A1"].font = Font(name="Arial", bold=True, size=14)

    # Saldi banca note
    if saldi_banca:
        parts = ", ".join(f"{b}: €{int(s):,}" for b, s in saldi_banca.items())
        ws["A2"] = f"Saldi banca: {parts}"
        ws["A2"].font = Font(name="Arial", size=9, color="888888")

    # Headers
    r = 4
    ws.cell(r, 1, "").font = FONT_HEADER
    ws.column_dimensions["A"].width = 22
    for i, row in enumerate(rows):
        col = i + 2
        ws.cell(r, col, MESI[row.mese - 1]).font = FONT_HEADER
        ws.cell(r, col).fill = FILL_HEADER
        ws.cell(r, col).alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = 14

    # Data rows
    labels = [
        ("Saldo iniziale", "saldo_iniziale", None),
        ("+ Entrate", "entrate", FILL_ENTRATE),
        ("- Uscite PF", "uscite_pf", FILL_USCITE),
        ("- Fornitori", "uscite_fornitori", FILL_USCITE),
        ("Netto mese", "netto", None),
        ("SALDO FINE MESE", "saldo_fine", FILL_TOTALE),
    ]

    for label, attr, fill in labels:
        r += 1
        ws.cell(r, 1, label).font = FONT_BOLD if attr == "saldo_fine" else FONT_NORMAL
        if fill:
            ws.cell(r, 1).fill = fill
        for i, row in enumerate(rows):
            col = i + 2
            val = getattr(row, attr)
            cell = ws.cell(r, col, round(val))
            cell.number_format = EUR_FMT
            if fill:
                cell.fill = fill
            if attr == "saldo_fine":
                cell.font = FONT_DANGER if row.stato == "PERICOLO" else FONT_BOLD
                if row.stato == "PERICOLO":
                    cell.fill = FILL_DANGER

    # Stato row
    r += 1
    ws.cell(r, 1, "Stato").font = FONT_BOLD
    for i, row in enumerate(rows):
        col = i + 2
        cell = ws.cell(r, col, row.stato)
        cell.font = FONT_BOLD
        cell.alignment = Alignment(horizontal="center")
        if row.stato == "PERICOLO":
            cell.fill = FILL_DANGER


def _build_dettaglio_sheet(
    wb: Workbook,
    societa: str,
    anno: int,
    voci_data: list[dict],
):
    ws = wb.create_sheet("Dettaglio Voci")

    ws.merge_cells("A1:N1")
    ws["A1"] = f"Dettaglio Piano Finanziario {societa} — {anno}"
    ws["A1"].font = Font(name="Arial", bold=True, size=14)

    # Headers: Voce | Gen(prev/bud/cons) | Feb(...) | ...
    r = 3
    ws.cell(r, 1, "Voce").font = FONT_HEADER
    ws.cell(r, 1).fill = FILL_HEADER
    ws.column_dimensions["A"].width = 32

    col = 2
    for mese in MESI:
        ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + 2)
        ws.cell(r, col, mese).font = FONT_HEADER
        ws.cell(r, col).fill = FILL_HEADER
        ws.cell(r, col).alignment = Alignment(horizontal="center")
        col += 3

    r += 1
    ws.cell(r, 1, "").font = FONT_HEADER
    col = 2
    for _ in MESI:
        for sub in ("Prev", "Budget", "Cons"):
            ws.cell(r, col, sub).font = Font(name="Arial", size=8, color="888888")
            ws.cell(r, col).alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(col)].width = 10
            col += 1

    # Group voci_data by voce_id, preserving order
    from collections import OrderedDict
    voce_groups: OrderedDict[str, dict] = OrderedDict()
    for row in voci_data:
        vid = row["voce_id"]
        if vid not in voce_groups:
            voce_groups[vid] = {
                "voce_label": row["voce_label"],
                "sezione": row["sezione"],
                "mesi": {},
            }
        voce_groups[vid]["mesi"][row["mese"]] = row

    current_sezione = None
    r += 1
    for vid, info in voce_groups.items():
        sezione = info["sezione"]
        if sezione != current_sezione:
            current_sezione = sezione
            ws.cell(r, 1, f"── {sezione} ──").font = Font(name="Arial", bold=True, size=11)
            fill = FILL_ENTRATE if sezione == "ENTRATE" else FILL_USCITE
            for c in range(1, 2 + 12 * 3):
                ws.cell(r, c).fill = fill
            r += 1

        ws.cell(r, 1, info["voce_label"]).font = FONT_NORMAL
        col = 2
        for mese in range(1, 13):
            mdata = info["mesi"].get(mese, {})
            for key in ("previsione", "budget", "consuntivo"):
                val = mdata.get(key, 0) or 0
                if val:
                    ws.cell(r, col, round(val)).number_format = EUR_FMT
                    ws.cell(r, col).font = FONT_NORMAL
                col += 1
        r += 1


def _build_fornitori_sheet(wb: Workbook, fornitori: list[dict]):
    ws = wb.create_sheet("Fornitori")

    ws["A1"] = "Scadenzario Fornitori"
    ws["A1"].font = Font(name="Arial", bold=True, size=14)

    # Sort by totale descending
    sorted_f = sorted(fornitori, key=lambda x: x.get("totale", 0), reverse=True)

    # Headers
    r = 3
    headers = ["Fornitore", "Totale", "Scaduto"]
    # Find month keys
    month_keys = sorted([k for k in fornitori[0] if k.startswith("mese_")])
    for mk in month_keys:
        mese_num = int(mk.split("_")[1])
        headers.append(MESI[mese_num - 1])

    for col, h in enumerate(headers, 1):
        ws.cell(r, col, h).font = FONT_HEADER
        ws.cell(r, col).fill = FILL_HEADER

    ws.column_dimensions["A"].width = 35
    for col in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 13

    for entry in sorted_f:
        r += 1
        ws.cell(r, 1, entry["fornitore"]).font = FONT_NORMAL
        ws.cell(r, 2, round(entry.get("totale", 0))).number_format = EUR_FMT
        ws.cell(r, 3, round(entry.get("scaduto", 0))).number_format = EUR_FMT
        for i, mk in enumerate(month_keys):
            ws.cell(r, 4 + i, round(entry.get(mk, 0))).number_format = EUR_FMT
```

- [ ] **Step 2: Commit**

```bash
git add condges/export_excel.py
git commit -m "feat: add clean Excel export for tesoreria"
```

---

### Task 6: Streamlit App

**Files:**
- Create: `condges/tesoreria.py`

This wires together all the modules: parse_pf, bq_data, cashflow, export_excel.

- [ ] **Step 1: Create tesoreria.py**

```python
# condges/tesoreria.py
"""Tesoreria — Check mensile cashflow per Rosa.

Carica il PF Excel di Rosa, incrocia con consuntivo Esolver + budget da BQ,
proietta il cashflow forward, scarica Excel pulito.

Usage: streamlit run condges/tesoreria.py
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from condges.parse_pf import parse_pf_excel, parse_scadenzario, PFData
from condges.cashflow import project_cashflow, CashflowRow
from condges.export_excel import generate_tesoreria_excel

st.set_page_config(page_title="Tesoreria", layout="wide")

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
        "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

BANCHE = {
    "ORTI": ["MPS", "Intesa", "MPS_KROSS"],
    "INTUR": ["Sella", "MPS", "Intesa", "BCP"],
}


def main():
    st.title("Tesoreria")
    st.caption("Check mensile: PF Rosa × Consuntivo Esolver × Budget")

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Impostazioni")

        anno = st.number_input("Anno", value=2026, min_value=2024, max_value=2030)

        st.subheader("Upload PF Excel")
        pf_file = st.file_uploader(
            "Piano Finanziario di Rosa",
            type=["xlsx"],
            key="pf_upload",
            help="Il file Excel con le previsioni (es. ORTI - Piano Finanziario - 03_mar2026.xlsx)",
        )

        # Parse PF if uploaded
        pf_data: PFData | None = None
        if pf_file:
            try:
                pf_data = parse_pf_excel(BytesIO(pf_file.read()))
                st.success(f"PF {pf_data.societa} caricato: {len(pf_data.voci)} voci")
                if pf_data.warnings:
                    for w in pf_data.warnings:
                        st.warning(w)
            except Exception as e:
                st.error(f"Errore parsing PF: {e}")

        societa = st.selectbox(
            "Società",
            ["ORTI", "INTUR"],
            index=0 if not pf_data else (0 if pf_data.societa == "ORTI" else 1),
        )

        st.subheader("Saldo Banca")
        data_saldo = st.date_input(
            "Data saldo",
            value=pf_data.data_saldo if pf_data and pf_data.data_saldo else date.today().replace(day=1) - __import__("datetime").timedelta(days=1),
        )

        # Saldi per banca
        saldi_banca: dict[str, float] = {}
        default_saldi = pf_data.saldi_banca if pf_data else {}
        for banca in BANCHE[societa]:
            default = default_saldi.get(banca, 0.0)
            saldi_banca[banca] = st.number_input(
                f"Saldo {banca}",
                value=default,
                step=1000.0,
                format="%.2f",
                key=f"saldo_{banca}",
            )
        saldo_totale = sum(saldi_banca.values())
        st.metric("Totale Banche", f"€{saldo_totale:,.0f}")

        st.subheader("Scadenzario Fornitori")
        scad_file = st.file_uploader(
            "Upload scadenzario (opzionale)",
            type=["xlsx"],
            key="scad_upload",
        )
        scad_data = None
        if scad_file:
            try:
                scad_data = parse_scadenzario(BytesIO(scad_file.read()))
                st.success(f"Scadenzario: {len(scad_data.fornitori)} fornitori")
            except Exception as e:
                st.error(f"Errore parsing scadenzario: {e}")

    # ── Main content ────────────────────────────────────────────────────────
    if not pf_data:
        st.info("Carica il Piano Finanziario Excel nella sidebar per iniziare.")
        return

    # Load BQ data
    from condges import bq_data

    with st.spinner("Caricamento dati da BigQuery..."):
        df_voci = bq_data.load_voci()
        df_consuntivo = bq_data.load_consuntivo(societa, anno)
        df_budget = bq_data.load_budget(societa, anno)

    # Determine current month (months < this are "closed")
    mese_corrente = date.today().month

    # ── Build unified data ──────────────────────────────────────────────────
    # For each voce × mese: previsione (from PF Excel), budget (from BQ), consuntivo (from BQ)
    voci_list = df_voci[
        (df_voci["societa_id"].isna()) | (df_voci["societa_id"] == societa)
    ].sort_values("ord")

    voci_data = []
    entrate_per_mese: dict[int, float] = {}
    uscite_per_mese: dict[int, float] = {}

    for _, vrow in voci_list.iterrows():
        vid = vrow["voce_id"]
        sezione = vrow["sezione"]

        for mese in range(1, 13):
            prev = 0.0
            if vid in pf_data.voci:
                prev = pf_data.voci[vid].importi.get(mese, 0)

            cons_row = df_consuntivo[
                (df_consuntivo["voce_id"] == vid) & (df_consuntivo["mese"] == mese)
            ]
            cons = float(cons_row["importo_consuntivo"].iloc[0]) if len(cons_row) > 0 else 0

            bud_row = df_budget[
                (df_budget["voce_id"] == vid) & (df_budget["mese"] == mese)
            ]
            bud = float(bud_row["importo_budget"].iloc[0]) if len(bud_row) > 0 else 0

            voci_data.append({
                "voce_id": vid,
                "voce_label": vrow["voce_label"],
                "sezione": sezione,
                "categoria": vrow.get("categoria", ""),
                "ord": vrow["ord"],
                "mese": mese,
                "previsione": prev,
                "budget": bud,
                "consuntivo": cons,
            })

            # Accumulate for cashflow
            if sezione == "ENTRATE":
                entrate_per_mese[mese] = entrate_per_mese.get(mese, 0) + prev
            else:
                uscite_per_mese[mese] = uscite_per_mese.get(mese, 0) + prev

    # ── 1. Header: Saldo Banca ──────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        if saldo_totale < 0:
            color = "🔴"
        elif saldo_totale < 50_000:
            color = "🟡"
        else:
            color = "🟢"
        st.metric(
            f"{color} Saldo Banca {societa} al {data_saldo.strftime('%d/%m/%Y')}",
            f"€{saldo_totale:,.0f}",
        )
    with col2:
        st.metric("Voci PF caricate", len(pf_data.voci))
    with col3:
        if scad_data:
            st.metric("Fornitori", len(scad_data.fornitori))
            if scad_data.scaduto_totale > 0:
                st.metric("Scaduto", f"€{scad_data.scaduto_totale:,.0f}")

    # ── 2. Cashflow Projection ──────────────────────────────────────────────
    st.header("Proiezione Cashflow")

    fornitori_mese = scad_data.totale_per_mese if scad_data else None
    cf_rows = project_cashflow(
        saldo_iniziale=saldo_totale,
        mese_inizio=mese_corrente,
        entrate_per_mese=entrate_per_mese,
        uscite_per_mese=uscite_per_mese,
        fornitori_per_mese=fornitori_mese,
    )

    # Cashflow table
    cf_df = pd.DataFrame([
        {
            "Mese": MESI[r.mese - 1],
            "Saldo Iniziale": round(r.saldo_iniziale),
            "Entrate": round(r.entrate),
            "Uscite PF": round(r.uscite_pf),
            "Fornitori": round(r.uscite_fornitori),
            "Netto": round(r.netto),
            "Saldo Fine": round(r.saldo_fine),
            "Stato": r.stato,
        }
        for r in cf_rows
    ])

    def _color_stato(val):
        if val == "PERICOLO":
            return "background-color: #FFC7CE; color: #CC0000; font-weight: bold"
        elif val == "ATTENZIONE":
            return "background-color: #FFEB9C; color: #9C5700"
        return "background-color: #C6EFCE; color: #006100"

    def _color_saldo(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "color: #CC0000; font-weight: bold"
            if val < 50_000:
                return "color: #9C5700"
        return ""

    styled = cf_df.style.applymap(_color_stato, subset=["Stato"])
    styled = styled.applymap(_color_saldo, subset=["Saldo Fine"])
    styled = styled.format({
        "Saldo Iniziale": "€{:,.0f}",
        "Entrate": "€{:,.0f}",
        "Uscite PF": "€{:,.0f}",
        "Fornitori": "€{:,.0f}",
        "Netto": "€{:,.0f}",
        "Saldo Fine": "€{:,.0f}",
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Cashflow chart
    fig = go.Figure()
    mesi_labels = [MESI[r.mese - 1] for r in cf_rows]
    fig.add_trace(go.Bar(
        x=mesi_labels,
        y=[r.entrate for r in cf_rows],
        name="Entrate",
        marker_color="#4CAF50",
    ))
    fig.add_trace(go.Bar(
        x=mesi_labels,
        y=[-r.uscite_pf - r.uscite_fornitori for r in cf_rows],
        name="Uscite",
        marker_color="#F44336",
    ))
    fig.add_trace(go.Scatter(
        x=mesi_labels,
        y=[r.saldo_fine for r in cf_rows],
        name="Saldo",
        line=dict(color="#1565C0", width=3),
        mode="lines+markers",
    ))
    # Red zone
    fig.add_hrect(y0=-1_000_000, y1=0, fillcolor="red", opacity=0.08, line_width=0)
    fig.add_hrect(y0=0, y1=50_000, fillcolor="orange", opacity=0.05, line_width=0)
    fig.update_layout(
        barmode="relative",
        title="Cashflow Mensile",
        yaxis_title="€",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── 3. Dettaglio Voci PF ────────────────────────────────────────────────
    st.header("Dettaglio Voci PF")

    current_sezione = None
    for _, vrow in voci_list.iterrows():
        vid = vrow["voce_id"]
        sezione = vrow["sezione"]

        if sezione != current_sezione:
            current_sezione = sezione
            st.subheader(f"{'📈' if sezione == 'ENTRATE' else '📉'} {sezione}")

        # Get this voce's data across months
        voce_months = [v for v in voci_data if v["voce_id"] == vid]
        if not any(v["previsione"] or v["consuntivo"] or v["budget"] for v in voce_months):
            continue

        with st.expander(f"{vrow['voce_label']}"):
            rows = []
            for vm in voce_months:
                m = vm["mese"]
                row = {"Mese": MESI[m - 1]}
                row["Previsione"] = round(vm["previsione"]) if vm["previsione"] else None
                row["Budget"] = round(vm["budget"]) if vm["budget"] else None

                if m < mese_corrente:
                    row["Consuntivo"] = round(vm["consuntivo"]) if vm["consuntivo"] else None
                    if vm["previsione"] and vm["consuntivo"]:
                        row["Delta Prev"] = round(vm["consuntivo"] - vm["previsione"])
                    if vm["budget"] and vm["consuntivo"]:
                        row["Delta Budget"] = round(vm["consuntivo"] - vm["budget"])
                else:
                    row["Consuntivo"] = None
                    if vm["previsione"] and vm["budget"]:
                        row["Delta P-B"] = round(vm["previsione"] - vm["budget"])

                rows.append(row)

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 4. Fornitori ────────────────────────────────────────────────────────
    if scad_data:
        st.header("Scadenzario Fornitori")

        # Top 10 by totale
        sorted_f = sorted(scad_data.fornitori, key=lambda x: x.get("totale", 0), reverse=True)
        top10 = sorted_f[:10]

        rows = []
        for f in top10:
            row = {"Fornitore": f["fornitore"], "Totale": f.get("totale", 0), "Scaduto": f.get("scaduto", 0)}
            for mese in sorted(scad_data.totale_per_mese.keys()):
                row[MESI[mese - 1]] = f.get(f"mese_{mese}", 0)
            rows.append(row)

        df_forn = pd.DataFrame(rows)
        st.dataframe(df_forn, use_container_width=True, hide_index=True)

        # Totale per mese
        st.subheader("Totale Uscite Fornitori per Mese")
        tot_rows = [{"Mese": MESI[m - 1], "Importo": round(v)} for m, v in sorted(scad_data.totale_per_mese.items())]
        st.dataframe(pd.DataFrame(tot_rows), use_container_width=True, hide_index=True)

    # ── Download Excel ──────────────────────────────────────────────────────
    st.divider()
    excel_buf = generate_tesoreria_excel(
        societa=societa,
        anno=anno,
        cashflow_rows=cf_rows,
        voci_data=voci_data,
        fornitori=scad_data.fornitori if scad_data else None,
        saldi_banca=saldi_banca,
    )
    st.download_button(
        "📥 Scarica Excel",
        data=excel_buf,
        file_name=f"Tesoreria_{societa}_{anno}_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test manually**

Run: `streamlit run condges/tesoreria.py`

Verify:
1. App loads without errors
2. Upload `ORTI - Piano Finanziario - 03_mar2026.xlsx` — societa auto-detected as ORTI
3. Saldi banca populated from Excel (MPS: 67.724, Intesa: 66.922)
4. Cashflow table shows monthly projection with semaphore
5. Chart renders with red zone
6. Voci detail expanders show previsione/budget/consuntivo
7. Excel download produces clean file

- [ ] **Step 3: Commit**

```bash
git add condges/tesoreria.py
git commit -m "feat: add tesoreria Streamlit app"
```

---

### Task 7: Wire up CLI

**Files:**
- Modify: `cli.py`

Add `hotelops tesoreria` command to launch the app.

- [ ] **Step 1: Read cli.py to find where to add the command**

Check current CLI structure and the pattern used for the existing `streamlit run condges/app.py` launch.

- [ ] **Step 2: Add tesoreria subcommand**

Add to the CLI's subcommand list, following the same pattern as any existing Streamlit launcher:

```python
# In the subcommands section of cli.py, add:
elif args.command == "tesoreria":
    import subprocess
    subprocess.run(["streamlit", "run", "condges/tesoreria.py"])
```

The exact insertion point depends on cli.py's structure (read it in Step 1).

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: add 'hotelops tesoreria' CLI command"
```

---

### Task 8: Integration Test with Real Data

**Files:** none (manual testing)

- [ ] **Step 1: Run with real ORTI PF Excel**

```bash
streamlit run condges/tesoreria.py
```

Upload: `/Users/stefanodellapietra/Desktop/WORK/pianifinanziari/ORTI - Piano Finanziario - 03_mar2026.xlsx`

Verify:
- Societa detected as ORTI
- Saldi banca: MPS 67.724, Intesa 66.922
- 17 voci parsed (6 entrate + 11 uscite)
- Consuntivo from BQ shows real Esolver data for Gen-Mar
- Budget from BQ shows approved budget numbers
- Cashflow projection shows June as danger zone (mutuo semestrale)
- Excel download is clean, no yellow

- [ ] **Step 2: Run with real INTUR PF Excel**

Upload: `/Users/stefanodellapietra/Desktop/WORK/pianifinanziari/Intur - Piano Finanziario - 1_Gen.2026.xlsx`

Verify:
- Societa detected as INTUR
- Saldi banca: Sella 17.318, MPS 37.076, Intesa 3.000
- Voci parsed correctly despite typos ("Godimento Benidi Terzi", "Caparre da girocantare aOrti")

- [ ] **Step 3: Test scadenzario upload**

Upload: `/Users/stefanodellapietra/Desktop/WORK/tesoreria/interrogazionesituazionesinteticascadenze.XLSX`

Verify:
- 71 fornitori parsed
- Monthly totals appear in cashflow projection as additional uscite
- Fornitori section visible with top 10

- [ ] **Step 4: Test Excel download**

Download the Excel and verify:
- 3 sheets (Proiezione Cashflow, Dettaglio Voci, Fornitori)
- No yellow highlights
- Numbers match what's shown in app
- Printable / clean formatting
