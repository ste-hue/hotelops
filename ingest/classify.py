#!/usr/bin/env python3
"""
File classifier + router for hotelops datahub.

Given one or more files, detects the file type by inspecting content (headers,
structure, column patterns), determines the correct datahub destination folder,
renames to canonical convention, and optionally triggers the right ingest pipeline.

Usage:
    python -m ingest.classify file1.xlsx file2.csv          # Classify + show plan
    python -m ingest.classify file1.xlsx --route             # Copy to datahub + rename
    python -m ingest.classify file1.xlsx --route --ingest    # Copy + rename + ingest to BQ
    python -m ingest.classify ~/Desktop/*.xls* --route       # Batch mode

Designed to be called by:
  - CLI:       hotelops classifica <file>
  - NanoClaw:  agent receives file via WhatsApp, calls classify → route → ingest
  - Humans:    drop files anywhere, let the system sort them out
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.datahub_sync import (
    DATAHUB_ROOT,
    RcloneError,
    rclone_copy_to_remote,
    rclone_copyto,
)

log = logging.getLogger("ingest.classify")

# ── Datahub root ──────────────────────────────────────────────────────────────

DEFAULT_DATAHUB = DATAHUB_ROOT

# All datahub input files live under ingresso/
INGRESSO_PREFIX = "ingresso"
AUDIT_DROP_FILE = "drops.jsonl"


def file_md5_hex(path: Path) -> str:
    """Fingerprint file (MD5) per audit drop — streaming, file grandi ok."""
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            block = f.read(1048576)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def append_drop_audit(datahub: Path, record: dict[str, Any]) -> None:
    """Append una riga JSON su ``ingresso/_audit/drops.jsonl`` (Drive mount / datahub)."""
    try:
        audit_dir = datahub / INGRESSO_PREFIX / "_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with (audit_dir / AUDIT_DROP_FILE).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("Audit drop non scritto: %s", e)


# ── Classification result ─────────────────────────────────────────────────────


# ── File lifecycle semantics ───────────────────────────────────────────────────
# APPEND:   idempotent ingestion — each file adds rows, MD5 dedup prevents duplicates.
#           Multiple files coexist in the datahub folder. BQ grows monotonically.
#           Examples: bank statements, movimenti contabili, accodamenti, coperti, consumi.
# SNAPSHOT: point-in-time state — latest file REPLACES previous data in BQ
#           (DELETE-INSERT by societa+date/period). Old files stay in datahub as history
#           but only the latest matters for the live model.
#           Examples: partite fornitori ("quanto dobbiamo ora"), bilancino, gasparotto budget,
#           piano finanziario (previsioni aggiornate).

LIFECYCLE_APPEND = "APPEND"
LIFECYCLE_SNAPSHOT = "SNAPSHOT"


@dataclass
class ClassificationResult:
    """What we know about a file after inspection."""

    file_path: Path
    file_type: str  # e.g. "banca_mps", "scheda_contabile", "movimenti_contabili"
    category: str  # top-level: banca, scheda_contabile, movimenti_contabili, etc.
    lifecycle: str = LIFECYCLE_APPEND  # APPEND or SNAPSHOT
    societa: Optional[str] = None  # ORTI / INTUR
    banca: Optional[str] = None  # MPS, MPS_KROSS, SELLA, INTESA, BCP
    canonical_name: Optional[str] = None  # standardized filename
    dest_folder: Optional[str] = None  # relative to datahub root
    pipeline_cmd: Optional[str] = None  # python -m ingest....
    confidence: float = 0.0  # 0.0 – 1.0
    details: dict = field(default_factory=dict)  # extra info (matched columns, etc.)

    @property
    def dest_path(self) -> Optional[Path]:
        if self.dest_folder and self.canonical_name:
            return Path(self.dest_folder) / self.canonical_name
        return None

    def summary(self) -> str:
        lifecycle_label = (
            "♻️ accumula"
            if self.lifecycle == LIFECYCLE_APPEND
            else "📸 snapshot (sostituisce)"
        )
        lines = [
            f"  File:        {self.file_path.name}",
            f"  Tipo:        {self.file_type} (confidence: {self.confidence:.0%})",
            f"  Lifecycle:   {lifecycle_label}",
            f"  Società:     {self.societa or '?'}",
        ]
        if self.banca:
            lines.append(f"  Banca:       {self.banca}")
        if self.dest_path:
            lines.append(f"  Destinazione: {self.dest_path}")
        if self.pipeline_cmd:
            lines.append(f"  Pipeline:    {self.pipeline_cmd}")
        if self.details:
            for k, v in self.details.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# ── Societa / Banca inference from filename / path ────────────────────────────

BANCA_PATTERNS = {
    "MPS_KROSS": ["KROSS", "MPS_KROSS", "MPSKROSS"],
    "MPS": ["MPS", "MONTEPASCHI", "MONTE_PASCHI", "BANCAMPS"],
    "SELLA": ["SELLA", "BANCASELLA"],
    "INTESA": ["INTESA", "SANPAOLO", "INTESASANPAOLO"],
    "BCP": ["BCP", "CREDITO_POPOLARE", "CREDITOPOPOLARE"],
}

ESOLVER_CC_MAP = {
    ("ORTI", "1"): "INTESA",
    ("ORTI", "2"): "MPS",
    ("ORTI", "3"): "MPS_KROSS",
    ("INTUR", "1"): "SELLA",
    ("INTUR", "2"): "MPS",
    ("INTUR", "3"): "INTESA",
    ("INTUR", "4"): "BCP",
}

# Reverse lookup: (cc_num, banca) → societa — for when societa is unknown
# Built from ESOLVER_CC_MAP. If a (cc, banca) combo is unique to one societa, we can infer it.
_CC_BANCA_TO_SOCIETA: dict[tuple[str, str], str] = {}
for (soc, cc), bnk in ESOLVER_CC_MAP.items():
    key = (cc, bnk)
    if key in _CC_BANCA_TO_SOCIETA:
        # Ambiguous — same cc+banca in multiple societa, can't infer
        _CC_BANCA_TO_SOCIETA[key] = ""  # empty = ambiguous
    else:
        _CC_BANCA_TO_SOCIETA[key] = soc

# Banks owned by a single societa: when we know the bank, we know the societa.
# Built from ESOLVER_CC_MAP. MPS_KROSS→ORTI, SELLA→INTUR, BCP→INTUR.
_BANCA_UNIQUE_OWNER: dict[str, str] = {}
_banca_owners: dict[str, set[str]] = {}
for (soc, _cc), bnk in ESOLVER_CC_MAP.items():
    _banca_owners.setdefault(bnk, set()).add(soc)
for bnk, owners in _banca_owners.items():
    if len(owners) == 1:
        _BANCA_UNIQUE_OWNER[bnk] = next(iter(owners))


def infer_societa(filename: str, path: Optional[Path] = None) -> Optional[str]:
    """Infer ORTI/INTUR from filename or parent directory."""
    upper = filename.upper()
    if "ORTI" in upper:
        return "ORTI"
    if "INTUR" in upper:
        return "INTUR"
    # Check parent dirs
    if path:
        for part in path.parts:
            if part.upper() == "ORTI":
                return "ORTI"
            if part.upper() == "INTUR":
                return "INTUR"
    return None


def _infer_societa_from_content(path: Path) -> Optional[str]:
    """Infer ORTI/INTUR by reading first few cells of an Excel file."""
    try:
        rows, _ = _read_xlsx_sample(path, max_rows=5)
        for row in rows[:5]:
            for cell in row[:3]:
                val = str(cell).upper() if cell else ""
                if "ORTI" in val:
                    return "ORTI"
                if "INTUR" in val:
                    return "INTUR"
    except Exception:
        pass
    return None


def infer_banca(filename: str, societa: Optional[str] = None) -> Optional[str]:
    """Infer bank from filename. Tries Cc# first, then name patterns."""
    upper = filename.upper().replace(" ", "_").replace("-", "_")

    # Try Esolver Cc# pattern: _Cc2_, _Cc3_ etc.
    cc_match = re.search(r"_CC(\d+)_", upper)
    if cc_match and societa:
        cc_num = cc_match.group(1)
        banca = ESOLVER_CC_MAP.get((societa, cc_num))
        if banca:
            return banca

    # MPS_KROSS must be checked before MPS
    for banca_id, patterns in BANCA_PATTERNS.items():
        for pat in patterns:
            if pat in upper:
                return banca_id
    return None


