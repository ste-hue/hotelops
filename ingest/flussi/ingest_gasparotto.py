#!/usr/bin/env python3
"""
Gasparotto Master Budget → BigQuery f_budget_mensile (fonte=GASPAROTTO).

Reads the "Budget" sheet of the Gasparotto Master XLSX. Extracts every data row
(ricavi + acquisti + costi produttivi + personale + costi commerciali +
costi amministrativi + oneri tributari + oneri finanziari) with its codice_conto,
descrizione, tipo (F/V/P/IP/X), and Previsione Anno 2026.

Account codes (codice_conto) come from:
  1. Column A if present (about 49 rows)
  2. Cross-reference against Conto Economico sheet by exact description match
  3. Manual mapping table for remaining ~24 rows

Monthly distribution: seasonality-weighted from d_coefficienti_stagionalita (falls back to 1/12 if unavailable).
No BU split (Gasparotto is company-level — use MAPPATURA for BU detail).

Output: f_budget_mensile rows with fonte=GASPAROTTO
Strategy: DELETE-INSERT for anno=ANNO AND fonte='GASPAROTTO'

Usage:
    python -m ingest.flussi.ingest_gasparotto --dry-run
    python -m ingest.flussi.ingest_gasparotto \\
        --file "/path/to/Master Completo Indici 2025 ORTI SRL_Budget26.xlsx"
    python -m ingest.flussi.ingest_gasparotto \\
        --file "/path/to/file.xlsx" --societa INTUR
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.schemas import BudgetMensileRow, validate_batch

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import PROJECT

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_FILE = Path(
    "/Users/stefanodellapietra/Desktop/WORK/artifacts/"
    "gasparotto_materialiereport/"
    "Master Completo Indici 2025 ORTI SRL_Budget26_AGG 17.03.xlsx"
)

BQ_TABLE = f"{PROJECT}.hotelops.f_budget_mensile"
ANNO = 2026
FONTE = "GASPAROTTO"

# ── Section classification ────────────────────────────────────────────────────

# Maps sections in the Budget sheet to (categoria_ce, default_tipo_costo)
SECTION_CATEGORY = {
    "RICAVI": ("Ricavi", "IP"),
    "ACQUISTI": ("Acquisti", "V"),
    "SERVIZI_PRODUZIONE": ("Costi Produttivi", "F"),
    "PERSONALE": ("Costo del Personale", "P"),
    "COSTI_COMMERCIALI": ("Costi Commerciali", "V"),
    "COSTI_AMMINISTRATIVI": ("Costi Amministrativi", "F"),
    "ONERI_TRIBUTARI": ("Oneri Tributari", "F"),
    "ONERI_FINANZIARI": ("Oneri Finanziari", "X"),
}

# ── Section transition keywords (in order of appearance in the sheet) ─────────

SECTION_TRANSITIONS = [
    ("TOTALE RICAVI", "ACQUISTI"),
    ("TOTALE ACQUISTI", "SERVIZI_PRODUZIONE"),
    ("COSTO MATERIE PRIME", "SERVIZI_PRODUZIONE"),  # Also resets to servizi
    ("COSTI PRODUTTIVI", "PERSONALE"),
    ("COSTO DEL VENDUTO", "PERSONALE"),
    ("1°  MARGINE", "PERSONALE"),
    ("COSTO DEL PERSONALE", "COSTI_COMMERCIALI"),
    ("COSTI COMMERCIALI", "COSTI_AMMINISTRATIVI"),
    ("COSTI AMMINISTRATIVI", "ONERI_TRIBUTARI"),
    ("AMMORTAMENTI", "ONERI_TRIBUTARI"),
    ("ONERI TRIBUTARI", "ONERI_FINANZIARI"),
    ("TOTALE COSTI OPERATIVI", "ONERI_FINANZIARI"),
    ("EBITDA", "ONERI_FINANZIARI"),
    ("2°  MARGINE", "ONERI_FINANZIARI"),
    ("ONERI FINANZIARI", None),
    ("PROVENTI FINANZIARI", None),
    ("RISULTATO", None),
]

# ── Skip patterns (section headers, totals, metadata) ────────────────────────

SKIP_PATTERNS = [
    "TOTALE",
    "SUBTOTALE",
    "MARGINE",
    "EBITDA",
    "COSTO DEL VENDUTO",
    "COSTI PRODUTTIVI",
    "MAGAZZINO RIM.",
    "RISULTATO",
    "UTILE",
    "PERDITA",
    "COSTI COMMERCIALI",
    "COSTI AMMINISTRATIVI",
    "AMMORTAMENTI",
    "AMM. MAT",
    "AMM. IMM",
    "ONERI TRIBUTARI",
    "ONERI FINANZIARI",
    "PROVENTI",
    "COSTO DEL PERSON",
    "1°",
    "2°",
    "%ALE PUNTO",
    "FATTURATO MINIMO",
    "GIORNO BEP",
    "DATA BEP",
    "COSTI EXTRA",
    "COSTO MATERIE PRIME",
    "TOTALE COSTI",
]

# ── Manual mapping: description → codice_conto ──────────────────────────────
# These rows appear in the Budget sheet WITHOUT a codice_conto in column A.
# Mappings sourced from:
#   1. Cross-reference with Conto Economico sheet (exact description match)
#   2. Standard Italian piano dei conti hierarchy for remaining entries

MANUAL_COD_MAP: dict[str, str] = {
    # Acquisti / servizi produzione
    "Acq.materiali di consumo (att.servizi)": "55.03.03",
    "Oneri accessori su acquisti (att.serv.)": "55.03.05",
    "Acquisto beni strument.inf.516,46 ded.": "55.07.01.01",
    "Acq.beni strum.inf.516,46 veic.prom.dip.": "55.07.01.15",
    "Attrezzatura minuta": "55.07.03",
    "Materiali manutenzioni diverse": "55.07.13",
    "Materiali manutenzione totalm.deducibili": "55.07.25",
    "Allestimento (piante, fiori ecc)": "55.07.90",
    "Acq.beni materiali per produz. servizi": "55.03.01",
    "Cancelleria varia": "55.07.17",
    # Trasporti / telefonia / utenze
    "Trasporti su acquisti": "57.05.01.01",
    "Trasporti di terzi (attività servizi)": "57.05.01.03",
    "Spese telefoniche ordinarie": "57.09.01.01",
    "Costi gestione reti interne": "57.09.09",
    "Energia elettrica": "57.09.13.01",
    "Acqua potabile": "57.09.17",
    "Gas": "57.09.19",
    "Spese di sanificazione": "57.09.90",
    # Manutenzione
    "Altre spese manutenzione beni propri": "57.11.07.01",
    "Altre spese manutenzione beni di terzi": "57.11.07.90",
    "Spese manut.impianti e macchin.di terzi": "57.11.15",
    "Spese manutenzione attrezzature di terzi": "57.11.17",
    "Spese manutenzione veicoli di terzi": "59.03.17.99",
    "Spese manut.su immobili di terzi": "57.13.01.13",
    "Spese manut.impianti e macchin. Propri": "57.11.07.01",  # PDC 2026: was 57.11.01
    # Godimento beni terzi / canoni
    "Canoni locazione CVM SDP": "65.01.05.90",
    "Spese condominiali e varie immobili di t": "65.01.07",
    "Canoni/spese access.nolegg.veicoli": "65.03.05.99",  # PDC 2026: was 59.03.90.01
    "Canoni leasing attrezzature": "65.05.05",  # PDC 2026: was 65.03.01
    "Canoni noleggio attrezzature": "65.05.15",  # PDC 2026: was 65.05.01
    "Canoni passivi affitto d\u2019azienda": "65.11.01",  # PDC 2026: was 65.07.01
    "Canoni passivi affitto d'azienda": "65.11.01",  # PDC 2026: was 65.07.01
    "Software per la Gestione Alberghiera": "65.90.01",  # PDC 2026: was 65.09.01
    "Software per Contabilità e Magazzino": "65.90.02",  # PDC 2026: was 65.09.03
    # Personale
    "Retribuzioni lorde dipendenti ordinari": "67.01.01.01",
    "Contributi INPS": "67.01.03",
    "Premi INAIL": "67.01.11",  # PDC 2026: was 67.01.05
    "Ricerca, formazione e addestramento": "67.03.13",
    "Altri costi per il personale dipendente": "67.03.51",
    "Formazione sicurezza": "67.03.90",
    "Software Reclutamento Personale": "67.03.91",
    "Vestiario dipendenti": "67.03.94",
    # Costi commerciali
    "Pubblicità, inserz. e affissioni ded.": "63.01.01.01",
    "Spese alberghi e ristor.deducibili": "63.01.09.11",
    "Spese per alberghi e ristoranti": "63.01.09.99",
    "Pedaggi autostradali veicoli": "63.01.15",
    "Spese di transfer": "63.01.90",
    "Omaggi": "63.03.03",
    # Costi amministrativi
    "Consulenze ammin.e fiscali (ordinarie)": "61.01.01.03",
    "Consulenze del lavoro (ordinarie)": "61.01.01.91",
    "Consulenze tecniche": "61.01.03",
    "Consulenze legali": "61.01.05",
    "Consulenze notarili": "61.01.07",
    "Consulenze marketing e pubblicitarie": "61.01.09",
    "Altre spese amministrative": "63.05.51",  # PDC 2026: was 61.09.01
    "Premi di assicurazioni obbligatorie": "63.05.15",  # PDC 2026: was 61.05.01
    "Servizi smaltimento rifiuti": "63.05.19",  # PDC 2026: was 61.07.01
    "Spese generali varie": "63.05.51",  # PDC 2026: was 61.09.90
    "Canone noleggio fotocopiatrici": "63.05.90",  # PDC 2026: was 61.11.01
    "Domini e Hosting": "65.90.08",  # PDC 2026: was 61.13.01
    "Mail e Pec": "65.90.09",  # PDC 2026: was 61.13.03
    "Abbonamenti, libri e pubblicazioni": "71.03.11",  # PDC 2026: was 61.15.01
    # Oneri tributari
    "IMU": "71.01.04",
    "Diritti camerali": "71.01.05",  # PDC 2026: was 71.01.06
    "Imposta di registro e concess. govern.": "71.01.07",  # PDC 2026: was 71.01.08
    # Oneri finanziari
    "Interessi passivi bancari": "75.01.01",
    "Commissioni e spese bancarie": "75.01.07",
    "Commissioni bancarie su finanziamenti": "75.01.11",  # PDC 2026: was 75.01.09
    "Interessi passivi su mutui": "75.03.05",  # PDC 2026: was 75.03.01
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def fetch_seasonality_coefficients(
    societa_id: str, business_unit_id: str = "HQ"
) -> dict[int, float]:
    """Fetch monthly coefficients from d_coefficienti_stagionalita.
    Returns {mese: coefficiente}. Falls back to flat 1.0 if table missing.
    """
    try:
        from google.cloud import bigquery

        client = get_client()
        q = f"""
        SELECT mese, coefficiente
        FROM `{PROJECT}.hotelops.d_coefficienti_stagionalita`
        WHERE societa_id = @societa AND business_unit_id = @bu
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa_id),
                bigquery.ScalarQueryParameter("bu", "STRING", business_unit_id),
            ]
        )
        return {
            row.mese: row.coefficiente
            for row in client.query(q, job_config=job_config).result()
        }
    except Exception:
        return {m: 1.0 for m in range(1, 13)}


