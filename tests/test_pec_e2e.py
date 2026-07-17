"""E2E su fixture: parse → classify → panel, con BQ/GCS finti.

Invarianti coperti: I-PEC-2 (entity dal registry), I-PEC-3 (personale mai nel
pannello), I-PEC-4 (idempotenza), I-PEC-6 (no path traversal). Il resto della
pipeline (intake/promote) ha i suoi test di lineage già esistenti.
"""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest


def _eml_con_allegato(path: Path, casella_from: str, nome_allegato: str) -> Path:
    m = EmailMessage()
    m["From"] = casella_from
    m["To"] = "avvocato@legalmail.it"
    m["Subject"] = "Diffida ad adempiere"
    m["Message-ID"] = f"<e2e-{nome_allegato}@test>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("testo")
    m.add_attachment(b"%PDF-fake", maintype="application", subtype="pdf",
                     filename=nome_allegato)
    path.write_bytes(bytes(m))
    return path


def test_e2e_parse_classify_panel(tmp_path, monkeypatch):
    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source
    from ingest.pec.classify import classify_message, load_ruleset

    # 1. Parse (dry-run: niente GCS/BQ) — entity dal registry
    src = resolve_pec_source("PEC_MAILBOX_PERSONALE_APPEND")
    eml = _eml_con_allegato(
        tmp_path / "m.eml", "stefanojunior.dellapietra@mpspec.it",
        "../../evil contratto.pdf",
    )
    report = ingest_file(eml, src, dry_run=True)
    assert report["righe_messaggi"] == 1

    # 2. Classify: oggetto legale → LEGALE/ALTA
    esito = classify_message(
        "avvocato@legalmail.it", "Diffida ad adempiere",
        ["../../evil contratto.pdf"], load_ruleset(),
    )
    assert esito["primary_category"] == "LEGALE"
    assert esito["importance"] == "ALTA"

    # 3. Panel: STEFANO_PERSONALE mai proiettabile (I-PEC-3)
    from ingest.pec.panel import _destination_path

    with pytest.raises(ValueError, match="whitelist"):
        _destination_path("STEFANO_PERSONALE", "LEGALE",
                          datetime(2026, 7, 15), "evil contratto.pdf")

    # 4. Per un'entity ammessa, il nome malevolo resta sotto root (I-PEC-6)
    rel = _destination_path("ORTI", "LEGALE", datetime(2026, 7, 15),
                            "../../evil contratto.pdf")
    assert rel.parts[0] == "ORTI" and ".." not in str(rel)


def test_e2e_idempotenza_parse(tmp_path):
    """Stesso file due volte: dedup in-file su msgid, stesse righe (I-PEC-4)."""
    import mailbox

    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")
    mb_path = tmp_path / "doppio.mbox"
    box = mailbox.mbox(str(mb_path))
    m = EmailMessage()
    m["From"] = "orti@pec.it"
    m["To"] = "x@pec.it"
    m["Subject"] = "s"
    m["Message-ID"] = "<dup-1@test>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("c")
    box.add(m)
    box.add(m)  # duplicato nello stesso container
    box.flush()

    report = ingest_file(mb_path, src, dry_run=True)
    assert report["messaggi_letti"] == 2
    assert report["dedup_in_file"] == 1
    assert report["righe_messaggi"] == 1
