# XLSX Movimenti Contabili Parser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support Esolver XLSX movimenti contabili exports alongside the existing XLS binary format.

**Architecture:** Add `parse_file_xlsx()` to `ingest_movimenti_contabili.py` that reads the "report-style" XLSX format (26 cols, PNC-based document grouping). The main `process_societa()` dispatches to the correct parser based on file extension. The classify detector is updated to accept `.xlsx` files. Same hash-based dedup, same BQ schema output.

**Tech Stack:** openpyxl (already a dependency), existing BQ pipeline.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `ingest/flussi/ingest_movimenti_contabili.py` | Modify | Add `parse_file_xlsx()`, update `process_societa()` dispatch |
| `ingest/classify.py` | Modify | Update `detect_movimenti_contabili()` to accept `.xlsx` |
| `tests/test_ingest_movimenti_xlsx.py` | Create | Tests for the new XLSX parser |

---

### Task 1: XLSX Parser Function

**Files:**
- Create: `tests/test_ingest_movimenti_xlsx.py`
- Modify: `ingest/flussi/ingest_movimenti_contabili.py:131-199`

- [ ] **Step 1: Write the failing test — basic XLSX parsing**

Create `tests/test_ingest_movimenti_xlsx.py`:

```python
"""Tests for XLSX movimenti contabili parser."""

import openpyxl
import pytest
from pathlib import Path


def _make_xlsx(tmp_path: Path, rows: list[list]) -> Path:
    """Create a minimal XLSX file with the Esolver report layout."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Foglio1"
    for row in rows:
        ws.append(row)
    path = tmp_path / "movimenticontabili.xlsx"
    wb.save(path)
    return path


# Columns: 0=logo, 1=societa, 2=timestamp, 3=None, 4=operatore, 5=data_reg,
#           6=sigla_doc, 7=data_orig, 8=tipo_doc, 9=cod_conto, 10=cod_partitario,
#           11=rag_sociale, 12=causale, 13=imp_dare, 14=imp_avere,
#           15-16=zeros, 17=totale_label, 18-25=running totals

SAMPLE_ROWS = [
    # Row 0: PNC 1, 26/02/2026, pagamento fornitore — dare
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "330301", 1152, "ROVIELLO S.R.L.",
        "Pagamento con Bonifico SEPA FT 678", 452.74, 0,
        0, 0, None, 452.74, 0, None, 452.74, 0, 452.74, 0, None,
    ],
    # Row 1: PNC 1, 26/02/2026, spese bancarie — dare
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "750191", 0,
        "Costo per bonifici verso altre banche",
        "Pagamento con Bonifico SEPA FT 678", 1.75, 0,
        0, 0, None, 454.49, 0, None, 454.49, 0, 454.49, 0, None,
    ],
    # Row 2: PNC 1, 26/02/2026, banca c/c — avere
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "190101", 2,
        "Banca c/c - MONTE DEI PASCHI DI SIENA S.P.A.",
        "Pagamento con Bonifico SEPA FT 678", 0, 454.49,
        0, 0, None, 454.49, 454.49, None, 454.49, 454.49, 454.49, 454.49, None,
    ],
    # Row 3: PNC 1, 02/03/2026, caparra — avere (march data)
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-03-02", "PNC 1", None,
        "701 - DARE/AVERE", "390521", 0, "CAPARRA",
        "CAPARRA_HOTEL FELICITALIA", 0, 916.0,
        0, 0, None, 916.0, 916.0, None, 916.0, 916.0, 916.0, 916.0, None,
    ],
]


class TestParseFileXlsx:
    def test_basic_parsing(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        assert len(rows) == 4

    def test_field_mapping(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        r0 = rows[0]
        assert r0["societa_id"] == "ORTI"
        assert r0["cod_conto"] == "330301"
        assert r0["cod_partitario"] == "1152"
        assert r0["rag_sociale"] == "ROVIELLO S.R.L."
        assert r0["causale_contabile"] == "Pagamento con Bonifico SEPA FT 678"
        assert r0["imp_dare"] == 452.74
        assert r0["imp_avere"] == 0.0
        assert r0["anno"] == 2026
        assert r0["mese"] == 2
        assert r0["data_registrazione"] == "2026-02-26"
        assert r0["sigla_doc"] == "PNC"
        assert r0["tipo_documento"] == "702 - Pagamenti fornitori"

    def test_hash_uniqueness(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        hashes = [r["hash_riga"] for r in rows]
        assert len(hashes) == len(set(hashes)), "Hashes must be unique"

    def test_idempotent_hashes(self, tmp_path):
        """Same file parsed twice produces identical hashes."""
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows1 = parse_file_xlsx(path, "ORTI", logger)
        rows2 = parse_file_xlsx(path, "ORTI", logger)

        assert [r["hash_riga"] for r in rows1] == [r["hash_riga"] for r in rows2]

    def test_all_required_fields_present(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx, FACT_HEADER
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        for row in rows:
            for field in FACT_HEADER:
                assert field in row, f"Missing field: {field}"

    def test_march_data(self, tmp_path):
        """Row 3 is March — verify date extraction from datetime col."""
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        r3 = rows[3]
        assert r3["anno"] == 2026
        assert r3["mese"] == 3
        assert r3["data_registrazione"] == "2026-03-02"
        assert r3["imp_avere"] == 916.0

    def test_pnc_id_extraction(self, tmp_path):
        """PNC number is extracted as id_documento."""
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        assert rows[0]["id_documento"] == 1  # "PNC 1"
        assert rows[0]["num_progr_riga"] == 0  # first row within this PNC+date group
        assert rows[1]["num_progr_riga"] == 1  # second row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest_movimenti_xlsx.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_file_xlsx'`

