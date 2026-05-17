"""Surgical update of HPAN25PIANO1_Tracking_v5.xlsx — in place, no v6.

Inputs:
  - /tmp/hpan25/HPAN25PIANO1_Tracking_v5.xlsx (current v5)
  - /tmp/hpan25/extracted_amounts.json (pdftotext-extracted totals per filename)

Actions per filename:
  - If Documents has matching row with €=None → fill amount
  - If Documents has no row → append new FATTURA row with amount
  - AMCN BONIFICO: re-label as BONIFICO (not FATTURA) so it doesn't count as separate
  - Skip OOS (DI GIULIO, LEROY MERLIN, OMBRELLONI LETTINI) — they go to OOS sheet

Recompute Tracking_Fornitori:
  - # Fatt = count of FATTURA rows in Documents per F-code
  - € Fatt = sum of amounts of FATTURA rows per F-code

Save in place: same path, no v6.
"""

import json
import re
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font

V5_PATH = Path("/tmp/hpan25/HPAN25PIANO1_Tracking_v5.xlsx")
AMOUNTS_JSON = Path("/tmp/hpan25/extracted_amounts.json")
BUDGET_TARGET_EUR = 1_200_000

# Filename → F-code mapping (manual, deterministic — same as audit script)
FILENAME_FCODE = {
    "ABC FLOOR DESIGNER SRL FT463 DEL 08 05 2026.PDF": "F002",
    "AMAZON FT6197 DEL 15 04 2026.PDF": "F004",
    "AMAZON FT619CMPABEI DEL 15 04 2026.PDF": "F004",
    "AMAZON FT619GI8ABEI DEL 15 04 2026.PDF": "F004",
    "AMAZON FT61B20WABEI DEL 19 04 2026.PDF": "F004",
    "AMAZON FT61B22GABEI DEL 19 04 2026.PDF": "F004",
    "AMCN BONIFICO 24042026.pdf": "F001_BONIFICO",  # special: not a fattura
    "B&T FT470 DEL 27032026.pdf": "F005",  # no amount (scanned)
    "B&T SPA FT07401 DEL 30 04 2026.PDF": "F005",
    "CERAMICA D'ARTE SICIGNANO SRL FT410 DEL 30 04 2026.PDF": "F007",
    "CG SERVICE DI CHIANESE GIOVANNI FT82 DEL 11 05 2026.PDF": "F008",
    "ELECTRA S.P.A. FT5023 DEL 230 02 2026.PDF": "F033",
    "ELECTRA S.P.A. FT6828 DEL 05 03 2026.PDF": "F033",
    "FLAB SRL FT588 DEL 30 04 2026.PDF": "F012",
    "FLAB SRL FT589 DEL 30 04 2026.pdf": "F012",
    "FLAB SRL FT590 DEL 30 04 2026.pdf": "F012",
    "IL CENTRO CSC FT203 DEL 12 05 2026.PDF": "F009",
    "INDEL B FT4523 DEL 22 04 2026.PDF": "F015",
    "INDEL B SPA FT4498 DEL 22 04 2026.PDF": "F015",
    "PORTEDI SRL FT1056 DEL 30 04 2026.PDF": "F023",
    "PORTEDI SRL FT116 DEL 30 04 2026.PDF": "F023",
    "SANTELIA LUIGI FT39 DEL 07 05 2026.PDF": "F027",
    "SKLUM FT3631 DEL 08 04 2026.pdf": "F031",
    "SKLUM FT52945 DEL 12 05 2026.pdf": "F031",
    "VDA GROUP SPA FT2131 DEL 29 04 206.PDF": "F028",
    # New camere F-codes
    "NINNI SRL FT57M2026 DEL 01 05 2026.PDF": "F034",
    "OCEANO SRL FT874 DEL 30 04 2026.PDF": "F035",
    "INNOVA RESIN DESIGN SRL FT18 DEL 04 05 2026.PDF": "F036",
    "IRWID SRL FT 2212 DEL 29 04 2026.PDF": "F037",
    # OOS
    "DI GIULIO SRL 577 DEL 30 04 2026.PDF": "OOS",
    "LEROY MERLIN FT11228 DEL 24 04 2026.PDF": "OOS",
}

# Suppliers info for new F-codes (for Tracking_Fornitori rows)
NEW_FCODES_INFO = {
    "F034": ("NINNI SRL", "ARREDI", "TV camere Samsung UE50/UE65"),
    "F035": ("OCEANO SRL", "ARREDI", "Sanitari (lavabi Circle 60, pilette)"),
    "F036": ("INNOVA RESIN DESIGN S.R.L.", "EDILE", "Pavimenti in resina"),
    "F037": ("IRWID SRL", "ARREDI", "Colonnine separatori con nastro"),
}

# Drive folder IDs for Apri → hyperlinks
F_FOLDER_IDS = {
    "F034": "1IIotQaiwmyuDymxGle2v2vmAe5YdBqdf",
    "F035": "1lyvWWTJmH8Ojf1kkDLlYSRqCsLxjuYMh",
    "F036": "1l90qYzNvKbY6uZwBy6UrMp5CP76wOrN_",
    "F037": "1Qbg05RRIeGcVixFh6NCRxpJdjH-XKpSA",
}

