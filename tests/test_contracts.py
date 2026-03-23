"""Tests for lib.contracts — data contract validation."""

import pytest

from core.contracts import SchemaViolationError, validate_columns


def test_validate_columns_passes_when_all_present():
    validate_columns(
        found=["a", "b", "c", "d"],
        required={"a", "c"},
        context="test",
    )


def test_validate_columns_raises_on_missing():
    with pytest.raises(SchemaViolationError, match="missing columns"):
        validate_columns(
            found=["a", "b"],
            required={"a", "b", "c", "d"},
            context="test file",
        )


def test_validate_columns_error_includes_context():
    with pytest.raises(SchemaViolationError, match="Sella CSV foo.csv"):
        validate_columns(
            found=["X"],
            required={"X", "Y"},
            context="Sella CSV foo.csv",
        )


def test_validate_columns_error_lists_missing_sorted():
    with pytest.raises(SchemaViolationError, match=r"\['B', 'D'\]"):
        validate_columns(
            found=["A", "C"],
            required={"A", "B", "C", "D"},
            context="test",
        )


def test_validate_columns_empty_found():
    with pytest.raises(SchemaViolationError):
        validate_columns(found=[], required={"a"}, context="empty")


def test_validate_columns_empty_required():
    validate_columns(found=["a", "b"], required=set(), context="none needed")


def test_validate_columns_accepts_set_as_found():
    validate_columns(
        found={"x", "y", "z"},
        required={"x", "z"},
        context="set input",
    )


def test_validate_columns_accepts_dict_keys():
    validate_columns(
        found={"col_a": "v1", "col_b": "v2"}.keys(),
        required={"col_a"},
        context="dict keys",
    )
