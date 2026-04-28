import pytest
from core.bq.write import SchemaViolationError, BigQueryInsertError


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