def infer_societa_from_cc(filename: str, banca: Optional[str] = None) -> Optional[str]:
    """Reverse-infer societa from Cc# + banca when filename doesn't contain ORTI/INTUR."""
    upper = filename.upper().replace(" ", "_").replace("-", "_")
    cc_match = re.search(r"_CC(\d+)_", upper)
    if not cc_match:
        return None
    cc_num = cc_match.group(1)

    # If we know the banca, try (cc, banca) → societa
    if banca:
        soc = _CC_BANCA_TO_SOCIETA.get((cc_num, banca), "")
        if soc:
            return soc

    # Try all societa for this cc — if only one match, it's unambiguous
    candidates = set()
    for (s, cc), b in ESOLVER_CC_MAP.items():
        if cc == cc_num:
            candidates.add(s)
    if len(candidates) == 1:
        return candidates.pop()

    return None


# ── Content-based detectors ───────────────────────────────────────────────────
# Each detector receives a file path and returns a ClassificationResult or None.
# They are tried in priority order — first match wins.


def _read_csv_sample(
    path: Path, delimiter: str = ",", max_rows: int = 5
) -> tuple[list[str], list[list[str]]]:
    """Read header + first N rows from a CSV-like file."""
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            with open(path, encoding=enc) as f:
                # Detect delimiter from first line
                first_line = f.readline()
                f.seek(0)
                if first_line.count(";") > first_line.count(","):
                    delimiter = ";"
                reader = csv.reader(f, delimiter=delimiter)
                header = next(reader, [])
                rows = []
                for i, row in enumerate(reader):
                    if i >= max_rows:
                        break
                    rows.append(row)
                return [h.strip() for h in header], rows
        except (UnicodeDecodeError, UnicodeError):
            continue
    return [], []


