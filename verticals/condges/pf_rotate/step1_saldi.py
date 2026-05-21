"""Step 1 della rotation — roll saldi banca alla colonna del mese in chiusura."""

from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import find_month_columns


# Mappa label-banca master → set di chiavi possibili passate in saldi-dict.
def _match_bank(label_col_a: str, saldi: dict[str, float]) -> float | None:
    """Match 'Saldo MPS' / 'Saldo Intesa' / 'Saldo BCP' to a saldi entry.

    Robust to case, underscore vs space, subset-of-words.
    """
    lower = label_col_a.lower().replace("_", " ")
    # Estrai parole della label, escluso 'saldo'
    label_words = set(w for w in lower.split() if w not in ("saldo", "saldo:"))
    for k, v in saldi.items():
        k_words = set(k.lower().replace("_", " ").split())
        if k_words & label_words:  # almeno una parola in comune
            return float(v)
    return None


def write_saldi_banca(
    wb: Workbook,
    *,
    mese_chiuso: int,
    data_saldo: date,
    saldi: dict[str, float],
) -> dict[str, object]:
    """Scrive i saldi nelle celle 31:34 + r4 della colonna del mese chiuso.

    saldi: {nome_banca: importo}. Le banche mancanti non sono toccate.
    Ritorna dict con cellule effettivamente scritte + nuovo totale.
    """
    if "Piano Finanziario" not in wb.sheetnames:
        raise ValueError("Foglio 'Piano Finanziario' assente.")
    pf = wb["Piano Finanziario"]
    cols = find_month_columns(pf, header_row=2)
    if mese_chiuso not in cols:
        raise ValueError(f"Mese chiuso {mese_chiuso} non trovato nel master.")
    col = cols[mese_chiuso]
    col_letter = get_column_letter(col)

    # Data in r31, col del mese chiuso
    pf.cell(31, col, data_saldo.strftime("%d/%m/%Y"))

    written: dict[int, float] = {}
    # Scansiona r32..r34 leggendo l'etichetta in col A
    for r in (32, 33, 34):
        label = pf.cell(r, 1).value
        if not label:
            continue
        match = _match_bank(str(label), saldi)
        if match is None:
            # banca non passata, lasciamo intatto
            continue
        pf.cell(r, col, float(match))
        written[r] = float(match)

    # Totale: somma dei valori (saldi appena scritti + quelli preesistenti per
    # banche non sovrascritte). Leggiamo le 3 celle.
    total = 0.0
    for r in (32, 33, 34):
        v = pf.cell(r, col).value
        if isinstance(v, (int, float)):
            total += float(v)
    pf.cell(4, col, total)  # hardcoded — Controllo #1 esige non-formula

    return {
        "col": col_letter,
        "scritti_r": list(written.keys()),
        "totale_banche": total,
    }


def fetch_saldi_da_bq(societa: str, data_saldo: date) -> dict[str, float]:
    """Legge i saldi banca da BQ per la coppia (societa, data_saldo).

    Ritorna {banca_id: saldo}. Empty dict se nulla.
    """
    from core.bq.client import get_client
    from core.config import F_SALDI_BANCA_CHIUSURA_MENSILE
    from google.cloud import bigquery

    sql = f"""
        SELECT banca_id, saldo
        FROM `{F_SALDI_BANCA_CHIUSURA_MENSILE}`
        WHERE societa_id = @soc AND data_saldo = @data
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
    return {row.banca_id: float(row.saldo) for row in job.result()}
