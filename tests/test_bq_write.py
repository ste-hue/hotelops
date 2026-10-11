import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from core.bq.write import (
    BigQueryInsertError,
    HashCollisionError,
    SchemaViolationError,
    SerializationBoundaryError,
    bq_write_validated,
)
from core.pipeline_run import PipelineRun


def test_schema_violation_error_message_lists_first_5():
    failures = [(i, {"x": i}, f"err {i}") for i in range(8)]
    err = SchemaViolationError("hotelops.f_x", failures)
    msg = str(err)
    assert "8 rows" in msg
    assert "hotelops.f_x" in msg
    # First 5 visible, rest summarized
    for i in range(5):
        assert f"err {i}" in msg
    assert "and 3 more" in msg


def test_schema_violation_error_message_under_5_no_summary():
    failures = [(0, {"x": 0}, "boom")]
    err = SchemaViolationError("hotelops.f_x", failures)
    msg = str(err)
    assert "1 rows" in msg
    assert "boom" in msg
    assert "more" not in msg.lower()


def test_bigquery_insert_error_carries_table_and_errors():
    err = BigQueryInsertError("hotelops.f_x", [{"index": 0, "errors": [...]}])
    assert err.table_id == "hotelops.f_x"
    assert err.errors == [{"index": 0, "errors": [...]}]
    assert "hotelops.f_x" in str(err)


class FakeRow(BaseModel):
    societa_id: str
    n: int


class FakeHashedRow(BaseModel):
    hash_riga: str
    societa_id: str
    importo: float


# --- Hash collision gate -----------------------------------------------------
# Una chiave di dedup che collide non duplica: CANCELLA. `filter_new_rows_by_hash`
# vede l'hash come "già presente" e scarta righe genuine. Il caso reale che ha
# motivato il gate: 3 mutui INTUR distinti collassati su un hash solo in
# f_piano_finanziario_input (audit 2026-08-09).


@patch("core.bq.write.get_client")
def test_duplicate_hash_riga_in_batch_is_rejected(mock_get_client):
    mock_get_client.return_value = MagicMock()
    rows = [
        FakeHashedRow(hash_riga="abc", societa_id="INTUR", importo=8500.0),
        FakeHashedRow(hash_riga="abc", societa_id="INTUR", importo=3210.53),
    ]
    with pytest.raises(HashCollisionError) as exc:
        bq_write_validated("hotelops.f_x", rows, mode="append")
    assert "abc" in str(exc.value)
    mock_get_client.return_value.load_table_from_json.assert_not_called()


@patch("core.bq.write.get_client")
def test_unique_hash_riga_passes(mock_get_client):
    mock_client = MagicMock()
    mock_client.load_table_from_json.return_value.result.return_value = None
    mock_get_client.return_value = mock_client
    rows = [
        FakeHashedRow(hash_riga="a", societa_id="INTUR", importo=1.0),
        FakeHashedRow(hash_riga="b", societa_id="INTUR", importo=2.0),
    ]
    bq_write_validated("hotelops.f_x", rows, mode="append")
    mock_client.load_table_from_json.assert_called_once()


@patch("core.bq.write.get_client")
def test_schema_without_hash_riga_is_unaffected(mock_get_client):
    mock_client = MagicMock()
    mock_client.load_table_from_json.return_value.result.return_value = None
    mock_get_client.return_value = mock_client
    rows = [FakeRow(societa_id="ORTI", n=1), FakeRow(societa_id="ORTI", n=1)]
    bq_write_validated("hotelops.f_x", rows, mode="append")
    mock_client.load_table_from_json.assert_called_once()


def test_empty_batch_is_noop(caplog):
    caplog.set_level("INFO")
    bq_write_validated("hotelops.f_x", [], mode="append")
    assert "empty batch for hotelops.f_x" in caplog.text


def test_snapshot_without_natural_key_raises():
    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(ValueError, match="snapshot mode requires natural_key"):
        bq_write_validated("hotelops.f_x", rows, mode="snapshot")


