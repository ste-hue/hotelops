"""Tests for PipelineRun context manager.

Observability Layer 2: records a row per pipeline execution in f_pipeline_runs.
All BQ interactions are best-effort — the pipeline must complete even if
the observability writes fail.
"""

import json
from unittest.mock import MagicMock, patch


class TestPipelineRun:
    def test_generates_uuid_on_enter(self):
        from core.pipeline_run import PipelineRun

        with patch("google.cloud.bigquery.Client") as mock_client:
            mock_client.return_value = MagicMock()
            with PipelineRun("test") as run:
                assert len(run.run_id) == 36  # UUID format
                assert run.status == "RUNNING"
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

    def test_inserts_running_row_on_enter(self):
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            with PipelineRun("test"):
                pass

        assert fake_client.insert_rows_json.called
        insert_call = fake_client.insert_rows_json.call_args
        row = insert_call.args[1][0]
        assert row["status"] == "RUNNING"
        assert row["pipeline_name"] == "test"

    def test_updates_final_row_on_exit(self):
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            with PipelineRun("test") as run:
                run.rows_new = 5

        assert fake_client.query.called
        sql = fake_client.query.call_args.args[0]
        assert "UPDATE" in sql
        assert "status = @status" in sql

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

    def test_bq_failure_on_enter_does_not_raise(self):
        """Observability must never break the pipeline."""
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.side_effect = RuntimeError("BQ down")
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            # Must NOT raise
            with PipelineRun("test") as run:
                run.rows_found = 10
            assert run.status == "OK"

    def test_bq_failure_on_exit_does_not_raise(self):
        from core.pipeline_run import PipelineRun

        fake_client = MagicMock()
        fake_client.insert_rows_json.return_value = []
        fake_client.query.side_effect = RuntimeError("BQ down on UPDATE")
        with patch("google.cloud.bigquery.Client", return_value=fake_client):
            with PipelineRun("test") as run:
                run.rows_found = 10
            # No exception propagated
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
