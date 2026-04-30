from unittest.mock import MagicMock, patch
from pydantic import BaseModel
from core.bq.dedup import filter_new_rows_by_hash


class HashedRow(BaseModel):
    hash_riga: str
    payload: int


@patch("core.bq.dedup.get_client")
def test_filter_returns_only_new_rows(mock_get_client):
    mock_client = MagicMock()
    # BQ says hashes "a" and "b" already exist
    mock_row = MagicMock()
    mock_row.hash_riga = "a"
    mock_row2 = MagicMock()
    mock_row2.hash_riga = "b"
    mock_client.query.return_value.result.return_value = [mock_row, mock_row2]
    mock_get_client.return_value = mock_client

    rows = [
        HashedRow(hash_riga="a", payload=1),  # already in BQ
        HashedRow(hash_riga="c", payload=3),  # new
        HashedRow(hash_riga="b", payload=2),  # already in BQ
    ]
    new_rows = filter_new_rows_by_hash("hotelops.f_x", rows, hash_column="hash_riga")

    assert len(new_rows) == 1
    assert new_rows[0].hash_riga == "c"


@patch("core.bq.dedup.get_client")
def test_filter_empty_input_returns_empty(mock_get_client):
    new_rows = filter_new_rows_by_hash("hotelops.f_x", [], hash_column="hash_riga")
    assert new_rows == []
    # No BQ query needed
    mock_get_client.return_value.query.assert_not_called()


@patch("core.bq.dedup.get_client")
def test_filter_accepts_dicts(mock_get_client):
    """Natural pipeline flow: parse → dict → dedup → pydantic → gate.
    Avoid double-validation by letting dedup work on raw dicts.
    """
    mock_client = MagicMock()
    mock_row = MagicMock()
    mock_row.hash_riga = "a"
    mock_client.query.return_value.result.return_value = [mock_row]
    mock_get_client.return_value = mock_client

    rows = [
        {"hash_riga": "a", "payload": 1},  # already in BQ
        {"hash_riga": "c", "payload": 3},  # new
    ]
    new_rows = filter_new_rows_by_hash("hotelops.f_x", rows, hash_column="hash_riga")
    assert len(new_rows) == 1
    assert new_rows[0]["hash_riga"] == "c"


@patch("core.bq.dedup.get_client")
def test_filter_all_new_when_table_empty(mock_get_client):
    mock_client = MagicMock()
    mock_client.query.return_value.result.return_value = []
    mock_get_client.return_value = mock_client

    rows = [HashedRow(hash_riga="a", payload=1), HashedRow(hash_riga="b", payload=2)]
    new_rows = filter_new_rows_by_hash("hotelops.f_x", rows, hash_column="hash_riga")
    assert len(new_rows) == 2