def test_snapshot_with_empty_natural_key_raises():
    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(ValueError, match="snapshot mode requires natural_key"):
        bq_write_validated("hotelops.f_x", rows, mode="snapshot", natural_key=[])


def test_validation_failure_raises_with_failures():
    rows = [
        FakeRow(societa_id="ORTI", n=1),
        "not a model",  # type: ignore  -- test the BaseModel guard
    ]
    with pytest.raises(SchemaViolationError) as exc:
        bq_write_validated("hotelops.f_x", rows, mode="append")
    assert exc.value.table_id == "hotelops.f_x"
    assert len(exc.value.failures) == 1
    assert exc.value.failures[0][0] == 1  # row index
    assert "BaseModel" in exc.value.failures[0][2]


def test_mixed_pydantic_types_raise():
    class OtherRow(BaseModel):
        x: str

    rows = [FakeRow(societa_id="ORTI", n=1), OtherRow(x="y")]
    with pytest.raises(SchemaViolationError) as exc:
        bq_write_validated("hotelops.f_x", rows, mode="append")
    assert "type" in exc.value.failures[0][2].lower()


@patch("core.bq.write.get_client")
def test_append_calls_load_table_from_json_with_write_append(mock_get_client):
    from google.cloud import bigquery

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1), FakeRow(societa_id="ORTI", n=2)]
    bq_write_validated("hotelops.f_x", rows, mode="append")

    mock_client.load_table_from_json.assert_called_once()
    args, kwargs = mock_client.load_table_from_json.call_args
    assert args[0] == [{"societa_id": "ORTI", "n": 1}, {"societa_id": "ORTI", "n": 2}]
    assert args[1] == "hotelops.f_x"
    job_config = kwargs["job_config"]
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert job_config.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    assert job_config.create_disposition == bigquery.CreateDisposition.CREATE_NEVER


@patch("core.bq.write.get_client")
def test_append_raises_bigquery_insert_error_on_job_errors(mock_get_client):
    mock_client = MagicMock()
    mock_job = MagicMock()
    # Simulate a load job that completed with row errors
    mock_job.result.side_effect = Exception("row errors: [{...}]")
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(BigQueryInsertError):
        bq_write_validated("hotelops.f_x", rows, mode="append")


@patch("core.bq.write.get_client")
def test_snapshot_runs_delete_then_insert(mock_get_client):
    mock_client = MagicMock()
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = None
    mock_client.query.return_value = mock_query_job

    mock_load_job = MagicMock()
    mock_load_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_load_job

    mock_get_client.return_value = mock_client

    rows = [
        FakeRow(societa_id="ORTI", n=1),
        FakeRow(societa_id="INTUR", n=2),
    ]
    bq_write_validated(
        "hotelops.f_x",
        rows,
        mode="snapshot",
        natural_key=["societa_id"],
    )

    # DELETE issued first, then INSERT
    assert mock_client.query.called
    delete_sql = mock_client.query.call_args.args[0]
    assert "DELETE FROM `hotelops.f_x`" in delete_sql
    assert "(societa_id) IN UNNEST" in delete_sql

    # INSERT happened after delete
    mock_client.load_table_from_json.assert_called_once()


@patch("core.bq.write.get_client")
def test_snapshot_natural_key_with_two_columns_uses_struct(mock_get_client):
    mock_client = MagicMock()
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = None
    mock_client.query.return_value = mock_query_job
    mock_load_job = MagicMock()
    mock_load_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_load_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    bq_write_validated(
        "hotelops.f_x",
        rows,
        mode="snapshot",
        natural_key=["societa_id", "n"],
    )

    delete_sql = mock_client.query.call_args.args[0]
    assert "(societa_id, n)" in delete_sql


