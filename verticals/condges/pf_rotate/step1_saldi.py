"""Step 1 della rotation — roll saldi banca alla colonna del mese in chiusura."""

from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import find_layout, find_month_columns
from verticals.condges.pf_rotate.saldi_registry import banche_richieste


class SaldiIncompletiError(RuntimeError):
    """Conti-saldo obbligatori mancanti in BQ per il fine-mese richiesto (gate O-A)."""


def banche_mancanti(societa: str, saldi: dict[str, float]) -> list[str]:
    """banca_id obbligatori (per la società) assenti dal dict saldi. Case-insensitive."""
    present = {k.upper() for k in saldi}
    return sorted(banche_richieste(societa) - present)


def preflight_saldi(
    societa: str,
    saldi: dict[str, float],
    data_saldo: date,
    *,
    allow_partial: bool = False,
) -> list[str]:
    """Gate di completezza: ritorna i banca_id obbligatori mancanti.

    Se ne mancano e ``allow_partial`` è False → hard-fail con errore azionabile
    (nomina le tuple mancanti + il comando di cattura). Va chiamato in preflight,
    prima di scrivere saldi/azzerare — non a valle.
    """
    mancanti = banche_mancanti(societa, saldi or {})
    if mancanti and not allow_partial:
        tuple_str = ", ".join(
            f"{societa}/{b}/{data_saldo.isoformat()}" for b in mancanti
        )
        raise SaldiIncompletiError(
            f"Saldi banca incompleti per {societa} al {data_saldo.isoformat()}: "
            f"mancano {tuple_str}. "
            f"Carica gli estratti: 'hotelops saldi-ufficiali --mese {data_saldo.month}', "
            f"oppure usa --allow-partial-saldi per un PF parziale marcato _FAILED_CHECKS."
        )
    return mancanti


# Mappa label-banca master → set di chiavi possibili passate in saldi-dict.
def _match_bank(label_col_a: str, saldi: dict[str, float]) -> float | None:
    """Match 'Saldo MPS' / 'Saldo Banca Sella' / 'Saldo MPS Kross' to a saldi entry.

    Esatto a livello banca: una chiave matcha solo se TUTTI i suoi token sono nella
    label (subset), e vince la più specifica (più token). Così 'Saldo MPS' non può
    prendere MPS_KROSS, e 'Saldo MPS Kross' non può prendere MPS — niente più
    overlap-di-una-parola, niente dipendenza dall'ordine del dict.
    """
    lower = label_col_a.lower().replace("_", " ")
    label_words = {w for w in lower.split() if w not in ("saldo", "saldo:")}
    best_ntoken = -1
    best_val: float | None = None
    for k, v in saldi.items():
        k_words = set(k.lower().replace("_", " ").split())
        if k_words and k_words <= label_words and len(k_words) > best_ntoken:
            best_ntoken = len(k_words)
            best_val = float(v)
    return best_val


