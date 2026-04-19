"""Centralized BigQuery client factory.

Every module needing a BQ client must import `get_client()` from here instead of
instantiating `bigquery.Client(...)` directly. Ensures one project constant
(from core.config) and reuses a single client instance per process.
"""
from google.cloud import bigquery

from core.config import PROJECT

_client: bigquery.Client | None = None


def get_client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT)
    return _client
