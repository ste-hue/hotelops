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

import argparse
import email.header
import email.message
import email.utils
import hashlib
import logging
import mailbox
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

from core.config import F_PEC_ALLEGATI, F_PEC_MESSAGES
from core.schemas import (
    PecAllegatoRow,
    PecMessageRow,
    make_hash,
    validate_batch,
)

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


def _decode_header(value: str | None) -> str:
    """RFC2047 → testo leggibile (subject, filename).

    Le parti bytes si decodificano col charset dichiarato (fallback latin-1
    su charset sconosciuto); i control char residui del folding (\\r\\n\\t)
    collassano in uno spazio singolo.
    """
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                parts.append(chunk.decode("latin-1", errors="replace"))
        else:
            parts.append(chunk)
    return re.sub(r"[\r\n\t]+", " ", "".join(parts)).strip()


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


def inner_message(
    msg: email.message.Message,
) -> tuple[email.message.Message, bool]:
    """Il messaggio reale: postacert.eml se presente, altrimenti la busta stessa.

    Le ricevute di accettazione spesso non hanno postacert: è normale (il
    contenuto informativo è nel daticert), non un errore.
    """
    import email as email_pkg

    for part in msg.walk():
        if (part.get_filename() or "").lower() == "postacert.eml":
            payload = part.get_payload(decode=True)
            if payload is None:  # message/rfc822: payload è già un Message
                sub = part.get_payload()
                if isinstance(sub, list) and sub:
                    return sub[0], True
            else:
                return email_pkg.message_from_bytes(payload), True
    return msg, False


def estrai_body_text(msg: email.message.Message) -> str | None:
    """text/plain preferito; niente HTML raw, niente binari."""
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
    return None


def iter_allegati_reali(msg: email.message.Message) -> list[tuple[str, bytes, str]]:
    """(nome, bytes, mime) per ogni allegato reale — esclusi artefatti busta."""
    out: list[tuple[str, bytes, str]] = []
    for part in msg.walk():
        nome = _decode_header(part.get_filename())
        if not nome or nome.lower() in ARTEFATTI_BUSTA:
            continue
        if part.get_content_disposition() != "attachment":
            continue
        content = part.get_payload(decode=True)
        if content is None:
            continue
        out.append((nome, content, part.get_content_type()))
    return out


SOURCE_NAME = "PEC_MAILBOX_INTUR_APPEND"


def _safe_object_name(nome: str, max_len: int = 180) -> str:
    """Componente path GCS sicuro: via i control char, cap sulla lunghezza.

    Il nome ORIGINALE resta fedele nella riga f_pec_allegati; qui si sanitizza
    solo il segmento dell'object name (l'unicità la dà già lo sha256 nel path).
    """
    safe = "".join("_" if (ord(c) < 32 or 0x7F <= ord(c) <= 0x9F) else c for c in nome)
    safe = safe.strip() or "allegato"
    if len(safe) > max_len:
        stem, dot, ext = safe.rpartition(".")
        if dot and len(ext) <= 10:
            safe = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            safe = safe[:max_len]
    return safe


class AllegatiStore:
    """Binari allegati su GCS, indirizzati per contenuto.

    Path: <SOURCE_NAME>/allegati/<sha256[:2]>/<sha256>/<nome> — lo stesso
    contenuto trasmesso N volte è un solo oggetto per nome; il fan-out sulle
    trasmissioni vive nelle righe f_pec_allegati.
    """

    def __init__(
        self, bucket_name: str = "hotelops-raw", dry_run: bool = False, client=None
    ):
        self.bucket_name = bucket_name
        self.dry_run = dry_run
        self._client = client
        self.n_uploaded = 0
        self.n_riusati = 0

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def store(self, nome: str, content: bytes) -> tuple[str, str]:
        sha = hashlib.sha256(content).hexdigest()
        path = f"{SOURCE_NAME}/allegati/{sha[:2]}/{sha}/{_safe_object_name(nome)}"
        uri = f"gs://{self.bucket_name}/{path}"
        if self.dry_run:
            return sha, uri
        blob = self._get_client().bucket(self.bucket_name).blob(path)
        if blob.exists():
            self.n_riusati += 1
        else:
            blob.upload_from_string(content, content_type="application/octet-stream")
            self.n_uploaded += 1
        return sha, uri


def _msgid_sintetico(msg: email.message.Message) -> str:
    return "synthetic-" + hashlib.sha256(bytes(msg)).hexdigest()[:32]


