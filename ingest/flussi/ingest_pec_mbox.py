#!/usr/bin/env python3
"""Ingest export mbox PEC → f_pec_messages + f_pec_allegati.

Due forme, distinte dal CONTENUTO (mai dal filename):
  - busta di trasporto (From=posta-certificata@...): daticert.xml è la verità
    certificata (msgid, mittente reale, timestamp opponibile, ref al messaggio
    originale per le ricevute); postacert.eml è il messaggio reale.
  - messaggio inviato (From=casella): raw, niente daticert; il timestamp
    certificato arriva dal link con la ricevuta di ACCETTAZIONE (ref_msgid).

Parser_module della source PEC_MAILBOX_INTUR_APPEND, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_pec_mbox --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --raw-object-id <id>
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --dry-run
"""

from __future__ import annotations

import email.message
import email.utils
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

log = logging.getLogger("ingest.pec_mbox")

CASELLA = "in.tur@pec.it"
SOCIETA = "INTUR"

# Nomi degli artefatti di busta: non sono allegati reali.
ARTEFATTI_BUSTA = {"daticert.xml", "postacert.eml", "smime.p7s"}

TIPO_MAP = {
    "posta-certificata": "POSTA_CERTIFICATA",
    "accettazione": "ACCETTAZIONE",
    "avvenuta-consegna": "CONSEGNA",
    "presa-in-carico": "ALTRO",
    "non-accettazione": "ANOMALIA",
    "errore-consegna": "ANOMALIA",
    "preavviso-errore-consegna": "ANOMALIA",
    "rilevazione-virus": "ANOMALIA",
}

SUBJECT_PREFIX_MAP = [
    ("POSTA CERTIFICATA", "POSTA_CERTIFICATA"),
    ("ACCETTAZIONE", "ACCETTAZIONE"),
    ("AVVENUTA CONSEGNA", "CONSEGNA"),
    ("CONSEGNA", "CONSEGNA"),
    ("ANOMALIA", "ANOMALIA"),
    ("MANCATA CONSEGNA", "ANOMALIA"),
]


def is_busta(msg: email.message.Message) -> bool:
    """Busta di trasporto PEC ⇔ From = posta-certificata@<provider>."""
    fr = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    return fr.startswith("posta-certificata@")


def parse_daticert(xml_bytes: bytes) -> dict | None:
    """daticert.xml → dict con la verità certificata. None se malformato."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    def _text(path: str) -> str | None:
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    giorno, ora = _text(".//data/giorno"), _text(".//data/ora")
    data_evento = None
    if giorno and ora:
        try:
            data_evento = datetime.strptime(f"{giorno} {ora}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass

    ref = _text(".//riferimento-messaggio") or _text(".//msgid")
    return {
        "tipo_raw": root.get("tipo"),
        "msgid": _text(".//identificativo"),
        "ref_msgid": ref.strip("<>") if ref else None,
        "mittente": _text(".//intestazione/mittente"),
        "destinatari": [
            el.text.strip()
            for el in root.findall(".//intestazione/destinatari")
            if el.text
        ],
        "data_evento": data_evento,
    }


def map_tipo(tipo_raw: str | None, subject: str, busta: bool) -> str:
    """Tipo canonico: daticert autoritativo, subject come fallback, ALTRO onesto."""
    if not busta:
        return "MESSAGGIO_INVIATO"
    if tipo_raw and tipo_raw in TIPO_MAP:
        return TIPO_MAP[tipo_raw]
    subj = (subject or "").upper()
    for prefix, tipo in SUBJECT_PREFIX_MAP:
        if subj.startswith(prefix):
            return tipo
    return "ALTRO"
