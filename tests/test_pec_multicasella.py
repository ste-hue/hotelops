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
