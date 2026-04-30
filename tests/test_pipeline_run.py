"""Tests for PipelineRun context manager.

Observability Layer 2: records a row per pipeline execution in f_pipeline_runs.
Single INSERT on __exit__ — no RUNNING placeholder, no UPDATE (streaming
buffer made that unreliable). All BQ interactions are best-effort.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_bq_client_singleton():
    """Clear the cached BQ client so each test's patch is honoured."""
    import core.bq.client as bq_client_mod

    bq_client_mod._client = None
    yield
    bq_client_mod._client = None


class TestPipelineRun:
    def test_generates_uuid_on_enter(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            with PipelineRun("test") as run:
                assert len(run.run_id) == 36  # UUID format
                assert run.started_at is not None

    def test_status_ok_on_clean_exit(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            with PipelineRun("test") as run:
                run.rows_found = 10
                run.rows_new = 3
            assert run.status == "OK"
            assert run.ended_at is not None

    def test_status_fail_on_exception(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            run_ref = None
            try:
                with PipelineRun("test") as run:
                    run_ref = run
                    raise ValueError("something broke")
            except ValueError:
                pass
            assert run_ref.status == "FAIL"
            assert "something broke" in run_ref.error_message

    def test_error_message_truncated_to_500(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            run_ref = None
            try:
                with PipelineRun("test") as run:
                    run_ref = run
                    raise ValueError("x" * 1000)
            except ValueError:
                pass
            assert len(run_ref.error_message) == 500

    def test_no_write_on_enter(self):
        """__enter__ must NOT touch BigQuery — we write once, on exit."""
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            run = PipelineRun("test").__enter__()
            assert not fake_client.insert_rows_json.called
            assert not fake_client.query.called
            # Cleanly close so the test client doesn't leak state.
            run.__exit__(None, None, None)

    def test_inserts_final_row_on_exit(self):
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            with PipelineRun("test") as run:
                run.rows_found = 10
                run.rows_new = 5

        assert fake_client.insert_rows_json.called
        row = fake_client.insert_rows_json.call_args.args[1][0]
        assert row["status"] == "OK"
        assert row["pipeline_name"] == "test"
        assert row["rows_found"] == 10
        assert row["rows_new"] == 5
        assert row["ended_at"] is not None

    def test_inserts_fail_row_on_exception(self):
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            try:
                with PipelineRun("test") as run:
                    run.rows_found = 10
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

        row = fake_client.insert_rows_json.call_args.args[1][0]
        assert row["status"] == "FAIL"
        assert row["rows_found"] == 10
        assert "boom" in row["error_message"]

    def test_never_calls_query(self):
        """No UPDATE anywhere — streaming buffer would block it."""
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            with PipelineRun("test") as run:
                run.rows_new = 1

        assert not fake_client.query.called

    def test_meta_serialized_as_json(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            with PipelineRun("test") as run:
                run.meta = {"watermarks": {"BOOKING|HOTEL": "2026-04-10"}}
            row = run._to_row()
            assert json.loads(row["meta_json"]) == {
                "watermarks": {"BOOKING|HOTEL": "2026-04-10"}
            }

    def test_bq_failure_on_exit_does_not_raise(self):
        """Observability must never break the pipeline."""
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.side_effect = RuntimeError("BQ down")
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            # Must NOT raise
            with PipelineRun("test") as run:
                run.rows_found = 10
            assert run.status == "OK"

    def test_societa_id_passed_through(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            with PipelineRun("banca_ingest", societa_id="ORTI") as run:
                pass
            assert run._to_row()["societa_id"] == "ORTI"

    def test_early_return_still_records_ok(self):
        """Early return from within `with` block still triggers __exit__."""
        from core.pipeline_run import PipelineRun

        def pipeline_with_early_return():
            with patch("google.cloud.bigquery.Client") as mock_client:
                mock_client.return_value = MagicMock()
                with PipelineRun("test") as run:
                    run.rows_found = 0
                    run.rows_new = 0
                    return run  # early return

        run = pipeline_with_early_return()
        assert run.status == "OK"


def test_pipeline_run_file_sorgente_attribute():
    from core.pipeline_run import PipelineRun

    run = PipelineRun("p", file_sorgente="ORTI_x.xlsx")
    assert run.file_sorgente == "ORTI_x.xlsx"


def test_pipeline_run_file_sorgente_default_none():
    from core.pipeline_run import PipelineRun

    run = PipelineRun("p")
    assert run.file_sorgente is None


def test_get_current_returns_none_outside_context():
    from core.pipeline_run import PipelineRun

    assert PipelineRun.get_current() is None


def test_get_current_returns_active_run_inside_context():
    from core.pipeline_run import PipelineRun

    with patch.object(PipelineRun, "_insert_final"):
        with PipelineRun("p1") as r1:
            assert PipelineRun.get_current() is r1


def test_get_current_handles_nested_contexts():
    from core.pipeline_run import PipelineRun

    with patch.object(PipelineRun, "_insert_final"):
        with PipelineRun("outer") as outer:
            assert PipelineRun.get_current() is outer
            with PipelineRun("inner") as inner:
                assert PipelineRun.get_current() is inner
            assert PipelineRun.get_current() is outer
        assert PipelineRun.get_current() is None