- [ ] **Step 3: Write `parse_file_xlsx()` implementation**

Add to `ingest/flussi/ingest_movimenti_contabili.py` after `parse_file()` (after line 199):

```python
def parse_file_xlsx(filepath: Path, societa_id: str, logger: logging.Logger) -> list[dict]:
    """Parse Esolver 'report-style' XLSX movimenti contabili.

    Column layout (26 cols):
        0=logo, 1=societa, 2=timestamp, 3=unused, 4=operatore,
        5=data_registrazione, 6=sigla_doc (e.g. "PNC 1"), 7=data_originale,
        8=tipo_documento, 9=cod_conto, 10=cod_partitario, 11=rag_sociale,
        12=causale_contabile, 13=imp_dare, 14=imp_avere, 15-25=running totals
    """
    import re
    from datetime import date, datetime

    import openpyxl

    today = date.today().isoformat()
    file_sorgente = filepath.name

    wb = openpyxl.load_workbook(str(filepath), read_only=True)
    ws = wb.active
    logger.info(f"  {file_sorgente}: {ws.max_row} righe (xlsx)")

    rows = []
    # Track row index within each (date, pnc_num) group for num_progr_riga
    group_counters: dict[tuple, int] = {}

    for raw_row in ws.iter_rows(values_only=True):
        # Extract date — col 5 can be datetime or string "YYYY-MM-DD"
        raw_date = raw_row[5]
        if isinstance(raw_date, datetime):
            data_reg = raw_date.date()
        elif isinstance(raw_date, date):
            data_reg = raw_date
        elif isinstance(raw_date, str):
            try:
                data_reg = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                continue  # skip non-data rows (headers, totals)
        else:
            continue

        # Extract PNC number from col 6 (e.g. "PNC 1" -> sigla="PNC", num=1)
        sigla_raw = str(raw_row[6]).strip() if raw_row[6] else ""
        match = re.match(r"([A-Z]+)\s+(\d+)", sigla_raw)
        if not match:
            continue
        sigla_doc = match.group(1)
        pnc_num = int(match.group(2))

        # num_progr_riga: sequential within (date, pnc_num)
        group_key = (data_reg.isoformat(), pnc_num)
        idx = group_counters.get(group_key, 0)
        group_counters[group_key] = idx + 1

        cod_conto = str(raw_row[9]).strip() if raw_row[9] else None
        if not cod_conto:
            continue

        cod_part_raw = raw_row[10]
        cod_partitario = str(int(cod_part_raw)) if isinstance(cod_part_raw, (int, float)) and cod_part_raw else None

        imp_dare = float(raw_row[13]) if isinstance(raw_row[13], (int, float)) else 0.0
        imp_avere = float(raw_row[14]) if isinstance(raw_row[14], (int, float)) else 0.0

        # Parse data_originale from col 7 (often " DD/MM/YY" or None)
        data_orig = None
        if raw_row[7] and str(raw_row[7]).strip():
            try:
                data_orig = datetime.strptime(str(raw_row[7]).strip(), "%d/%m/%y").date().isoformat()
            except ValueError:
                pass

        # Hash: use date + pnc_num + idx for stable dedup
        hash_key = f"{societa_id}|{data_reg.isoformat()}|{pnc_num}|{idx}"
        hash_riga = hashlib.md5(hash_key.encode()).hexdigest()

        rows.append({
            "hash_riga": hash_riga,
            "societa_id": societa_id,
            "id_documento": pnc_num,
            "num_progr_riga": idx,
            "gruppo_doc": sigla_raw,
            "anno": data_reg.year,
            "mese": data_reg.month,
            "data_registrazione": data_reg.isoformat(),
            "sigla_doc": sigla_doc,
            "rif_registrazione": None,
            "num_doc_originale": None,
            "data_originale": data_orig,
            "tipo_documento": str(raw_row[8]).strip() if raw_row[8] else None,
            "cod_conto": cod_conto,
            "cod_partitario": cod_partitario,
            "rag_sociale": str(raw_row[11]).strip() if raw_row[11] else None,
            "causale_contabile": str(raw_row[12]).strip() if raw_row[12] else None,
            "imp_dare": imp_dare,
            "imp_avere": imp_avere,
            "cod_divisione": None,
            "file_sorgente": file_sorgente,
            "data_ingresso": today,
        })

    wb.close()
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_movimenti_xlsx.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_ingest_movimenti_xlsx.py ingest/flussi/ingest_movimenti_contabili.py
git commit -m "feat: add parse_file_xlsx for Esolver report-style XLSX movimenti"
```