def _read_xlsx_sample(
    path: Path, sheet_name: Optional[str] = None, max_rows: int = 10
) -> tuple[list[list], str]:
    """Read first N rows from XLSX. Returns (rows, sheet_name_used)."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        if sheet_name and sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.active
            sheet_name = ws.title
        # Some Excel exports write dimension=A1:A1 even with data, which makes
        # read_only mode stop after row 1. Force a full scan.
        ws.reset_dimensions()
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            rows.append(list(row))
        wb.close()
        return rows, sheet_name
    except Exception as e:
        log.debug(f"Failed to read XLSX {path}: {e}")
        return [], ""


def _read_xls_sample(path: Path, max_rows: int = 10) -> list[list]:
    """Read first N rows from XLS (binary Excel)."""
    try:
        import xlrd

        wb = xlrd.open_workbook(str(path))
        ws = wb.sheet_by_index(0)
        rows = []
        for i in range(min(ws.nrows, max_rows)):
            rows.append([ws.cell_value(i, j) for j in range(ws.ncols)])
        return rows
    except Exception as e:
        log.debug(f"Failed to read XLS {path}: {e}")
        return []


def _cols_upper(row: list) -> list[str]:
    """Normalize a row to uppercase strings for matching."""
    return [str(c).strip().upper() if c is not None else "" for c in row]


def _has_columns(row_upper: list[str], required: list[str]) -> bool:
    """Check if all required column keywords appear in the row."""
    return all(any(req in col for col in row_upper) for req in required)


# ── Individual detectors ──────────────────────────────────────────────────────


def detect_scheda_contabile(path: Path) -> Optional[ClassificationResult]:
    """Esolver scheda contabile — CSV (semicolon) or XLSX with Saldo in UdC."""
    ext = path.suffix.lower()
    societa = infer_societa(path.name, path)

    if ext == ".csv":
        header, rows = _read_csv_sample(path, delimiter=";")
        header_upper = [h.upper() for h in header]
        # Key signature: "SALDO IN UDC" or semicolon CSV with dare/avere/saldo structure
        if any("SALDO" in h and "UDC" in h for h in header_upper) or (
            any("DARE" in h for h in header_upper)
            and any("AVERE" in h for h in header_upper)
            and any("SALDO" in h for h in header_upper)
        ):
            banca = infer_banca(path.name, societa)
            if not societa:
                societa = infer_societa_from_cc(path.name, banca)
            return _build_scheda_result(path, societa, banca, confidence=0.95)

        # Esolver CSV auto-naming: *_Conto_*_Cc*_Saldo*
        if re.search(r"_Conto_.*_Cc\d+_Saldo", path.name):
            banca = infer_banca(path.name, societa)
            if not societa:
                societa = infer_societa_from_cc(path.name, banca)
            return _build_scheda_result(path, societa, banca, confidence=0.90)

    elif ext == ".xlsx":
        rows, sheet = _read_xlsx_sample(path)
        for row in rows[:5]:
            row_upper = _cols_upper(row)
            # La scheda contabile Esolver ha esattamente l'header "Saldo in UdC"
            # — match più stretto di "SALDO" + "UDC" su celle separate, che
            # falsamente matchava le partite fornitori ("SALDO SCADENZA IN UDC").
            if any("SALDO IN UDC" in c for c in row_upper) or (
                any("DARE" in c for c in row_upper)
                and any("AVERE" in c for c in row_upper)
                and any("SALDO" in c for c in row_upper)
                and any("REGISTR" in c for c in row_upper)
            ):
                banca = infer_banca(path.name, societa)
                if not societa:
                    societa = infer_societa_from_cc(path.name, banca)
                return _build_scheda_result(path, societa, banca, confidence=0.90)

        # Filename fallback
        if "scheda" in path.name.lower() and "contabil" in path.name.lower():
            banca = infer_banca(path.name, societa)
            if not societa:
                societa = infer_societa_from_cc(path.name, banca)
            return _build_scheda_result(path, societa, banca, confidence=0.70)

    return None


def _build_scheda_result(
    path: Path, societa: Optional[str], banca: Optional[str], confidence: float
) -> ClassificationResult:
    today = datetime.now().strftime("%Y%m%d")
    soc = societa or "UNKNOWN"
    bnk = banca or "UNKNOWN"
    ext = path.suffix.lower()
    canonical = f"{soc}_SCHEDA_{bnk}_{today}{ext}"
    dest = f"registro_banca_esolver/{soc}" if societa else "registro_banca_esolver"
    pipeline = f"python -m ingest.flussi.ingest_scheda_contabile --file {{dest_file}}"
    if societa:
        pipeline += f" --societa {societa}"
    if banca:
        pipeline += f" --banca {banca}"
    return ClassificationResult(
        file_path=path,
        file_type=f"scheda_contabile_{bnk.lower()}",
        category="scheda_contabile",
        societa=societa,
        banca=banca,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


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


def _build_movimenti_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    ext = path.suffix  # preserve original extension
    canonical = f"{soc}_LISTAMOVCONT{ext.upper()}"
    dest = f"movimenti_contabili/{soc}" if societa else "movimenti_contabili"
    pipeline = (
        f"python -m ingest.flussi.ingest_movimenti_contabili --file {{dest_file}}"
    )
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


def detect_partite_fornitori(path: Path) -> Optional[ClassificationResult]:
    """Esolver Situazione Partite Fornitori — XLSX."""
    ext = path.suffix.lower()
    if ext != ".xlsx":
        return None

    # Filename check
    name_upper = path.name.upper()
    if "PARTIT" in name_upper and ("FORNI" in name_upper or "APERTE" in name_upper):
        societa = infer_societa(path.name, path)
        if not societa:
            societa = _infer_societa_from_content(path)
        return _build_partite_result(path, societa, confidence=0.90)

    # Content check: look for fornitore columns
    rows, sheet = _read_xlsx_sample(path, max_rows=15)
    for row in rows[:10]:
        row_upper = _cols_upper(row)
        joined = " ".join(row_upper)
        if ("FORNITORE" in joined or "RAG.SOCIALE" in joined) and (
            "SCADENZA" in joined or "RESIDUO" in joined or "PAGAMENTO" in joined
        ):
            societa = infer_societa(path.name, path)
            if not societa:
                societa = _infer_societa_from_content(path)
            return _build_partite_result(path, societa, confidence=0.85)

    return None


def _build_partite_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    today = datetime.now().strftime("%Y%m%d")
    canonical = f"{soc}_PARTITE_FORNITORI_{today}.xlsx"
    dest = f"partite_fornitori/{soc}" if societa else "partite_fornitori"
    pipeline = f"python -m ingest.flussi.ingest_partite_aperte --file {{dest_file}}"
    if societa:
        pipeline += f" --societa {societa}"
    return ClassificationResult(
        file_path=path,
        file_type="partite_fornitori",
        category="partite_fornitori",
        lifecycle=LIFECYCLE_SNAPSHOT,
        societa=societa,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


def detect_bilancino(path: Path) -> Optional[ClassificationResult]:
    """Bilancio di verifica Esolver — XLS."""
    ext = path.suffix.lower()
    if ext != ".xls":
        return None

    name_upper = path.name.upper()
    # Pattern: MESE_ESOLVER.xls or MESEANNOESOLVER.xls
    if "ESOLVER" in name_upper:
        societa = infer_societa(path.name, path)
        return _build_bilancino_result(path, societa, confidence=0.90)

    # Content check: codice_conto dotted (57.09.13) + dare/avere/saldo + livello "Si"
    rows = _read_xls_sample(path)
    for row in rows[1:5]:
        if len(row) >= 12:
            col0 = str(row[0]).strip()
            col10 = str(row[10]).strip() if len(row) > 10 else ""
            if re.match(r"^\d{2}\.\d{2}\.\d{2}$", col0) and col10.lower() == "si":
                societa = infer_societa(path.name, path)
                return _build_bilancino_result(path, societa, confidence=0.85)

    return None


def _build_bilancino_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    # Keep original name — it usually has the month
    canonical = path.name
    dest = f"bilancino/{soc}" if societa else "bilancino"
    pipeline = f"python -m ingest.flussi.ingest_bilancino --file {{dest_file}}"
    if societa:
        pipeline += f" --societa {societa}"
    return ClassificationResult(
        file_path=path,
        file_type="bilancino",
        category="bilancino",
        lifecycle=LIFECYCLE_SNAPSHOT,
        societa=societa,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


def detect_gasparotto(path: Path) -> Optional[ClassificationResult]:
    """Gasparotto Master Completo — XLSX with 'Budget' sheet."""
    ext = path.suffix.lower()
    if ext != ".xlsx":
        return None

    name_upper = path.name.upper()
    if "MASTER" in name_upper and ("COMPLETO" in name_upper or "INDICI" in name_upper):
        societa = infer_societa(path.name, path) or "ORTI"  # Default ORTI
        return _build_gasparotto_result(path, societa, confidence=0.95)

    # Check for Budget sheet
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True)
        sheets = [s.upper() for s in wb.sheetnames]
        wb.close()
        if "BUDGET" in sheets and ("CONTO ECONOMICO" in sheets or "CE" in sheets):
            societa = infer_societa(path.name, path) or "ORTI"
            return _build_gasparotto_result(path, societa, confidence=0.85)
    except Exception:
        pass

    return None


def _build_gasparotto_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "ORTI"
    today = datetime.now().strftime("%Y%m%d")
    # Keep descriptive name but standardize
    canonical = f"Master_Completo_{soc}_{today}.xlsx"
    dest = "gasparotto"
    pipeline = f"python -m ingest.flussi.ingest_gasparotto --file {{dest_file}} --societa {soc}"
    return ClassificationResult(
        file_path=path,
        file_type="gasparotto_budget",
        category="gasparotto",
        lifecycle=LIFECYCLE_SNAPSHOT,
        societa=soc,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


def detect_piano_finanziario(path: Path) -> Optional[ClassificationResult]:
    """Piano Finanziario XLSX — has 'Piano Finanziario' sheet or voce labels."""
    ext = path.suffix.lower()
    if ext != ".xlsx":
        return None

    name_upper = path.name.upper()
    if "PIANO" in name_upper and "FINANZIARIO" in name_upper:
        societa = infer_societa(path.name, path)
        return _build_pf_result(path, societa, confidence=0.95)

    # Check sheet name
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True)
        sheets_upper = [s.upper() for s in wb.sheetnames]
        wb.close()
        if any("PIANO" in s and "FINANZIARIO" in s for s in sheets_upper):
            societa = infer_societa(path.name, path)
            return _build_pf_result(path, societa, confidence=0.90)
    except Exception:
        pass

    return None


def _build_pf_result(
    path: Path, societa: Optional[str], confidence: float
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    today = datetime.now().strftime("%Y%m%d")
    # Extract month from original name if possible (e.g. "03_mar2026")
    m = re.search(r"(\d{2})_(\w{3}\d{4})", path.name)
    month_tag = m.group(0) if m else today
    canonical = f"{soc}_Piano_Finanziario_{month_tag}.xlsx"
    dest = f"piani_finanziari/{soc}" if societa else "piani_finanziari"
    pipeline = (
        f"python -m ingest.flussi.ingest_piano_finanziario_xlsx --file {{dest_file}}"
    )
    if societa:
        pipeline += f" --societa {societa}"
    return ClassificationResult(
        file_path=path,
        file_type="piano_finanziario",
        category="piano_finanziario",
        lifecycle=LIFECYCLE_SNAPSHOT,
        societa=societa,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


def detect_banca(path: Path) -> Optional[ClassificationResult]:
    """Bank statement files — MPS, Sella, Intesa XLS/XLSX/CSV."""
    ext = path.suffix.lower()
    if ext not in (".xls", ".xlsx", ".csv"):
        return None

    societa = infer_societa(path.name, path)
    banca = infer_banca(path.name, societa)
    # If banca is known but societa is not, infer from unique owner (KROSS→ORTI, SELLA/BCP→INTUR).
    if banca and not societa:
        societa = _BANCA_UNIQUE_OWNER.get(banca)
    # Last resort: read content (e.g. "Ragione sociale: ORTI SRL" header in INTESA exports).
    if not societa and ext in (".xlsx",):
        societa = _infer_societa_from_content(path)

    if ext == ".csv":
        header, rows = _read_csv_sample(path)
        header_upper = [h.upper() for h in header]

        # Sella CSV: has "Codice identificativo" + "Data operazione" + "Debito" + "Credito"
        if _has_columns(
            header_upper, ["CODICE IDENTIFICATIVO", "DATA OPERAZIONE", "DEBITO"]
        ):
            banca = banca or "SELLA"
            return _build_banca_result(path, societa, banca, confidence=0.95)

    elif ext == ".xls":
        rows = _read_xls_sample(path, max_rows=15)
        for row in rows[:10]:
            row_upper = _cols_upper(row)
            # MPS: DATA + VALUTA + DARE + AVERE + DESCRIZIONE OPERAZIONI
            if _has_columns(row_upper, ["DATA", "VALUTA", "DARE", "AVERE"]):
                banca = banca or "MPS"
                return _build_banca_result(path, societa, banca, confidence=0.85)
            # Sella XLS: CODICE IDENTIFICATIVO + DATA OPERAZIONE + DEBITO
            if _has_columns(row_upper, ["CODICE IDENTIFICATIVO", "DATA OPERAZIONE"]):
                banca = banca or "SELLA"
                return _build_banca_result(path, societa, banca, confidence=0.85)

    elif ext == ".xlsx":
        rows, sheet = _read_xlsx_sample(path, max_rows=15)
        for row in rows[:10]:
            row_upper = _cols_upper(row)
            # Intesa (check before MPS: DARE+AVERE is more specific than IMPORTO,
            # and Intesa exports include "Importo Origine/Regolato" columns that
            # would otherwise match the MPS pattern).
            if _has_columns(
                row_upper, ["DATA CONTABILE", "DATA VALUTA", "DARE", "AVERE"]
            ):
                banca = banca or "INTESA"
                return _build_banca_result(path, societa, banca, confidence=0.90)
            # MPS 2026: DATA CONT. + DATA VAL. + DESCRIZIONE + IMPORTO(€), no DARE/AVERE
            if _has_columns(
                row_upper, ["DATA CONT", "DATA VAL", "IMPORTO"]
            ) and not _has_columns(row_upper, ["DARE", "AVERE"]):
                banca = banca or "MPS"
                return _build_banca_result(path, societa, banca, confidence=0.90)
            # Generic bank: DATA + DARE + AVERE
            if _has_columns(row_upper, ["DATA", "DARE", "AVERE"]):
                return _build_banca_result(path, societa, banca, confidence=0.70)

    return None


def _build_banca_result(
    path: Path,
    societa: Optional[str],
    banca: Optional[str],
    confidence: float,
) -> ClassificationResult:
    soc = societa or "UNKNOWN"
    bnk = banca or "UNKNOWN"
    today = datetime.now().strftime("%Y%m%d")
    ext = path.suffix.lower()
    canonical = f"{soc}_{bnk}_{today}{ext}"
    if societa and banca:
        dest = f"homebanking/{soc}/{bnk}"
    elif societa:
        dest = f"homebanking/{soc}"
    else:
        dest = "homebanking"
    # Bank ingest uses --source dir, not single file — just indicate pipeline
    pipeline = (
        f"python -m ingest.banca.ingest --datahub {{datahub}} --source {{staging}}"
    )
    return ClassificationResult(
        file_path=path,
        file_type=f"banca_{bnk.lower()}",
        category="banca",
        societa=societa,
        banca=banca,
        canonical_name=canonical,
        dest_folder=dest,
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


def detect_accodamenti(path: Path) -> Optional[ClassificationResult]:
    """HotelCube PMS TXT files — pipe-delimited with specific prefixes."""
    ext = path.suffix.lower()
    if ext != ".txt":
        return None

    name = path.name
    # H_*_Corrispettivi.txt, R_*_Fatture.txt, C_*_Movimenti.txt
    if re.match(
        r"^[HRC]_.*_(Corrispettivi|Fatture|Movimenti|Clienti)\.txt$",
        name,
        re.IGNORECASE,
    ):
        societa = "ORTI"  # HotelCube = always ORTI
        bu_prefix = name[0].upper()
        bu_map = {"H": "HOTEL", "R": "RESIDENCE", "C": "CVM"}
        bu = bu_map.get(bu_prefix, "HOTEL")
        return ClassificationResult(
            file_path=path,
            file_type=f"accodamenti_{bu.lower()}",
            category="accodamenti",
            societa=societa,
            canonical_name=name,  # Keep original name (already standard)
            dest_folder="accodamenti/ORTI",
            pipeline_cmd="python -m ingest.banca.ingest_accodamenti --datahub {datahub}",
            confidence=0.95,
        )

    # Fallback: check for pipe-delimited content
    try:
        with open(path, encoding="latin-1") as f:
            first_line = f.readline()
            if "|" in first_line and first_line.count("|") >= 3:
                return ClassificationResult(
                    file_path=path,
                    file_type="accodamenti",
                    category="accodamenti",
                    societa="ORTI",
                    canonical_name=name,
                    dest_folder="accodamenti/ORTI",
                    pipeline_cmd="python -m ingest.banca.ingest_accodamenti --datahub {datahub}",
                    confidence=0.60,
                )
    except Exception:
        pass

    return None


def detect_coperti(path: Path) -> Optional[ClassificationResult]:
    """Coperti giornalieri — CSV (Google Form) or XLSX with meal columns."""
    ext = path.suffix.lower()
    if ext not in (".csv", ".xlsx"):
        return None

    name_upper = path.name.upper()
    if "COPERT" in name_upper or "SCARICO" in name_upper:
        return _build_coperti_result(path, confidence=0.90)

    if ext == ".csv":
        header, _ = _read_csv_sample(path)
        header_upper = [h.upper() for h in header]
        joined = " ".join(header_upper)
        if any(
            meal in joined
            for meal in ["BREAKFAST", "LUNCH", "DINNER", "COLAZIONE", "PRANZO", "CENA"]
        ):
            return _build_coperti_result(path, confidence=0.85)

    elif ext == ".xlsx":
        try:
            from openpyxl import load_workbook

            wb = load_workbook(path, read_only=True)
            sheets_upper = [s.upper() for s in wb.sheetnames]
            wb.close()
            if any(
                any(meal in s for meal in ["BRK", "LUNCH", "DINNER", "SCARICO"])
                for s in sheets_upper
            ):
                return _build_coperti_result(path, confidence=0.85)
        except Exception:
            pass

    return None


def _build_coperti_result(path: Path, confidence: float) -> ClassificationResult:
    today = datetime.now().strftime("%Y%m%d")
    ext = path.suffix.lower()
    canonical = f"coperti_{today}{ext}"
    return ClassificationResult(
        file_path=path,
        file_type="coperti",
        category="coperti",
        societa="ORTI",
        canonical_name=canonical,
        dest_folder="coperti",
        pipeline_cmd=f"python -m ingest.flussi.ingest_coperti --file {{dest_file}}",
        confidence=confidence,
    )


def detect_economato(path: Path) -> Optional[ClassificationResult]:
    """Consumi economato — XLSX with Codice/Descrizione/Quantita/Euro columns."""
    ext = path.suffix.lower()
    if ext != ".xlsx":
        return None

    name_upper = path.name.upper()
    if (
        "CONSUMI" in name_upper
        or "ECONOMATO" in name_upper
        or "SITUAZIONECONSUMI" in name_upper
    ):
        is_consolidato = (
            "SITUAZIONECONSUMI" in name_upper.replace(" ", "")
            or "CONSOLIDAT" in name_upper
        )
        return _build_economato_result(path, is_consolidato, confidence=0.90)

    # Content check
    rows, sheet = _read_xlsx_sample(path)
    for row in rows[:5]:
        row_upper = _cols_upper(row)
        if _has_columns(
            row_upper, ["CODICE", "DESCRIZIONE", "QUANTITA"]
        ) or _has_columns(row_upper, ["CODICE", "DESCRIZIONE", "EURO"]):
            is_consolidato = len(rows) > 3 and any(
                "REPARTO" in str(c).upper() for r in rows[:3] for c in r
            )
            return _build_economato_result(path, is_consolidato, confidence=0.80)

    return None


def _build_economato_result(
    path: Path, is_consolidato: bool, confidence: float
) -> ClassificationResult:
    today = datetime.now().strftime("%Y%m%d")
    if is_consolidato:
        canonical = f"ECO_Consolidato_{today}.xlsx"
        pipeline = f"python -m ingest.flussi.ingest_consumi_economato_consolidato --file {{dest_file}}"
    else:
        canonical = f"ECO_{today}.xlsx"
        pipeline = (
            f"python -m ingest.flussi.ingest_consumi_economato --source {{dest_file}}"
        )
    return ClassificationResult(
        file_path=path,
        file_type="economato_consolidato" if is_consolidato else "economato",
        category="economato",
        societa="ORTI",
        canonical_name=canonical,
        dest_folder="economato",
        pipeline_cmd=pipeline,
        confidence=confidence,
    )


# ── Master classifier ─────────────────────────────────────────────────────────

# Priority order matters: more specific detectors first
DETECTORS = [
    detect_accodamenti,  # TXT pipe-delimited — very specific
    detect_movimenti_contabili,  # XLS LISTAMOVCONT — very specific
    detect_partite_fornitori,  # XLSX filename PARTIT+FORNI — very specific (must precede scheda)
    detect_scheda_contabile,  # CSV semicolon or XLSX with Saldo in UdC
    detect_bilancino,  # XLS with dotted conto + livello "Si"
    detect_gasparotto,  # XLSX with Budget sheet
    detect_piano_finanziario,  # XLSX with Piano Finanziario sheet
    detect_coperti,  # CSV/XLSX with meal columns
    detect_economato,  # XLSX with codice/quantita/euro
    detect_banca,  # XLS/XLSX/CSV bank statements — most generic, last
]


def classify(path: Path) -> ClassificationResult:
    """
    Classify a single file. Returns the best-matching ClassificationResult.
    If no detector matches, returns an UNKNOWN result.
    """
    path = path.expanduser().resolve()
    if not path.exists():
        return ClassificationResult(
            file_path=path,
            file_type="error",
            category="error",
            confidence=0.0,
            details={"error": "File not found"},
        )

    if path.suffix.lower() not in (".csv", ".xls", ".xlsx", ".txt", ".tsv"):
        return ClassificationResult(
            file_path=path,
            file_type="unknown",
            category="unknown",
            confidence=0.0,
            details={"error": f"Unsupported extension: {path.suffix}"},
        )

    for detector in DETECTORS:
        try:
            result = detector(path)
            if result and result.confidence > 0:
                return result
        except Exception as e:
            log.warning(f"Detector {detector.__name__} failed on {path.name}: {e}")
            continue

    return ClassificationResult(
        file_path=path,
        file_type="unknown",
        category="unknown",
        confidence=0.0,
        details={"note": "No detector matched this file"},
    )


def classify_batch(paths: list[Path]) -> list[ClassificationResult]:
    """Classify multiple files."""
    return [classify(p) for p in paths]


# ── Route (copy + rename) ────────────────────────────────────────────────────

# Local cache mirrors for pipelines that read from a staging dir instead of the
# datahub directly. Keyed by classify category. Structure mirrors dest_folder
# (e.g. banca → homebanking/{societa}/ → banche_staging/{societa}/).
_CACHE_BASE = Path.home() / ".cache" / "hotelops"
CACHE_MIRRORS = {
    "banca": _CACHE_BASE / "banche_staging",
}


def _mirror_to_cache(result: ClassificationResult) -> Optional[Path]:
    """Mirror a routed file into the local cache for pipelines that read from
    a staging dir (e.g. ingest.banca.ingest). Returns the cache path or None
    if this category has no cache mirror.

    The cache path strips the top-level datahub folder (e.g. 'homebanking/')
    from dest_folder, preserving only the societa subfolder so the staging
    layout matches what fetch_drive.py rclone-syncs.
    """
    cache_base = CACHE_MIRRORS.get(result.category)
    if cache_base is None or not result.dest_folder or not result.canonical_name:
        return None
    # dest_folder is e.g. "homebanking/ORTI" — we want "ORTI" under cache_base.
    parts = Path(result.dest_folder).parts
    subpath = Path(*parts[1:]) if len(parts) > 1 else Path()
    cache_dir = cache_base / subpath
    cache_file = cache_dir / result.canonical_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.file_path, cache_file)
    log.info(f"Mirrored to cache: {result.file_path.name} → {cache_file}")
    return cache_file


def route_file(
    result: ClassificationResult,
    datahub: Path,
    dry_run: bool = False,
    use_rclone: bool = True,
) -> Optional[Path]:
    """
    Copy file to its canonical datahub location via rclone (Drive) or local copy.

    Destination subpath: {INGRESSO_PREFIX}/{dest_folder}/{canonical_name}
    e.g. ingresso/homebanking/ORTI/ORTI_MPS_20260323.xls

    For categories with a CACHE_MIRRORS entry (e.g. banca), also mirrors the
    file into the local staging cache so downstream ingest pipelines that read
    from staging (instead of the datahub) can see it.

    Returns the destination path (local staging copy), or None if routing not possible.
    """
    if (
        result.category == "unknown"
        or not result.dest_folder
        or not result.canonical_name
    ):
        log.warning(
            f"Cannot route {result.file_path.name}: unclassified or missing destination"
        )
        return None

    # Full remote subpath: ingresso/{category}/{societa}/
    remote_dest = f"{INGRESSO_PREFIX}/{result.dest_folder}"

    if dry_run:
        log.info(
            f"[DRY-RUN] Would rclone copy {result.file_path.name} "
            f"→ {remote_dest}/{result.canonical_name}"
        )
        if result.category in CACHE_MIRRORS:
            log.info(
                f"[DRY-RUN] Would mirror to cache: "
                f"{CACHE_MIRRORS[result.category]}/.../{result.canonical_name}"
            )
        # Return a synthetic local path for downstream compatibility
        return datahub / INGRESSO_PREFIX / result.dest_folder / result.canonical_name

    if use_rclone:
        # Copy to a temp location with canonical name, then rclone to Drive
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / result.canonical_name
            shutil.copy2(result.file_path, staged)
            try:
                rclone_copy_to_remote(staged, remote_dest, timeout=60)
            except RcloneError as e:
                log.error(f"rclone failed: {e}")
                return None
        log.info(
            f"Routed (rclone): {result.file_path.name} "
            f"→ {remote_dest}/{result.canonical_name}"
        )
        _mirror_to_cache(result)
    else:
        # Fallback: local copy (mount locale)
        dest_dir = datahub / INGRESSO_PREFIX / result.dest_folder
        dest_file = dest_dir / result.canonical_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest_file.exists():
            stem = dest_file.stem
            ext = dest_file.suffix
            i = 1
            while dest_file.exists():
                dest_file = dest_dir / f"{stem}_{i}{ext}"
                i += 1
        shutil.copy2(result.file_path, dest_file)
        log.info(f"Routed (local): {result.file_path.name} → {dest_file}")
        _mirror_to_cache(result)
        return dest_file

    return datahub / INGRESSO_PREFIX / result.dest_folder / result.canonical_name


# ── Ingest (trigger pipeline) ────────────────────────────────────────────────


def _rclone_sync_to_local(remote_dest: str, canonical_name: str) -> Optional[Path]:
    """Sync a single file from Drive to local staging via rclone."""
    staging_dir = Path.home() / ".cache" / "hotelops" / "ingest_staging"
    local_file = staging_dir / canonical_name

    remote_subpath = f"{INGRESSO_PREFIX}/{remote_dest}/{canonical_name}"
    try:
        rclone_copyto(remote_subpath, local_file, timeout=60)
    except RcloneError as e:
        log.error(f"rclone sync failed: {e}")
        return None
    return local_file


def run_ingest(
    result: ClassificationResult,
    dest_file: Path,
    datahub: Path,
    dry_run: bool = False,
) -> bool:
    """
    Run the appropriate ingest pipeline for a classified + routed file.
    Syncs file from Drive via rclone to local staging, then runs pipeline.
    Returns True on success, False on failure.
    """
    if not result.pipeline_cmd:
        log.warning(f"No pipeline defined for {result.file_type}")
        return False

    import shlex

    # Sync file from Drive to local staging via rclone
    if not dry_run and result.dest_folder and result.canonical_name:
        local_file = _rclone_sync_to_local(result.dest_folder, result.canonical_name)
        if local_file and local_file.exists():
            ingest_file = local_file
        else:
            log.warning(f"rclone sync failed, using dest_file path: {dest_file}")
            ingest_file = dest_file
    else:
        ingest_file = dest_file

    # For banca pipeline: staging dir is parent of the local file
    staging_dir = ingest_file.parent if ingest_file else dest_file.parent

    substitutions = {
        "dest_file": str(ingest_file),
        "datahub": str(datahub),
        "staging": str(staging_dir),
    }
    # Tokenize the template first, then substitute placeholders per-token so
    # that path values containing spaces don't get split into multiple argv.
    argv = [tok.format(**substitutions) for tok in shlex.split(result.pipeline_cmd)]

    if dry_run:
        log.info(f"[DRY-RUN] Would run: {argv}")
        return True

    log.info(f"Running pipeline: {argv}")
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode == 0:
            log.info(f"Pipeline OK: {result.file_type}")
            return True
        else:
            log.error(f"Pipeline FAILED ({proc.returncode}): {proc.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"Pipeline TIMEOUT: {argv}")
        return False
    except Exception as e:
        log.error(f"Pipeline ERROR: {e}")
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Classify, route, and ingest hotelops data files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m ingest.classify ~/Desktop/MPSORTI_schedacontabile.xlsx
  python -m ingest.classify ~/Desktop/*.xls* --route
  python -m ingest.classify ~/Desktop/report.xlsx --route --ingest
  python -m ingest.classify ~/Desktop/*.csv --route --ingest --dry-run
        """,
    )
    parser.add_argument("files", nargs="+", type=Path, help="Files to classify")
    parser.add_argument(
        "--route",
        action="store_true",
        help="Copy files to their canonical datahub location",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Run the appropriate ingest pipeline after routing",
    )
    parser.add_argument(
        "--datahub",
        type=Path,
        default=DEFAULT_DATAHUB,
        help=f"Datahub root (default: {DEFAULT_DATAHUB})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show plan without executing"
    )
    parser.add_argument(
        "--locale",
        action="store_true",
        help="Smista sul mount locale del datahub (niente rclone verso Drive remoto)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Expand globs if shell didn't
    files = []
    for f in args.files:
        if "*" in str(f) or "?" in str(f):
            import glob

            files.extend(Path(p) for p in glob.glob(str(f)))
        else:
            files.append(f)

    if not files:
        print("Nessun file trovato.")
        sys.exit(1)

    results = classify_batch(files)

    # Display results
    print(f"\n{'=' * 70}")
    print(f"  CLASSIFICAZIONE FILE — {len(results)} file analizzati")
    print(f"{'=' * 70}\n")

    ok_count = 0
    unknown_count = 0
    routed_count = 0
    ingested_count = 0

    for r in results:
        if r.category == "unknown" or r.category == "error":
            unknown_count += 1
            print(f"❓ {r.file_path.name}")
            if r.details:
                for k, v in r.details.items():
                    print(f"     {k}: {v}")
            print()
            continue

        ok_count += 1
        emoji = "✅" if r.confidence >= 0.8 else "⚠️"
        print(f"{emoji} {r.file_path.name}")
        print(r.summary())

        dest_file = None
        if args.route:
            dest_file = route_file(
                r,
                args.datahub,
                dry_run=args.dry_run,
                use_rclone=not args.locale,
            )
            if dest_file:
                routed_count += 1
                prefix = "[DRY-RUN] " if args.dry_run else ""
                print(
                    f"  {prefix}→ {dest_file.relative_to(args.datahub) if not args.dry_run else dest_file}"
                )

        if args.ingest and dest_file:
            success = run_ingest(r, dest_file, args.datahub, dry_run=args.dry_run)
            if success:
                ingested_count += 1

        print()

    # Summary
    print(f"{'─' * 70}")
    print(
        f"  Classificati: {ok_count}/{len(results)}  |  Non riconosciuti: {unknown_count}"
    )
    if args.route:
        print(f"  Smistati: {routed_count}  |  Ingeriti: {ingested_count}")
    print(f"{'─' * 70}\n")


if __name__ == "__main__":
    main()
