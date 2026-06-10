"""
Parser per file TXT di accodamento Esolver (formato pipe-delimited).

Ported from reconciliation_dino/src/parser.py to eliminate external dependency.

I file sono generati da HotelCube PMS e contengono record di tipo:
- TES: testata documento (corrispettivi, fatture)
- RIG: riga dettaglio (ricavi per aliquota/conto)
- GEN: riga generica (pagamenti, movimenti contabili)
- PAR: partitario (riferimenti partita per giro caparra)
- IVA: riepilogo IVA (solo in fatture)
"""

from decimal import Decimal, InvalidOperation
import logging
import os

logger = logging.getLogger(__name__)

# Conto Esolver 39.05.21 è *il* conto caparre: ogni evento che lo tocca è
# caparra per definizione (non euristica). Export Esolver usa la forma compatta.
CAPARRA_ACCOUNT = "390521"


def is_caparra_account(conto_esolver: str) -> bool:
    """True se il conto Esolver è 39.05.21 (caparre), in forma compatta o puntata."""
    if not conto_esolver:
        return False
    return conto_esolver.replace(".", "") == CAPARRA_ACCOUNT


def _esolver_dotted(raw: str) -> str:
    """Conto compatto (479101) → puntato (47.91.01)."""
    raw = raw.strip()
    if "." in raw:
        return raw
    if len(raw) == 6:
        return f"{raw[0:2]}.{raw[2:4]}.{raw[4:6]}"
    if len(raw) == 8:
        return f"{raw[0:2]}.{raw[2:4]}.{raw[4:6]}.{raw[6:8]}"
    return raw


def classify_payment_account(conto_esolver: str) -> str:
    """Classifica un conto Esolver come pos | cash | caparra | '' (riconciliazione cassa)."""
    if not conto_esolver:
        return ""
    if is_caparra_account(conto_esolver):
        return "caparra"
    dotted = _esolver_dotted(conto_esolver)
    if dotted.startswith("19.90"):
        return "pos"
    if dotted == "19.03.03":
        return "cash"
    return ""


def categoria_cassa(etype: str, conto_esolver: str) -> str:
    """Categoria cassa per riga f_accodamenti, da (tipo evento × conto).

    Porta in BQ la semantica di business che `events_to_rows` altrimenti appiattisce,
    così la riconciliazione Gaia si ricostruisce direttamente da BigQuery. Le righe
    '*_contropartita' / 'movimento_generico' / 'altro' NON entrano nei totali cassa.
    """
    cls = classify_payment_account(conto_esolver)
    if etype == "corrispettivo":
        return {
            "pos": "corrispettivo_pos",
            "cash": "corrispettivo_contanti",
            "caparra": "corrispettivo_storno_caparra",
        }.get(cls, "corrispettivo_altro")
    if etype == "incasso_caparra":
        return {
            "pos": "caparra_incassata_pos",
            "cash": "caparra_incassata_contanti",
        }.get(cls, "caparra_incasso_contropartita")
    if etype == "giro_caparra":
        return "caparra_evasa" if cls == "caparra" else "giro_contropartita"
    if etype == "fattura":
        return "fattura"
    if etype == "movimento_generico":
        return "movimento_generico"
    return "altro"


def _parse_decimal(value: str) -> Decimal:
    """Converte importo Esolver (virgola decimale) in Decimal."""
    if not value or not value.strip():
        return Decimal("0")
    value = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        logger.warning("Importo non parsabile: %r, uso 0", value)
        return Decimal("0")


def _parse_int(value: str, default: int = 0) -> int:
    if not value or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _split_line(line: str) -> list[str]:
    return [f.strip() for f in line.split("|")]


def _detect_struttura(filepath: str) -> str:
    basename = os.path.basename(filepath)
    if basename.startswith("H_"):
        return "hotel"
    elif basename.startswith("R_"):
        return "residence"
    elif basename.startswith("C_"):
        return "cvm"
    logger.warning(
        "Prefisso filename sconosciuto (atteso H_/R_/C_): %s → struttura=unknown",
        basename,
    )
    return "unknown"


# ── CORRISPETTIVI ─────────────────────────────────────────────────────────────

def _parse_corrispettivo_tes(fields: list[str]) -> dict:
    return {
        "tipo": "TES",
        "causale_esolver": fields[2] if len(fields) > 2 else "",
        "anno": fields[3] if len(fields) > 3 else "",
        "data_doc": fields[4] if len(fields) > 4 else "",
        "num_doc": _parse_int(fields[5]) if len(fields) > 5 else 0,
        "data_reg": fields[7] if len(fields) > 7 else "",
        "progressivo": _parse_int(fields[8]) if len(fields) > 8 else 0,
        "sezionale": fields[9] if len(fields) > 9 else "",
        "descrizione": fields[10] if len(fields) > 10 else "",
        "mese": _parse_int(fields[12]) if len(fields) > 12 else 0,
        "totale": _parse_decimal(fields[13]) if len(fields) > 13 else Decimal("0"),
    }


