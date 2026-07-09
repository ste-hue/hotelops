"""Documenti ufficiali via openapi-ita. OGNI ordine a pagamento e' esplicito.

Contratto reale di openapi_ita.visure.VisureAPI (verificato leggendo
src/openapi_ita/visure.py in openapi_ita, non modificato):

- submit(endpoint, **body) -> dict gia' "spacchettato" (data.get("data", data)),
  contiene almeno {"id": request_id}. Body atteso: cf_piva_id=... (vedi docstring
  del modulo sorgente).
- status(endpoint, request_id) -> dict gia' spacchettato con campo
  "stato_richiesta" o "status".
- is_ready(status_data) -> bool, staticmethod.
- download(endpoint, request_id) -> dict/list eterogeneo con gli allegati in
  base64 (campo "file"). Puo' presentarsi come:
    * un singolo dict {"file": <b64>, "nome"/"filename": <name>, ...}
    * un dict contenitore {"allegati": [...]} o {"files": [...]}
    * una list di dict allegato
  Non e' MAI una lista di tuple (filename, bytes) gia' pronte: vanno
  normalizzate e decodificate qui (vedi _extract_attachments).
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import time
import zipfile
from datetime import date

from ..dossier_config import DOSSIER_STATE_DIR, DossierCompany, WRITE_AS
from ..drive import ensure_subfolder, get_drive_writer, upload_bytes

# prezzi base (senza sconti best-price): il gate mostra il caso peggiore
ORDER_CATALOG: dict[str, dict] = {
    "visura": {"endpoint": "storica-societa-capitale", "cost": 5.90,
               "category": "01_Societario", "label": "Visura storica"},
    "bilancio": {"endpoint": "bilancio-ottico", "cost": 4.50,
                 "category": "03_Bilanci", "label": "Bilancio ottico (ultimo)"},
    "soci": {"endpoint": "soci-attivi", "cost": 2.30,
             "category": "01_Societario", "label": "Elenco soci attivi"},
}


def order_summary(orders: list[str]) -> tuple[list[dict], float]:
    """Pure: valida le chiavi (KeyError se sconosciuta) e somma il costo."""
    out = []
    for oid in orders:
        entry = dict(ORDER_CATALOG[oid])  # KeyError se sconosciuto
        entry["order_id"] = oid
        out.append(entry)
    return out, round(sum(e["cost"] for e in out), 2)


def fetch_profile(company: DossierCompany) -> dict:
    from openapi_ita import CompanyAPI

    data = CompanyAPI().advanced(company.tax_code)
    DOSSIER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = DOSSIER_STATE_DIR / f"profile_{company.company_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  Profilo salvato: {path}")
    return data


def _extract_attachments(raw, fallback_name: str) -> list[tuple[str, bytes]]:
    """Normalizza il payload eterogeneo di VisureAPI.download() in
    [(filename, bytes), ...], decodificando il base64.

    Il campo download() di visure.py e' documentato solo come "dict/list con
    allegati (campo 'file' in base64)" — gli script legacy dell'SDK
    (scripts/get_bilancio.py, scripts/redownload_bilanci.py) mostrano che la
    forma varia: a volte un singolo dict con "file" in cima, a volte un dict
    con "allegati"/"files" annidati, a volte gia' una lista di allegati.
    """
    if raw is None:
        return []

    if isinstance(raw, dict):
        # Dict contenitore con lista annidata.
        nested = raw.get("allegati") or raw.get("files")
        if nested is not None:
            candidates = nested
        elif raw.get("file"):
            # Singolo allegato "piatto".
            candidates = [raw]
        else:
            candidates = []
    elif isinstance(raw, list):
        candidates = raw
    else:
        candidates = []

    out: list[tuple[str, bytes]] = []
    for i, att in enumerate(candidates):
        if not isinstance(att, dict):
            continue
        content_b64 = att.get("file") or att.get("content") or att.get("data")
        if not content_b64:
            continue
        name = (
            att.get("filename")
            or att.get("nome")
            or att.get("name")
            or (f"{fallback_name}.pdf" if i == 0 else f"{fallback_name}_{i}.pdf")
        )
        out.append((name, base64.b64decode(content_b64)))
    return out


def expand_archives(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes, str]]:
    """Espande gli archivi ZIP nei file contenuti; ritorna (nome, bytes, mime).

    I download visure (es. bilancio-ottico) arrivano come ZIP base64 con dentro
    PDF+XBRL: su Drive vanno i file interni, non l'archivio.
    """
    out: list[tuple[str, bytes, str]] = []
    for name, data in files:
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    inner_bytes = zf.read(member.filename)
                    mime = mimetypes.guess_type(member.filename)[0] or "application/octet-stream"
                    out.append((member.filename, inner_bytes, mime))
        else:
            mime = mimetypes.guess_type(name)[0] or "application/pdf"
            out.append((name, data, mime))
    return out


def place_orders(company: DossierCompany, orders: list[str], poll_minutes: int = 20, anno_chiusura: int | None = None) -> list[dict]:
    """Invia gli ordini a pagamento, fa polling dello stato e carica i PDF su Drive.

    Adattato al contratto reale di openapi_ita.visure.VisureAPI (vedi docstring
    di modulo): submit()/status() ritornano gia' il dict "data" spacchettato
    (quindi l'id richiesta e' req["id"], non req["data"]["id"]), e download()
    NON ritorna coppie (filename, bytes) pronte ma un payload eterogeneo che va
    normalizzato via _extract_attachments().

    Args:
        company: DossierCompany da elaborare
        orders: lista di order_id (chiavi in ORDER_CATALOG)
        poll_minutes: timeout polling in minuti
        anno_chiusura: anno chiusura bilancio per bilancio-ottico (default: anno precedente)
    """
    from openapi_ita import VisureAPI

    api = VisureAPI()
    writer = get_drive_writer(WRITE_AS)
    results = []
    plan, _ = order_summary(orders)
    default_anno = anno_chiusura or (date.today().year - 1)
    for entry in plan:
        body = {"cf_piva_id": company.tax_code}
        if entry["endpoint"] == "bilancio-ottico":
            body["anno_chiusura"] = default_anno
        req = api.submit(entry["endpoint"], **body)
        req_id = req.get("id") or req.get("request_id")
        print(f"  {entry['label']}: richiesta {req_id}, polling…")
        deadline = time.time() + poll_minutes * 60
        ready = False
        while time.time() < deadline:
            st = api.status(entry["endpoint"], req_id)
            if api.is_ready(st):
                ready = True
                break
            time.sleep(60)
        if not ready:
            results.append({"order": entry["order_id"], "status": "timeout", "request_id": req_id})
            continue
        raw = api.download(entry["endpoint"], req_id)
        files = _extract_attachments(raw, fallback_name=f"{entry['order_id']}_{company.company_id}")
        expanded = expand_archives(files)
        folder = ensure_subfolder(writer, company.drive_folder_id, entry["category"])
        for fname, data, mime in expanded:
            upload_bytes(writer, folder, fname, data, mime)
        results.append({"order": entry["order_id"], "status": "ok",
                        "files": [f for f, _, _ in expanded]})
    return results
