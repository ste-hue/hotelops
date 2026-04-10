"""Tests for review alert logic and email rendering."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from reviews.alert import should_alert, render_alert_body
from reviews.email import render_weekly_report


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
    from reviews.alert import send_alerts

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

    with patch("reviews.email.send_email") as mock_send:
        alerted = send_alerts(rows, first_run_keys=first_run_keys)

    assert [r["review_hash"] for r in alerted] == ["h2"]
    assert mock_send.call_count == 1


def test_send_alerts_no_grace_window_when_key_not_first_run():
    """If key is NOT in first_run_keys, all negatives alert regardless of age."""
    from reviews.alert import send_alerts

    old_date = (date.today() - timedelta(days=30)).isoformat()
    rows = [{
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
    }]

    with patch("reviews.email.send_email") as mock_send:
        alerted = send_alerts(rows, first_run_keys=set())

    assert len(alerted) == 1
    assert mock_send.call_count == 1


def test_mark_alerts_sent_issues_parameterized_update():
    """mark_alerts_sent should run an UPDATE with parameterized hash list."""
    from reviews.alert import mark_alerts_sent

    fake_client = MagicMock()
    with patch("reviews.alert.bigquery.Client", return_value=fake_client):
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
    from reviews.alert import mark_alerts_sent

    fake_client = MagicMock()
    with patch("reviews.alert.bigquery.Client", return_value=fake_client):
        mark_alerts_sent([])

    assert not fake_client.query.called


def _make_buffer_error():
    from google.api_core.exceptions import BadRequest

    return BadRequest(
        "UPDATE or DELETE statement over table foo would affect rows "
        "in the streaming buffer, which is not supported"
    )


def test_mark_alerts_sent_retries_on_streaming_buffer_then_succeeds(tmp_path, monkeypatch):
    """First 2 attempts hit streaming buffer, 3rd succeeds — no pending file."""
    from reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])
    monkeypatch.setattr(
        alert_mod, "_PENDING_STATE_PATH", tmp_path / "pending.json"
    )

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

    with patch.object(alert_mod.bigquery, "Client", return_value=fake_client):
        alert_mod.mark_alerts_sent(["h1", "h2"])

    assert call_count["n"] == 3
    assert not (tmp_path / "pending.json").exists()


def test_mark_alerts_sent_persists_pending_after_all_retries_fail(tmp_path, monkeypatch):
    """All retries exhausted: hashes persisted to pending state file, no raise."""
    import json as _json
    from reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])
    state_path = tmp_path / "pending.json"
    monkeypatch.setattr(alert_mod, "_PENDING_STATE_PATH", state_path)

    fake_client = MagicMock()
    fake_client.query.side_effect = _make_buffer_error()

    with patch.object(alert_mod.bigquery, "Client", return_value=fake_client):
        # Must NOT raise — pending file is the graceful fallback
        alert_mod.mark_alerts_sent(["h1", "h2"])

    assert state_path.exists()
    data = _json.loads(state_path.read_text())
    assert sorted(data["hashes"]) == ["h1", "h2"]
    assert "last_updated" in data


def test_mark_alerts_sent_reraises_non_buffer_errors(tmp_path, monkeypatch):
    """Non-streaming-buffer errors propagate immediately (no retry, no pending)."""
    from reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_MARK_ALERTS_RETRY_DELAYS", [0, 0, 0])
    monkeypatch.setattr(
        alert_mod, "_PENDING_STATE_PATH", tmp_path / "pending.json"
    )

    fake_client = MagicMock()
    fake_client.query.side_effect = RuntimeError("some other failure")

    with patch.object(alert_mod.bigquery, "Client", return_value=fake_client):
        try:
            alert_mod.mark_alerts_sent(["h1"])
            raised = False
        except RuntimeError:
            raised = True

    assert raised is True
    assert not (tmp_path / "pending.json").exists()


def test_flush_pending_alert_flags_success_clears_state(tmp_path, monkeypatch):
    """On successful flush, state file is removed."""
    import json as _json
    from reviews import alert as alert_mod

    state_path = tmp_path / "pending.json"
    state_path.write_text(_json.dumps({"hashes": ["h1", "h2"], "last_updated": "x"}))
    monkeypatch.setattr(alert_mod, "_PENDING_STATE_PATH", state_path)

    fake_client = MagicMock()
    with patch.object(alert_mod.bigquery, "Client", return_value=fake_client):
        flushed = alert_mod.flush_pending_alert_flags()

    assert flushed == 2
    assert not state_path.exists()


def test_flush_pending_alert_flags_noop_when_no_state(tmp_path, monkeypatch):
    from reviews import alert as alert_mod

    monkeypatch.setattr(alert_mod, "_PENDING_STATE_PATH", tmp_path / "nope.json")
    flushed = alert_mod.flush_pending_alert_flags()
    assert flushed == 0


def test_flush_pending_alert_flags_keeps_state_if_buffer_still_blocking(
    tmp_path, monkeypatch
):
    """If the buffer is still blocking, state file stays intact for next run."""
    import json as _json
    from reviews import alert as alert_mod

    state_path = tmp_path / "pending.json"
    state_path.write_text(_json.dumps({"hashes": ["h1"], "last_updated": "x"}))
    monkeypatch.setattr(alert_mod, "_PENDING_STATE_PATH", state_path)

    fake_client = MagicMock()
    fake_client.query.side_effect = _make_buffer_error()

    with patch.object(alert_mod.bigquery, "Client", return_value=fake_client):
        flushed = alert_mod.flush_pending_alert_flags()

    assert flushed == 0
    assert state_path.exists()  # preserved for next attempt


def test_persist_pending_merges_with_existing(tmp_path, monkeypatch):
    """Repeated failures merge hashes, never lose old ones."""
    import json as _json
    from reviews import alert as alert_mod

    state_path = tmp_path / "pending.json"
    monkeypatch.setattr(alert_mod, "_PENDING_STATE_PATH", state_path)

    alert_mod._persist_pending(["h1", "h2"])
    alert_mod._persist_pending(["h2", "h3"])

    data = _json.loads(state_path.read_text())
    assert sorted(data["hashes"]) == ["h1", "h2", "h3"]
