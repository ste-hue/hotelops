"""Build HPAN25PIANO1_Tracking.xlsx — operational master CapEx tracking.

Source data (read-only):
  - HPAN25PIANO1_CapEx_Controllo.xlsx (Fornitori, Dati Fatture, Preventivi)
  - rclone lsjson on 06_FATTURE_LAVORI_HOTEL/ + 07_fornitori/F*/ + Preventivi_Lavori_Hotel/
    + root PDFs → Drive file IDs for hyperlinks
  - Optional --classifier-csv (mining run output) → Candidates sheet

Output sheets:
  - Summary           top-level dashboard (vs €1.2M target)
  - Tracking_Fornitori 33 rows, one per F-code, with F-folder link + status
  - Documents         every doc found, with direct Drive link
  - Candidates        mining-recovered candidates (matched + needs review)

Workflow: Stefano drops files in canonical folders → re-run script → xlsx updates.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BUDGET_TARGET_EUR = 1_200_000
PROJECT_DRIVE_PATH = "04_Progetti_Investimenti/Investimenti2026/HPAN25PIANO1_CamerePrimoPiano"
RCLONE_REMOTE = "mywork"

F_TO_BUDGET_MACRO = {
    "F001": "EDILE", "F008": "EDILE", "F019": "EDILE", "F024": "EDILE", "F022": "EDILE",
    "F025": "ELETTRICO", "F033": "ELETTRICO",
    "F027": "IMPIANTI", "F028": "IMPIANTI", "F009": "IMPIANTI",
    "F003": "SPESE TECNICHE", "F013": "SPESE TECNICHE", "F018": "SPESE TECNICHE",
    "F021": "SPESE TECNICHE", "F017": "SPESE TECNICHE", "F032": "SPESE TECNICHE",
    "F029": "INFISSI", "F026": "INFISSI", "F023": "INFISSI", "F012": "INFISSI",
    "F002": "ARREDI", "F004": "ARREDI", "F005": "ARREDI", "F006": "ARREDI",
    "F007": "ARREDI", "F010": "ARREDI", "F011": "ARREDI", "F014": "ARREDI",
    "F015": "ARREDI", "F016": "ARREDI", "F020": "ARREDI", "F030": "ARREDI",
    "F031": "ARREDI",
}

SUPPLIERS_YAML = Path(__file__).parent / "suppliers.yaml"

# Filters to exclude noisy classifier matches
NOISE_KEYWORDS = re.compile(
    r"\b(sintesi|previsionale|ammodernament|riepilogo|fitto[\s_]azienda|locazione|sublocazione|"
    r"recruiting|altamira|aras|nulla[\s_]osta|donazione|visura|catastale|atto[\s\d]|sentenza|procura)\b",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"\b(S\.?\s*R\.?\s*L\.?|S\.?\s*P\.?\s*A\.?|SOCIO\s*UNICO|AZIONISTA\s*UNICO|SRL|SPA|SAS|SNC|GROUP)\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_fuzzy_map() -> dict[str, str]:
    cfg = yaml.safe_load(SUPPLIERS_YAML.read_text())
    out: dict[str, str] = {}
    for s in cfg["suppliers"]:
        cod = s["code"]
        rs = normalize(s["ragione_sociale"])
        out[rs] = cod
        compact = re.sub(r"\s+", "", rs)
        if compact and compact != rs:
            out.setdefault(compact, cod)
        for tok in rs.split():
            if len(tok) >= 4 and tok not in {"SRL", "SPA", "SAS", "GROUP", "COSTRUZIONI", "TAPPEZZERIA", "GIUSEPPE", "ITALIA", "S.P.A", "PIASTRELLISTI"}:
                out.setdefault(tok, cod)
    return out


def match_name(name: str, fmap: dict[str, str]) -> str | None:
    if not name:
        return None
    norm = normalize(name)
    if not norm:
        return None
    compact = re.sub(r"\s+", "", norm)
    if norm in fmap:
        return fmap[norm]
    if compact in fmap:
        return fmap[compact]
    for known, cod in fmap.items():
        if len(known) < 4:
            continue
        if known in norm or known in compact:
            return cod
    return None


def drive_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def rclone_lsjson(remote_path: str, recursive: bool = False, dirs_only: bool = False) -> list[dict]:
    cmd = ["rclone", "lsjson", f"{RCLONE_REMOTE}:{remote_path}"]
    if recursive:
        cmd.append("-R")
    if dirs_only:
        cmd.append("--dirs-only")
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def parse_importo(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("€", "").replace(",", ".").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def load_xlsx_data(xlsx: Path) -> dict:
    wb = load_workbook(xlsx, data_only=True)

    fornitori = {}
    ws = wb["Fornitori"]
    in_h = False
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        if row[0] == "Cod. Interno":
            in_h = True
            continue
        if not in_h:
            continue
        cod = str(row[0]).strip() if row[0] else ""
        if cod.startswith("F"):
            fornitori[cod] = {
                "ragione_sociale": row[1] or "",
                "scope": row[2] or "",
                "referente": row[3] or "",
                "cod_gestionale": row[7] or "",
            }

    fatture_xlsx: dict[str, list[dict]] = defaultdict(list)
    ws = wb["Dati Fatture"]
    headers = None
    importo_idx = None
    in_h = False
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        if row[0] == "#":
            headers = row
            in_h = True
            for i, h in enumerate(headers):
                if h and "importo" in str(h).lower():
                    importo_idx = i
                    break
            continue
        if not in_h or not isinstance(row[0], (int, float)):
            continue
        cod = str(row[2]).strip() if row[2] else ""
        if not cod.startswith("F"):
            continue
        imp = parse_importo(row[importo_idx]) if importo_idx is not None else 0.0
        if imp == 0.0:
            # fallback: last numeric column
            for v in reversed(row):
                if isinstance(v, (int, float)) and v > 0:
                    imp = float(v)
                    break
        fatture_xlsx[cod].append({
            "fornitore_name": row[1] or "",
            "numero": row[4],
            "data": row[5],
            "importo_eur": imp,
        })

    preventivi_xlsx: dict[str, list[dict]] = defaultdict(list)
    ws = wb["Preventivi"]
    in_h = False
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        if row[0] == "#":
            in_h = True
            continue
        if not in_h or not isinstance(row[0], (int, float)):
            continue
        cod = str(row[2]).strip() if row[2] else ""
        if not cod.startswith("F"):
            continue
        preventivi_xlsx[cod].append({
            "fornitore_name": row[3] or "",
            "voce": row[4] or "",
            "numero": row[5] or "",
            "data": row[6],
            "importo_eur": parse_importo(row[7]),
        })

    return {
        "fornitori": fornitori,
        "fatture_xlsx": fatture_xlsx,
        "preventivi_xlsx": preventivi_xlsx,
    }


def load_classifier_by_filename(classifier_csv: Path | None) -> dict[str, dict]:
    """Index classifier output by filename → category/fornitore/importo."""
    if not classifier_csv or not classifier_csv.exists():
        return {}
    out = {}
    with classifier_csv.open() as f:
        for r in csv.DictReader(f):
            out[r["filename"]] = r
    return out


def scan_drive(drive_index_json: Path, f_folders_json: Path,
               classifier_by_name: dict[str, dict] | None = None) -> tuple[list[dict], dict[str, str]]:
    """Return (documents list, F-folder ID map). Includes ALL files (canonical + mining)."""
    files = json.loads(drive_index_json.read_text())
    classifier_by_name = classifier_by_name or {}
    f_folders = {}
    for d in json.loads(f_folders_json.read_text()):
        m = re.match(r"(F\d{3})_", d["Name"])
        if m:
            f_folders[m.group(1)] = d["ID"]

    docs = []
    for f in files:
        name = f["Name"]
        path = f["Path"]
        # Skip pure metadata
        if name in (".keep", "thread.json"):
            continue
        if name.endswith(".xlsx") and "HPAN25PIANO1_CapEx_Controllo" in name:
            continue
        if name.endswith(".xlsx") and "HPAN25PIANO1_Tracking" in name:
            continue

        fcode = None
        cat = "?"
        source = ""

        if path.startswith("07_fornitori/"):
            m = re.match(r"07_fornitori/(F\d{3})_[^/]+/([^/]+)/", path)
            if m:
                fcode = m.group(1)
                subfolder = m.group(2)
                cat = {
                    "01_preventivi": "PREVENTIVO",
                    "02_ordini_contratti": "CONTRATTO",
                    "03_fatture": "FATTURA",
                    "04_comunicazioni": "COMUNICAZIONE",
                }.get(subfolder, "?")
                source = "07_fornitori"
            elif name == "_NOTE.md":
                continue  # skip note files
            elif name == "README.md":
                continue
        elif path.startswith("FATTURE_LAVORI_HOTEL/"):
            cat = "FATTURA"
            source = "06_FATTURE"
        elif path.startswith("Preventivi_Lavori_Hotel/"):
            cat = "PREVENTIVO"
            source = "Preventivi_Lavori"
        elif path.startswith("Blocco Camere/"):
            cat = "TECNICO"
            source = "Blocco Camere"
        elif path.startswith("workspace-controller-test/"):
            source = "MINING"
            if name in ("index.csv", "README.md"):
                continue
            c = classifier_by_name.get(name)
            if c:
                cat = c.get("category_final") or c.get("stage2") or c.get("stage1") or "?"
            else:
                cat = "MINING_UNCLASSIFIED"
            # FILTER mining output: only keep CapEx-relevant categories
            # Drop LEGAL_NOISE, GENERIC_PROJECT, ALTRO, NOISE, SKIP, FOTO, MINING_UNCLASSIFIED
            RELEVANT_FROM_MINING = {"PREVENTIVO", "CONTRATTO", "FATTURA", "TECNICO"}
            if cat not in RELEVANT_FROM_MINING:
                continue
            # Also filter by extracted name noise (e.g., "Delibera Regione Campania")
            if NOISE_KEYWORDS.search(name):
                continue
        elif "/" not in path:  # root
            source = "root"
            n = name.lower()
            if "offerta" in n or "preventivo" in n:
                cat = "PREVENTIVO"
            elif "rendering" in n or "sal" in n or "report" in n or "appunti" in n:
                cat = "TECNICO"
            else:
                cat = "ROOT"

        # Optional fornitore/importo from classifier
        forn = ""
        importo = 0.0
        c = classifier_by_name.get(name)
        if c:
            forn = c.get("fornitore", "") or ""
            try:
                importo = float(c["importo_eur"]) if c.get("importo_eur") else 0.0
            except (ValueError, TypeError):
                importo = 0.0
            if importo > 500_000:
                importo = 0.0  # noise cap

        docs.append({
            "path": path,
            "name": name,
            "size_kb": f["Size"] // 1024,
            "drive_id": f["ID"],
            "drive_url": drive_url(f["ID"]),
            "category": cat,
            "fcode": fcode or "",
            "source": source,
            "fornitore_extracted": forn,
            "importo_extracted": importo,
        })

    return docs, f_folders


def integrate_classifier(classifier_csv: Path, fmap: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Returns (matched, unmatched) candidates from mining classifier."""
    matched, unmatched = [], []
    if not classifier_csv.exists():
        return matched, unmatched
    with classifier_csv.open() as f:
        for r in csv.DictReader(f):
            cat = r.get("category_final", "")
            if cat not in ("PREVENTIVO", "CONTRATTO"):
                continue
            name = r.get("filename", "")
            forn = r.get("fornitore", "")
            # noise filter
            if NOISE_KEYWORDS.search(name) or NOISE_KEYWORDS.search(forn or ""):
                continue
            try:
                imp = float(r["importo_eur"]) if r["importo_eur"] else 0.0
            except (ValueError, TypeError):
                imp = 0.0
            # sanity cap
            if imp > 500_000:
                imp = 0.0  # likely misread
            cod = match_name(forn, fmap) or match_name(name, fmap)
            row = {
                "category": cat,
                "fornitore": forn,
                "filename": name,
                "path": r.get("path", ""),
                "fcode": cod or "",
                "importo_eur": imp,
                "confidence": r.get("confidence", ""),
                "reasoning": (r.get("reasoning") or "")[:200],
            }
            if cod:
                matched.append(row)
            else:
                unmatched.append(row)
    return matched, unmatched


