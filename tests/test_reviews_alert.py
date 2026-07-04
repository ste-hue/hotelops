"""Tests for review alert logic and email rendering."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from verticals.reviews.alert import should_alert, render_alert_body
from verticals.reviews.email import render_weekly_report


@pytest.fixture(autouse=True)
def _reset_bq_client_singleton():
    """Clear the cached BQ client so each test's patch is honoured."""
    import core.bq.client as bq_client_mod

    bq_client_mod._client = None
    yield
    bq_client_mod._client = None


def test_should_alert_negative():
    row = {"punteggio_norm": 4.0, "alert_inviato": False}
    assert should_alert(row) is True


def test_should_alert_threshold_boundary():
    row = {"punteggio_norm": 6.0, "alert_inviato": False}
    assert should_alert(row) is True


def test_should_not_alert_positive():
    row = {"punteggio_norm": 8.0, "alert_inviato": False}
    assert should_alert(row) is False


def test_should_not_alert_already_sent():
    row = {"punteggio_norm": 3.0, "alert_inviato": True}
    assert should_alert(row) is False


def test_render_alert_body():
    row = {
        "piattaforma": "BOOKING",
        "business_unit_id": "HOTEL",
        "punteggio_raw": 4.0,
        "punteggio_norm": 4.0,
        "data_review": "2026-04-01",
        "categoria_nlp": "PULIZIA",
        "reviewer_nome": "Mario R.",
        "reviewer_paese": "IT",
        "riassunto_nlp": "Camera sporca al check-in.",
        "testo": "La camera era sporca, bagno con muffa.",
        "url_review": "https://booking.com/review/001",
    }
    body = render_alert_body(row)
    assert "BOOKING" in body
    assert "HOTEL" in body
    assert "PULIZIA" in body
    assert "Camera sporca" in body
    assert "booking.com/review/001" in body


def test_render_weekly_report():
    rows = [
        {
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 4.0,
            "punteggio_raw": 4.0,
            "categoria_nlp": "PULIZIA",
            "sentiment_nlp": "NEGATIVO",
            "riassunto_nlp": "Sporco.",
            "data_review": "2026-04-01",
        },
        {
            "piattaforma": "GOOGLE",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 9.0,
            "punteggio_raw": 4.5,
            "categoria_nlp": "STAFF",
            "sentiment_nlp": "POSITIVO",
            "riassunto_nlp": "Personale gentile.",
            "data_review": "2026-04-02",
        },
    ]
    html = render_weekly_report(rows, "2026-03-31", "2026-04-06")
    assert "BOOKING" in html
    assert "GOOGLE" in html
    assert "6.5" in html  # average of 4.0 and 9.0
    assert "1" in html  # 1 negative


def test_send_alerts_applies_grace_window_for_first_run_keys():
    """Reviews older than 7 days for a first-run key should NOT alert."""
    from verticals.reviews.alert import send_alerts

    today = date.today()
    old_date = (today - timedelta(days=30)).isoformat()
    recent_date = (today - timedelta(days=2)).isoformat()

    rows = [
        {
            "review_hash": "h1",
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 4.0,
            "punteggio_raw": 4.0,
            "data_review": old_date,
            "categoria_nlp": None,
            "reviewer_nome": "X",
            "reviewer_paese": None,
            "riassunto_nlp": None,
            "testo": "",
            "url_review": None,
            "alert_inviato": False,
        },
        {
            "review_hash": "h2",
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 4.0,
            "punteggio_raw": 4.0,
            "data_review": recent_date,
            "categoria_nlp": None,
            "reviewer_nome": "Y",
            "reviewer_paese": None,
            "riassunto_nlp": None,
            "testo": "",
            "url_review": None,
            "alert_inviato": False,
        },
    ]
    first_run_keys = {("BOOKING", "HOTEL")}

    with patch("verticals.reviews.email.send_email") as mock_send:
        alerted = send_alerts(rows, first_run_keys=first_run_keys)

    assert [r["review_hash"] for r in alerted] == ["h2"]
    assert mock_send.call_count == 1