def _parse_corrispettivo_rig(fields: list[str]) -> dict:
    return {
        "tipo": "RIG",
        "causale_esolver": fields[2] if len(fields) > 2 else "",
        "data_doc": fields[4] if len(fields) > 4 else "",
        "progressivo": _parse_int(fields[8]) if len(fields) > 8 else 0,
        "conto_esolver": fields[14] if len(fields) > 14 else "",
        "valuta": fields[15] if len(fields) > 15 else "EUR",
        "importo_lordo": _parse_decimal(fields[16]) if len(fields) > 16 else Decimal("0"),
        "aliquota_iva": fields[17] if len(fields) > 17 else "",
        "imponibile": _parse_decimal(fields[18]) if len(fields) > 18 else Decimal("0"),
        "imposta": _parse_decimal(fields[19]) if len(fields) > 19 else Decimal("0"),
        "descrizione": fields[24] if len(fields) > 24 else "",
    }


def _parse_corrispettivo_gen(fields: list[str]) -> dict:
    conto = fields[26] if len(fields) > 26 else ""
    importo = _parse_decimal(fields[33]) if len(fields) > 33 else Decimal("0")
    descrizione = fields[41] if len(fields) > 41 else ""
    metodo_pagamento = fields[-1].strip() if fields else ""

    return {
        "tipo": "GEN",
        "causale_esolver": fields[2] if len(fields) > 2 else "",
        "data_doc": fields[4] if len(fields) > 4 else "",
        "progressivo": _parse_int(fields[8]) if len(fields) > 8 else 0,
        "conto_esolver": conto,
        "importo": importo,
        "descrizione": descrizione,
        "metodo_pagamento": metodo_pagamento,
        "is_caparra": "CAPARRA" in descrizione.upper() if descrizione else False,
    }


def parse_corrispettivi(filepath: str) -> list[dict]:
    """Parsa file corrispettivi (H_Corrispettivi.txt, etc.)."""
    struttura = _detect_struttura(filepath)
    events = []
    current_event = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip("\n\r")
            if not line:
                continue
            fields = _split_line(line)
            record_type = fields[0] if fields else ""

            if record_type == "TES":
                if current_event:
                    events.append(current_event)
                tes = _parse_corrispettivo_tes(fields)
                current_event = {
                    "type": "corrispettivo",
                    "struttura": struttura,
                    "tes": tes,
                    "rigs": [],
                    "gens": [],
                    "source_file": filepath,
                    "source_line": line_num,
                }
            elif record_type == "RIG" and current_event:
                current_event["rigs"].append(_parse_corrispettivo_rig(fields))
            elif record_type == "GEN" and current_event:
                current_event["gens"].append(_parse_corrispettivo_gen(fields))

    if current_event:
        events.append(current_event)

    logger.info("Corrispettivi %s: %d eventi da %s", struttura, len(events), filepath)
    return events


# ── MOVIMENTI ─────────────────────────────────────────────────────────────────

def _parse_movimento_gen(fields: list[str]) -> dict:
    return {
        "tipo": "GEN",
        "causale_esolver": fields[2] if len(fields) > 2 else "",
        "data_doc": fields[4] if len(fields) > 4 else "",
        "num_doc": _parse_int(fields[5]) if len(fields) > 5 else 0,
        "progressivo": _parse_int(fields[8]) if len(fields) > 8 else 0,
        "conto_esolver": fields[10] if len(fields) > 10 else "",
        "codice_cliente": fields[12] if len(fields) > 12 else "",
        "importo_dare": _parse_decimal(fields[18]) if len(fields) > 18 else Decimal("0"),
        "importo_avere": _parse_decimal(fields[17]) if len(fields) > 17 else Decimal("0"),
        "descrizione": fields[22] if len(fields) > 22 else "",
        "metodo_pagamento": fields[-1].strip() if fields else "",
    }


def _parse_movimento_par(fields: list[str]) -> dict:
    imp_partita = _parse_decimal(fields[48]) if len(fields) > 48 else Decimal("0")
    if imp_partita == Decimal("0"):
        imp_partita = _parse_decimal(fields[47]) if len(fields) > 47 else Decimal("0")

    imp_valuta = _parse_decimal(fields[50]) if len(fields) > 50 else Decimal("0")
    if imp_valuta == Decimal("0"):
        imp_valuta = _parse_decimal(fields[49]) if len(fields) > 49 else Decimal("0")

    return {
        "tipo": "PAR",
        "causale_esolver": fields[2] if len(fields) > 2 else "",
        "data_doc": fields[4] if len(fields) > 4 else "",
        "num_doc": _parse_int(fields[5]) if len(fields) > 5 else 0,
        "progressivo": _parse_int(fields[8]) if len(fields) > 8 else 0,
        "conto_esolver": fields[10] if len(fields) > 10 else "",
        "tipo_doc_partita": fields[42] if len(fields) > 42 else "",
        "num_doc_partita": _parse_int(fields[44]) if len(fields) > 44 else 0,
        "data_doc_partita": fields[46] if len(fields) > 46 else "",
        "importo_partita": imp_partita,
        "importo_valuta": imp_valuta,
        "sezionale_partita": fields[51] if len(fields) > 51 else "",
    }