---

### Task 2: Dispatch by Extension + CLI Support

**Files:**
- Modify: `ingest/flussi/ingest_movimenti_contabili.py:268-351`

- [ ] **Step 1: Update `process_societa()` to dispatch by extension**

In `ingest/flussi/ingest_movimenti_contabili.py`, replace line 272:

```python
# Old:
        rows = parse_file(f, societa_id, logger)
# New:
        if f.suffix.lower() == ".xlsx":
            rows = parse_file_xlsx(f, societa_id, logger)
        else:
            rows = parse_file(f, societa_id, logger)
```

- [ ] **Step 2: Update file glob in multi-file mode to include .xlsx**

In `main()`, replace line 329:

```python
# Old:
                xls_files = list(societa_dir.glob("*.XLS")) + list(societa_dir.glob("*.xls"))
# New:
                xls_files = (
                    list(societa_dir.glob("*.XLS")) + list(societa_dir.glob("*.xls"))
                    + list(societa_dir.glob("*.XLSX")) + list(societa_dir.glob("*.xlsx"))
                )
```

- [ ] **Step 3: Update CLI help text**

In `main()`, line 297 — update description and `--file` help:

```python
    parser = argparse.ArgumentParser(description="Ingest Lista movimenti contabili Esolver → f_movimenti_contabili")
    # ...
    parser.add_argument("--file", help="Single XLS or XLSX file to ingest")
```

- [ ] **Step 4: Dry-run test with the real file**