def extract_message(
    msg: email.message.Message,
    raw_object_id: str,
    store: AllegatiStore,
    now: datetime,
) -> tuple[dict, list[dict]]:
    """Una busta/inviata → (riga f_pec_messages, righe f_pec_allegati)."""
    busta = is_busta(msg)
    warning = None

    daticert = None
    if busta:
        for part in msg.walk():
            if (part.get_filename() or "").lower() == "daticert.xml":
                daticert = parse_daticert(part.get_payload(decode=True) or b"")
                break
        if daticert is None:
            warning = "daticert assente o malformato: fallback su header busta"

    inner, ha_postacert = inner_message(msg) if busta else (msg, False)
    subject_inner = _decode_header(str(inner.get("Subject", ""))) or _decode_header(
        str(msg.get("Subject", ""))
    )
    tipo = map_tipo(
        daticert.get("tipo_raw") if daticert else None, subject_inner, busta
    )

    # msgid: il daticert `identificativo` è l'id della CATENA di ricevute (lo
    # stesso per POSTA_CERTIFICATA + ACCETTAZIONE + CONSEGNA), non dell'evento
    # — verificato sul corpus Aruba 2026-07-08 (18/80 righe collassate).
    # Priorità: envelope Message-ID header (per-evento, stabile tra re-export)
    # > daticert identificativo composto col tipo (disambigua la catena) > sintetico.
    header_msgid = (str(msg.get("Message-ID", "")) or "").strip().strip("<>")
    if header_msgid:
        msgid = header_msgid
    elif daticert and daticert.get("msgid"):
        msgid = f"{daticert['msgid']}#{tipo}"
    else:
        msgid = _msgid_sintetico(msg)
        warning = (warning or "") + " msgid sintetico da sha256"

    # data: daticert (certificata) > Date header
    data_evento, certificata = None, False
    if daticert and daticert.get("data_evento"):
        data_evento, certificata = daticert["data_evento"], True
    else:
        try:
            data_evento = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        except (TypeError, ValueError):
            warning = (warning or "") + " data non parsabile"
    if data_evento is not None and data_evento.tzinfo is not None:
        data_evento = data_evento.astimezone(tz=None).replace(tzinfo=None)

    if daticert and daticert.get("mittente"):
        mittente = daticert["mittente"]
        destinatari = daticert.get("destinatari") or []
    else:
        mittente = email.utils.parseaddr(str(inner.get("From", "")))[1] or None
        destinatari = [
            a for _, a in email.utils.getaddresses([str(inner.get("To", ""))]) if a
        ]

    provider = None
    if busta:
        fr_busta = email.utils.parseaddr(str(msg.get("From", "")))[1]
        provider = fr_busta.split("@", 1)[1] if "@" in fr_busta else None

    allegati_rows: list[dict] = []
    for nome, content, mime in iter_allegati_reali(inner):
        sha, uri = store.store(nome, content)
        allegati_rows.append(
            {
                "msgid": msgid,
                "nome_file": nome,
                "mime_type": mime,
                "size_bytes": len(content),
                "sha256": sha,
                "is_firmato": nome.lower().endswith((".p7m", ".p7s")),
                "gcs_uri": uri,
                "hash_riga": make_hash(msgid, sha, nome),
                "raw_object_id": raw_object_id,
                "data_caricamento": now,
            }
        )

    riga = {
        "msgid": msgid,
        "source_folder": "RECEIVED" if busta else "SENT",
        "tipo": tipo,
        "ref_msgid": daticert.get("ref_msgid") if daticert else None,
        "data_evento": data_evento or now,
        "data_certificata": certificata,
        "mittente": mittente,
        "destinatari": ";".join(destinatari) or None,
        "n_destinatari": len(destinatari),
        "subject": subject_inner or None,
        "body_text": estrai_body_text(inner),
        "provider": provider,
        "casella": CASELLA,
        "societa_id": SOCIETA,
        "n_allegati": len(allegati_rows),
        "ha_postacert": ha_postacert,
        "parse_warning": warning.strip() if warning else None,
        "hash_riga": make_hash(msgid),
        "raw_object_id": raw_object_id,
        "data_caricamento": now,
    }
    return riga, allegati_rows