@patch("core.bq.write.get_client")
@patch("core.pipeline_run.PipelineRun._insert_final")  # avoid real BQ write
def test_lineage_populated_from_active_pipeline_run(
    mock_insert, mock_get_client, caplog
):
    caplog.set_level("INFO")
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    with PipelineRun("test_pipeline", file_sorgente="my_file.xlsx") as run:
        bq_write_validated("hotelops.f_x", rows, mode="append")

    # The success log line carries lineage in `extra`
    record = next(
        r for r in caplog.records
        if getattr(r, "table", None) == "hotelops.f_x"
    )
    assert record.pipeline_name == "test_pipeline"
    assert record.run_id == run.run_id
    assert record.file_sorgente == "my_file.xlsx"
    assert record.mode == "append"


class RowWithDate(BaseModel):
    societa_id: str
    data_snapshot: date
    creato_il: datetime
    importo: Decimal


@patch("core.bq.write.get_client")
def test_model_dump_produces_json_serializable_dict(mock_get_client):
    """Regression: load_table_from_json calls json.dumps WITHOUT a default
    handler, so model_dump() must coerce date/datetime/Decimal to JSON
    primitives upstream. Default mode='python' would crash with
    'Object of type date is not JSON serializable'.
    """
    captured: list[dict] = []

    def fake_load(rows_dict, table, job_config=None):
        # Mirror google.cloud.bigquery.Client.load_table_from_json:
        # it serializes each row with json.dumps(item, ensure_ascii=False)
        # — no default handler — and would crash on raw date objects.
        for item in rows_dict:
            json.dumps(item, ensure_ascii=False)
        captured.extend(rows_dict)
        job = MagicMock()
        job.result.return_value = None
        return job

    mock_client = MagicMock()
    mock_client.load_table_from_json.side_effect = fake_load
    mock_get_client.return_value = mock_client

    rows = [
        RowWithDate(
            societa_id="ORTI",
            data_snapshot=date(2026, 4, 28),
            creato_il=datetime(2026, 4, 28, 14, 30, 0),
            importo=Decimal("1234.56"),
        )
    ]
    bq_write_validated("hotelops.f_x", rows, mode="append")

    assert captured == [
        {
            "societa_id": "ORTI",
            "data_snapshot": "2026-04-28",
            "creato_il": "2026-04-28T14:30:00",
            "importo": "1234.56",
        }
    ]


@patch("core.bq.write.get_client")
def test_serialization_boundary_blocks_unserializable_dict(mock_get_client):
    """Future regression guard: even if a Pydantic schema's model_dump returns
    a dict json.dumps cannot handle, the gate raises BEFORE any BQ side-effect.

    Critical for snapshot mode: a partial DELETE landing before the INSERT
    crashes would leave the table half-wiped. The boundary probe runs after
    validation, before mode dispatch — so DELETE never fires.
    """
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    # Simulate a future drift: model_dump returns a non-JSON-serializable dict
    with patch.object(FakeRow, "model_dump", return_value={"x": object()}):
        with pytest.raises(SerializationBoundaryError) as exc:
            bq_write_validated(
                "hotelops.f_x", rows, mode="snapshot", natural_key=["societa_id"]
            )

    assert exc.value.table_id == "hotelops.f_x"
    assert len(exc.value.failures) == 1
    # Crucially: no BQ side-effects fired (no DELETE, no INSERT)
    mock_client.query.assert_not_called()
    mock_client.load_table_from_json.assert_not_called()


def test_lineage_warns_when_no_active_run(caplog):
    caplog.set_level("INFO")
    with patch("core.bq.write.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = None
        mock_client.load_table_from_json.return_value = mock_job
        mock_get_client.return_value = mock_client

        rows = [FakeRow(societa_id="ORTI", n=1)]
        bq_write_validated("hotelops.f_x", rows, mode="append")

    assert "outside PipelineRun context" in caplog.text
    assert "hotelops.f_x" in caplog.text

    # Out-of-PipelineRun: gate generates a standalone UUID and tags
    # pipeline_name='unknown_pipeline' (DATA_ENGINEERING_RULES.md §3).
    record = next(
        r for r in caplog.records
        if getattr(r, "table", None) == "hotelops.f_x"
    )
    assert record.pipeline_name == "unknown_pipeline"
    assert record.run_id is not None
    uuid.UUID(record.run_id)  # raises ValueError if not a valid UUID string