# Manual amounts for files where pdftotext couldn't extract or where we need to add manually
MANUAL_AMOUNTS = {
    # FATTURE (Hospitality from PDFs)
    "HOSPITALITY PROJECT FT6 DEL 27012026.pdf":   ("F013", "FATTURA", 3416.00),
    "HOSPITALITY PROJECT FT14 DEL 23022026.pdf":  ("F013", "FATTURA", 3416.00),
    "HOSPITALITY PROJECT FT30 DEL 24042026.pdf":  ("F013", "FATTURA", 3416.00),
    "ORTI SRL - HOSPITALITY PROJECT SALDO FT DEL 27012026.pdf": ("F013", "BONIFICO (saldo FT6)", 3416.60),
    # FATTURE mancanti da Esolver Lista (no PDF locale ma in registro INTUR)
    "ILLUXIT FT 019-2026 del 16-04-2026 (Esolver Lista)":       ("F014", "FATTURA (Esolver)", 7869.00),   # imp 6450 + 22% IVA
    "NESE FT 372-26 del 08-04-2026 (Esolver Lista)":            ("F021", "FATTURA (Esolver)", 4544.56),  # imp 3725.05 + 22% IVA
    "OLIVA COPERTURE FT125 DEL 14 05 2026.pdf":                 ("F022", "FATTURA", 2257.00),     # FPR 125/26 nuova del 14/05

    # PREVENTIVI (categoria PREVENTIVO → cont. col 5/6 # Prev / € Prev)
    "PORTEDI DIERRE Proforma N202 DEL 25022026.pdf":            ("F023", "PREVENTIVO", 24373.81),  # proforma
    "2025-11-10_AMCN_Computo_Metrico_Edile.pdf":                ("F001", "PREVENTIVO", 375389.25),  # computo edile
    "2026-04-16_FalegnameriaCuomo_Preventivo_Camere.pdf":       ("F011", "PREVENTIVO", 77836.00),   # 63800 imp + 22%
    "2026-04-21_Illuxit_Preventivo.pdf":                        ("F014", "PREVENTIVO", 15822.42),   # 12969.20 + IVA
    "2025-11-08_Santelia_Offerta_Lavori_Idro_Meccanico.pdf":    ("F027", "DOC STORICO (rev. superata da 27/11)", 86088.28),  # NON conta
    "offerta_santelia_imp_meccanico_idrico.pdf":                ("F027", "PREVENTIVO", 115297.51),  # valido (rev. 27/11/2025)
    "2026-01-07_METAL2000_Internorm_Serramenti_PVC.pdf":        ("F026", "PREVENTIVO (METAL2000)", 106647.10),  # METAL2000 = SALA, merged in F026
    "2025-10-21_STE_Computo_Metrico_Elettrico.pdf":             ("F025", "PREVENTIVO", 124081.13),  # 101.705,84 imponibile + 22% IVA (Riepilogo Sub Categorie pag 23)
}

# Filesystem rows in Documents that are DUPLICATES of xlsx rows (same fattura, different naming)
# Verified by reading the PDFs. Should be deleted from Documents to avoid double-count.
DUPLICATE_FS_ROWS = {
    # Fatture
    ("F005", "B&T FT470 DEL 27032026.pdf"),  # = xlsx FT V326-00470 (TD02 acconto €4,562.74)
    ("F019", "MARINO FT26 DEL 03042026.pdf"),  # = xlsx FT FPR 4/26 (€2,002)
    ("F020", "MIELE GIUSEPPE FT887 DEL 31032026.pdf"),  # = xlsx FT S/887 (€10,857.37)
    ("F022", "OLIVA COPERTURE FT26 DEL 07012026.PDF"),  # = xlsx FT FPR 2/26 (€3,294)
    # Preventivi — filesystem dupes of xlsx PREVENTIVO rows
    ("F011", "2026-04-16_FalegnameriaCuomo_Preventivo_Camere.pdf"),  # = xlsx Prev PREV-2026-04-16 €63,800
    ("F014", "2026-04-21_Illuxit_Preventivo.pdf"),  # = xlsx Prev PV010.26 €15,822.42
    # F017 LAUDATO AUTOGRU is a preventivo not fattura — relabel rather than delete
}

# Re-categorize as PREVENTIVO (not FATTURA)
RELABEL_AS_PREVENTIVO = {
    ("F017", "Laudato Gru di Laudato Francesco AUTOGRU.PDF"),
}


