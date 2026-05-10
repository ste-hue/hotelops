"""
Riconciliazione cassa giornaliera da accodamenti HotelCube → Esolver.

Legge i file TXT pipe-delimited (H_/R_/C_ × Corrispettivi/Movimenti/Fatture),
aggrega per giorno × struttura (POS, contanti, caparre incassate/evase,
corrispettivi netti/lordi, fatture emesse) e produce un Excel con due fogli:
"Riepilogo" (totali giornalieri) e "Dettaglio strutture" (HP/ANGELINA/CVM).

Logica portata da reconciliation_dino amputata di IMPPN, fingerprint state,
CSV writer e Dino account mapping.

Uso programmatico:
    from verticals.condges.cassa_giornaliera import run_accodamenti_to_excel
    run_accodamenti_to_excel(Path("~/datahub/ingresso/accodamenti/ORTI"),
                              Path("~/Desktop/Riconciliazione.xlsx"))
"""

from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.parsers.accodamenti import (
    is_caparra_account,
    parse_corrispettivi,
    parse_fatture,
    parse_movimenti,
)

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT = Path.home() / "Desktop" / "Riconciliazione_accodamenti.xlsx"

_STRUTTURA_DISPLAY = {"hotel": "HP", "residence": "ANGELINA", "cvm": "CVM", "unknown": "???"}
_STRUTTURA_FT_SUFFIX = {"hotel": "H", "residence": "R", "cvm": "C", "unknown": ""}

# Tolleranza di quadratura: differenza massima (€) tra incassi e atteso
# prima di marcare la riga come "non quadra". 1€ copre arrotondamenti centesimi
# su più movimenti senza nascondere errori reali.
_QUADRA_TOLERANCE = Decimal("1")


# ── Classificazione conti ─────────────────────────────────────────────────────


def esolver_account_to_dotted(raw: str) -> str:
    """Converte conto Esolver da compatto (479101) a puntato (47.91.01)."""
    raw = raw.strip()
    if "." in raw:
        return raw
    if len(raw) == 6:
        return f"{raw[0:2]}.{raw[2:4]}.{raw[4:6]}"
    if len(raw) == 8:
        return f"{raw[0:2]}.{raw[2:4]}.{raw[4:6]}.{raw[6:8]}"
    return raw


def classify_payment_account(conto_esolver: str) -> str:
    """Classifica un conto Esolver come pos | cash | caparra | ''."""
    if not conto_esolver:
        return ""
    if is_caparra_account(conto_esolver):
        return "caparra"
    dotted = esolver_account_to_dotted(conto_esolver)
    if dotted.startswith("19.90"):
        return "pos"
    if dotted == "19.03.03":
        return "cash"
    return ""


# ── Normalizzazione date ──────────────────────────────────────────────────────


def _normalize_date(date_str: str) -> str:
    """Normalizza a dd/mm/yyyy da ddmmyyyy (Esolver), dd/mm/yyyy, yyyy-mm-dd.

    Returns "" on unparseable input.
    """
    date_str = date_str.strip() if date_str else ""
    if not date_str:
        return ""
    if "/" in date_str and len(date_str) == 10:
        return date_str
    if "-" in date_str:
        parts = date_str.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}"
    logger.warning("Data non parsabile: %r → scartato", date_str)
    return ""


def _sort_key_date(date_str: str) -> tuple:
    try:
        d, m, y = date_str.split("/")
        return (int(y), int(m), int(d))
    except (ValueError, IndexError):
        return (9999, 99, 99)


# ── Aggregazione giornaliera ──────────────────────────────────────────────────


def _new_day() -> dict:
    return {
        "corrispettivi_pos": Decimal("0"),
        "corrispettivi_contanti": Decimal("0"),
        "corrispettivi_storno_caparra": Decimal("0"),
        "caparre_incassate_pos": Decimal("0"),
        "caparre_incassate_contanti": Decimal("0"),
        "caparre_evase": Decimal("0"),
        "fatture_importo": Decimal("0"),
        "fatture_lista": [],
        "giri_caparra_ft": [],
    }