def test_send_alerts_no_grace_window_when_key_not_first_run():
    """If key is NOT in first_run_keys, all negatives alert regardless of age."""
    from verticals.reviews.alert import send_alerts

    old_date = (date.today() - timedelta(days=30)).isoformat()
    rows = [
        {
            "review_hash": "h1",
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 4.0,
            "punteggio_raw": 4.0,
            "data_review": old_date,
            "categoria_nlp": None,
            "reviewer_nome": "X",
            "reviewer_paese": None,
            "riassunto_nlp": None,
            "testo": "",
            "url_review": None,
            "alert_inviato": False,
        }
    ]

    with patch("verticals.reviews.email.send_email") as mock_send:
        alerted = send_alerts(rows, first_run_keys=set())

    assert len(alerted) == 1
    assert mock_send.call_count == 1


def test_mark_alerts_sent_issues_parameterized_update():
    """mark_alerts_sent should run an UPDATE with parameterized hash list."""
    from verticals.reviews.alert import mark_alerts_sent

    fake_client = MagicMock()
    with patch("verticals.reviews.alert.bigquery.Client", return_value=fake_client):
        mark_alerts_sent(["h1", "h2", "h3"])

    assert fake_client.query.called
    call = fake_client.query.call_args
    sql = call.args[0]
    assert "UPDATE" in sql
    assert "alert_inviato = TRUE" in sql
    # parameterized, not string-interpolated
    assert "h1" not in sql
    job_config = call.kwargs["job_config"]
    params = job_config.query_parameters
    assert params[0].name == "hashes"
    assert params[0].values == ["h1", "h2", "h3"]


def test_mark_alerts_sent_noop_on_empty_list():
    from verticals.reviews.alert import mark_alerts_sent

    fake_client = MagicMock()
    with patch("verticals.reviews.alert.bigquery.Client", return_value=fake_client):
        mark_alerts_sent([])

    assert not fake_client.query.called


def _make_buffer_error():
    from google.api_core.exceptions import BadRequest

    return BadRequest(
        "UPDATE or DELETE statement over table foo would affect rows "
        "in the streaming buffer, which is not supported"
    )


def test_mark_alerts_sent_retries_on_streaming_buffer_then_succeeds(monkeypatch):
    """First 2 attempts hit streaming buffer, 3rd succeeds — no pending write."""
    from verticals.reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])

    fake_client = MagicMock()
    fake_query = MagicMock()
    fake_client.query.return_value = fake_query

    call_count = {"n": 0}

    def query_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _make_buffer_error()
        return fake_query

    fake_client.query.side_effect = query_side_effect

    with (
        patch.object(alert_mod.bigquery, "Client", return_value=fake_client),
        patch.object(alert_mod, "append_pending_flags") as mock_append,
    ):
        alert_mod.mark_alerts_sent(["h1", "h2"])

    assert call_count["n"] == 3
    mock_append.assert_not_called()


def test_mark_alerts_sent_persists_pending_after_all_retries_fail(monkeypatch):
    """All retries exhausted: hashes persisted to pending state in BQ."""
    from verticals.reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])

    fake_client = MagicMock()
    fake_client.query.side_effect = _make_buffer_error()

    with (
        patch.object(alert_mod.bigquery, "Client", return_value=fake_client),
        patch.object(alert_mod, "append_pending_flags", return_value=2) as mock_append,
        patch.object(alert_mod, "read_pending_flags", return_value=["h1", "h2"]),
    ):
        alert_mod.mark_alerts_sent(["h1", "h2"])

    mock_append.assert_called_once()
    assert sorted(mock_append.call_args.args[0]) == ["h1", "h2"]


def test_mark_alerts_sent_reraises_non_buffer_errors(monkeypatch):
    """Non-streaming-buffer errors propagate immediately (no retry, no pending write)."""
    from verticals.reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])

    fake_client = MagicMock()
    fake_client.query.side_effect = RuntimeError("some other failure")

    with (
        patch.object(alert_mod.bigquery, "Client", return_value=fake_client),
        patch.object(alert_mod, "append_pending_flags") as mock_append,
    ):
        with pytest.raises(RuntimeError):
            alert_mod.mark_alerts_sent(["h1"])

    mock_append.assert_not_called()


