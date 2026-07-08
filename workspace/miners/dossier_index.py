"""Indice xlsx + gap list del dossier (caricato nella cartella Drive società)."""

from __future__ import annotations

import io
from datetime import date

import openpyxl

from ..dossier_config import DossierCompany, WRITE_AS
from ..drive import get_drive_writer, upload_bytes

GAP_CHECKLIST: list[tuple[str, str]] = [
    ("01_Societario", "Statuto vigente"),
    ("01_Societario", "Visura camerale aggiornata"),
    ("01_Societario", "Libri sociali (verbali assemblee/CdA)"),
    ("02_Fiscale", "Dichiarazioni redditi ultimi 3 anni"),
    ("02_Fiscale", "F24 / cartelle pendenti"),
    ("03_Bilanci", "Bilanci depositati ultimi 5 anni"),
    ("04_Banche_Finanza", "Contratti conto corrente"),
    ("04_Banche_Finanza", "Contratti mutuo/leasing e piani ammortamento"),
    ("04_Banche_Finanza", "Fidi e garanzie/fideiussioni"),
    ("05_Immobili_Catasto", "Visure catastali immobili"),
    ("05_Immobili_Catasto", "Atti di provenienza"),
    ("06_Personale", "Contratti di lavoro in essere"),
    ("07_Legale_Ispezioni", "Contenziosi/ispezioni in corso"),
    ("08_Contratti", "Contratti fornitori strategici"),
    ("08_Contratti", "Concessioni (demaniali/licenze)"),
]

INDEX_COLUMNS = [
    "Categoria",
    "Confidenza",
    "Nome",
    "Fonte",
    "Owner",
    "Detentori",
    "Modificato",
    "Link",
]


def build_index_xlsx(items: list[dict], inaccessible: list[str]) -> bytes:
    wb = openpyxl.Workbook()
    idx = wb.active
    idx.title = "Indice"
    idx.append(INDEX_COLUMNS)
    for it in sorted(items, key=lambda x: (x["category"], -x["confidence"])):
        idx.append(
            [
                it["category"],
                it["confidence"],
                it["name"],
                it["source"],
                it.get("owner", ""),
                ", ".join(it.get("holders", [])),
                it.get("modified", ""),
                it.get("link", ""),
            ]
        )
    gap = wb.create_sheet("GapList")
    gap.append(["Categoria", "Documento", "Trovato"])
    have = {it["category"] for it in items}
    for category, voce in GAP_CHECKLIST:
        gap.append([category, voce, "✔" if category in have else "DA CHIEDERE"])
    for email in inaccessible:
        gap.append(["", f"Account non accessibile: {email}", "VERIFICARE"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_index(company: DossierCompany, xlsx_bytes: bytes) -> str:
    svc = get_drive_writer(WRITE_AS)
    name = f"_INDICE_DOSSIER_{company.company_id}_{date.today().isoformat()}.xlsx"
    return upload_bytes(
        svc,
        company.drive_folder_id,
        name,
        xlsx_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