def _gen_importo(gen: dict) -> Decimal:
    return max(gen.get("importo_dare", Decimal("0")), gen.get("importo_avere", Decimal("0")))


def _accumulate(corr_events, mov_events, fatt_events, days, key_fn):
    # Corrispettivi
    for event in corr_events:
        data = _normalize_date(event["tes"]["data_doc"])
        if not data:
            continue
        day = days[key_fn(event, data)]
        for gen in event["gens"]:
            importo = gen["importo"]
            if importo == Decimal("0"):
                continue
            tipo = classify_payment_account(gen["conto_esolver"])
            if tipo == "pos":
                day["corrispettivi_pos"] += importo
            elif tipo == "cash":
                day["corrispettivi_contanti"] += importo
            elif tipo == "caparra":
                day["corrispettivi_storno_caparra"] += importo

    # Movimenti
    for event in mov_events:
        if not event["gens"]:
            continue
        data = _normalize_date(event["gens"][0]["data_doc"])
        if not data:
            continue
        day = days[key_fn(event, data)]
        event_type = event["type"]

        if event_type == "incasso_caparra":
            for gen in event["gens"]:
                importo = _gen_importo(gen)
                if importo <= Decimal("0"):
                    continue
                tipo = classify_payment_account(gen["conto_esolver"])
                if tipo == "pos":
                    day["caparre_incassate_pos"] += importo
                elif tipo == "cash":
                    day["caparre_incassate_contanti"] += importo

        elif event_type == "giro_caparra":
            for gen in event["gens"]:
                importo = _gen_importo(gen)
                if importo > Decimal("0") and classify_payment_account(gen["conto_esolver"]) == "caparra":
                    day["caparre_evase"] += importo
            par = event.get("par")
            if par and par.get("num_doc_partita"):
                suffix = _STRUTTURA_FT_SUFFIX.get(event.get("struttura", ""), "")
                day["giri_caparra_ft"].append({
                    "num": par["num_doc_partita"],
                    "label": f"F{par['num_doc_partita']}{suffix}",
                    "importo": par.get("importo_partita", Decimal("0")),
                })

    # Fatture
    for event in fatt_events:
        ivas = event.get("ivas", [])
        num_doc = event["tes"].get("num_doc", 0)
        if not ivas:
            # Solo le righe IVA portano imposta → totale LORDO affidabile.
            # Rigs da solo danno NETTO e silenziosamente sottostima fatture_importo.
            logger.warning(
                "Fattura senza righe IVA scartata: num=%s data=%s",
                num_doc, event["tes"].get("data_doc"),
            )
            continue
        data = _normalize_date(event["tes"]["data_doc"])
        if not data:
            continue
        day = days[key_fn(event, data)]
        totale = sum(iva["imponibile"] + iva["imposta"] for iva in ivas)
        day["fatture_importo"] += totale
        if num_doc:
            suffix = _STRUTTURA_FT_SUFFIX.get(event.get("struttura", ""), "")
            day["fatture_lista"].append(f"F{num_doc}{suffix}")


