import pytest
from pydantic import BaseModel

from core.bq.write import SchemaViolationError, BigQueryInsertError, bq_write_validated


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
