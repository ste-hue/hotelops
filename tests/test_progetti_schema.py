"""Pydantic validation tests for projects event-sourced models (Step 1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.schemas import PreventivoMeta, Rata


class TestRata:
    def test_happy_path(self):
        r = Rata(
            seq=1,
            data_prevista=date(2026, 5, 1),
            importo_eur=Decimal("100.00"),
            descrizione="Acconto 30%",
            stato="PIANIFICATA",
        )
        assert r.seq == 1
        assert r.importo_eur == Decimal("100.00")
        assert r.stato == "PIANIFICATA"

    def test_invalid_stato_rejected(self):
        with pytest.raises(ValidationError):
            Rata(
                seq=1,
                data_prevista=date(2026, 5, 1),
                importo_eur=Decimal("100"),
                descrizione="x",
                stato="UNKNOWN_STATO",
            )


class TestPreventivoMeta:
    def test_minimal_required(self):
        m = PreventivoMeta(
            articolo="Pagoda 220",
            stato_preventivo="RICEVUTO",
        )
        assert m.tipo == "PREVENTIVO"
        assert m.articolo == "Pagoda 220"
        assert m.numero_preventivo is None

    def test_full_fields(self):
        m = PreventivoMeta(
            numero_preventivo="SQ221807-2",
            data_preventivo=date(2025, 3, 10),
            validita_fino_a=date(2025, 6, 10),
            articolo="Sand Desk Brown Inground Wood",
            codice_articolo="NRO510-0611",
            stato_preventivo="ACCETTATO",
            note="Sconto 20% applicato",
        )
        assert m.numero_preventivo == "SQ221807-2"
        assert m.codice_articolo == "NRO510-0611"

    def test_invalid_stato_preventivo_rejected(self):
        with pytest.raises(ValidationError):
            PreventivoMeta(articolo="x", stato_preventivo="MAYBE")
