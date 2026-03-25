"""Shared pytest fixtures for hotelops tests."""

from unittest.mock import MagicMock, patch

import pytest

DATAHUB_FOLDERS = [
    "homebanking/ORTI",
    "homebanking/INTUR",
    "movimenti_contabili/ORTI",
    "movimenti_contabili/INTUR",
    "registro_banca_esolver/ORTI",
    "registro_banca_esolver/INTUR",
    "partite_fornitori/ORTI",
    "partite_fornitori/INTUR",
    "piani_finanziari/ORTI",
    "piani_finanziari/INTUR",
    "accodamenti/ORTI",
    "economato",
    "coperti",
    "bilancino/ORTI",
    "bilancino/INTUR",
    "gasparotto",
    "dimensioni",
    "fatti",
    "meta",
]


@pytest.fixture()
def tmp_datahub(tmp_path):
    """Create a minimal datahub directory structure under tmp_path."""
    for folder in DATAHUB_FOLDERS:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def mock_bq_client():
    """Patch google.cloud.bigquery.Client with a MagicMock.

    Yields the mock client so tests can configure return values.
    """
    with patch("google.cloud.bigquery.Client") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield client
