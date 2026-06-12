"""Costanti del generatore PF: nomi puliti, mesi, stili."""

from __future__ import annotations

# Nomi foglio PULITI (scrittura). La lettura dei file precedenti resta
# tollerante via VOCE_TO_SHEET_CANDIDATES (app_scadenzario) + questi.
VOCE_SHEET_NAME = {
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_UTENZE": "Utenze",
    "USCITE_MATERIE_PRIME": "Materie Prime e Consumo",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commissioni Portali",
    "USCITE_MUTUI": "Mutui e Finanziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
    "USCITE_VARIE_EXT": "Varie ed Eventuali",
}

MESI = [
    "GENNAIO",
    "FEBBRAIO",
    "MARZO",
    "APRILE",
    "MAGGIO",
    "GIUGNO",
    "LUGLIO",
    "AGOSTO",
    "SETTEMBRE",
    "OTTOBRE",
    "NOVEMBRE",
    "DICEMBRE",
]
COL_PRIMO_MESE = 3  # GEN=3 ... DIC=14

RIGA_HEADER_MESI = 2
RIGA_TOTALE = 3
RIGA_SEZIONE_A = 5
PRIMA_RIGA_BLOCCO_A = 6

LABEL_SEZIONE_A = "PARTITE APERTE (motore)"
LABEL_SEZIONE_B = "PREVISIONI (manuale)"
LABEL_RETTIFICA = "RETTIFICA PARTITE/PREVISIONI"

# colori (ARGB)
FILL_SEZIONE_A = "FFDCE6F1"  # blu chiaro
FILL_SEZIONE_B = "FFFFF2CC"  # giallo chiaro
FILL_MESE_CHIUSO = "FFEFEFEF"  # grigio chiaro
FONT_PREVISIONE = "FF1F4E99"  # blu
NUMFMT_CONTABILE = "#,##0.00"


def col_mese(mese: int) -> int:
    """Colonna del mese (1-12) nel layout generato."""
    return COL_PRIMO_MESE + mese - 1