Run: `python -m ingest.flussi.ingest_movimenti_contabili --file /Users/stefanodellapietra/Desktop/movimenticontabili.xlsx --societa ORTI --dry-run`
Expected: output showing `~399 righe (xlsx)` parsed, no BQ writes.

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_movimenti_contabili.py
git commit -m "feat: dispatch xlsx/xls parser by extension, glob .xlsx in staging"
```

---

### Task 3: Update Classifier to Accept XLSX

**Files:**
- Modify: `ingest/classify.py:382-426`

- [ ] **Step 1: Update `detect_movimenti_contabili()` to handle .xlsx**

Replace the function in `ingest/classify.py`:

```python
def detect_movimenti_contabili(path: Path) -> Optional[ClassificationResult]:
    """Esolver LISTAMOVCONT — XLS binary or XLSX report format."""
    ext = path.suffix.lower()

    if ext == ".xls":
        # Original XLS detection logic
        if "LISTAMOVCONT" in path.name.upper():
            societa = infer_societa(path.name, path)
            return _build_movimenti_result(path, societa, confidence=0.95)

        rows = _read_xls_sample(path)
        if len(rows) >= 3:
            for row in rows[1:5]:
                if len(row) >= 20:
                    col12 = str(row[12]).strip() if len(row) > 12 else ""
                    if re.match(r"^\d{5,7}$", col12):
                        societa = infer_societa(path.name, path)
                        return _build_movimenti_result(path, societa, confidence=0.80)

    elif ext == ".xlsx":
        # XLSX: check for Esolver report layout (col 0 = logo path, col 9 = cod_conto)
        if "MOVIMENTI" in path.name.upper() and "CONTABIL" in path.name.upper():
            societa = _infer_societa_from_xlsx(path)
            return _build_movimenti_result(path, societa, confidence=0.90)

        # Content sniff: col 0 contains ESOLVER path, col 9 is 6-digit code
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True)
            ws = wb.active
            for i, row in enumerate(ws.iter_rows(max_row=3, values_only=True)):
                col0 = str(row[0]) if row[0] else ""
                col9 = str(row[9]).strip() if len(row) > 9 and row[9] else ""
                if "ESOLVER" in col0.upper() and re.match(r"^\d{5,7}$", col9):
                    societa = _infer_societa_from_xlsx(path)
                    wb.close()
                    return _build_movimenti_result(path, societa, confidence=0.85)
            wb.close()
        except Exception:
            pass

    return None


def _infer_societa_from_xlsx(path: Path) -> Optional[str]:
    """Read societa from XLSX col 1 (e.g. 'ORTI S.R.L.')."""
    name_upper = path.name.upper()
    if "ORTI" in name_upper:
        return "ORTI"
    if "INTUR" in name_upper:
        return "INTUR"
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True)
        ws = wb.active
        for row in ws.iter_rows(max_row=1, values_only=True):
            col1 = str(row[1]).upper() if row[1] else ""
            if "ORTI" in col1:
                wb.close()
                return "ORTI"
            if "INTUR" in col1:
                wb.close()
                return "INTUR"
        wb.close()
    except Exception:
        pass
    return None
```

- [ ] **Step 2: Update `_build_movimenti_result` to handle both extensions**

```python
def _build_movimenti_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    ext = path.suffix  # preserve original extension
    canonical = f"{soc}_LISTAMOVCONT{ext.upper()}"
    dest = f"movimenti_contabili/{soc}" if societa else "movimenti_contabili"
    pipeline = f"python -m ingest.flussi.ingest_movimenti_contabili --file {{dest_file}}"
    if societa:
        pipeline += f" --societa {societa}"
    return ClassificationResult(
        file_path=path,
        file_type="movimenti_contabili",
        category="movimenti_contabili",
        societa=societa,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )
```

- [ ] **Step 3: Test with `hotelops classifica`**

Run: `hotelops classifica /Users/stefanodellapietra/Desktop/movimenticontabili.xlsx`
Expected: recognized as `movimenti_contabili`, societa=ORTI, confidence >= 0.85

- [ ] **Step 4: Commit**

```bash
git add ingest/classify.py
git commit -m "feat: classify XLSX movimenti contabili (filename + content sniff)"
```

---

### Task 4: Ingest the Real File

- [ ] **Step 1: Run the real ingest**

Run: `python -m ingest.flussi.ingest_movimenti_contabili --file /Users/stefanodellapietra/Desktop/movimenticontabili.xlsx --societa ORTI`
Expected: ~399 rows parsed, new rows written to BQ (feb+mar data, existing feb rows deduped).

- [ ] **Step 2: Verify with `hotelops pf --mese 3`**

Run: `hotelops pf --mese 3`
Expected: consuntivo numbers for march should now show updated values for Esolver-sourced voci (salari, utenze, materie prime, etc.).

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: all tests pass, including new xlsx tests.
