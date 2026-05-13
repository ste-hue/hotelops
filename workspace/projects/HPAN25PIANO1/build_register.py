"""Build CapEx register HPAN25PIANO1: documenti su carta + aggregato vs budget target.

Source 1: HPAN25PIANO1_CapEx_Controllo.xlsx
  - Foglio "Dati Fatture" → COMPETENZA (33 fatture con importo)
  - Foglio "Preventivi"   → IMPEGNO (4 preventivi noti con importo)
  - Foglio "Fornitori"    → anagrafica F001..F033

Source 2 (opzionale, --classifier-csv): output di classify_attachments.py
  → integra nuovi preventivi/contratti scoperti dal mining

Output: register CSV + summary testuale (totale per categoria, per macro budget, gap vs €1.2M).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import re

import yaml
from openpyxl import load_workbook

BUDGET_TARGET_EUR = 1_200_000

SUPPLIERS_YAML = Path(__file__).parent / "suppliers.yaml"


def normalize(s: str) -> str:
    s = (s or "").upper()
    # strip suffixes and punctuation
    s = re.sub(r"\b(S\.?\s*R\.?\s*L\.?|S\.?\s*P\.?\s*A\.?|SOCIO\s*UNICO|AZIONISTA\s*UNICO|SRL|SPA|SAS|SNC|GROUP)\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_fuzzy_map() -> dict[str, str]:
    """Build normalized-name → F-code lookup from suppliers.yaml."""
    cfg = yaml.safe_load(SUPPLIERS_YAML.read_text())
    out: dict[str, str] = {}
    for s in cfg["suppliers"]:
        cod = s["code"]
        rs = normalize(s["ragione_sociale"])
        out[rs] = cod
        # Also add the compacted version (spaces removed) to handle acronyms:
        # "A.M.C.N. COSTRUZIONI" → normalize → "A M C N COSTRUZIONI" → compact → "AMCNCOSTRUZIONI"
        # matches classifier "AMCN COSTRUZIONI" → normalize → "AMCN COSTRUZIONI" → compact → "AMCNCOSTRUZIONI"
        compact_rs = re.sub(r"\s+", "", rs)
        if compact_rs and compact_rs != rs:
            out.setdefault(compact_rs, cod)
        # Also each significant token as standalone (e.g., "ILLUXIT", "DORELAN")
        for tok in rs.split():
            if len(tok) >= 4 and tok not in {"SRL", "SPA", "SAS", "GROUP", "COSTRUZIONI"}:
                out.setdefault(tok, cod)
    return out


def match_name(name: str, fuzzy_map: dict[str, str]) -> str | None:
    """Like match_fornitore_to_fcode but with compact-spaces fallback."""
    if not name:
        return None
    norm = normalize(name)
    if not norm:
        return None
    compact = re.sub(r"\s+", "", norm)
    if norm in fuzzy_map:
        return fuzzy_map[norm]
    if compact in fuzzy_map:
        return fuzzy_map[compact]
    for known, cod in fuzzy_map.items():
        if len(known) < 4:
            continue
        if known in norm or known in compact or norm in known:
            return cod
    return None


def match_fornitore_to_fcode(name: str, fuzzy_map: dict[str, str]) -> str | None:
    """Return F-code if name matches any known supplier, else None."""
    if not name:
        return None
    norm = normalize(name)
    if not norm:
        return None
    # exact match
    if norm in fuzzy_map:
        return fuzzy_map[norm]
    # substring match: classifier name contains a known F-code key
    for known, cod in fuzzy_map.items():
        if len(known) < 4:
            continue
        if known in norm or norm in known:
            return cod
    return None

# Mapping F-code → macro budget (categorie del file budget_camere.xlsx)
F_TO_BUDGET_MACRO = {
    # EDILE
    "F001": "EDILE", "F008": "EDILE", "F019": "EDILE", "F024": "EDILE",
    "F022": "EDILE",  # OLIVA = smaltimento eternit → EDILE
    # ELETTRICO
    "F025": "ELETTRICO", "F033": "ELETTRICO",
    # IMPIANTI (idro-meccanico + building automation + REI)
    "F027": "IMPIANTI", "F028": "IMPIANTI", "F009": "IMPIANTI",
    # SPESE TECNICHE (progettazione + PM + autorizzazioni + trasporto cantiere)
    "F003": "SPESE TECNICHE", "F013": "SPESE TECNICHE", "F018": "SPESE TECNICHE",
    "F021": "SPESE TECNICHE", "F017": "SPESE TECNICHE", "F032": "SPESE TECNICHE",
    # INFISSI (porte + finestre)
    "F029": "INFISSI", "F026": "INFISSI", "F023": "INFISSI", "F012": "INFISSI",
    # ARREDI / FORNITURE (mobili + apparati + sanitari)
    "F002": "ARREDI", "F004": "ARREDI", "F005": "ARREDI", "F006": "ARREDI",
    "F007": "ARREDI", "F010": "ARREDI", "F011": "ARREDI", "F014": "ARREDI",
    "F015": "ARREDI", "F016": "ARREDI", "F020": "ARREDI", "F030": "ARREDI",
    "F031": "ARREDI",
}


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


def load_fornitori(wb) -> dict[str, dict]:
    """Return F-code → {ragione_sociale, scope, cod_gestionale}."""
    ws = wb["Fornitori"]
    out = {}
    in_header = False
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        if row[0] == "Cod. Interno":
            in_header = True
            continue
        if not in_header:
            continue
        cod = str(row[0]).strip() if row[0] else ""
        if not cod.startswith("F"):
            continue
        out[cod] = {
            "ragione_sociale": row[1] or "",
            "scope": row[2] or "",
            "referente": row[3] or "",
            "cod_gestionale": row[7] or "",
        }
    return out


def load_fatture(wb) -> list[dict]:
    """Read Dati Fatture sheet → list of fatture dicts."""
    ws = wb["Dati Fatture"]
    out = []
    in_header = False
    headers = None
    for row in ws.iter_rows(values_only=True):
        if not row or all(v is None for v in row):
            continue
        if row[0] == "#":
            headers = row
            in_header = True
            continue
        if not in_header or not isinstance(row[0], (int, float)):
            continue
        # Schema: # | Fornitore | Cod. Interno | Cod. Fornitore | N° Fattura | Data Emissione | Data Registr | Tipo Doc | ... | Importo
        out.append({
            "fornitore": str(row[1]).strip() if row[1] else "",
            "cod_interno": str(row[2]).strip() if row[2] else "",
            "cod_fornitore": row[3],
            "numero": row[4],
            "data_emissione": row[5],
            "tipo_doc": row[7],
            # importo is somewhere in remaining columns; try last few
            "_raw_row": row,
        })
    # Heuristic: find importo column by scanning headers
    if headers:
        for col_idx, h in enumerate(headers):
            if h and "importo" in str(h).lower():
                for f in out:
                    if col_idx < len(f["_raw_row"]):
                        f["importo_eur"] = parse_importo(f["_raw_row"][col_idx])
                break
        else:
            # No "importo" header found; try last numeric column
            for f in out:
                f["importo_eur"] = 0.0
                for v in reversed(f["_raw_row"]):
                    if isinstance(v, (int, float)) and v > 0:
                        f["importo_eur"] = float(v)
                        break
    for f in out:
        f.pop("_raw_row", None)
    return out


def load_preventivi(wb) -> list[dict]:
    """Read Preventivi sheet → list of preventivi dicts."""
    ws = wb["Preventivi"]
    out = []
    in_header = False
    for row in ws.iter_rows(values_only=True):
        if not row or all(v is None for v in row):
            continue
        if row[0] == "#":
            in_header = True
            continue
        if not in_header or not isinstance(row[0], (int, float)):
            continue
        # # | Cod. Comm. | Cod. Fornitore | Fornitore | Voce/Scope | N° Preventivo | Data | Importo (€)
        out.append({
            "cod_interno": str(row[2]).strip() if row[2] else "",
            "fornitore": str(row[3]).strip() if row[3] else "",
            "voce": row[4] or "",
            "numero": row[5] or "",
            "data": row[6],
            "importo_eur": parse_importo(row[7]),
        })
    return out


def fcode_macro(cod: str) -> str:
    return F_TO_BUDGET_MACRO.get(cod, "NON CATEGORIZZATO")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, type=Path, help="HPAN25PIANO1_CapEx_Controllo.xlsx")
    ap.add_argument("--register-out", required=True, type=Path)
    ap.add_argument("--classifier-csv", type=Path, help="optional: output of classify_attachments.py")
    args = ap.parse_args()

    if not args.xlsx.exists():
        print(f"ERROR: xlsx not found at {args.xlsx}", file=sys.stderr)
        sys.exit(1)

    wb = load_workbook(args.xlsx, data_only=True)
    fornitori = load_fornitori(wb)
    fatture = load_fatture(wb)
    preventivi = load_preventivi(wb)

    print(f"Fornitori in anagrafica: {len(fornitori)}")
    print(f"Fatture in 'Dati Fatture': {len(fatture)}")
    print(f"Preventivi in 'Preventivi': {len(preventivi)}")

    # Build register rows
    register: list[dict] = []
    for f in fatture:
        cod = f["cod_interno"]
        register.append({
            "categoria": "FATTURA",
            "fornitore": f["fornitore"],
            "cod_interno": cod,
            "macro": fcode_macro(cod),
            "numero": f["numero"],
            "data": f["data_emissione"],
            "importo_eur": f.get("importo_eur", 0.0),
            "fonte": "Controllo.xlsx::Dati Fatture",
        })
    for p in preventivi:
        cod = p["cod_interno"]
        register.append({
            "categoria": "PREVENTIVO",
            "fornitore": p["fornitore"],
            "cod_interno": cod,
            "macro": fcode_macro(cod),
            "numero": p["numero"],
            "data": p["data"],
            "importo_eur": p["importo_eur"],
            "fonte": "Controllo.xlsx::Preventivi",
        })

    # Optional: integrate classifier output (with fuzzy F-code matching)
    candidates_unmatched: list[dict] = []
    if args.classifier_csv and args.classifier_csv.exists():
        fuzzy_map = build_fuzzy_map()
        for r in csv.DictReader(args.classifier_csv.open()):
            cat = r.get("category_final", "")
            if cat not in ("PREVENTIVO", "CONTRATTO"):
                continue  # ignore FATTURA from classifier; skip TECNICO/NOISE
            try:
                imp = float(r["importo_eur"]) if r["importo_eur"] else 0.0
            except (ValueError, TypeError):
                imp = 0.0
            forn_name = r.get("fornitore", "") or ""
            # Also try matching against the filename if fornitore is empty
            cod = match_fornitore_to_fcode(forn_name, fuzzy_map)
            if not cod:
                cod = match_fornitore_to_fcode(r.get("filename", ""), fuzzy_map)
            row = {
                "categoria": cat,
                "fornitore": forn_name,
                "cod_interno": cod or "",
                "macro": fcode_macro(cod) if cod else "NON CATEGORIZZATO",
                "numero": "",
                "data": "",
                "importo_eur": imp,
                "fonte": f"classifier:{r.get('path', '')[:60]}",
            }
            if cod:
                register.append(row)
            else:
                candidates_unmatched.append(row)

    # Write register CSV
    fields = ["categoria", "fornitore", "cod_interno", "macro", "numero", "data", "importo_eur", "fonte"]
    with args.register_out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in register:
            w.writerow(r)
    print(f"\nWrote register (MATCHED): {args.register_out} ({len(register)} rows)")

    # Also write unmatched candidates separately
    if candidates_unmatched:
        unmatched_out = args.register_out.with_name(args.register_out.stem + "_unmatched.csv")
        with unmatched_out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in candidates_unmatched:
                w.writerow(r)
        unmatched_total = sum(r["importo_eur"] for r in candidates_unmatched)
        print(f"Wrote UNMATCHED candidates: {unmatched_out} ({len(candidates_unmatched)} rows, ~€{unmatched_total:,.0f} aggregate — needs review)")

    # Aggregations
    by_cat = defaultdict(float)
    by_macro_cat: dict[tuple[str, str], float] = defaultdict(float)
    by_fornitore: dict[str, dict] = defaultdict(lambda: {"PREVENTIVO": 0.0, "CONTRATTO": 0.0, "FATTURA": 0.0, "macro": ""})

    for r in register:
        cat = r["categoria"]
        macro = r["macro"]
        imp = r["importo_eur"] or 0.0
        by_cat[cat] += imp
        by_macro_cat[(macro, cat)] += imp
        cod = r["cod_interno"] or r["fornitore"]
        by_fornitore[cod][cat] += imp
        if r["cod_interno"]:
            by_fornitore[cod]["macro"] = r["macro"]
            by_fornitore[cod]["ragione_sociale"] = r["fornitore"]

    total_impegno = by_cat["PREVENTIVO"] + by_cat["CONTRATTO"]
    total_competenza = by_cat["FATTURA"]
    gap_etere = BUDGET_TARGET_EUR - max(total_impegno, total_competenza)

    print(f"\n{'━' * 64}")
    print(f"  HPAN25PIANO1 — Registro documenti CapEx")
    print(f"{'━' * 64}\n")

    print(f"Per CATEGORIA:")
    for cat in ("PREVENTIVO", "CONTRATTO", "FATTURA"):
        print(f"  {cat:15s} €{by_cat[cat]:>14,.0f}")
    print(f"  {'─' * 30}")
    print(f"  IMPEGNO totale  €{total_impegno:>14,.0f}  (preventivi + contratti)")
    print(f"  COMPETENZA      €{total_competenza:>14,.0f}  (fatture)")

    print(f"\nPer MACRO budget × categoria:")
    macros = sorted(set(m for m, _ in by_macro_cat.keys()))
    print(f"  {'Macro':<22s} {'Prev':>12s} {'Contr':>12s} {'Fatt':>12s}")
    for m in macros:
        prev = by_macro_cat[(m, "PREVENTIVO")]
        contr = by_macro_cat[(m, "CONTRATTO")]
        fatt = by_macro_cat[(m, "FATTURA")]
        print(f"  {m:<22s} €{prev:>11,.0f} €{contr:>11,.0f} €{fatt:>11,.0f}")

    print(f"\nGAP vs target €{BUDGET_TARGET_EUR:,.0f}:")
    print(f"  Documentato (max impegno/competenza): €{max(total_impegno, total_competenza):,.0f}")
    print(f"  Mancante 'nell'etere':                €{gap_etere:,.0f}  ({gap_etere/BUDGET_TARGET_EUR*100:.0f}%)")

    print(f"\nPer FORNITORE (top 15 by max IMPEGNO+COMPETENZA):")
    sorted_forn = sorted(by_fornitore.items(), key=lambda kv: -(max(kv[1]["PREVENTIVO"] + kv[1]["CONTRATTO"], kv[1]["FATTURA"])))[:15]
    print(f"  {'Cod':<8s} {'Ragione sociale':<35s} {'Macro':<14s} {'Prev':>10s} {'Fatt':>10s}")
    for cod, d in sorted_forn:
        prev = d["PREVENTIVO"] + d["CONTRATTO"]
        fatt = d["FATTURA"]
        rs = (d.get("ragione_sociale") or fornitori.get(cod, {}).get("ragione_sociale") or cod)[:33]
        print(f"  {cod:<8s} {rs:<35s} {d.get('macro', '—')[:13]:<14s} €{prev:>9,.0f} €{fatt:>9,.0f}")


if __name__ == "__main__":
    main()