def _v(x) -> float:
    """Coerce cell value to float, 0.0 for None/NaN/datetime."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        import math

        return 0.0 if math.isnan(float(x)) else float(x)
    return 0.0


def _is_conto(val) -> bool:
    """Check if value looks like a codice_conto (has dots, short string).

    Leading/trailing whitespace is tolerated (CE sometimes pads cells).
    """
    if not isinstance(val, str):
        return False
    v = val.strip()
    return "." in v and len(v) < 20


def decode_timedelta_cod_conto(
    td: timedelta, prefix_h: int, prefix_m: int
) -> str | None:
    """Reverse-engineer a cod_conto that Excel parsed as time H:M:S.

    Given a timedelta ``td`` (Excel's normalized form) and the section context
    prefix ``prefix_h.prefix_m`` derived from neighbouring non-corrupted rows,
    solve for the last segment ``s`` and return ``"HH.MM.SS"``.

    Example: Italian PDC "47.91.03" was parsed by Excel as 47h 91m 3s →
    normalized to timedelta(days=2, seconds=1863). Given prefix_h=47,
    prefix_m=91, this function returns "47.91.03".

    Returns None if the prefix does not yield a valid 0-99 seconds segment.
    """
    total_s = int(round(td.total_seconds()))
    s = total_s - prefix_h * 3600 - prefix_m * 60
    if 0 <= s < 100:
        return f"{prefix_h}.{prefix_m:02d}.{s:02d}"
    return None


def _prefix_hm(cod: str) -> tuple[int, int] | None:
    """Extract (h, m) prefix from a dotted cod_conto string."""
    parts = cod.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _resolve_cod_conto_with_context(
    ce_rows: list[tuple[int, object, str]], ce_idx: int
) -> str | None:
    """Resolve cod_conto at ce_rows[ce_idx], decoding timedelta via neighbours.

    ce_rows is a list of (row_num, raw_cell_value, desc) tuples from the
    Conto Economico sheet. Strategy:
      1. If raw is already a cod_conto string (possibly whitespace-padded),
         return it stripped.
      2. If raw is a timedelta or float (day-fraction), compute total seconds
         and solve ``s = total_s - h*3600 - m*60`` with ``(h, m)`` drawn
         from non-corrupted neighbours. Try nearest first; when prev and
         next minutes differ, prefer next (transition rule).
      3. When direct neighbour prefixes fail, broaden the search to a ±10
         window of hours and enumerate m ∈ [0, 99]. Pick the unique valid
         (h, m, s) candidate; when multiple, prefer the one whose minute
         appears in nearby non-corrupted rows.
    """
    _, raw, _ = ce_rows[ce_idx]
    if _is_conto(raw):
        return str(raw).strip()

    if isinstance(raw, timedelta):
        total_s = int(round(raw.total_seconds()))
    elif isinstance(raw, float):
        total_s = int(round(raw * 86400))
    else:
        return None

    prev_cod = None
    for i in range(ce_idx - 1, -1, -1):
        if _is_conto(ce_rows[i][1]):
            prev_cod = str(ce_rows[i][1]).strip()
            break
    next_cod = None
    for i in range(ce_idx + 1, len(ce_rows)):
        if _is_conto(ce_rows[i][1]):
            next_cod = str(ce_rows[i][1]).strip()
            break

    prev_hm = _prefix_hm(prev_cod) if prev_cod else None
    next_hm = _prefix_hm(next_cod) if next_cod else None

    tight: list[tuple[int, int]] = []
    if prev_hm and next_hm:
        tight = [prev_hm] if prev_hm == next_hm else [next_hm, prev_hm]
    elif next_hm:
        tight = [next_hm]
    elif prev_hm:
        tight = [prev_hm]

    for h, m in tight:
        s = total_s - h * 3600 - m * 60
        if 0 <= s < 100:
            return f"{h}.{m:02d}.{s:02d}"

    window = 20
    h_seen: set[int] = set()
    h_ordered: list[int] = []
    for i in range(max(0, ce_idx - window), min(len(ce_rows), ce_idx + window + 1)):
        if i == ce_idx:
            continue
        v = ce_rows[i][1]
        if _is_conto(v):
            hm = _prefix_hm(str(v).strip())
            if hm and hm[0] not in h_seen:
                h_seen.add(hm[0])
                h_ordered.append(hm[0])

    for h in h_ordered:
        remainder = total_s - h * 3600
        if remainder < 0:
            continue
        m, s = divmod(remainder, 60)
        if 0 <= m <= 99 and 0 <= s <= 99:
            return f"{h}.{m:02d}.{s:02d}"
    return None


def _build_ce_rows(ws_ce) -> list[tuple[int, object, str]]:
    """Collect (row_num, raw_col_A, desc) for each non-empty data row in CE.

    Starts at row 10 (first real data row in the Gasparotto 2025 template).
    Preserves sheet order so duplicate descriptions can be matched by position.
    """
    out: list[tuple[int, object, str]] = []
    for r in range(10, ws_ce.max_row + 1):
        raw = ws_ce.cell(r, 1).value
        desc_cell = ws_ce.cell(r, 2).value
        desc = str(desc_cell).strip() if desc_cell else ""
        if desc:
            out.append((r, raw, desc))
    return out


def _detect_section(desc_upper: str, current_section: str) -> str:
    """Check if this row triggers a section transition."""
    for keyword, new_section in SECTION_TRANSITIONS:
        if keyword in desc_upper:
            if new_section is not None:
                return new_section
            return "__STOP__"
    return current_section


def _should_skip(desc_upper: str) -> bool:
    """Check if this row is a header/total/metadata row."""
    for pattern in SKIP_PATTERNS:
        if pattern in desc_upper:
            return True
    # Skip row separator lines (\\\\\\\\) but not normal backslashes in descriptions
    if desc_upper.startswith("\\") and len(set(desc_upper.replace(" ", ""))) <= 2:
        return True
    return False


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_gasparotto")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


# ── Main parser ───────────────────────────────────────────────────────────────


def parse_gasparotto_budget(
    filepath: Path,
    societa_id: str,
    logger: logging.Logger,
) -> list[dict]:
    """Parse the Budget sheet of Gasparotto Master XLSX.

    New file format (``gasparotto_Budget_Indici2025.xlsx``): Budget col A
    is empty — cod_conto lives only in the Conto Economico sheet. Rows are
    matched by description via a sequential CE pointer (handles duplicate
    descriptions across Hotel/Residence/CVM blocks). Timedelta-corrupted
    cod_conto cells in CE are decoded via neighbouring-row prefix.

    Returns list of dicts ready for f_budget_mensile.
    """
    wb = openpyxl.load_workbook(str(filepath), data_only=True)
    now = datetime.now(timezone.utc)

    if "Budget" not in wb.sheetnames:
        logger.error(f"Foglio 'Budget' non trovato in {filepath.name}")
        wb.close()
        return []
    if "Conto Economico" not in wb.sheetnames:
        logger.error(f"Foglio 'Conto Economico' non trovato in {filepath.name}")
        wb.close()
        return []

    ws_ce = wb["Conto Economico"]
    ce_rows = _build_ce_rows(ws_ce)
    logger.info(f"  Conto Economico: {len(ce_rows)} righe dati (row 10+)")

    ws = wb["Budget"]

    # Sanity check: Budget col H must contain cached numeric values.
    # If >80% of col H is formula strings (not numbers), the workbook needs recalc.
    sample_h = [ws.cell(r, 8).value for r in range(11, min(60, ws.max_row + 1))]
    numeric_h = sum(1 for v in sample_h if isinstance(v, (int, float)))
    if numeric_h < 10:
        logger.error(
            f"  Budget col H non contiene valori cached ({numeric_h} numerici "
            f"su {len(sample_h)}). Il workbook richiede recalc (LibreOffice headless)."
        )
        wb.close()
        return []

    # Fetch seasonality coefficients (company-level weighted average)
    seasonality = fetch_seasonality_coefficients(societa_id, "HQ")

    section = "RICAVI"
    records: list[dict] = []
    skipped = 0
    unmapped = 0
    ce_ptr = 0  # sequential pointer into ce_rows

    for bg_row in range(11, ws.max_row + 1):
        col_a = ws.cell(bg_row, 1).value
        col_b = ws.cell(bg_row, 2).value
        col_c = ws.cell(bg_row, 3).value
        col_e = ws.cell(bg_row, 5).value
        col_h = ws.cell(bg_row, 8).value

        if not col_b or str(col_b).strip() in ("0", ""):
            continue

        desc = str(col_b).strip()
        desc_upper = desc.upper()

        # Check section transition BEFORE processing data
        new_section = _detect_section(desc_upper, section)
        if new_section == "__STOP__":
            break  # Past RISULTATO — done
        if new_section != section:
            section = new_section
            if _should_skip(desc_upper):
                continue

        # Skip headers/totals
        if _should_skip(desc_upper):
            skipped += 1
            continue

        # Must have a non-zero value for either 2025 or 2026
        val_2025 = _v(col_c)
        val_2026 = _v(col_h)
        if val_2025 == 0 and val_2026 == 0:
            continue

        # Resolve codice_conto via sequential CE match
        codice_conto: str | None = None
        match_idx = None
        for i in range(ce_ptr, len(ce_rows)):
            if ce_rows[i][2].strip().upper() == desc_upper:
                match_idx = i
                break
        if match_idx is not None:
            ce_ptr = match_idx + 1
            codice_conto = _resolve_cod_conto_with_context(ce_rows, match_idx)

        # Fallbacks: Budget col A (rare) then MANUAL_COD_MAP
        if not codice_conto and _is_conto(col_a):
            codice_conto = str(col_a).strip()
        if not codice_conto:
            codice_conto = MANUAL_COD_MAP.get(desc)
        if not codice_conto:
            logger.warning(
                f'  UNMAPPED: "{desc}" (2026={val_2026:,.0f}) — riga saltata'
            )
            unmapped += 1
            continue

        # Determine tipo_costo from col_e or section default
        tipo_from_sheet = (
            str(col_e).strip()
            if col_e and str(col_e).strip() not in ("", "\\")
            else None
        )
        cat_ce, default_tipo = SECTION_CATEGORY.get(section, ("Costi Produttivi", "F"))

        if tipo_from_sheet in ("F", "V", "P", "X", "IP"):
            tipo_costo = tipo_from_sheet
        elif tipo_from_sheet == "Z":
            continue  # Zero/azzerato — skip
        elif tipo_from_sheet == "O":
            tipo_costo = default_tipo  # "come anno precedente"
        else:
            tipo_costo = default_tipo

        # Build 12 monthly rows from annual total
        annual = val_2026
        if annual == 0:
            continue

        for mese in range(1, 13):
            records.append(
                {
                    "societa_id": societa_id,
                    "anno": ANNO,
                    "mese": mese,
                    "codice_conto": codice_conto,
                    "descrizione": desc,
                    "tipo_costo": tipo_costo,
                    "categoria_ce": cat_ce,
                    "business_unit_id": None,  # Gasparotto is company-level
                    "importo": round(annual / 12 * seasonality.get(mese, 1.0), 4),
                    "fonte": FONTE,
                    "data_caricamento": now.isoformat(),
                }
            )

    wb.close()

    # Summary
    conti_unique = len({r["codice_conto"] for r in records})
    logger.info(f"  {societa_id}: {conti_unique} conti → {len(records)} righe mensili")
    if unmapped > 0:
        logger.warning(f"  {unmapped} righe senza codice_conto — saltate")
    if skipped > 0:
        logger.info(f"  {skipped} righe header/totale saltate")

    return records


# ── Quality summary ───────────────────────────────────────────────────────────


def quality_summary(rows: list[dict], logger: logging.Logger) -> None:
    """Print budget totals by section."""
    by_cat: dict[str, float] = {}
    for r in rows:
        cat = r["categoria_ce"] or "?"
        by_cat[cat] = by_cat.get(cat, 0.0) + r["importo"]

    logger.info("═" * 56)
    logger.info("  QUALITY SUMMARY — Gasparotto → f_budget_mensile")
    logger.info("═" * 56)

    total = 0.0
    for cat in [
        "Ricavi",
        "Acquisti",
        "Costi Produttivi",
        "Costo del Personale",
        "Costi Commerciali",
        "Costi Amministrativi",
        "Oneri Tributari",
        "Oneri Finanziari",
    ]:
        v = by_cat.get(cat, 0)
        if v:
            logger.info(f"  {cat:<24s}: {v:>14,.0f} €/anno")
            total += v
    logger.info(f"  {'─' * 42}")
    logger.info(f"  {'TOTALE':<24s}: {total:>14,.0f} €/anno")
    logger.info("═" * 56)


# ── Pydantic validation ──────────────────────────────────────────────────────


def validate_rows(rows: list[dict], logger: logging.Logger) -> list[dict]:
    """Validate all rows using BudgetMensileRow schema."""
    try:
        from core.schemas import BudgetMensileRow, validate_batch

        validate_batch(rows, BudgetMensileRow, context=f"Gasparotto {FONTE}")
        logger.info(f"  Pydantic validation OK: {len(rows)} righe")
    except ImportError:
        logger.warning("  lib.schemas non disponibile — skip Pydantic validation")
    except Exception as e:
        logger.error(f"  Pydantic validation FAILED: {e}")
        sys.exit(1)
    return rows


# ── BigQuery ──────────────────────────────────────────────────────────────────

BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("anno", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("mese", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("codice_conto", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("descrizione", "STRING"),
        bigquery.SchemaField("tipo_costo", "STRING"),
        bigquery.SchemaField("categoria_ce", "STRING"),
        bigquery.SchemaField("business_unit_id", "STRING"),
        bigquery.SchemaField("importo", "FLOAT64"),
        bigquery.SchemaField("fonte", "STRING"),
        bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
    ]
    if HAS_BQ
    else []
)


def load_to_bq(rows: list[dict], bq_client, logger: logging.Logger) -> None:
    if not rows:
        logger.warning("Nessuna riga da caricare")
        return

    # Delete existing GASPAROTTO rows for this year
    bq_client.query(
        f"DELETE FROM `{BQ_TABLE}` WHERE anno = {ANNO} AND fonte = '{FONTE}'"
    ).result()
    logger.info(f"  Righe precedenti anno={ANNO} fonte={FONTE} cancellate")

    validate_batch(rows, BudgetMensileRow, "f_budget_mensile (gasparotto)")
    job = bq_client.load_table_from_json(
        rows,
        BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"  {BQ_TABLE}: {len(rows)} righe caricate (fonte={FONTE})")


# ── CSV dump ──────────────────────────────────────────────────────────────────

FIELDS = [
    "societa_id",
    "anno",
    "mese",
    "codice_conto",
    "descrizione",
    "tipo_costo",
    "categoria_ce",
    "business_unit_id",
    "importo",
    "fonte",
]


def dump_csv(rows: list[dict], path: Path, logger: logging.Logger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info(f"  CSV: {path}  ({len(rows)} righe)")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gasparotto Master Budget → f_budget_mensile (fonte=GASPAROTTO)"
    )
    parser.add_argument(
        "--file", default=str(DEFAULT_FILE), help="Path al Master Completo XLSX"
    )
    parser.add_argument(
        "--societa",
        default="ORTI",
        choices=["ORTI", "INTUR"],
        help="Società (default ORTI)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse + validate + CSV, no BQ write"
    )
    parser.add_argument(
        "--output-dir", default="output", help="Directory per CSV output in dry-run"
    )
    args = parser.parse_args()

    logger = setup_logger()

    if not HAS_OPENPYXL:
        logger.error("openpyxl non installato: pip install openpyxl")
        sys.exit(1)

    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    logger.info(f"File: {filepath.name}")
    logger.info(f"Società: {args.societa}")
    logger.info(f"Anno: {ANNO}")

    rows = parse_gasparotto_budget(filepath, args.societa, logger)
    if not rows:
        logger.error("Nessuna riga estratta")
        sys.exit(1)

    validate_rows(rows, logger)
    quality_summary(rows, logger)

    if args.dry_run:
        dump_csv(rows, Path(args.output_dir) / "f_budget_gasparotto.csv", logger)
        logger.info("DRY RUN completato — nessuna scrittura su BQ.")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = get_client()
    load_to_bq(rows, bq_client, logger)
    logger.info("✓ DONE")


if __name__ == "__main__":
    main()