def _day_to_row(day: dict, data: str, struttura: str = "") -> dict:
    totale_pos = day["corrispettivi_pos"] + day["caparre_incassate_pos"]
    totale_contanti = day["corrispettivi_contanti"] + day["caparre_incassate_contanti"]
    caparre_incassate = day["caparre_incassate_pos"] + day["caparre_incassate_contanti"]
    corrispettivi_netti = day["corrispettivi_pos"] + day["corrispettivi_contanti"]
    corrispettivi_lordi = corrispettivi_netti + day["corrispettivi_storno_caparra"]
    di_cui_ft = sum(ft["importo"] for ft in day["giri_caparra_ft"])
    lista_ft = ", ".join(day["fatture_lista"]) if day["fatture_lista"] else ""

    totale_incassi = totale_pos + totale_contanti
    totale_atteso = corrispettivi_netti + caparre_incassate
    diff = abs(totale_incassi - totale_atteso)
    quadra_ok = diff <= _QUADRA_TOLERANCE

    notes = []
    if totale_contanti > Decimal("0"):
        notes.append(f"contanti: {totale_contanti:.2f}")
    if day["corrispettivi_storno_caparra"] > Decimal("0"):
        notes.append(f"storno caparra: {day['corrispettivi_storno_caparra']:.2f}")
    if not quadra_ok:
        notes.append(f"SBILANCIO: diff={diff:.2f}")

    row = {
        "data": data,
        "totali_pos": totale_pos,
        "contanti": totale_contanti,
        "caparre_incassate": caparre_incassate,
        "corrispettivi": corrispettivi_netti,
        "corrispettivi_lordi": corrispettivi_lordi,
        "storno_caparra": day["corrispettivi_storno_caparra"],
        "caparre_evase": day["caparre_evase"],
        "di_cui_ft": di_cui_ft,
        "lista_fatture": lista_ft,
        "quadra": "OK" if quadra_ok else "!!",
        "note": "; ".join(notes),
    }
    if struttura:
        row["struttura"] = struttura
    return row


def build_daily_reconciliation(corr_events, mov_events, fatt_events) -> list[dict]:
    """Aggrega tutti gli eventi per data (tutte le strutture sommate)."""
    days: dict = defaultdict(_new_day)
    _accumulate(corr_events, mov_events, fatt_events, days, key_fn=lambda _e, d: d)
    return [_day_to_row(days[data], data) for data in sorted(days.keys(), key=_sort_key_date)]


def build_detail_reconciliation(corr_events, mov_events, fatt_events) -> list[dict]:
    """Aggrega per (data, struttura)."""
    days: dict = defaultdict(_new_day)
    _accumulate(
        corr_events,
        mov_events,
        fatt_events,
        days,
        key_fn=lambda e, d: (d, e.get("struttura", "unknown")),
    )

    rows = []
    for data, struttura in sorted(days.keys(), key=lambda k: (_sort_key_date(k[0]), k[1])):
        display = _STRUTTURA_DISPLAY.get(struttura, struttura)
        rows.append(_day_to_row(days[(data, struttura)], data, display))
    return rows


# ── Excel output ──────────────────────────────────────────────────────────────

_BLU = PatternFill("solid", fgColor="1F4E79")
_CHIARO = PatternFill("solid", fgColor="D6E4F0")
_BIANCO = PatternFill("solid", fgColor="FFFFFF")
_VERDE = PatternFill("solid", fgColor="E2EFDA")
_ROSSO = PatternFill("solid", fgColor="FCE4D6")
_GRIGIO = PatternFill("solid", fgColor="F2F2F2")
_GIALLO = PatternFill("solid", fgColor="FFF2CC")

_THIN = Side(style="thin", color="BFBFBF")
_BORDO = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _hdr(cell, testo, fill=None):
    cell.value = testo
    cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    cell.fill = fill or _BLU
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _BORDO


def _cel(cell, valore, fill=None, bold=False, align="left", color="000000"):
    cell.value = valore
    cell.font = Font(name="Calibri", bold=bold, size=10, color=color)
    cell.fill = fill or _BIANCO
    cell.alignment = Alignment(horizontal=align, vertical="center")
    cell.border = _BORDO