def write_xlsx(out_path: Path, source_xlsx: Path, data: dict, docs: list[dict], f_folders: dict[str, str],
               candidates_matched: list[dict], candidates_unmatched: list[dict]):
    """Load source xlsx (preserving Fornitori/Preventivi/Dati Fatture), strip & re-add auto sheets."""
    if source_xlsx.exists():
        wb = load_workbook(source_xlsx)
        # Drop existing auto-generated sheets to avoid duplication
        for auto_name in ("Summary", "Tracking_Fornitori", "Documents", "Candidates"):
            if auto_name in wb.sheetnames:
                del wb[auto_name]
    else:
        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])

    # Styles
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    money_fmt = '€#,##0;[Red]-€#,##0;"—"'
    border = Border(left=Side(style="thin", color="BFBFBF"), right=Side(style="thin", color="BFBFBF"),
                    top=Side(style="thin", color="BFBFBF"), bottom=Side(style="thin", color="BFBFBF"))
    link_font = Font(color="0563C1", underline="single")

    def write_header(ws, headers, row=1):
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=i, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border

    # ── Sheet 1: Tracking_Fornitori ─────────────────────────────────────────
    ws = wb.create_sheet("Tracking_Fornitori", 0)
    write_header(ws, [
        "Cod", "Ragione Sociale", "Macro", "Scope",
        "# Prev", "€ Prev (xlsx)", "# Contr", "# Fatt", "€ Fatt (xlsx)",
        "Status", "Cartella F* (Drive)",
    ])

    # Compute per-F-code aggregates
    docs_by_fcode: dict[str, dict[str, list]] = defaultdict(lambda: {"PREVENTIVO": [], "CONTRATTO": [], "FATTURA": []})
    for d in docs:
        if d["fcode"] and d["category"] in ("PREVENTIVO", "CONTRATTO", "FATTURA"):
            docs_by_fcode[d["fcode"]][d["category"]].append(d)

    row_idx = 2
    fornitori = data["fornitori"]
    for cod in sorted(fornitori.keys()):
        f = fornitori[cod]
        macro = F_TO_BUDGET_MACRO.get(cod, "—")
        n_prev = len(docs_by_fcode[cod]["PREVENTIVO"]) + len(data["preventivi_xlsx"].get(cod, []))
        n_contr = len(docs_by_fcode[cod]["CONTRATTO"])
        n_fatt = len(docs_by_fcode[cod]["FATTURA"]) + len(data["fatture_xlsx"].get(cod, []))

        # money from xlsx authoritative
        eur_prev_xlsx = sum(p["importo_eur"] for p in data["preventivi_xlsx"].get(cod, []))
        eur_fatt_xlsx = sum(p["importo_eur"] for p in data["fatture_xlsx"].get(cod, []))

        # Status
        if n_fatt > 0 and n_prev > 0:
            status = "FATTURATO+PREV"
        elif n_fatt > 0:
            status = "FATTURATO (no prev)"
        elif n_prev > 0:
            status = "SOLO PREVENTIVO"
        else:
            status = "SCOPERTO"

        ws.cell(row=row_idx, column=1, value=cod)
        ws.cell(row=row_idx, column=2, value=f["ragione_sociale"])
        ws.cell(row=row_idx, column=3, value=macro)
        ws.cell(row=row_idx, column=4, value=f["scope"])
        ws.cell(row=row_idx, column=5, value=n_prev)
        c = ws.cell(row=row_idx, column=6, value=eur_prev_xlsx if eur_prev_xlsx else None)
        c.number_format = money_fmt
        ws.cell(row=row_idx, column=7, value=n_contr)
        ws.cell(row=row_idx, column=8, value=n_fatt)
        c = ws.cell(row=row_idx, column=9, value=eur_fatt_xlsx if eur_fatt_xlsx else None)
        c.number_format = money_fmt
        ws.cell(row=row_idx, column=10, value=status)
        if cod in f_folders:
            c = ws.cell(row=row_idx, column=11, value="Apri →")
            c.hyperlink = folder_url(f_folders[cod])
            c.font = link_font
        for col in range(1, 12):
            ws.cell(row=row_idx, column=col).border = border
        row_idx += 1

    # Totals row
    tot_prev = sum(sum(p["importo_eur"] for p in v) for v in data["preventivi_xlsx"].values())
    tot_fatt = sum(sum(p["importo_eur"] for p in v) for v in data["fatture_xlsx"].values())
    n_prev_tot = sum(len(v) for v in data["preventivi_xlsx"].values()) + sum(len(docs_by_fcode[c]["PREVENTIVO"]) for c in fornitori)
    n_fatt_tot = sum(len(v) for v in data["fatture_xlsx"].values()) + sum(len(docs_by_fcode[c]["FATTURA"]) for c in fornitori)
    ws.cell(row=row_idx, column=1, value="TOTALE").font = Font(bold=True)
    ws.cell(row=row_idx, column=5, value=n_prev_tot).font = Font(bold=True)
    c = ws.cell(row=row_idx, column=6, value=tot_prev); c.number_format = money_fmt; c.font = Font(bold=True)
    ws.cell(row=row_idx, column=8, value=n_fatt_tot).font = Font(bold=True)
    c = ws.cell(row=row_idx, column=9, value=tot_fatt); c.number_format = money_fmt; c.font = Font(bold=True)

    for col, w in enumerate([6, 36, 14, 32, 7, 14, 8, 7, 14, 22, 16], 1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A2"

    # ── Sheet 2: Documents ──────────────────────────────────────────────────
    ws_doc = wb.create_sheet("Documents", 1)
    write_header(ws_doc, [
        "Cod", "Categoria", "Source", "Path Drive", "Nome file", "Size KB",
        "Fornitore estratto", "€ importo", "Link Drive",
    ])
    r = 2
    # xlsx fatture (authoritative for importi, no Drive link since per-record)
    for cod, lst in data["fatture_xlsx"].items():
        for item in lst:
            ws_doc.cell(row=r, column=1, value=cod)
            ws_doc.cell(row=r, column=2, value="FATTURA (xlsx)")
            ws_doc.cell(row=r, column=3, value="Controllo.xlsx")
            ws_doc.cell(row=r, column=4, value="Dati Fatture sheet")
            ws_doc.cell(row=r, column=5, value=f"FT {item.get('numero', '?')} del {item.get('data', '?')}")
            ws_doc.cell(row=r, column=7, value=item.get("fornitore_name", ""))
            c = ws_doc.cell(row=r, column=8, value=item["importo_eur"])
            c.number_format = money_fmt
            for col in range(1, 10):
                ws_doc.cell(row=r, column=col).border = border
            r += 1
    for cod, lst in data["preventivi_xlsx"].items():
        for item in lst:
            ws_doc.cell(row=r, column=1, value=cod)
            ws_doc.cell(row=r, column=2, value="PREVENTIVO (xlsx)")
            ws_doc.cell(row=r, column=3, value="Controllo.xlsx")
            ws_doc.cell(row=r, column=4, value="Preventivi sheet")
            ws_doc.cell(row=r, column=5, value=f"Prev {item.get('numero', '')} del {item.get('data', '')}")
            ws_doc.cell(row=r, column=7, value=item.get("fornitore_name", ""))
            c = ws_doc.cell(row=r, column=8, value=item["importo_eur"])
            c.number_format = money_fmt
            for col in range(1, 10):
                ws_doc.cell(row=r, column=col).border = border
            r += 1
    # All Drive files (canonical + mining), each with clickable link
    for d in sorted(docs, key=lambda x: (x["source"], x["fcode"] or "ZZZ", x["category"], x["path"])):
        ws_doc.cell(row=r, column=1, value=d["fcode"] or "—")
        ws_doc.cell(row=r, column=2, value=d["category"])
        ws_doc.cell(row=r, column=3, value=d["source"])
        ws_doc.cell(row=r, column=4, value=d["path"])
        ws_doc.cell(row=r, column=5, value=d["name"])
        ws_doc.cell(row=r, column=6, value=d["size_kb"])
        ws_doc.cell(row=r, column=7, value=d["fornitore_extracted"])
        if d["importo_extracted"]:
            c = ws_doc.cell(row=r, column=8, value=d["importo_extracted"])
            c.number_format = money_fmt
        c = ws_doc.cell(row=r, column=9, value="Apri →")
        c.hyperlink = d["drive_url"]
        c.font = link_font
        for col in range(1, 10):
            ws_doc.cell(row=r, column=col).border = border
        r += 1

    for col, w in enumerate([6, 22, 18, 70, 50, 8, 28, 14, 12], 1):
        ws_doc.column_dimensions[get_column_letter(col)].width = w
    ws_doc.freeze_panes = "A2"

    # ── Sheet 3: Candidates (mining recovery) ───────────────────────────────
    ws_c = wb.create_sheet("Candidates", 2)
    write_header(ws_c, [
        "Stato", "Cod (suggerito)", "Categoria", "Fornitore (estratto)", "Filename", "Importo (estratto)",
        "Confidence", "Reasoning",
    ])
    r = 2
    for row in candidates_matched + candidates_unmatched:
        stato = "MATCHED" if row["fcode"] else "DA REVIEWARE"
        ws_c.cell(row=r, column=1, value=stato)
        ws_c.cell(row=r, column=2, value=row["fcode"])
        ws_c.cell(row=r, column=3, value=row["category"])
        ws_c.cell(row=r, column=4, value=row["fornitore"])
        ws_c.cell(row=r, column=5, value=row["filename"])
        if row["importo_eur"]:
            c = ws_c.cell(row=r, column=6, value=row["importo_eur"])
            c.number_format = money_fmt
        ws_c.cell(row=r, column=7, value=row["confidence"])
        ws_c.cell(row=r, column=8, value=row["reasoning"])
        for col in range(1, 9):
            ws_c.cell(row=r, column=col).border = border
        r += 1

    for col, w in enumerate([14, 12, 14, 32, 60, 14, 10, 60], 1):
        ws_c.column_dimensions[get_column_letter(col)].width = w
    ws_c.freeze_panes = "A2"

    # ── Sheet 4: Summary ─────────────────────────────────────────────────────
    ws_s = wb.create_sheet("Summary", 0)
    ws_s["A1"] = "HPAN25PIANO1 — Camere Primo Piano · Tracking Master"
    ws_s["A1"].font = Font(bold=True, size=14)
    ws_s["A3"] = f"Budget target:"
    ws_s["B3"] = BUDGET_TARGET_EUR
    ws_s["B3"].number_format = money_fmt

    ws_s["A5"] = "IMPEGNO (preventivi xlsx)"
    ws_s["B5"] = tot_prev
    ws_s["B5"].number_format = money_fmt
    ws_s["A6"] = "COMPETENZA (fatture xlsx)"
    ws_s["B6"] = tot_fatt
    ws_s["B6"].number_format = money_fmt

    candidates_matched_eur = sum(c["importo_eur"] for c in candidates_matched)
    ws_s["A7"] = "Candidati mining (matched, importo estratto)"
    ws_s["B7"] = candidates_matched_eur
    ws_s["B7"].number_format = money_fmt
    ws_s["C7"] = "(import. da verificare)"

    documented = max(tot_prev + candidates_matched_eur, tot_fatt)
    gap = BUDGET_TARGET_EUR - documented
    ws_s["A9"] = "Documentato (max IMPEGNO/COMPETENZA)"
    ws_s["B9"] = documented
    ws_s["B9"].number_format = money_fmt
    ws_s["B9"].font = Font(bold=True)
    ws_s["A10"] = "Gap 'nell'etere' (da scoprire)"
    ws_s["B10"] = gap
    ws_s["B10"].number_format = money_fmt
    ws_s["B10"].font = Font(bold=True, color="C00000")
    ws_s["C10"] = f"{gap / BUDGET_TARGET_EUR * 100:.0f}% del target"

    ws_s["A12"] = "Per macro (fatture xlsx + preventivi xlsx):"
    ws_s["A12"].font = Font(bold=True)
    macro_agg = defaultdict(lambda: {"prev": 0.0, "fatt": 0.0})
    for cod, lst in data["preventivi_xlsx"].items():
        macro_agg[F_TO_BUDGET_MACRO.get(cod, "?")]["prev"] += sum(p["importo_eur"] for p in lst)
    for cod, lst in data["fatture_xlsx"].items():
        macro_agg[F_TO_BUDGET_MACRO.get(cod, "?")]["fatt"] += sum(p["importo_eur"] for p in lst)

    ws_s["A13"] = "Macro"
    ws_s["B13"] = "€ Preventivi"
    ws_s["C13"] = "€ Fatture"
    for col in ("A13", "B13", "C13"):
        ws_s[col].font = hdr_font
        ws_s[col].fill = hdr_fill
    r = 14
    for macro in sorted(macro_agg.keys()):
        ws_s.cell(row=r, column=1, value=macro)
        c = ws_s.cell(row=r, column=2, value=macro_agg[macro]["prev"]); c.number_format = money_fmt
        c = ws_s.cell(row=r, column=3, value=macro_agg[macro]["fatt"]); c.number_format = money_fmt
        r += 1

    ws_s["A" + str(r + 2)] = "Documenti scoperti (fornitori senza alcun documento):"
    ws_s["A" + str(r + 2)].font = Font(bold=True)
    scoperti = [
        f"{cod} {data['fornitori'][cod]['ragione_sociale']}"
        for cod in fornitori
        if not data["preventivi_xlsx"].get(cod) and not data["fatture_xlsx"].get(cod) and not docs_by_fcode[cod]["PREVENTIVO"] and not docs_by_fcode[cod]["FATTURA"]
    ]
    for i, sc in enumerate(scoperti, r + 3):
        ws_s["A" + str(i)] = sc

    for col, w in enumerate([40, 18, 30], 1):
        ws_s.column_dimensions[get_column_letter(col)].width = w

    wb.save(out_path)
    return tot_prev, tot_fatt, candidates_matched_eur, gap, len(scoperti)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, type=Path, help="Controllo.xlsx (read-only source)")
    ap.add_argument("--drive-index", required=True, type=Path, help="rclone lsjson -R output (files)")
    ap.add_argument("--f-folders", required=True, type=Path, help="rclone lsjson --dirs-only of 07_fornitori/")
    ap.add_argument("--classifier-csv", type=Path, help="Optional: output of classify_attachments.py")
    ap.add_argument("--output", required=True, type=Path, help="Output tracking xlsx path")
    args = ap.parse_args()

    data = load_xlsx_data(args.xlsx)
    print(f"Loaded: {len(data['fornitori'])} fornitori, "
          f"{sum(len(v) for v in data['fatture_xlsx'].values())} fatture, "
          f"{sum(len(v) for v in data['preventivi_xlsx'].values())} preventivi (xlsx)")

    classifier_by_name = load_classifier_by_filename(args.classifier_csv) if args.classifier_csv else {}
    docs, f_folders = scan_drive(args.drive_index, args.f_folders, classifier_by_name)
    print(f"Drive: {len(docs)} documenti (incl. mining run), {len(f_folders)} F-folder IDs")

    matched, unmatched = [], []
    if args.classifier_csv and args.classifier_csv.exists():
        fmap = build_fuzzy_map()
        matched, unmatched = integrate_classifier(args.classifier_csv, fmap)
        print(f"Classifier: {len(matched)} matched + {len(unmatched)} unmatched (after noise filter)")

    tot_p, tot_f, mc_eur, gap, n_scoperti = write_xlsx(args.output, args.xlsx, data, docs, f_folders, matched, unmatched)
    print(f"\nWrote: {args.output}")
    print(f"  IMPEGNO (xlsx):              €{tot_p:>11,.0f}")
    print(f"  COMPETENZA (xlsx):           €{tot_f:>11,.0f}")
    print(f"  Candidati mining matched €:  €{mc_eur:>11,.0f}")
    print(f"  Gap vs €1.2M:                €{gap:>11,.0f}")
    print(f"  Fornitori scoperti:          {n_scoperti}")


if __name__ == "__main__":
    main()