def main():
    wb = load_workbook(V5_PATH)
    docs = wb["Documents"]
    track = wb["Tracking_Fornitori"]
    amounts = json.loads(AMOUNTS_JSON.read_text())

    # ── Phase 0.5: F029 METAL 2000 == F026 SALA GIANPIERO (stessa entità) ──
    # Merge: reassign all F029 Documents rows to F026
    ALIAS_MAP = {"F029": "F026"}
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        if cod in ALIAS_MAP:
            docs.cell(r, 1).value = ALIAS_MAP[cod]

    # ── Phase 1: index Documents by (cod, filename) ──
    docs_idx = {}  # (cod, filename) → row_number
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        fn = docs.cell(r, 5).value
        if cod and fn:
            docs_idx[(cod, str(fn).strip())] = r

    # ── Phase 2: apply amounts ──
    updated_existing = []
    appended_new = []
    oos_skipped = []
    bonifico = []
    bt_scanned = []

    for fn, info in amounts.items():
        cod = FILENAME_FCODE.get(fn)
        amt = info["amount"]

        if cod == "OOS":
            oos_skipped.append((fn, amt))
            continue

        if cod == "F001_BONIFICO":
            # Re-label any existing FATTURA row for this BONIFICO as BONIFICO
            key = ("F001", fn)
            if key in docs_idx:
                r = docs_idx[key]
                docs.cell(r, 2).value = "BONIFICO (saldo FPR37)"
                docs.cell(r, 8).value = amt
            else:
                # Append new row
                new_r = docs.max_row + 1
                docs.cell(new_r, 1).value = "F001"
                docs.cell(new_r, 2).value = "BONIFICO (saldo FPR37)"
                docs.cell(new_r, 3).value = "Drive filesystem"
                docs.cell(new_r, 4).value = "06_FATTURE_LAVORI_HOTEL"
                docs.cell(new_r, 5).value = fn
                docs.cell(new_r, 8).value = amt
                docs_idx[("F001", fn)] = new_r
            bonifico.append((fn, amt))
            continue

        if cod is None:
            continue

        key = (cod, fn)
        if key in docs_idx:
            r = docs_idx[key]
            existing_amt = docs.cell(r, 8).value
            if existing_amt is None and amt is not None:
                docs.cell(r, 8).value = amt
                updated_existing.append((cod, fn, amt))
        else:
            # Append new FATTURA row
            new_r = docs.max_row + 1
            docs.cell(new_r, 1).value = cod
            docs.cell(new_r, 2).value = "FATTURA"
            docs.cell(new_r, 3).value = "Drive filesystem"
            docs.cell(new_r, 4).value = "06_FATTURE_LAVORI_HOTEL"
            docs.cell(new_r, 5).value = fn
            docs.cell(new_r, 8).value = amt
            docs_idx[key] = new_r
            appended_new.append((cod, fn, amt))
            if amt is None:
                bt_scanned.append((cod, fn))

    # ── Phase 2.5: apply MANUAL_AMOUNTS ──
    manual_added = 0
    manual_updated = 0
    for fn, (cod, cat, amt) in MANUAL_AMOUNTS.items():
        key = (cod, fn)
        if key in docs_idx:
            r = docs_idx[key]
            existing_amt = docs.cell(r, 8).value
            if existing_amt is None and amt is not None:
                docs.cell(r, 8).value = amt
                docs.cell(r, 2).value = cat  # also update category (FATTURA → PREVENTIVO, etc.)
                manual_updated += 1
        else:
            new_r = docs.max_row + 1
            docs.cell(new_r, 1).value = cod
            docs.cell(new_r, 2).value = cat
            docs.cell(new_r, 3).value = "Drive filesystem"
            docs.cell(new_r, 4).value = "06_FATTURE_LAVORI_HOTEL"
            docs.cell(new_r, 5).value = fn
            docs.cell(new_r, 8).value = amt
            docs_idx[key] = new_r
            manual_added += 1

    # Re-label LAUDATO AUTOGRU as PREVENTIVO (not fattura)
    relabeled = 0
    for (cod, fn) in RELABEL_AS_PREVENTIVO:
        if (cod, fn) in docs_idx:
            r = docs_idx[(cod, fn)]
            docs.cell(r, 2).value = "PREVENTIVO"
            relabeled += 1

    # Delete known FS duplicate rows (same fattura as xlsx, different naming)
    rows_to_delete = []
    for (cod, fn) in DUPLICATE_FS_ROWS:
        if (cod, fn) in docs_idx:
            rows_to_delete.append(docs_idx[(cod, fn)])
    for r in sorted(rows_to_delete, reverse=True):
        docs.delete_rows(r, 1)

    print(f"\n── Documents updates ──")
    print(f"  Updated existing (€None → €amount): {len(updated_existing)}")
    print(f"  Appended new FATTURA rows:          {len(appended_new)}")
    print(f"  Manual additions (Hospitality+Proforma): {manual_added}")
    print(f"  Re-labeled FATTURA → PREVENTIVO:    {relabeled}")
    print(f"  Deleted FS-duplicate rows:          {len(rows_to_delete)}")
    print(f"  Relabeled BONIFICO (excluded):      {len(bonifico)}")
    print(f"  Skipped OOS:                        {len(oos_skipped)}")
    print(f"  Scanned PDF (€ unknown):            {len(bt_scanned)}")
    for c, f in bt_scanned:
        print(f"    {c}: {f}")

    # ── Cleanup obsolete F019 rows (Santelia mis-routed, shortcuts deleted on Drive) ──
    obsolete_to_delete = []
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        fn = docs.cell(r, 5).value
        if cod == "F019" and fn:
            if "SANTELIA" in str(fn).upper() or "FALEGNAMERIA" in str(fn).upper() or "CUOMO" in str(fn).upper():
                obsolete_to_delete.append(r)
    # Delete in reverse to preserve row indices
    for r in reversed(obsolete_to_delete):
        docs.delete_rows(r, 1)
    print(f"  Deleted obsolete F019 rows:         {len(obsolete_to_delete)}")

    # ── Add missing ROMANO FT13 row ──
    has_ft13 = any(
        docs.cell(r, 1).value == "F024" and "FT13" in str(docs.cell(r, 5).value or "").upper()
        for r in range(2, docs.max_row + 1)
    )
    if not has_ft13:
        new_r = docs.max_row + 1
        docs.cell(new_r, 1).value = "F024"
        docs.cell(new_r, 2).value = "FATTURA"
        docs.cell(new_r, 3).value = "Drive filesystem"
        docs.cell(new_r, 4).value = "06_FATTURE_LAVORI_HOTEL"
        docs.cell(new_r, 5).value = "ROMANO GAETANO FT13 DEL 29 04 2026.PDF"
        docs.cell(new_r, 8).value = 3100.00  # placeholder — user said ~€3,100, will be verified
        print(f"  Added ROMANO FT13 placeholder €3,100 (will be verified)")

    # ── Phase 3: add new F034..F037 rows in Tracking_Fornitori (if missing) ──
    existing_codes = set()
    track_rows = {}  # cod → row
    for r in range(2, track.max_row + 1):
        c = track.cell(r, 1).value
        if c and c != "TOTALE":
            existing_codes.add(c)
            track_rows[c] = r

    last_data_row = max(track_rows.values())
    totale_row = None
    for r in range(2, track.max_row + 1):
        if track.cell(r, 1).value == "TOTALE":
            totale_row = r
            break

    new_codes_to_add = [c for c in NEW_FCODES_INFO if c not in existing_codes]
    if new_codes_to_add and totale_row:
        # AVOID insert_rows (breaks hyperlinks). Instead: cache TOTALE, write new codes
        # in rows currently occupied by TOTALE, then place TOTALE below them.
        totale_values = [track.cell(totale_row, c).value for c in range(1, track.max_column + 1)]
        # Clear TOTALE row
        for c in range(1, track.max_column + 1):
            track.cell(totale_row, c).value = None
        # Write new F-codes + hyperlink "Apri →" in col 13
        for offset, cod in enumerate(new_codes_to_add):
            r = totale_row + offset
            nome, macro, scope = NEW_FCODES_INFO[cod]
            track.cell(r, 1).value = cod
            track.cell(r, 2).value = nome
            track.cell(r, 3).value = macro
            track.cell(r, 4).value = scope
            # Drive folder hyperlink
            folder_id = F_FOLDER_IDS.get(cod)
            if folder_id:
                cell = track.cell(r, 13)
                cell.value = "Apri →"
                cell.hyperlink = f"https://drive.google.com/drive/folders/{folder_id}"
                cell.font = Font(color="0000FF", underline="single")
            track_rows[cod] = r
        # Write TOTALE in new position
        new_totale_row = totale_row + len(new_codes_to_add)
        for c, v in enumerate(totale_values, start=1):
            track.cell(new_totale_row, c).value = v
        totale_row = new_totale_row

    # ── Phase 4: recompute # Fatt and € Fatt per F-code from Documents ──
    from collections import defaultdict
    counts = defaultdict(int)
    sums = defaultdict(float)
    has_unknown_amt = defaultdict(bool)
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        cat = docs.cell(r, 2).value
        amt = docs.cell(r, 8).value
        if not cod or not cat:
            continue
        cat_s = str(cat).upper()
        # Count FATTURA rows (including "FATTURA (xlsx)" and "FATTURA")
        # Exclude BONIFICO, COMUNICAZIONE, PREVENTIVO, ORDINE, "?" placeholders
        if "FATTURA" not in cat_s:
            continue
        if "BONIFICO" in cat_s:
            continue
        # Skip "FATTURA (xlsx)" if a corresponding "FATTURA" filesystem row exists for the same FT number
        # but simpler: dedup by FT number
        counts[cod] += 1
        if amt is not None and isinstance(amt, (int, float)):
            sums[cod] += amt
        else:
            has_unknown_amt[cod] = True

    # Dedup: F001 has BOTH "FATTURA (xlsx) FT FPR 31/26" AND "FATTURA A.M.C.N. SRL FT31 DEL 26 03 2026.PDF"
    # which is the SAME fattura. Keep "FATTURA (xlsx)" with amount, but don't double-count filesystem row.
    def extract_ft_num(fname):
        s = str(fname).upper().replace('_', ' ')  # treat _ as space for tokenization
        pre = re.split(r'\s+DEL\s+', s, maxsplit=1)[0]
        # Strategy 1: FT/FPR directly stuck to alphanumeric (most reliable)
        m = re.search(r'\b(?:FT|FPR)([A-Z0-9]+)', pre)
        if m:
            captured = m.group(1)
            # If captured ends with digits, prefer trailing digits (SDI codes like IT00126V0001851 → 1851)
            trail = re.search(r'\d+$', captured)
            if trail and len(trail.group(0)) >= 3 and re.search(r'[A-Z]', captured):
                return trail.group(0).lstrip('0') or trail.group(0)
            return captured.lstrip('0') or captured
        # Strategy 2: FT/FPR keyword followed by space + token
        cleaned = re.sub(r'\b(FATTURA\s+N\.?|FT|FPR|F\.T\.|FATT\.|N\.)\b\s*', ' ', pre)
        # Strip only 2-digit year suffix /YY (not 3+ digit FT numbers)
        cleaned = re.sub(r'/\d{2}\b', '', cleaned)
        digits = re.findall(r'\d+', cleaned)
        if not digits: return None
        for d in reversed(digits):
            if not (len(d) == 4 and 2020 <= int(d) <= 2030):
                return d.lstrip('0') or d
        return digits[-1].lstrip('0') or digits[-1]

    counts = defaultdict(int)
    sums = defaultdict(float)
    has_unknown_amt = defaultdict(bool)
    fatt_rows = []
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        cat = docs.cell(r, 2).value
        fn = docs.cell(r, 5).value
        amt = docs.cell(r, 8).value
        if not cod or not cat: continue
        cat_s = str(cat).upper()
        if "FATTURA" not in cat_s: continue
        if "BONIFICO" in cat_s: continue
        ft = extract_ft_num(fn) or str(fn)[:30]
        fatt_rows.append((cod, cat_s, fn, ft, amt))

    # Prefer "FATTURA (xlsx)" over filesystem for amount
    # Strategy: group by (cod, ft), pick the row with non-None amount preferring xlsx
    from collections import OrderedDict
    groups = OrderedDict()
    for cod, cat_s, fn, ft, amt in fatt_rows:
        k = (cod, ft)
        if k not in groups:
            groups[k] = []
        groups[k].append((cat_s, fn, amt))

    for (cod, ft), entries in groups.items():
        # Pick entry: prefer one with non-None amount; if multiple, prefer xlsx
        best = None
        for cat_s, fn, amt in entries:
            if amt is None: continue
            if best is None or "XLSX" in cat_s:
                best = (cat_s, fn, amt)
        if best is None:
            # All None → still count as a row, amount unknown
            counts[cod] += 1
            has_unknown_amt[cod] = True
        else:
            counts[cod] += 1
            sums[cod] += best[2]

    # ── Phase 4b: recompute # Prev and € Prev per F-code from PREVENTIVO rows ──
    prev_counts = defaultdict(int)
    prev_sums = defaultdict(float)
    prev_unknown = defaultdict(bool)
    for r in range(2, docs.max_row + 1):
        cod = docs.cell(r, 1).value
        cat = docs.cell(r, 2).value
        amt = docs.cell(r, 8).value
        if not cod or not cat: continue
        cat_s = str(cat).upper()
        if "PREVENTIVO" not in cat_s and "PROFORMA" not in cat_s:
            continue
        prev_counts[cod] += 1
        if amt is not None and isinstance(amt, (int, float)):
            prev_sums[cod] += amt
        else:
            prev_unknown[cod] = True

    # ── Phase 5: write counts/sums to Tracking_Fornitori ──
    for cod, r in track_rows.items():
        # F029 METAL 2000 == F026 SALA — riga unita: azzera + indica merge
        if cod == "F029":
            track.cell(r, 2).value = "METAL 2000 → vedi F026 SALA (stessa entità)"
            for c in (5, 6, 7, 8, 9, 10, 11):
                track.cell(r, c).value = None
            track.cell(r, 12).value = "MERGED → F026"
            continue
        # Preventivi
        np = prev_counts.get(cod, 0)
        ep = prev_sums.get(cod, 0)
        track.cell(r, 5).value = np if np > 0 else 0
        track.cell(r, 6).value = ep if ep > 0 else None
        # Fatture
        n = counts.get(cod, 0)
        s = sums.get(cod, 0)
        track.cell(r, 9).value = n if n > 0 else 0
        track.cell(r, 10).value = s if s > 0 else None
        # Totale € = MAX(€ Prev, € Fatt) + € Contr — preventivo è il cap, fatt è la realizzazione
        # Prev + Fatt sarebbe double-count perché la fattura realizza il preventivo
        contr = track.cell(r, 8).value or 0
        total = max(ep, s) + contr
        track.cell(r, 11).value = total if total > 0 else None
        # Status (col 12)
        contr_n = track.cell(r, 7).value or 0
        notes = []
        if has_unknown_amt.get(cod): notes.append("€? fatt")
        if prev_unknown.get(cod): notes.append("€? prev")
        note = f" ({', '.join(notes)})" if notes else ""
        if n > 0 and (np > 0 or contr_n > 0):
            status = "COMPLETO" + note
        elif n > 0:
            status = "SOLO COMPETENZA" + note
        elif np > 0 or contr_n > 0:
            status = "SOLO IMPEGNO" + note
        else:
            status = "SCOPERTO"
        track.cell(r, 12).value = status

    # Update TOTALE row
    if totale_row:
        tot_prev = sum((track.cell(r, 6).value or 0) for r in track_rows.values())
        tot_contr = sum((track.cell(r, 8).value or 0) for r in track_rows.values())
        tot_fatt = sum((track.cell(r, 10).value or 0) for r in track_rows.values())
        tot_max = sum((track.cell(r, 11).value or 0) for r in track_rows.values())  # MAX-per-row aggregato
        track.cell(totale_row, 6).value = tot_prev if tot_prev else None
        track.cell(totale_row, 8).value = tot_contr if tot_contr else None
        track.cell(totale_row, 10).value = tot_fatt if tot_fatt else None
        track.cell(totale_row, 11).value = tot_max  # Σ MAX(Prev, Fatt) per F-code

    # ── Phase 6: write OOS sheet ──
    sheet_name = "OOS_Out_Of_Scope"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    oos = wb.create_sheet(sheet_name)
    oos.cell(1, 1).value = "Fornitore"
    oos.cell(1, 2).value = "File"
    oos.cell(1, 3).value = "€ Importo"
    oos.cell(1, 4).value = "Motivo OOS"
    for c in range(1, 5):
        oos.cell(1, c).font = Font(bold=True)
        oos.cell(1, c).fill = PatternFill("solid", fgColor="FFD9D9D9")

    oos_data = [
        ("DI GIULIO SRL", "DI GIULIO SRL 577 DEL 30 04 2026.PDF", 58.00, "Centralina irrigazione — giardino/esterno"),
        ("LEROY MERLIN", "LEROY MERLIN FT11228 DEL 24 04 2026.PDF", 349.39, "Fioriere — outdoor, intestate PANORAMA COMPANY"),
        ("OMBRELLONI LETTINI ITALIA SRL", "OMBRELLONI LETTINI ITALIA SRL FT23 DEL 22 04 2026.PDF", None, "Spiaggia — altro progetto HPAN25SPIAGGIA"),
        ("OMBRELLONI LETTINI ITALIA SRL", "OMBRELLONI LETTINI ITALIA SRL FT30 DEL 12 05 2026.PDF", None, "Spiaggia — altro progetto HPAN25SPIAGGIA"),
    ]
    for i, (fornitore, fn, amt, motivo) in enumerate(oos_data, start=2):
        oos.cell(i, 1).value = fornitore
        oos.cell(i, 2).value = fn
        oos.cell(i, 3).value = amt
        oos.cell(i, 4).value = motivo
    oos.column_dimensions["A"].width = 30
    oos.column_dimensions["B"].width = 55
    oos.column_dimensions["C"].width = 12
    oos.column_dimensions["D"].width = 60

    # ── Phase 7: build Chiusura_Fornitori sheet (operational cockpit) ──
    # Reads partite aperte INTUR + ORTI (for F013) from Esolver export, computes € Pagato per F-code
    partite_xlsx = Path('/Users/stefanodellapietra/Desktop/WORK/tmp/situazionepartitefornitoriINTUR.xlsx')
    partite_orti_xlsx = Path('/Users/stefanodellapietra/Desktop/situazionepartitefornitoriORTI.xlsx')
    open_per_fc = {}
    open_docs_per_fc = {}
    if partite_xlsx.exists():
        from openpyxl import load_workbook as lwb
        pwb = lwb(partite_xlsx, data_only=True)
        pws = pwb['Foglio1']
        HPAN_LOCAL = {
            'A.M.C.N': 'F001', 'ABC FLOOR': 'F002', 'AMAZON': 'F004', 'Amazon': 'F004',
            'B & T': 'F005', 'SICIGNANO': 'F007', 'CHIANESE': 'F008', 'CG SERVICE': 'F008',
            'CENTRO CSC': 'F009', 'DOMUS': 'F010', 'CUOMO': 'F011', 'FALEGNAMERIA': 'F011',
            'F.L.A.B': 'F012', 'HOSPITALITY': 'F013', 'ILLUXIT': 'F014', 'INDEL': 'F015',
            'ITX': 'F016', 'LAUDATO': 'F017', 'MARIGLIANO': 'F018', 'MARINO LUIGI': 'F019',
            'MIELE': 'F020', 'NESE': 'F021', 'OLIVA': 'F022', 'PORTEDI': 'F023', 'DIERRE': 'F023',
            'ROMANO GAETANO': 'F024', 'S.T.E': 'F025', 'SALA': 'F026', 'METAL 2000': 'F029',
            'SANTELIA': 'F027', 'VDA': 'F028', 'GRANATO': 'F030', 'SKLUM': 'F031',
            'ORILIA': 'F032', 'ELECTRA': 'F033', 'NINNI': 'F034', 'OCEANO': 'F035',
            'INNOVA': 'F036', 'IWIRD': 'F037', 'IRWID': 'F037', 'PISACANE': 'F003',
            'CAPONE': 'F006',
        }
        def _fc(s):
            s = str(s or '').upper()
            for p, c in HPAN_LOCAL.items():
                if p.upper() in s: return c
            return None
        for r in range(2, pws.max_row+1):
            forn = pws.cell(r, 12).value
            saldo = pws.cell(r, 26).value
            docref = pws.cell(r, 19).value
            fc = _fc(forn)
            if fc and isinstance(saldo, (int, float)) and saldo != 0:
                open_per_fc[fc] = open_per_fc.get(fc, 0) + abs(saldo)
                open_docs_per_fc.setdefault(fc, []).append(str(docref or '')[:30])

    # ORTI partite: only relevant for F013 HOSPITALITY (and possibly F029 SALA?)
    # Other matches in ORTI are FALSE POSITIVES (different suppliers with similar names)
    if partite_orti_xlsx.exists():
        from openpyxl import load_workbook as lwb
        owb = lwb(partite_orti_xlsx, data_only=True)
        ows = owb['Foglio1']
        for r in range(2, ows.max_row+1):
            forn = ows.cell(r, 12).value
            saldo = ows.cell(r, 26).value
            docref = ows.cell(r, 19).value
            # Only HOSPITALITY PROJECT SRL is a real HPAN25 fornitore in ORTI partite
            if forn and 'HOSPITALITY PROJECT' in str(forn).upper():
                if isinstance(saldo, (int, float)) and saldo != 0:
                    open_per_fc['F013'] = open_per_fc.get('F013', 0) + abs(saldo)
                    open_docs_per_fc.setdefault('F013', []).append(f"{str(docref or '')[:30]} (ORTI)")

    # Preserve manual columns (Lavoro Finito?, Note) from existing Chiusura before rebuild
    prev_finito = {}
    prev_note_manual = {}
    if "Chiusura_Fornitori" in wb.sheetnames:
        old = wb["Chiusura_Fornitori"]
        hdr = {old.cell(1, c).value: c for c in range(1, old.max_column + 1)}
        col_fin = hdr.get("Lavoro Finito?")
        col_note = hdr.get("Note")
        for r in range(2, old.max_row + 1):
            cod = old.cell(r, 1).value
            if not cod or cod == "TOTALE":
                continue
            if col_fin and old.cell(r, col_fin).value:
                prev_finito[cod] = old.cell(r, col_fin).value
            if col_note and old.cell(r, col_note).value:
                prev_note_manual[cod] = old.cell(r, col_note).value
        del wb["Chiusura_Fornitori"]

    chs = wb.create_sheet("Chiusura_Fornitori")
    headers = ["Cod", "Fornitore", "Macro", "Scope",
               "€ Preventivo", "€ Fatturato", "€ Consuntivo", "Scostamento",
               "€ Pagato", "€ Da Pagare", "€ Da Fatturare",
               "Lavoro Finito?", "Stato Operativo", "Ultima Evidenza", "Prossima Azione", "Note"]
    for c, h in enumerate(headers, start=1):
        cell = chs.cell(1, c)
        cell.value = h
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor="FF2E5BBA")

    # Build cockpit data (values only — formulas written after)
    cockpit_rows = []
    for cod in sorted(track_rows.keys()):
        if cod == "F029":  # merged into F026
            continue
        tr = track_rows[cod]
        ep = track.cell(tr, 6).value or 0      # € Preventivo
        ef = track.cell(tr, 10).value or 0     # € Consuntivo (= Fatturato)
        e_aperto = open_per_fc.get(cod, 0)
        e_pagato = max(0, ef - e_aperto) if ef else 0
        e_da_pagare = e_aperto if e_aperto > 0 else 0
        finito = prev_finito.get(cod, "")
        # € Da Fatturare: 0 se lavoro finito (gap = risparmio), altrimenti Prev - Cons
        e_da_fatt = 0 if finito == "SI" else max(0, ep - ef)
        evidenza = ""
        if open_docs_per_fc.get(cod):
            evidenza = open_docs_per_fc[cod][-1][:30]
        elif ef > 0:
            evidenza = "Tutte fatture pagate"
        note_auto = "(ORTI)" if cod == "F013" else ""
        note = note_auto or prev_note_manual.get(cod, "")
        cockpit_rows.append({
            "cod": cod, "nome": track.cell(tr, 2).value or "",
            "macro": track.cell(tr, 3).value or "", "scope": track.cell(tr, 4).value or "",
            "ep": ep, "ef": ef, "pagato": e_pagato, "dapagare": e_da_pagare,
            "dafatt": e_da_fatt, "finito": finito, "evidenza": evidenza, "note": note,
        })

    # Write rows. Colonne (16):
    #  E € Preventivo (val) | F € Fatturato (val) | G € Consuntivo (formula, vuoto finché non finito)
    #  H Scostamento (formula) | I € Pagato (val) | J € Da Pagare (val) | K € Da Fatturare (formula)
    #  L Lavoro Finito? (manuale, dropdown) | M Stato (formula) | N Evidenza | O Azione (formula) | P Note
    row = 2
    for d in cockpit_rows:
        r = row
        chs.cell(r, 1).value = d["cod"]
        chs.cell(r, 2).value = d["nome"]
        chs.cell(r, 3).value = d["macro"]
        chs.cell(r, 4).value = d["scope"]
        chs.cell(r, 5).value = d["ep"] or None                             # E € Preventivo
        chs.cell(r, 6).value = d["ef"] or None                             # F € Fatturato
        chs.cell(r, 7).value = f'=IF(L{r}="SI",F{r},"")'                   # G € Consuntivo — vuoto finché non finito
        chs.cell(r, 8).value = f'=IF(G{r}="","",G{r}-E{r})'                # H Scostamento — vuoto finché no consuntivo
        chs.cell(r, 9).value = d["pagato"] or None                         # I € Pagato
        chs.cell(r, 10).value = d["dapagare"] or None                      # J € Da Pagare
        chs.cell(r, 11).value = f'=IF(L{r}="SI",0,MAX(E{r}-F{r},0))'       # K € Da Fatturare
        chs.cell(r, 12).value = d["finito"] or None                        # L Lavoro Finito? (manuale)
        chs.cell(r, 13).value = (                                          # M Stato Operativo
            f'=IF(AND(F{r}=0,E{r}=0),"SCOPERTO",'
            f'IF(AND(F{r}=0,E{r}>0),"SOLO IMPEGNO",'
            f'IF(AND(J{r}>0,K{r}>0),"LAVORI IN CORSO",'
            f'IF(J{r}>0,"DA PAGARE",'
            f'IF(K{r}>0,"DA FATTURARE","CHIUSO")))))'
        )
        chs.cell(r, 14).value = d["evidenza"] or None                      # N Ultima Evidenza
        chs.cell(r, 15).value = (                                          # O Prossima Azione
            f'=IF(M{r}="DA PAGARE","Verificare bonifico / pagare",'
            f'IF(M{r}="DA FATTURARE","Sollecitare fattura saldo",'
            f'IF(M{r}="LAVORI IN CORSO","Attendere completamento + saldo",'
            f'IF(M{r}="SOLO IMPEGNO","Avviare lavori o annullare ordine",'
            f'IF(M{r}="SCOPERTO","Verificare se serve","—")))))'
        )
        chs.cell(r, 16).value = d["note"] or None                          # P Note
        row += 1
    last_row = row - 1

    # Dropdown SI/PARZIALE/NO su Lavoro Finito? (col L)
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1='"SI,PARZIALE,NO"', allow_blank=True)
    chs.add_data_validation(dv)
    dv.add(f"L2:L{last_row}")

    # Conditional formatting colori su Stato Operativo (col M)
    from openpyxl.formatting.rule import CellIsRule
    cf_colors = {
        "CHIUSO": "FFA5D6A7", "DA PAGARE": "FFFFE082", "DA FATTURARE": "FFFFAB91",
        "LAVORI IN CORSO": "FFFFD54F", "SOLO IMPEGNO": "FF90CAF9", "SCOPERTO": "FFE0E0E0",
    }
    for txt, color in cf_colors.items():
        chs.conditional_formatting.add(
            f"M2:M{last_row}",
            CellIsRule(operator="equal", formula=[f'"{txt}"'],
                       fill=PatternFill("solid", fgColor=color)))

    # Totale row
    chs.cell(row, 1).value = "TOTALE"
    chs.cell(row, 1).font = Font(bold=True)
    for col in ("E", "F", "G", "H", "I", "J", "K"):
        cidx = ord(col) - 64
        chs.cell(row, cidx).value = f"=SUM({col}2:{col}{last_row})"
        chs.cell(row, cidx).font = Font(bold=True)

    # Column widths (16 colonne)
    widths = [6, 30, 11, 28, 12, 12, 12, 11, 11, 11, 12, 13, 16, 26, 30, 20]
    for i, w in enumerate(widths, start=1):
        chs.column_dimensions[chr(64+i)].width = w

    print(f"\n── Chiusura_Fornitori sheet built ──")
    print(f"  Rows: {row-2} F-codes + 1 totale")

    # ── Phase 8: rebuild Summary sheet ──
    summ = wb["Summary"]
    # Clear existing content
    for r in range(1, summ.max_row + 1):
        for c in range(1, summ.max_column + 1):
            summ.cell(r, c).value = None

    # Aggregate from Tracking_Fornitori (skip F029 merged + TOTALE)
    s_prev = s_fatt = s_total = 0
    macro_prev = defaultdict(float)
    macro_fatt = defaultdict(float)
    scoperti = []
    for cod, r in track_rows.items():
        if cod == "F029":
            continue
        ep = track.cell(r, 6).value or 0
        ef = track.cell(r, 10).value or 0
        tt = track.cell(r, 11).value or 0
        macro = track.cell(r, 3).value or "—"
        nome = track.cell(r, 2).value or cod
        s_prev += ep; s_fatt += ef; s_total += tt
        macro_prev[macro] += ep
        macro_fatt[macro] += ef
        if ep == 0 and ef == 0:
            scoperti.append(f"{cod} {nome}")

    # Aggregate cassa from cockpit_rows (valori calcolati, non celle-formula)
    s_pagato = sum(d["pagato"] for d in cockpit_rows)
    s_dapagare = sum(d["dapagare"] for d in cockpit_rows)
    s_dafatturare = sum(d["dafatt"] for d in cockpit_rows)
    # Totale progetto = consuntivo-aware: pagato + da pagare + da fatturare
    # (quando Lavoro Finito=SI, da fatturare=0 → il fornitore conta per il consuntivo reale)
    s_total = s_pagato + s_dapagare + s_dafatturare

    bold = Font(bold=True)
    title_fill = PatternFill("solid", fgColor="FF2E5BBA")
    summ.cell(1, 1).value = "HPAN25PIANO1 — Camere Primo Piano · Tracking Master"
    summ.cell(1, 1).font = Font(bold=True, size=13)
    summ.cell(3, 1).value = "Budget target"
    summ.cell(3, 2).value = BUDGET_TARGET_EUR
    summ.cell(3, 1).font = bold

    rows_data = [
        (5, "IMPEGNO — Σ preventivi/contratti (€ Prev)", s_prev),
        (6, "COMPETENZA — Σ fatture emesse (€ Fatt)", s_fatt),
        (7, "CASSA — Σ realmente pagato (€ Pagato)", s_pagato),
        (9, "TOTALE PROGETTO — Pagato + Da Pagare + Da Fatturare (consuntivo-aware)", s_total),
        (10, "  ├─ già pagato (CASSA)", s_pagato),
        (11, "  ├─ fatturato da pagare (€ Da Pagare)", s_dapagare),
        (12, "  └─ impegnato da fatturare (€ Da Fatturare)", s_dafatturare),
        (14, "Budget residuo vs target (€1.2M)", BUDGET_TARGET_EUR - s_total),
    ]
    for r, label, val in rows_data:
        summ.cell(r, 1).value = label
        summ.cell(r, 2).value = val
        if r in (9,):
            summ.cell(r, 1).font = bold
            summ.cell(r, 2).font = bold

    # Macro breakdown
    summ.cell(16, 1).value = "Per macro categoria:"
    summ.cell(16, 1).font = bold
    summ.cell(17, 1).value = "Macro"
    summ.cell(17, 2).value = "€ IMPEGNO (Prev)"
    summ.cell(17, 3).value = "€ COMPETENZA (Fatt)"
    for c in range(1, 4):
        summ.cell(17, c).font = bold
    rr = 18
    for macro in sorted(set(list(macro_prev.keys()) + list(macro_fatt.keys()))):
        summ.cell(rr, 1).value = macro
        summ.cell(rr, 2).value = round(macro_prev[macro], 2) or None
        summ.cell(rr, 3).value = round(macro_fatt[macro], 2) or None
        rr += 1

    # Scoperti
    rr += 1
    summ.cell(rr, 1).value = f"Fornitori SCOPERTI (zero preventivi + zero fatture): {len(scoperti)}"
    summ.cell(rr, 1).font = bold
    rr += 1
    for sc in scoperti:
        summ.cell(rr, 1).value = sc
        rr += 1

    summ.column_dimensions["A"].width = 56
    summ.column_dimensions["B"].width = 18
    summ.column_dimensions["C"].width = 20

    print(f"\n── Summary rebuilt ──")
    print(f"  IMPEGNO €{s_prev:,.0f} | COMPETENZA €{s_fatt:,.0f} | CASSA €{s_pagato:,.0f}")
    print(f"  TOTALE IMPEGNO €{s_total:,.0f} | Budget residuo €{BUDGET_TARGET_EUR - s_total:,.0f}")
    print(f"  Scoperti: {len(scoperti)} ({', '.join(s.split()[0] for s in scoperti)})")

    wb.save(V5_PATH)
    print(f"\nSaved: {V5_PATH}")

    # Final summary
    print(f"\n── Tracking_Fornitori (post-update) ──")
    print(f"{'Cod':<6} {'Nome':<32} {'#F':<4} {'€ Fatt':>12} {'Status'}")
    print("-" * 90)
    for cod in sorted(track_rows.keys()):
        r = track_rows[cod]
        nome = (track.cell(r, 2).value or "")[:30]
        n = track.cell(r, 9).value
        s = track.cell(r, 10).value
        st = track.cell(r, 12).value or ""
        s_str = f"€{s:,.0f}" if s else "-"
        print(f"{cod:<6} {nome:<32} {n!s:<4} {s_str:>12} {st}")
    print(f"\nTOTALE € Fatt: €{sum((track.cell(r, 10).value or 0) for r in track_rows.values()):,.2f}")


if __name__ == "__main__":
    main()
