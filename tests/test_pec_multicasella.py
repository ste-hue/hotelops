"""PEC multi-casella — EntityId, schema righe, registry, parser generalizzato."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.schemas import PecMessageRow, validate_batch


def _row(**over) -> dict:
    base = {
        "msgid": "m1@pec.aruba.it",
        "source_folder": "RECEIVED",
        "tipo": "POSTA_CERTIFICATA",
        "ref_msgid": None,
        "data_evento": datetime(2026, 7, 1, 10, 0),
        "data_certificata": True,
        "mittente": "x@pec.it",
        "destinatari": "orti@pec.it",
        "n_destinatari": 1,
        "subject": "s",
        "body_text": None,
        "provider": "pec.aruba.it",
        "casella": "orti@pec.it",
        "entity_id": "ORTI",
        "societa_id": "ORTI",
        "n_allegati": 0,
        "ha_postacert": False,
        "parse_warning": None,
        "hash_riga": "h1",
        "raw_object_id": "raw-1",
        "data_caricamento": datetime(2026, 7, 17, 12, 0),
    }
    base.update(over)
    return base


def test_entity_id_literal_completo():
    from core.schemas import EntityId
    from typing import get_args

    assert set(get_args(EntityId)) == {"INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"}


def test_societa_id_non_esteso():
    from core.schemas import SocietaId
    from typing import get_args

    assert set(get_args(SocietaId)) == {"ORTI", "INTUR"}


def test_riga_personale_senza_societa():
    row = _row(
        casella="stefanojunior.dellapietra@mpspec.it",
        entity_id="STEFANO_PERSONALE",
        societa_id=None,
    )
    validate_batch([row], PecMessageRow, context="test")


def test_riga_vigna_con_societa_rifiutata():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch(
            [_row(entity_id="VIGNA", societa_id="VIGNA")], PecMessageRow, context="test"
        )


def test_entity_id_obbligatorio():
    from core.schemas import SchemaViolationError

    row = _row()
    del row["entity_id"]
    with pytest.raises(SchemaViolationError):
        validate_batch([row], PecMessageRow, context="test")


# ── Step 1: Tests registry (falliscono finché non implemento Task 2) ──────────


def test_registry_quattro_sorgenti_pec():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    attese = {
        "PEC_MAILBOX_INTUR_APPEND": ("in.tur@pec.it", "INTUR", "hotelops-raw"),
        "PEC_MAILBOX_ORTI_APPEND": ("orti@pec.it", "ORTI", "orti-raw"),
        "PEC_MAILBOX_VIGNA_APPEND": ("vineyardamalficoast@pec.it", "VIGNA", "vigna-raw"),
        "PEC_MAILBOX_PERSONALE_APPEND": (
            "stefanojunior.dellapietra@mpspec.it",
            "STEFANO_PERSONALE",
            "stefano-raw",
        ),
    }
    for name, (casella, entity, bucket) in attese.items():
        s = reg.get(name)
        assert s is not None, name
        assert s.casella == casella
        assert s.entity_id == entity
        assert s.raw_storage.bucket == bucket
        assert s.parser_module == "ingest.flussi.ingest_pec_mbox"
        assert s.system == "PEC"


def test_registry_personale_accetta_eml():
    from core.lineage.source_resolver import load_registry

    s = load_registry().get("PEC_MAILBOX_PERSONALE_APPEND")
    assert "eml" in s.input_formats


def test_source_pec_senza_casella_rifiutata():
    from core.lineage.schemas import SourceDefinition
    from pydantic import ValidationError

    base = dict(
        source_name="PEC_MAILBOX_TEST_APPEND",
        system="PEC",
        dataset="MAILBOX",
        societa="INTUR",
        lifecycle="APPEND",
        canonical_table="f_pec_messages",
        parser_module="ingest.flussi.ingest_pec_mbox",
        promotion_policy="AUTO",
        detector_category="pec_mbox",
        raw_storage={"backend": "gcs", "bucket": "b", "path_template": "p"},
    )
    with pytest.raises(ValidationError):
        SourceDefinition(**base)  # PEC senza casella/entity_id
