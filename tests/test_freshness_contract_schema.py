"""Contratto freshness/acquisition dentro SourceDefinition (spec 2026-09-09 §3)."""

import pytest
from pydantic import ValidationError

from core.lineage.schemas import (
    AcquisitionContract,
    FreshnessContract,
    SourceDefinition,
)


def _base(**over) -> dict:
    d = dict(
        source_name="MPS_BANCA_ORTI_APPEND",
        system="MPS",
        dataset="BANCA",
        societa="ORTI",
        lifecycle="APPEND",
        canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest",
        loop_targets=["cash_control"],
        promotion_policy="AUTO",
        detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
    )
    d.update(over)
    return d


def test_source_definition_senza_contratto_carica_ancora():
    sd = SourceDefinition(**_base())
    assert sd.freshness is None and sd.acquisition is None


def test_freshness_canonical_richiede_coverage_column():
    with pytest.raises(ValidationError, match="coverage_column"):
        FreshnessContract(tier="E", cadence="monthly", grain="daily")


def test_freshness_raw_non_ammette_coverage_column_ne_dims():
    with pytest.raises(ValidationError, match="raw"):
        FreshnessContract(
            tier="E",
            cadence="monthly",
            grain="daily",
            basis="raw",
            coverage_column="data",
        )
    with pytest.raises(ValidationError, match="raw"):
        FreshnessContract(
            tier="E", cadence="monthly", grain="daily", basis="raw", dims=["banca_id"]
        )


def test_grace_day_fuori_range_rifiutato():
    with pytest.raises(ValidationError, match="grace_day"):
        FreshnessContract(
            tier="E",
            cadence="monthly",
            grain="daily",
            coverage_column="data",
            grace_day=31,
        )


def test_acquisition_auto_richiede_job_e_owner_job():
    with pytest.raises(ValidationError, match="job"):
        AcquisitionContract(mode="AUTO", owner="job", location="Drive", report="x")
    with pytest.raises(ValidationError, match="owner"):
        AcquisitionContract(
            mode="AUTO",
            owner="Stefano",
            location="Drive",
            report="x",
            job="drive_fetch:X",
        )


def test_acquisition_semi_non_ammette_job():
    with pytest.raises(ValidationError, match="job"):
        AcquisitionContract(
            mode="SEMI", owner="Stefano", location="Esolver", report="x", job="ingest_x"
        )


def test_raw_only_con_freshness_deve_essere_basis_raw():
    with pytest.raises(ValidationError, match="RAW_ONLY"):
        SourceDefinition(
            **_base(
                promotion_policy="RAW_ONLY",
                loop_targets=[],
                freshness={
                    "tier": "M",
                    "cadence": "adhoc",
                    "grain": "snapshot",
                    "coverage_column": "data",
                },
            )
        )


def test_contratto_completo_round_trip():
    sd = SourceDefinition(
        **_base(
            freshness={
                "tier": "E",
                "cadence": "monthly",
                "grain": "daily",
                "coverage_column": "data_operazione",
                "dims": ["banca_id"],
                "dim_filter": {"banca_id": ["MPS", "MPS_KROSS"]},
            },
            acquisition={
                "mode": "SEMI",
                "owner": "Stefano",
                "location": "Homebanking MPS",
                "report": "Lista movimenti",
                "filters": "mese pieno",
                "format": "xls",
            },
        )
    )
    assert sd.freshness.grace_day == 10
    assert sd.freshness.dim_filter["banca_id"] == ["MPS", "MPS_KROSS"]
    assert sd.acquisition.job is None