def parse_movimenti(filepath: str) -> list[dict]:
    """Parsa file movimenti (H_Movimenti.txt, etc.)."""
    struttura = _detect_struttura(filepath)
    events = []
    lines_data = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip("\n\r")
            if not line:
                continue
            fields = _split_line(line)
            record_type = fields[0] if fields else ""
            if record_type == "GEN":
                lines_data.append(("GEN", _parse_movimento_gen(fields), line_num))
            elif record_type == "PAR":
                lines_data.append(("PAR", _parse_movimento_par(fields), line_num))

    i = 0
    while i < len(lines_data):
        rec_type, rec, line_num = lines_data[i]

        if rec_type != "GEN":
            i += 1
            continue

        has_par = False
        par_rec = None
        group_gens = [rec]
        j = i + 1

        if j < len(lines_data) and lines_data[j][0] == "PAR":
            has_par = True
            par_rec = lines_data[j][1]
            j += 1

        if j < len(lines_data) and lines_data[j][0] == "GEN":
            group_gens.append(lines_data[j][1])
            j += 1

        if has_par:
            event_type = "giro_caparra"
        elif any(is_caparra_account(g["conto_esolver"]) for g in group_gens):
            event_type = "incasso_caparra"
        else:
            event_type = "movimento_generico"

        events.append({
            "type": event_type,
            "struttura": struttura,
            "gens": group_gens,
            "par": par_rec,
            "source_file": filepath,
            "source_line": line_num,
        })
        i = j

    logger.info("Movimenti %s: %d eventi da %s", struttura, len(events), filepath)
    return events


# ── FATTURE ───────────────────────────────────────────────────────────────────

def _parse_fattura_tes(fields: list[str]) -> dict:
    return {
        "tipo": "TES",
        "causale_esolver": fields[1] if len(fields) > 1 else "",
        "num_doc": _parse_int(fields[2]) if len(fields) > 2 else 0,
        "data_doc": fields[3] if len(fields) > 3 else "",
        "codice_cliente": _parse_int(fields[4]) if len(fields) > 4 else 0,
        "registro_iva": fields[5] if len(fields) > 5 else "",
        "sezionale": fields[6] if len(fields) > 6 else "",
        "file_xml": fields[-2] if len(fields) > 2 else "",
    }


def _parse_fattura_rig(fields: list[str]) -> dict:
    return {
        "tipo": "RIG",
        "causale_esolver": fields[1] if len(fields) > 1 else "",
        "num_doc": _parse_int(fields[2]) if len(fields) > 2 else 0,
        "data_doc": fields[3] if len(fields) > 3 else "",
        "conto_esolver": fields[10] if len(fields) > 10 else "",
        "aliquota_iva": fields[14] if len(fields) > 14 else "",
        "imponibile": _parse_decimal(fields[15]) if len(fields) > 15 else Decimal("0"),
    }


def _parse_fattura_iva(fields: list[str]) -> dict:
    return {
        "tipo": "IVA",
        "causale_esolver": fields[1] if len(fields) > 1 else "",
        "num_doc": _parse_int(fields[2]) if len(fields) > 2 else 0,
        "data_doc": fields[3] if len(fields) > 3 else "",
        "aliquota_iva": fields[16] if len(fields) > 16 else "",
        "imponibile": _parse_decimal(fields[17]) if len(fields) > 17 else Decimal("0"),
        "imposta": _parse_decimal(fields[18]) if len(fields) > 18 else Decimal("0"),
    }


def parse_fatture(filepath: str) -> list[dict]:
    """Parsa file fatture (H_Fatture.txt, etc.)."""
    struttura = _detect_struttura(filepath)
    events = []
    current_event = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip("\n\r")
            if not line:
                continue
            fields = _split_line(line)
            record_type = fields[0] if fields else ""

            if record_type == "TES":
                if current_event:
                    events.append(current_event)
                tes = _parse_fattura_tes(fields)
                current_event = {
                    "type": "fattura",
                    "struttura": struttura,
                    "tes": tes,
                    "rigs": [],
                    "ivas": [],
                    "source_file": filepath,
                    "source_line": line_num,
                }
            elif record_type == "RIG" and current_event:
                current_event["rigs"].append(_parse_fattura_rig(fields))
            elif record_type == "IVA" and current_event:
                current_event["ivas"].append(_parse_fattura_iva(fields))

    if current_event:
        events.append(current_event)

    logger.info("Fatture %s: %d eventi da %s", struttura, len(events), filepath)
    return events