def coverage_gaps(dates: list, min_gap_days: int = 14) -> list[tuple]:
    """Vuoti > min_gap_days nella serie date (per il report no-silent-skips)."""
    out = []
    ordered = sorted(set(dates))
    for prev, cur in zip(ordered, ordered[1:]):
        gap = (cur - prev).days
        if gap > min_gap_days:
            out.append((prev, cur, gap))
    return out


def ingest_file(
    path: Path, raw_object_id: str | None = None, dry_run: bool = False
) -> dict:
    """Un mbox → righe nuove in f_pec_messages/f_pec_allegati + report."""
    if not dry_run and not raw_object_id:
        raise ValueError(
            "raw_object_id obbligatorio in write mode (I9): usa --raw-object-id o --dry-run"
        )
    store = AllegatiStore(dry_run=dry_run)
    now = datetime.now()
    ro_id = raw_object_id or "dry-run"

    righe: dict[str, dict] = {}  # msgid → riga (dedup in-file)
    allegati: dict[str, list[dict]] = {}  # msgid → righe allegato
    letti = dedup_in_file = 0

    for msg in mailbox.mbox(str(path)):
        letti += 1
        riga, alls = extract_message(msg, ro_id, store, now)
        if riga["msgid"] in righe:
            dedup_in_file += 1
            continue
        righe[riga["msgid"]] = riga
        allegati[riga["msgid"]] = alls

    msg_rows = list(righe.values())
    all_rows = [a for alls in allegati.values() for a in alls]

    validate_batch(msg_rows, PecMessageRow, context="f_pec_messages")
    validate_batch(all_rows, PecAllegatoRow, context="f_pec_allegati")

    dedup_bq = dedup_bq_allegati = 0
    if not dry_run:
        from core.bq.dedup import filter_new_rows_by_hash
        from core.bq.write import bq_write_validated

        nuove = filter_new_rows_by_hash(F_PEC_MESSAGES, msg_rows, "hash_riga")
        dedup_bq = len(msg_rows) - len(nuove)
        # Dedup allegati sul LORO hash_riga, indipendente dalla novità del
        # messaggio: le due tabelle sono idempotenti ciascuna per sé (abilita
        # il backfill allegati anche quando i messaggi sono già in BQ).
        nuove_all = filter_new_rows_by_hash(F_PEC_ALLEGATI, all_rows, "hash_riga")
        dedup_bq_allegati = len(all_rows) - len(nuove_all)

        if nuove:
            bq_write_validated(
                F_PEC_MESSAGES, [PecMessageRow(**r) for r in nuove], mode="append"
            )
        if nuove_all:
            bq_write_validated(
                F_PEC_ALLEGATI, [PecAllegatoRow(**a) for a in nuove_all], mode="append"
            )
        msg_rows, all_rows = nuove, nuove_all

    report = {
        "file": path.name,
        "messaggi_letti": letti,
        "dedup_in_file": dedup_in_file,
        "dedup_bq": dedup_bq,
        "dedup_bq_allegati": dedup_bq_allegati,
        "righe_messaggi": len(msg_rows),
        "righe_allegati": len(all_rows),
        "con_warning": sum(1 for r in msg_rows if r["parse_warning"]),
        "senza_postacert": sum(1 for r in msg_rows if not r["ha_postacert"]),
        "per_tipo": dict(Counter(r["tipo"] for r in msg_rows)),
        "coverage_gaps": [
            (str(a), str(b), g)
            for a, b, g in coverage_gaps([r["data_evento"].date() for r in msg_rows])
        ],
        "allegati_caricati": store.n_uploaded,
        "allegati_riusati": store.n_riusati,
    }
    for k, v in report.items():
        log.info("  %s: %s", k, v)
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Ingest mbox PEC → f_pec_messages")
    ap.add_argument("--file", required=True, type=Path, help="export mbox PEC")
    ap.add_argument(
        "--societa",
        default=None,
        help="passata dal promotion path; deve combaciare con la casella (INTUR)",
    )
    ap.add_argument(
        "--raw-object-id",
        default=None,
        help="FK a f_raw_objects (stampato su ogni riga — promotion path)",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    if args.societa and args.societa != SOCIETA:
        ap.error(
            f"--societa {args.societa} non combacia con la casella {CASELLA} ({SOCIETA})"
        )

    report = ingest_file(
        args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run
    )
    log.info(
        "DONE %s: %d nuove righe messaggi, %d allegati",
        args.file.name,
        report["righe_messaggi"],
        report["righe_allegati"],
    )


if __name__ == "__main__":
    main()