def _fmt_money(v: Decimal, show_zero: bool = False) -> str:
    if not show_zero and v == Decimal("0"):
        return ""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _write_riepilogo_sheet(ws, rows: list[dict]) -> None:
    ws.sheet_view.showGridLines = False

    col_widths = [13, 13, 16, 16, 13, 10, 22, 6, 30]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20

    ws.merge_cells("A1:I1")
    t = ws["A1"]
    t.value = "Riconciliazione Giornaliera"
    t.font = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    t.fill = _BLU
    t.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("A2:I2")
    sub = ws["A2"]
    sub.value = f"Generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    sub.font = Font(name="Calibri", size=9, italic=True, color="595959")
    sub.fill = _GRIGIO
    sub.alignment = Alignment(horizontal="center", vertical="center")

    headers = ["DATA", "TOTALI POS", "CAPARRE\nincassate", "CORRISPETTIVI*",
               "CAPARRE\nevase", "di cui ft", "Lista Fatture", "OK?", "Note"]
    for col, h in enumerate(headers, 1):
        _hdr(ws.cell(row=3, column=col), h)

    totals = defaultdict(lambda: Decimal("0"))
    r = 4
    for i, row in enumerate(rows):
        is_ok = row["quadra"] == "OK"
        fill = (_CHIARO if i % 2 == 0 else _BIANCO) if is_ok else _ROSSO

        _cel(ws.cell(r, 1), row["data"], fill, align="center")
        _cel(ws.cell(r, 2), _fmt_money(row["totali_pos"], True), fill, align="right")
        _cel(ws.cell(r, 3), _fmt_money(row["caparre_incassate"]), fill, align="right")
        _cel(ws.cell(r, 4), _fmt_money(row["corrispettivi"], True), fill, align="right")
        _cel(ws.cell(r, 5), _fmt_money(row["caparre_evase"]), fill, align="right")
        _cel(ws.cell(r, 6), _fmt_money(row["di_cui_ft"]), fill, align="right")
        _cel(ws.cell(r, 7), row["lista_fatture"], fill)

        qcell = ws.cell(r, 8)
        qcell.value = "✓" if is_ok else "!!"
        qcell.font = Font(name="Calibri", bold=True, size=11,
                          color="375623" if is_ok else "C00000")
        qcell.fill = _VERDE if is_ok else _ROSSO
        qcell.alignment = Alignment(horizontal="center", vertical="center")
        qcell.border = _BORDO

        _cel(ws.cell(r, 9), row["note"], fill)

        for k in ("totali_pos", "caparre_incassate", "corrispettivi", "caparre_evase", "di_cui_ft"):
            totals[k] += row[k]
        r += 1

    # Riga totali
    if rows:
        _cel(ws.cell(r, 1), "TOTALE", _GRIGIO, bold=True, align="center")
        _cel(ws.cell(r, 2), _fmt_money(totals["totali_pos"], True), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 3), _fmt_money(totals["caparre_incassate"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 4), _fmt_money(totals["corrispettivi"], True), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 5), _fmt_money(totals["caparre_evase"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 6), _fmt_money(totals["di_cui_ft"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 7), "", _GRIGIO)
        _cel(ws.cell(r, 8), "", _GRIGIO)
        _cel(ws.cell(r, 9), "", _GRIGIO)

    ws.freeze_panes = "A4"


def _write_dettaglio_sheet(ws, detail_rows: list[dict]) -> None:
    ws.sheet_view.showGridLines = False

    col_widths = [13, 12, 13, 16, 16, 13, 10, 22]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20

    ws.merge_cells("A1:H1")
    t = ws["A1"]
    t.value = "Dettaglio per Struttura"
    t.font = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    t.fill = _BLU
    t.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("A2:H2")
    sub = ws["A2"]
    sub.value = f"Generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    sub.font = Font(name="Calibri", size=9, italic=True, color="595959")
    sub.fill = _GRIGIO
    sub.alignment = Alignment(horizontal="center", vertical="center")

    headers = ["DATA", "STRUTTURA", "TOTALI POS", "CAPARRE\nincassate",
               "CORRISPETTIVI*", "CAPARRE\nevase", "di cui ft", "Fattura"]
    for col, h in enumerate(headers, 1):
        _hdr(ws.cell(row=3, column=col), h)

    struttura_fills = {"HP": _CHIARO, "CVM": _VERDE, "ANGELINA": _GIALLO}
    r = 4
    from itertools import groupby
    sorted_rows = sorted(detail_rows, key=lambda x: _sort_key_date(x["data"]))

    for data, group in groupby(sorted_rows, key=lambda x: x["data"]):
        day_rows = list(group)
        day_totals = defaultdict(lambda: Decimal("0"))
        all_ft = []

        for row in day_rows:
            fill = struttura_fills.get(row["struttura"], _BIANCO)
            _cel(ws.cell(r, 1), "", fill)
            _cel(ws.cell(r, 2), row["struttura"], fill, bold=True, align="center")
            _cel(ws.cell(r, 3), _fmt_money(row["totali_pos"], True), fill, align="right")
            _cel(ws.cell(r, 4), _fmt_money(row["caparre_incassate"]), fill, align="right")
            _cel(ws.cell(r, 5), _fmt_money(row["corrispettivi"], True), fill, align="right")
            _cel(ws.cell(r, 6), _fmt_money(row["caparre_evase"]), fill, align="right")
            _cel(ws.cell(r, 7), _fmt_money(row["di_cui_ft"]), fill, align="right")
            _cel(ws.cell(r, 8), row.get("lista_fatture", ""), fill)

            for k in ("totali_pos", "caparre_incassate", "corrispettivi", "caparre_evase", "di_cui_ft"):
                day_totals[k] += row[k]
            if row.get("lista_fatture"):
                all_ft.append(row["lista_fatture"])
            r += 1

        # Totale giornaliero
        _cel(ws.cell(r, 1), data, _GRIGIO, bold=True, align="center")
        _cel(ws.cell(r, 2), "TOTALE", _GRIGIO, bold=True, align="center")
        _cel(ws.cell(r, 3), _fmt_money(day_totals["totali_pos"], True), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 4), _fmt_money(day_totals["caparre_incassate"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 5), _fmt_money(day_totals["corrispettivi"], True), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 6), _fmt_money(day_totals["caparre_evase"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 7), _fmt_money(day_totals["di_cui_ft"]), _GRIGIO, bold=True, align="right")
        _cel(ws.cell(r, 8), "; ".join(all_ft) if all_ft else "", _GRIGIO, bold=True)
        r += 1

        # Separatore
        ws.row_dimensions[r].height = 5
        for col in range(1, 9):
            ws.cell(r, col).fill = _GRIGIO
        r += 1

    ws.freeze_panes = "A4"


def write_excel(rows: list[dict], detail_rows: list[dict], output_path: Path) -> None:
    """Genera XLSX con 2 fogli: Riepilogo + Dettaglio strutture."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)

    ws1 = wb.create_sheet("Riepilogo")
    _write_riepilogo_sheet(ws1, rows)

    ws2 = wb.create_sheet("Dettaglio strutture")
    _write_dettaglio_sheet(ws2, detail_rows)

    wb.active = wb.worksheets[0]
    wb.save(output_path)


# ── File discovery & parsing orchestration ───────────────────────────────────


def find_input_files(input_dir: Path) -> dict[str, list[str]]:
    """Scansiona (ricorsivamente) TXT e classifica per tipo."""
    files = {"corrispettivi": [], "movimenti": [], "fatture": [], "clienti": []}
    for dirpath, _dirnames, filenames in os.walk(input_dir):
        for entry in sorted(filenames):
            if not entry.endswith(".txt"):
                continue
            full = os.path.join(dirpath, entry)
            name = entry.lower()
            if "corrispettivi" in name:
                files["corrispettivi"].append(full)
            elif "movimenti" in name:
                files["movimenti"].append(full)
            elif "fattur" in name:
                files["fatture"].append(full)
            elif "clienti" in name:
                files["clienti"].append(full)
    return files


def parse_all_events(input_files: dict) -> tuple[list, list, list]:
    """Parsa corrispettivi + movimenti + fatture da tutti i file."""
    corr, mov, fatt = [], [], []
    for fp in input_files["corrispettivi"]:
        corr.extend(parse_corrispettivi(fp))
    for fp in input_files["movimenti"]:
        mov.extend(parse_movimenti(fp))
    for fp in input_files["fatture"]:
        fatt.extend(parse_fatture(fp))
    return corr, mov, fatt


# ── Report ultime date ────────────────────────────────────────────────────────

_STRUTTURE_PREFIX = {"H": "HOTEL", "C": "CVM", "R": "RESIDENCE"}


def report_ultime_date(input_dir: Path) -> dict[str, datetime]:
    """Scansiona TXT per prefisso struttura e trova ultima data presente."""
    ultime: dict[str, datetime] = {}
    for dirpath, _dirnames, filenames in os.walk(input_dir):
        for entry in filenames:
            if not entry.endswith(".txt"):
                continue
            prefisso = entry[0].upper()
            if prefisso not in _STRUTTURE_PREFIX:
                continue
            full = os.path.join(dirpath, entry)
            with open(full, encoding="latin-1", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split("|")
                    if len(parts) > 4 and parts[0] in ("TES", "GEN") and len(parts[4]) == 8:
                        try:
                            d = datetime.strptime(parts[4], "%d%m%Y")
                            if prefisso not in ultime or d > ultime[prefisso]:
                                ultime[prefisso] = d
                        except ValueError:
                            pass
    return ultime


def print_ultime_date(ultime: dict[str, datetime]) -> None:
    print()
    print("=" * 58)
    print("  PROSSIMO EXPORT DA ESOLVER")
    print("=" * 58)
    for prefisso, nome in sorted(_STRUTTURE_PREFIX.items()):
        if prefisso in ultime:
            u = ultime[prefisso]
            prossima = (u + timedelta(days=1)).strftime("%d/%m/%Y")
            print(f"  {nome:<12}  già caricato fino al {u.strftime('%d/%m/%Y')}  →  esporta da {prossima}")
        else:
            print(f"  {nome:<12}  nessun dato — esporta dall'inizio del mese")
    print("=" * 58)
    print()


# ── Entry point orchestrazione ───────────────────────────────────────────────


def run_accodamenti_to_excel(input_dir: Path, output_path: Path) -> dict:
    """Orchestra: parse → aggregate → Excel. Returns stats dict."""
    input_files = find_input_files(input_dir)
    total_txt = sum(len(v) for v in input_files.values())
    logger.info("File trovati: %d (%d corrispettivi, %d movimenti, %d fatture, %d clienti)",
                total_txt, len(input_files["corrispettivi"]), len(input_files["movimenti"]),
                len(input_files["fatture"]), len(input_files["clienti"]))

    corr, mov, fatt = parse_all_events(input_files)
    logger.info("Eventi parsati: %d corrispettivi, %d movimenti, %d fatture",
                len(corr), len(mov), len(fatt))

    rows = build_daily_reconciliation(corr, mov, fatt)
    detail = build_detail_reconciliation(corr, mov, fatt)

    write_excel(rows, detail, output_path)
    logger.info("Excel generato: %s (%d giorni, %d righe dettaglio)",
                output_path, len(rows), len(detail))

    return {
        "giorni": len(rows),
        "righe_dettaglio": len(detail),
        "corrispettivi": len(corr),
        "movimenti": len(mov),
        "fatture": len(fatt),
        "output": str(output_path),
    }


if __name__ == "__main__":
    # Smoke test manuale
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python -m condges.cassa_giornaliera <input_dir> [output.xlsx]")
        sys.exit(1)
    in_dir = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    run_accodamenti_to_excel(in_dir, out)