def test_flush_pending_alert_flags_success_clears_state(monkeypatch):
    """On successful flush, pending hashes are cleared from BQ state."""
    from verticals.reviews import alert as alert_mod

    fake_client = MagicMock()
    with (
        patch.object(alert_mod.bigquery, "Client", return_value=fake_client),
        patch.object(alert_mod, "read_pending_flags", return_value=["h1", "h2"]),
        patch.object(alert_mod, "clear_pending_flags", return_value=2) as mock_clear,
    ):
        flushed = alert_mod.flush_pending_alert_flags()

    assert flushed == 2
    mock_clear.assert_called_once_with(["h1", "h2"])


def test_flush_pending_alert_flags_noop_when_no_state(monkeypatch):
    from verticals.reviews import alert as alert_mod

    with patch.object(alert_mod, "read_pending_flags", return_value=[]):
        flushed = alert_mod.flush_pending_alert_flags()
    assert flushed == 0


def test_flush_pending_alert_flags_keeps_state_if_buffer_still_blocking(monkeypatch):
    """If the buffer is still blocking, pending hashes stay for next run."""
    from verticals.reviews import alert as alert_mod

    fake_client = MagicMock()
    fake_client.query.side_effect = _make_buffer_error()

    with (
        patch.object(alert_mod.bigquery, "Client", return_value=fake_client),
        patch.object(alert_mod, "read_pending_flags", return_value=["h1"]),
        patch.object(alert_mod, "clear_pending_flags") as mock_clear,
    ):
        flushed = alert_mod.flush_pending_alert_flags()

    assert flushed == 0
    mock_clear.assert_not_called()


def test_weekly_report_renders_cost_section_when_data_present():
    """Cost section must render when _fetch_apify_costs returns rows."""
    from verticals.reviews.email import render_weekly_report

    fake_costs = [
        {
            "piattaforma": "BOOKING",
            "n_runs": 3,
            "n_items": 45,
            "cost_usd": 0.2250,
            "n_cap_violated": 0,
        },
        {
            "piattaforma": "EXPEDIA",
            "n_runs": 3,
            "n_items": 12,
            "cost_usd": 0.0600,
            "n_cap_violated": 1,
        },
    ]
    with patch("verticals.reviews.email._fetch_apify_costs", return_value=fake_costs):
        html = render_weekly_report(
            rows=[], date_start="2026-04-06", date_end="2026-04-12"
        )

    assert "Costi Apify" in html
    assert "$0.2850" in html  # total cost = 0.225 + 0.06
    assert "BOOKING" in html
    assert "EXPEDIA" in html
    # Cap violations are highlighted
    assert "Cap violati" in html


def test_weekly_report_omits_cost_section_when_no_data():
    """Cost section is silent when _fetch_apify_costs returns empty."""
    from verticals.reviews.email import render_weekly_report

    with patch("verticals.reviews.email._fetch_apify_costs", return_value=[]):
        html = render_weekly_report(
            rows=[], date_start="2026-04-06", date_end="2026-04-12"
        )

    assert "Costi Apify" not in html


def test_persist_pending_stores_run_id_when_available():
    """Pending persistence should include active run_id metadata when present."""
    from verticals.reviews import alert as alert_mod

    run = MagicMock()
    run.run_id = "run-123"
    with (
        patch.object(alert_mod, "append_pending_flags", return_value=2) as mock_append,
        patch.object(alert_mod, "read_pending_flags", return_value=["h1", "h2"]),
        patch("core.pipeline_run.PipelineRun.get_current", return_value=run),
    ):
        alert_mod._persist_pending(["h1", "h2"])

    assert mock_append.call_count == 1
    assert mock_append.call_args.kwargs["run_id"] == "run-123"