def write_saldi_banca(
    wb: Workbook,
    *,
    mese_chiuso: int,
    data_saldo: date,
    saldi: dict[str, float],
) -> dict[str, object]:
    """Scrive i saldi nelle celle saldi_banca_rows + saldo_iniziale_row della colonna del mese chiuso.

    saldi: {nome_banca: importo}. Le banche mancanti non sono toccate.
    Ritorna dict con cellule effettivamente scritte + nuovo totale.
    """
    if "Piano Finanziario" not in wb.sheetnames:
        raise ValueError("Foglio 'Piano Finanziario' assente.")
    pf = wb["Piano Finanziario"]
    cols = find_month_columns(pf, header_row=2)
    if mese_chiuso not in cols:
        raise ValueError(f"Mese chiuso {mese_chiuso} non trovato nel master.")
    col_mese_chiuso = cols[mese_chiuso]
    col_mese_chiuso_letter = get_column_letter(col_mese_chiuso)

    layout = find_layout(wb)

    if layout.snapshot_kind == "fixed-snapshot":
        # INTUR-style: saldi banche + data live in fixed column C, regardless of
        # which month is closed. Do NOT touch the closed-month column on saldi
        # rows or the saldo_iniziale_row.
        target_col = 3  # C
        target_col_letter = "C"
        # Data goes in C2 (directly under "DATA RILEVAZ" header in C1)
        data_row = 2
    else:
        # ORTI-style: saldi banche go in the closed month column.
        target_col = col_mese_chiuso
        target_col_letter = col_mese_chiuso_letter
        # Data alla riga immediatamente precedente al primo saldo banca
        data_row = min(layout.saldi_banca_rows) - 1

    pf.cell(data_row, target_col, data_saldo.strftime("%d/%m/%Y"))

    written: dict[int, float] = {}
    for r in layout.saldi_banca_rows:
        label = pf.cell(r, 1).value
        if not label:
            continue
        match = _match_bank(str(label), saldi)
        if match is None:
            continue
        pf.cell(r, target_col, float(match))
        written[r] = float(match)

    # Totale: somma effettiva delle righe saldi
    total = 0.0
    for r in layout.saldi_banca_rows:
        v = pf.cell(r, target_col).value
        if isinstance(v, (int, float)):
            total += float(v)

    manual_block_rows: list[int] = []
    if layout.snapshot_kind == "month-closed":
        # Scrivi totale come saldo iniziale — hardcoded (Controllo #1 esige non-formula).
        # NB: il primo mese aperto resta '=<chiusa>37' BY CONTRACT (check C3 esige la
        # catena a formula): l'apertura è corretta SOLO se step 2 azzera davvero tutta
        # la colonna chiusa, dettagli riga-3 inclusi (leak 40k, 2026-07-04).
        pf.cell(layout.saldo_iniziale_row, target_col, total)

        # Avanza il blocco saldi MANUALE (col B = data, col C = valori testo) al cutover.
        # È un blocco di display umano separato dalla colonna del mese: se non aggiornato
        # resta al mese precedente (B32=31/03 in un foglio di maggio). Saltato quando C è
        # la colonna cutover (layout dove i mesi partono da C). I valori sono TESTO così
        # non entrano nelle somme (TOTALE BANCHE / T-totali); le celle-formula non si
        # toccano (invariante mai-azzerare-formule).
        MANUAL_DATE_COL, MANUAL_VAL_COL = 2, 3  # B, C
        if target_col != MANUAL_VAL_COL and layout.saldi_banca_rows:
            date_cell = pf.cell(min(layout.saldi_banca_rows), MANUAL_DATE_COL)
            if not (isinstance(date_cell.value, str) and date_cell.value.startswith("=")):
                date_cell.value = data_saldo.strftime("%d/%m/%Y")
            for r in layout.saldi_banca_rows:
                label = pf.cell(r, 1).value
                if not label:
                    continue
                match = _match_bank(str(label), saldi)
                if match is None:
                    continue
                val_cell = pf.cell(r, MANUAL_VAL_COL)
                if isinstance(val_cell.value, str) and val_cell.value.startswith("="):
                    continue  # mai sovrascrivere una formula
                val_cell.value = f"{float(match):,.2f} €"
                manual_block_rows.append(r)

    return {
        "col": target_col_letter,
        "data_row": data_row,
        "saldi_rows_scritte": list(written.keys()),
        "saldo_iniziale_row": layout.saldo_iniziale_row,
        "totale_banche": total,
        "snapshot_kind": layout.snapshot_kind,
        "manual_block_rows": manual_block_rows,
    }


def fetch_saldi_da_bq(societa: str, data_saldo: date) -> dict[str, float]:
    """Legge i saldi banca da BQ per la coppia (societa, data_saldo).

    Ritorna {banca_id: saldo}. Empty dict se nulla.
    """
    from core.bq.client import get_client
    from core.config import F_SALDI_BANCA_CHIUSURA_MENSILE
    from google.cloud import bigquery

    sql = f"""
        SELECT banca_id, saldo_eur
        FROM `{F_SALDI_BANCA_CHIUSURA_MENSILE}`
        WHERE societa_id = @soc AND data_riferimento = @data
        ORDER BY banca_id
    """
    job = get_client().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("soc", "STRING", societa),
                bigquery.ScalarQueryParameter("data", "DATE", data_saldo),
            ]
        ),
    )
    return {row.banca_id: float(row.saldo_eur) for row in job.result()}
