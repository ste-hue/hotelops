"""Pydantic validation tests for projects event-sourced models (Step 1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.schemas import (
    DocumentoMeta,
    FatturaMeta,
    ImpegnoMeta,
    PagamentoMeta,
    PreventivoMeta,
    Progetto,
    ProgettoEvento,
    ProgettoVoce,
    Rata,
)


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


class TestImpegnoMeta:
    def test_minimal_with_rate(self):
        m = ImpegnoMeta(
            data_firma=date(2026, 2, 27),
            rate=[
                Rata(
                    seq=1,
                    data_prevista=date(2026, 3, 1),
                    importo_eur=Decimal("7200.00"),
                    descrizione="Acconto 30%",
                    stato="PIANIFICATA",
                )
            ],
            stato_commitment="FIRMATO",
        )
        assert m.tipo == "IMPEGNO"
        assert len(m.rate) == 1
        assert m.from_preventivo_evento_id is None
        assert m.motivo_variazione is None

    def test_with_variazione(self):
        m = ImpegnoMeta(
            data_firma=date(2026, 3, 1),
            rate=[],
            stato_commitment="IN_CORSO",
            motivo_variazione="Overrun amianto Ft 02-26",
            from_preventivo_evento_id="evt-uuid-001",
        )
        assert m.motivo_variazione.startswith("Overrun")


class TestFatturaMeta:
    def test_minimal(self):
        m = FatturaMeta(
            numero_fattura="IT00126V0001851",
            data_emissione=date(2026, 4, 15),
            tipo_doc="FT",
            condizioni_pagamento="Bonifico 30gg",
        )
        assert m.tipo == "FATTURA"
        assert m.movimento_row_hash is None
        assert m.copre_rate == []

    def test_full(self):
        m = FatturaMeta(
            numero_fattura="FPR 31/26",
            data_emissione=date(2026, 3, 26),
            data_ricezione=date(2026, 3, 28),
            tipo_doc="FT-RC",
            condizioni_pagamento="Bonifico 90gg DF FM",
            data_scadenza=date(2026, 6, 30),
            movimento_row_hash="abc123def456",
            copre_rate=[1, 2],
        )
        assert m.tipo_doc == "FT-RC"
        assert m.copre_rate == [1, 2]


class TestPagamentoMeta:
    def test_happy_path(self):
        m = PagamentoMeta(
            data_valuta=date(2026, 5, 14),
            metodo="BONIFICO",
            importo_pagato_eur=Decimal("2169.16"),
            copre_fatture=["evt-fattura-001"],
        )
        assert m.tipo == "PAGAMENTO"
        assert m.banca_movimento_hash is None

    def test_multi_fattura_coverage(self):
        m = PagamentoMeta(
            data_valuta=date(2026, 5, 14),
            metodo="BONIFICO",
            importo_pagato_eur=Decimal("10000.00"),
            copre_fatture=["evt-f-001", "evt-f-002", "evt-f-003"],
            banca_movimento_hash="md5xyz",
        )
        assert len(m.copre_fatture) == 3


class TestDocumentoMeta:
    def test_minimal(self):
        m = DocumentoMeta(
            tipo_doc="PREVENTIVO",
            drive_url="https://drive.google.com/file/d/abc",
            file_name="Preventivo_Kompan.pdf",
            file_hash_md5="abc123",
        )
        assert m.tipo == "DOCUMENTO"
        assert m.correlato_evento_id is None

    def test_correlato_to_event(self):
        m = DocumentoMeta(
            tipo_doc="FATTURA",
            drive_url="https://drive.google.com/...",
            file_name="ft_03.pdf",
            file_hash_md5="def456",
            correlato_evento_id="evt-fattura-uuid",
        )
        assert m.correlato_evento_id == "evt-fattura-uuid"


class TestProgetto:
    def test_happy_path(self):
        p = Progetto(
            progetto_id="HPAN25PIANO1",
            nome="Camere Primo Piano - Hotel Panorama",
            societa_owner_id="INTUR",
            business_unit_id="HOTEL",
            struttura="Hotel Panorama",
            budget_cap_eur=Decimal("1200000.00"),
            data_inizio=date(2026, 2, 1),
            stato="IN_CORSO",
            owner="Stefano Della Pietra Jr",
        )
        assert p.progetto_id == "HPAN25PIANO1"
        assert p.data_fine_prevista is None
        assert p.drive_root_url is None

    def test_invalid_societa_rejected(self):
        with pytest.raises(ValidationError):
            Progetto(
                progetto_id="X",
                nome="X",
                societa_owner_id="UNKNOWN",  # invalid - not ORTI/INTUR
                business_unit_id="HOTEL",
                budget_cap_eur=Decimal("1"),
                data_inizio=date(2026, 1, 1),
                stato="IN_CORSO",
                owner="x",
            )


class TestProgettoVoce:
    def test_minimal(self):
        v = ProgettoVoce(
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            codice_interno="001",
            descrizione="Opere murarie strutturali piano 1",
            categoria="EDILE",
            societa_pagante_id="INTUR",
        )
        assert v.fornitore_id is None
        assert v.qta is None

    def test_with_fornitore_chosen(self):
        v = ProgettoVoce(
            voce_id="HPAN25PIANO1.010",
            progetto_id="HPAN25PIANO1",
            codice_interno="010",
            descrizione="Project Management",
            categoria="CONSULENZA",
            societa_pagante_id="ORTI",  # opex via ORTI
            fornitore_id="anag-hospitality-project-001",
        )
        assert v.societa_pagante_id == "ORTI"
        assert v.fornitore_id is not None


class TestProgettoEvento:
    def test_preventivo_event_validates(self):
        e = ProgettoEvento(
            evento_id="evt-001",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 15),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Opere murarie strutturali piano 1",
                "stato_preventivo": "ACCETTATO",
            },
        )
        assert e.metadata.tipo == "PREVENTIVO"
        assert e.metadata.articolo.startswith("Opere")

    def test_impegno_event_validates_with_rate(self):
        e = ProgettoEvento(
            evento_id="evt-002",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO",
            data_evento=date(2026, 2, 27),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "IMPEGNO",
                "data_firma": "2026-02-27",
                "rate": [
                    {
                        "seq": 1,
                        "data_prevista": "2026-03-15",
                        "importo_eur": "100000.00",
                        "descrizione": "Acconto",
                        "stato": "PIANIFICATA",
                    }
                ],
                "stato_commitment": "FIRMATO",
            },
        )
        assert e.metadata.tipo == "IMPEGNO"
        assert len(e.metadata.rate) == 1
        assert e.metadata.rate[0].seq == 1

    def test_tipo_mismatch_rejected(self):
        # tipo_evento=FATTURA but metadata.tipo=PREVENTIVO -> must fail
        with pytest.raises(ValidationError):
            ProgettoEvento(
                evento_id="evt-bad",
                voce_id="x",
                progetto_id="x",
                tipo_evento="FATTURA",
                data_evento=date(2026, 1, 1),
                data_registrazione="2026-04-26T10:00:00",
                metadata={
                    "tipo": "PREVENTIVO",  # mismatch!
                    "articolo": "x",
                    "stato_preventivo": "RICEVUTO",
                },
            )

    def test_documento_event_with_correlato(self):
        e = ProgettoEvento(
            evento_id="evt-doc",
            voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="DOCUMENTO",
            data_evento=date(2025, 3, 10),
            data_registrazione="2026-04-26T10:00:00",
            metadata={
                "tipo": "DOCUMENTO",
                "tipo_doc": "PREVENTIVO",
                "drive_url": "https://drive.google.com/file/d/xyz",
                "file_name": "Preventivo_Ethimo.pdf",
                "file_hash_md5": "deadbeef",
                "correlato_evento_id": "evt-prev-ethimo",
            },
        )
        assert e.metadata.correlato_evento_id == "evt-prev-ethimo"

    def test_serialization_roundtrip(self):
        """Ensure model_dump → model_validate roundtrip preserves data."""
        original = ProgettoEvento(
            evento_id="evt-rt",
            voce_id="x",
            progetto_id="x",
            tipo_evento="PAGAMENTO",
            data_evento=date(2026, 5, 14),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("100.00"),
            metadata={
                "tipo": "PAGAMENTO",
                "data_valuta": "2026-05-14",
                "metodo": "BONIFICO",
                "importo_pagato_eur": "100.00",
                "copre_fatture": ["evt-f-1"],
            },
        )
        dumped = original.model_dump(mode="json")
        restored = ProgettoEvento.model_validate(dumped)
        assert restored.metadata.tipo == "PAGAMENTO"
        assert restored.metadata.metodo == "BONIFICO"
