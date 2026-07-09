"""Config del dossier societario ORTI/INTUR (fronte dossier-societario)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import DOMAIN  # noqa: F401  (riesportato per i miner)

WRITE_AS = "stefano@panoramagroup.it"
DIRECTORY_SUBJECT = "stefano@panoramagroup.it"

DOSSIER_STATE_DIR = Path.home() / ".config" / "hotelops" / "dossier"

CONFIDENCE_THRESHOLD = 0.6

AMM_CEO_FOLDER_ID = "1S81cBxrzPW5NxuCSBoIszAcBuyk_ILr-"  # cartella CEO (vuota, struttura da definire)

TAXONOMY = [
    "01_Societario",
    "02_Fiscale",
    "03_Bilanci",
    "04_Banche_Finanza",
    "05_Immobili_Catasto",
    "06_Personale",
    "07_Legale_Ispezioni",
    "08_Contratti",
    "_DaRivedere",
]


@dataclass(frozen=True)
class DossierCompany:
    company_id: str
    display_name: str
    search_phrases: list[str] = field(default_factory=list)  # Drive fullText
    gmail_terms: list[str] = field(default_factory=list)     # Gmail q
    tax_code: str = ""
    drive_folder_id: str = ""


COMPANIES: dict[str, DossierCompany] = {
    # "orti" e' una parola comune: MAI il termine nudo, solo frasi esatte + CF.
    "ORTI": DossierCompany(
        company_id="ORTI",
        display_name="ORTI S.R.L.",
        search_phrases=['"ORTI S.R.L."', '"ORTI SRL"', "04391390657"],
        gmail_terms=['"ORTI S.R.L." OR "ORTI SRL" OR 04391390657'],
        tax_code="04391390657",
        drive_folder_id="1jtik538_t4udzOM033KHXa88PaY-o53S",
    ),
    "INTUR": DossierCompany(
        company_id="INTUR",
        display_name="INTUR S.R.L.",
        search_phrases=["INTUR", "00553430653"],
        gmail_terms=["INTUR OR 00553430653"],
        tax_code="00553430653",
        drive_folder_id="1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG",
    ),
}
