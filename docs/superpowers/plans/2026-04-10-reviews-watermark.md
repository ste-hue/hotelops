# Reviews Watermark-Driven Scraping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `alert_inviato` dead-column bug by introducing a watermark gate (`MAX(data_review) GROUP BY piattaforma, business_unit_id`) in the reviews pipeline, and persist the alert flag to BigQuery after email send.

**Architecture:** A pure `filter_by_watermark()` function drops already-seen reviews in `reviews/ingest.py` before classify/load. `alert.py` gains a `mark_alerts_sent()` UPDATE helper and a grace window for first-run keys. A gap-detection email is sent when any `(piattaforma, bu)` returns `len(kept) == cap`. No new BQ tables.

**Tech Stack:** Python 3.11, google-cloud-bigquery (parameterized queries), pytest.

**Spec:** `docs/superpowers/specs/2026-04-10-reviews-watermark-design.md`

---

## File Structure

**Create:**
- `tests/test_reviews_watermark.py` — unit tests for `filter_by_watermark`, `read_watermarks` (mocked BQ)
- `docs/adr/0003-reviews-watermark-driven-scraping.md` — ADR

**Modify:**
- `reviews/ingest.py` — add `read_watermarks()`, `filter_by_watermark()`
- `reviews/alert.py` — add `mark_alerts_sent()`, add grace-window parameter to `send_alerts()`, add `send_gap_alert()`
- `reviews/cli_commands.py:_cmd_scrape` — rewire pipeline order: read watermark → scrape → normalize → filter → classify → load → alert → mark → gap mail
- `tests/test_reviews_alert.py` — add tests for grace window, `mark_alerts_sent`
- `docs/procedures/reviews_pipeline.md` — bump `last_verified`, mark 🔴 `alert_inviato` as resolved, document watermark behavior

---

## Task 1: Apify actor reconnaissance (no code)

**Files:** None (research output goes in runbook update later)

- [ ] **Step 1: Check Apify README for each actor**

For each actor, open its README on Apify Store and look for parameters
like `reviewsStartDate`, `sinceDate`, `minDate`, `dateFrom`, `startDate`:

- `voyager/booking-reviews-scraper`
- `maxcopell/tripadvisor-reviews`
- `compass/Google-Maps-Reviews-Scraper`
- `memo23/expedia-scraper`

- [ ] **Step 2: Record findings in a scratch file**

Write results to `/tmp/apify-date-params.md` with one line per actor:
`<actor>: <param_name or "NONE FOUND">`.

This drives whether we pass a server-side date filter in Task 7.
If all four say NONE FOUND, we do pure client-side filtering and
that's fine — the spec explicitly covers both paths.

- [ ] **Step 3: No commit (scratch file, ephemeral)**

---

## Task 2: `filter_by_watermark` pure function — failing test

**Files:**
- Create: `tests/test_reviews_watermark.py`

- [ ] **Step 1: Write the failing test file**

```python
"""Tests for watermark-based review filtering."""

from reviews.ingest import filter_by_watermark


def _item(piattaforma, bu, data_review, review_id="x"):
    return {
        "piattaforma": piattaforma,
        "business_unit_id": bu,
        "data_review": data_review,
        "review_id": review_id,
        "punteggio_norm": 8.0,
    }


def test_filter_empty_watermark_keeps_all():
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05", "a"),
        _item("BOOKING", "HOTEL", "2026-03-01", "b"),
    ]
    kept, gap_keys = filter_by_watermark({}, items, cap=15)
    assert len(kept) == 2
    assert gap_keys == []


def test_filter_drops_items_at_or_before_watermark():
    watermarks = {("BOOKING", "HOTEL"): "2026-04-01"}
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05", "new"),
        _item("BOOKING", "HOTEL", "2026-04-01", "boundary"),  # equal → drop
        _item("BOOKING", "HOTEL", "2026-03-15", "old"),
    ]
    kept, _ = filter_by_watermark(watermarks, items, cap=15)
    assert [k["review_id"] for k in kept] == ["new"]


def test_filter_unknown_key_keeps_all_for_that_key():
    watermarks = {("BOOKING", "HOTEL"): "2026-04-01"}
    items = [
        _item("GOOGLE", "HOTEL", "2024-01-01", "g1"),  # no watermark for GOOGLE
    ]
    kept, _ = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 1


def test_filter_drops_malformed_date():
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05T12:00Z", "bad"),
        _item("BOOKING", "HOTEL", "", "empty"),
        _item("BOOKING", "HOTEL", "2026-04-05", "good"),
    ]
    kept, _ = filter_by_watermark({}, items, cap=15)
    assert [k["review_id"] for k in kept] == ["good"]


def test_filter_gap_detection_when_all_items_new():
    watermarks = {("BOOKING", "HOTEL"): "2026-03-01"}
    items = [_item("BOOKING", "HOTEL", f"2026-04-{i:02d}", str(i)) for i in range(1, 16)]
    assert len(items) == 15
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 15
    assert gap_keys == [("BOOKING", "HOTEL")]


def test_filter_no_gap_when_below_cap():
    watermarks = {("BOOKING", "HOTEL"): "2026-03-01"}
    items = [_item("BOOKING", "HOTEL", f"2026-04-{i:02d}", str(i)) for i in range(1, 15)]
    assert len(items) == 14
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 14
    assert gap_keys == []


def test_filter_multiple_keys_independent_gap():
    watermarks = {
        ("BOOKING", "HOTEL"): "2026-03-01",
        ("GOOGLE", "HOTEL"): "2026-03-01",
    }
    items = (
        [_item("BOOKING", "HOTEL", f"2026-04-{i:02d}", f"b{i}") for i in range(1, 16)]
        + [_item("GOOGLE", "HOTEL", "2026-04-05", "g1")]
    )
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 16
    assert gap_keys == [("BOOKING", "HOTEL")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reviews_watermark.py -v`
Expected: `ImportError` or `AttributeError` — `filter_by_watermark` does not exist.

---

## Task 3: Implement `filter_by_watermark`

**Files:**
- Modify: `reviews/ingest.py`

- [ ] **Step 1: Add the function at the bottom of `reviews/ingest.py` (after `dedup_reviews`)**

```python
import re

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def filter_by_watermark(
    watermarks: dict[tuple[str, str], str],
    items: list[dict],
    cap: int,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Drop items with data_review <= watermark for their (piattaforma, bu) key.

    Args:
        watermarks: dict (piattaforma, business_unit_id) -> 'YYYY-MM-DD'.
                    Missing key means no watermark → all items for that key pass.
        items: normalized review dicts.
        cap: per-key cap used to detect suspected gaps.

    Returns:
        (kept_items, gap_keys). gap_keys lists (piattaforma, bu) pairs where
        len(kept) == cap — possible gap, caller should emit a warning email.

    Malformed data_review (not YYYY-MM-DD) is dropped with a warning log.
    Pure function; no BQ access.
    """
    kept: list[dict] = []
    per_key_count: dict[tuple[str, str], int] = {}
    dropped_malformed = 0

    for item in items:
        data = item.get("data_review") or ""
        if not _ISO_DATE.match(data):
            dropped_malformed += 1
            continue

        key = (item.get("piattaforma"), item.get("business_unit_id"))
        wm = watermarks.get(key)
        if wm is not None and data <= wm:
            continue

        kept.append(item)
        per_key_count[key] = per_key_count.get(key, 0) + 1

    if dropped_malformed:
        log.warning(
            "filter_by_watermark: dropped %d items with malformed data_review",
            dropped_malformed,
        )

    gap_keys = [k for k, n in per_key_count.items() if n == cap]
    return kept, gap_keys
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_reviews_watermark.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add reviews/ingest.py tests/test_reviews_watermark.py
git commit -m "feat(reviews): filter_by_watermark pure function + unit tests"
```

---

## Task 4: `read_watermarks` with malformed-row logging — failing test

**Files:**
- Modify: `tests/test_reviews_watermark.py`

- [ ] **Step 1: Append failing test**

```python
from unittest.mock import MagicMock, patch


def test_read_watermarks_returns_dict(monkeypatch):
    fake_client = MagicMock()

    # First query: watermarks
    watermark_rows = [
        MagicMock(piattaforma="BOOKING", business_unit_id="HOTEL", watermark="2026-04-06"),
        MagicMock(piattaforma="GOOGLE", business_unit_id="HOTEL", watermark="2026-03-03"),
    ]
    # Second query: malformed count
    malformed_rows = [
        MagicMock(piattaforma="GOOGLE", n_malformed=42),
    ]

    fake_client.query.side_effect = [
        MagicMock(result=MagicMock(return_value=iter(watermark_rows))),
        MagicMock(result=MagicMock(return_value=iter(malformed_rows))),
    ]

    with patch("reviews.ingest.bigquery.Client", return_value=fake_client):
        from reviews.ingest import read_watermarks
        result = read_watermarks()

    assert result == {
        ("BOOKING", "HOTEL"): "2026-04-06",
        ("GOOGLE", "HOTEL"): "2026-03-03",
    }
    # Two queries issued: watermark + malformed audit
    assert fake_client.query.call_count == 2


def test_read_watermarks_empty(monkeypatch):
    fake_client = MagicMock()
    fake_client.query.side_effect = [
        MagicMock(result=MagicMock(return_value=iter([]))),
        MagicMock(result=MagicMock(return_value=iter([]))),
    ]
    with patch("reviews.ingest.bigquery.Client", return_value=fake_client):
        from reviews.ingest import read_watermarks
        assert read_watermarks() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reviews_watermark.py::test_read_watermarks_returns_dict -v`
Expected: FAIL — `read_watermarks` does not exist, or `reviews.ingest.bigquery` not imported at module level.

---

## Task 5: Implement `read_watermarks`

**Files:**
- Modify: `reviews/ingest.py`

- [ ] **Step 1: Add module-level bigquery import at top of `reviews/ingest.py`**

Find the existing imports (line 1-10) and add:

```python
from google.cloud import bigquery
```

Also remove the `from google.cloud import bigquery` line inside `load_to_bq` (it's
now at module level).

- [ ] **Step 2: Add `read_watermarks` function (after `filter_by_watermark`)**

```python
def read_watermarks() -> dict[tuple[str, str], str]:
    """Read per-(piattaforma, business_unit_id) watermark from f_reviews.

    Watermark = MAX(data_review) filtered by LENGTH(data_review)=10 to guard
    against format drift (the pre-fix Google rows with ISO timestamps).
    Also issues a second audit query to log how many rows are excluded by
    the LENGTH guard, so the drift stays visible until backfill.

    Raises on BQ error — caller must abort the run (never proceed with an
    involuntarily empty watermark).
    """
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)

    wm_sql = f"""
    SELECT piattaforma, business_unit_id, MAX(data_review) AS watermark
    FROM `{F_REVIEWS}`
    WHERE LENGTH(data_review) = 10
    GROUP BY piattaforma, business_unit_id
    """
    result = {
        (row.piattaforma, row.business_unit_id): row.watermark
        for row in client.query(wm_sql).result()
    }

    audit_sql = f"""
    SELECT piattaforma, COUNT(*) AS n_malformed
    FROM `{F_REVIEWS}`
    WHERE LENGTH(data_review) <> 10
    GROUP BY piattaforma
    """
    for row in client.query(audit_sql).result():
        log.warning(
            "WATERMARK EXCLUDED %d malformed data_review rows on %s",
            row.n_malformed,
            row.piattaforma,
        )

    log.info("read_watermarks: %d keys", len(result))
    return result
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_reviews_watermark.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add reviews/ingest.py tests/test_reviews_watermark.py
git commit -m "feat(reviews): read_watermarks with malformed-row audit logging"
```

---

## Task 6: `mark_alerts_sent` + grace window for first-run keys — failing tests

**Files:**
- Modify: `tests/test_reviews_alert.py`

- [ ] **Step 1: Append failing tests**

```python
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


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

    with patch("reviews.alert.send_email") as mock_send:
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

    with patch("reviews.alert.send_email") as mock_send:
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews_alert.py -v -k "grace_window or mark_alerts_sent"`
Expected: FAIL — `first_run_keys` parameter not supported, `mark_alerts_sent` missing.

---

## Task 7: Implement `mark_alerts_sent`, grace window, and `send_gap_alert`

**Files:**
- Modify: `reviews/alert.py`

- [ ] **Step 1: Rewrite `reviews/alert.py`**

Full new content (replaces the file):

```python
"""Email alerts for negative reviews."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from google.cloud import bigquery

from reviews.config import ALERT_THRESHOLD, ALERT_RECIPIENTS

log = logging.getLogger(__name__)

GRACE_WINDOW_DAYS = 7


def should_alert(row: dict) -> bool:
    """Return True if this review should trigger an alert."""
    if row.get("alert_inviato"):
        return False
    return row.get("punteggio_norm", 10.0) <= ALERT_THRESHOLD


def _within_grace_window(row: dict, today: date | None = None) -> bool:
    today = today or date.today()
    cutoff = (today - timedelta(days=GRACE_WINDOW_DAYS)).isoformat()
    return (row.get("data_review") or "") >= cutoff


def render_alert_body(row: dict) -> str:
    """Render plain-text email body for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return f"""Review negativa ricevuta

Piattaforma: {row["piattaforma"]}
Struttura: {row["business_unit_id"]}
Punteggio: {row["punteggio_raw"]}/{scala}
Data review: {row["data_review"]}
Categoria: {row.get("categoria_nlp") or "N/A"}
Reviewer: {row.get("reviewer_nome") or "Anonimo"} ({row.get("reviewer_paese") or "?"})

Riassunto: {row.get("riassunto_nlp") or "N/A"}

Testo completo:
{row.get("testo", "")}

Link: {row.get("url_review") or "N/A"}
"""


def render_alert_subject(row: dict) -> str:
    """Render email subject line for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return (
        f"Review negativa — {row['business_unit_id']} — "
        f"{row['piattaforma']} — {row['punteggio_raw']}/{scala}"
    )


def send_alerts(
    rows: list[dict],
    first_run_keys: set[tuple[str, str]] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Send email alerts for negative reviews.

    Args:
        rows: reviews to consider (should already be filtered to "new" by
              the watermark gate — this function does NOT re-filter by hash).
        first_run_keys: set of (piattaforma, business_unit_id) that had no
              pre-existing watermark. For these keys, a 7-day grace window
              is applied to avoid spamming historical reviews at seed time.
        dry_run: don't actually send.

    Returns: list of alerted rows. Caller is responsible for calling
    mark_alerts_sent() with the hashes of the returned rows.
    """
    from reviews.email import send_email

    first_run_keys = first_run_keys or set()

    alerted = []
    for row in rows:
        if not should_alert(row):
            continue

        key = (row.get("piattaforma"), row.get("business_unit_id"))
        if key in first_run_keys and not _within_grace_window(row):
            log.info(
                "Grace window: skipping alert for %s %s (first-run, data_review=%s)",
                key[0], key[1], row.get("data_review"),
            )
            continue

        subject = render_alert_subject(row)
        body = render_alert_body(row)

        if dry_run:
            log.info("[DRY RUN] Would send alert: %s", subject)
        else:
            send_email(to=ALERT_RECIPIENTS, subject=subject, body=body)
            log.info("Alert sent: %s", subject)

        alerted.append(row)

    return alerted


def mark_alerts_sent(review_hashes: list[str]) -> None:
    """UPDATE f_reviews SET alert_inviato=TRUE for the given hashes.

    Uses a parameterized ARRAY query (never string interpolation).
    No-op if the list is empty.
    """
    if not review_hashes:
        return

    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    UPDATE `{F_REVIEWS}`
    SET alert_inviato = TRUE
    WHERE review_hash IN UNNEST(@hashes)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hashes", "STRING", review_hashes),
        ]
    )
    client.query(sql, job_config=job_config).result()
    log.info("mark_alerts_sent: flagged %d reviews", len(review_hashes))


def send_gap_alert(gap_keys: list[tuple[str, str]], dry_run: bool = False) -> None:
    """Send a single summary email when one or more (piattaforma, bu) pairs
    returned a full cap of new reviews (possible gap beyond the 16th item).
    """
    if not gap_keys:
        return

    from reviews.email import send_email

    lines = [f"- {p} / {bu}" for p, bu in gap_keys]
    body = (
        "Gap sospetto nella pipeline reviews: per le seguenti piattaforme/BU "
        "l'actor ha restituito un cap pieno di nuove review, potrebbero "
        "esserci review più vecchie del 16° elemento non catturate.\n\n"
        + "\n".join(lines)
        + "\n\nValutare un rilancio manuale con cap più alto."
    )
    subject = f"[hotelops] GAP SUSPECTED reviews — {len(gap_keys)} chiavi"

    if dry_run:
        log.info("[DRY RUN] Would send gap alert: %s", subject)
    else:
        send_email(to=ALERT_RECIPIENTS, subject=subject, body=body)
        log.warning("Gap alert sent: %s", subject)
```

- [ ] **Step 2: Run alert tests**

Run: `pytest tests/test_reviews_alert.py -v`
Expected: all tests PASS (existing ones still work, new ones pass).

- [ ] **Step 3: Commit**

```bash
git add reviews/alert.py tests/test_reviews_alert.py
git commit -m "feat(reviews): mark_alerts_sent + grace window + gap mail"
```

---

## Task 8: Rewire `_cmd_scrape` pipeline

**Files:**
- Modify: `reviews/cli_commands.py`

- [ ] **Step 1: Replace the body of `_cmd_scrape`**

Find the function in `reviews/cli_commands.py` (around line 63) and replace
its body (keep the signature):

```python
def _cmd_scrape(args):
    """Trigger manual scrape. Watermark-gated pipeline."""
    from reviews.scrape import scrape_platform, scrape_all
    from reviews.ingest import (
        normalize_items,
        dedup_reviews,
        load_to_bq,
        read_watermarks,
        filter_by_watermark,
    )
    from reviews.classify import classify_reviews
    from reviews.alert import send_alerts, mark_alerts_sent, send_gap_alert
    from reviews.config import MAX_REVIEWS_PER_PROPERTY

    platform = args.only.upper() if args.only else None

    print(f"\n  Scraping {'all platforms' if not platform else platform}...")

    # 1. Read watermarks BEFORE scraping (if read fails, abort)
    if args.dry_run:
        watermarks = {}
    else:
        try:
            watermarks = read_watermarks()
        except Exception as e:
            print(f"  ABORT: read_watermarks failed: {e}")
            raise

    # 2. Scrape
    if platform:
        raw = scrape_platform(platform, dry_run=args.dry_run)
    else:
        raw = scrape_all(dry_run=args.dry_run)

    if args.dry_run:
        print(f"  [DRY RUN] Would process {len(raw)} raw items")
        return

    print(f"  Collected {len(raw)} raw items")

    # 3. Normalize
    rows = normalize_items(raw)
    rows = dedup_reviews(rows)
    print(f"  Normalized: {len(rows)} unique reviews")

    # 4. Watermark filter — drop already-seen, detect gaps
    #    Track which keys were first-run (watermark was None) BEFORE filtering.
    present_keys = {(r["piattaforma"], r["business_unit_id"]) for r in rows}
    first_run_keys = {k for k in present_keys if k not in watermarks}

    new_rows, gap_keys = filter_by_watermark(
        watermarks, rows, cap=MAX_REVIEWS_PER_PROPERTY
    )
    print(f"  Watermark filter: {len(new_rows)} new (dropped {len(rows) - len(new_rows)})")
    if gap_keys:
        print(f"  ⚠️  Gap suspected on: {gap_keys}")

    if not new_rows:
        print("  No new reviews; skipping classify/load/alert.")
        if gap_keys:
            send_gap_alert(gap_keys)
        return

    # 5. Classify (only new)
    new_rows = classify_reviews(new_rows)
    print(f"  Classified: {len(new_rows)} reviews")

    # 6. Load to BQ
    inserted = load_to_bq(new_rows)
    print(f"  Loaded to BQ: {inserted} new reviews")

    # 7. Send alerts (only on new, with grace window for first-run keys)
    alerted = send_alerts(new_rows, first_run_keys=first_run_keys)
    print(f"  Alerts sent: {len(alerted)}")

    # 8. Persist alert flag
    if alerted:
        mark_alerts_sent([r["review_hash"] for r in alerted])
        print(f"  alert_inviato flagged on {len(alerted)} rows")

    # 9. Gap mail (if any)
    if gap_keys:
        send_gap_alert(gap_keys)
```

- [ ] **Step 2: Smoke test the module imports**

Run: `python -c "from reviews import cli_commands"`
Expected: no ImportError.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/test_reviews_watermark.py tests/test_reviews_alert.py tests/test_reviews_ingest.py tests/test_reviews_classify.py tests/test_reviews_schema_sync.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add reviews/cli_commands.py
git commit -m "feat(reviews): rewire _cmd_scrape through watermark gate"
```

---

## Task 9: Regression test — old negative review does not re-alert

**Files:**
- Modify: `tests/test_reviews_watermark.py`

- [ ] **Step 1: Add regression test**

Append to `tests/test_reviews_watermark.py`:

```python
def test_regression_old_negative_review_blocked_by_watermark():
    """
    Bug 2026-04-10: alert.py sent mail for a Zuzana review from Jul 2025
    because alert_inviato was never persisted. With the watermark gate,
    an old negative review already in f_reviews (reflected in the
    watermark) must NOT be re-alerted.
    """
    from reviews.ingest import filter_by_watermark

    # watermark says "we've seen up to 2026-04-06 on BOOKING/HOTEL"
    watermarks = {("BOOKING", "HOTEL"): "2026-04-06"}

    # actor re-returns an old negative review (pre-watermark)
    items = [
        {
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "data_review": "2025-07-15",
            "review_id": "zuzana",
            "punteggio_norm": 4.0,
        }
    ]

    kept, _ = filter_by_watermark(watermarks, items, cap=15)
    assert kept == []  # blocked — no alert possible downstream
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_reviews_watermark.py::test_regression_old_negative_review_blocked_by_watermark -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reviews_watermark.py
git commit -m "test(reviews): regression for stale negative review alert bug"
```

---

## Task 10: Update runbook + write ADR

**Files:**
- Modify: `docs/procedures/reviews_pipeline.md`
- Create: `docs/adr/0003-reviews-watermark-driven-scraping.md`

- [ ] **Step 1: Update `docs/procedures/reviews_pipeline.md`**

Change the YAML front-matter `last_verified` to today's date (2026-04-10).

In the "Bug noti / debt" section, replace the 🔴 `alert_inviato` block with:

```markdown
### ✅ `alert_inviato` — RISOLTO 2026-04-10
Risolto introducendo `mark_alerts_sent()` in `alert.py` che esegue
`UPDATE f_reviews SET alert_inviato=TRUE WHERE review_hash IN UNNEST(@hashes)`
dopo ogni mail inviata con successo. Oltre al flag, la pipeline ora ha
un watermark gate (`MAX(data_review)` per `(piattaforma, business_unit_id)`)
che droppa le review già viste prima ancora di arrivare all'alert.
Vedi ADR 0003 e `docs/superpowers/specs/2026-04-10-reviews-watermark-design.md`.
```

Append a new section after "Parametri attuali":

```markdown
## Watermark gate (2026-04-10+)

Pipeline `hotelops reviews --scrape`:

1. `read_watermarks()` → dict (piattaforma, bu) → MAX(data_review)
2. scrape (cap 15/property)
3. `normalize_items` → `dedup_reviews`
4. `filter_by_watermark` → droppa items ≤ watermark, detecta gap se `kept==15`
5. Se 0 nuove → skip classify/load/alert
6. `classify_reviews` → Claude Haiku (solo nuove)
7. `load_to_bq`
8. `send_alerts` con grace window 7gg per prime run
9. `mark_alerts_sent` → UPDATE BQ
10. `send_gap_alert` → mail riepilogativa se gap rilevato

**Gap detection**: quando `len(kept) == cap` per una chiave, potrebbero
esserci review oltre il 16° item. Mail a `ALERT_RECIPIENTS`, decisione
di rilancio manuale all'utente.

**Grace window**: per una `(piattaforma, bu)` mai ingerita prima, si
notificano solo review con `data_review >= today - 7` per evitare mail
di massa al seed.
```

Update the actor table if Task 1 found any `reviewsStartDate` parameter:
add a column "Date filter" with the param name or "NONE".

- [ ] **Step 2: Create `docs/adr/0003-reviews-watermark-driven-scraping.md`**

```markdown
---
date: 2026-04-10
status: accepted
supersedes: none
---

# ADR 0003 — Reviews watermark-driven scraping

## Contesto

La pipeline reviews (`hotelops reviews --scrape`) aveva due bug collegati:

1. `alert.py` mandava la mail ma non aggiornava mai `alert_inviato` in BQ.
   Ogni rebuild/ripass scraper rimandava l'alert su review vecchie.
2. Nessun concetto di "già visto": l'actor Apify tornava le N più recenti
   e classificavamo tutto (Claude Haiku) anche quando erano duplicati.

Il 2026-04-10 3 mail di alert sono partite per review negative di
lug/ago/set 2025, rumore puro.

## Decisione

Introduciamo un **watermark gate** derivato da `f_reviews`:

```sql
SELECT piattaforma, business_unit_id, MAX(data_review)
FROM f_reviews
WHERE LENGTH(data_review) = 10
GROUP BY piattaforma, business_unit_id
```

La funzione pura `filter_by_watermark(watermarks, items, cap)` droppa
tutto ciò che è `≤` watermark, prima di classify/load/alert.

Dopo l'invio della mail, `mark_alerts_sent()` esegue un UPDATE
parameterized su BQ per persistere `alert_inviato=TRUE`, chiudendo il
bug del flag morto.

Quando una chiave (piattaforma, bu) ritorna `len(kept) == cap` scatta
un **gap alert** via mail: potrebbero esserci review oltre il 16° item
e l'utente decide se rilanciare con cap più alto.

Per le **prime run** di una nuova `(piattaforma, bu)` (watermark `None`)
si applica una **grace window** di 7 giorni agli alert per evitare di
seedare la tabella con decine di mail storiche.

## Alternative scartate

- **Solo flag-based (`alert_inviato`)**: fragile a rebuild di `f_reviews`,
  non protegge da duplicati di `review_hash` se il make_hash cambia.
- **Solo data-based (finestra rolling)**: perde review se l'actor
  ritorna timestamp antico per review appena pubblicate.
- **Auto-catchup al gap**: rischio loop costi Apify. Preferito l'utente
  nel loop con mail manuale.
- **Tabella dedicata `d_reviews_watermark`**: materializzazione
  prematura; il dato vive già in `f_reviews`. Quando arriverà
  `f_pipeline_runs` (Layer 2) il watermark esplicito ci sarà come
  backup, ma non è bloccante.

## Conseguenze

**Positive:**
- Nessuna mail duplicata su review storiche (bug risolto alla radice).
- Risparmio costo Claude Haiku: classifichiamo solo le nuove.
- Observability dei gap pre-catastrofe (vedi gap Google 5+ settimane).
- Audit del format drift (log `WATERMARK EXCLUDED n malformed rows`).

**Negative / limitazioni (v1):**
- Gap detection rigido a `len(kept) == cap`: review cancellata lato
  piattaforma → 14/15 → nessun warning. Rivedere dopo 2 settimane di
  dati reali.
- Crash window tra `mail sent` e `mark_alerts_sent`: se il processo
  crasha in mezzo, il prossimo run manda duplicato. Scelta consapevole:
  alert duplicato > alert perso.
- Filtro `LENGTH=10` è silenzioso per i record malformati; mitigato dal
  log audit di `read_watermarks`.

## Riferimenti

- Spec: `docs/superpowers/specs/2026-04-10-reviews-watermark-design.md`
- Plan: `docs/superpowers/plans/2026-04-10-reviews-watermark.md`
- Runbook: `docs/procedures/reviews_pipeline.md`
```

- [ ] **Step 3: Verify docs freshness still clean**

Run: `hotelops docs check` (or `python scripts/check_docs_freshness.py`)
Expected: exit 0, no stale/dead paths for `reviews_pipeline.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/procedures/reviews_pipeline.md docs/adr/0003-reviews-watermark-driven-scraping.md
git commit -m "docs(reviews): ADR 0003 + runbook update for watermark gate"
```

---

## Task 11: Live verification run

**Files:** none (verification only)

- [ ] **Step 1: Run the suite once more end-to-end**

Run: `pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 2: Manual scrape against BQ (real data)**

```bash
set -a; source .env; set +a
hotelops reviews --scrape --only booking
```

Expected in output:
- `read_watermarks: N keys`
- `Watermark filter: X new (dropped Y)` with Y > 0 (reviews already in BQ)
- `Alerts sent: 0` (there should be no new negative reviews since last run
  for BOOKING, or if there are, exactly those)
- `alert_inviato flagged on N rows` only if alerts were actually sent

- [ ] **Step 3: Verify BQ state post-run**

```bash
bq query --use_legacy_sql=false "
SELECT piattaforma, COUNTIF(alert_inviato) AS flagged, COUNT(*) AS total
FROM \`hotelops-suite.hotelops.f_reviews\`
GROUP BY piattaforma ORDER BY piattaforma
"
```

Expected: `flagged` > 0 for at least one piattaforma (was `0` pre-fix per
the runbook snapshot).

- [ ] **Step 4: Tail the log for the audit line**

Check console or log file for:
`WATERMARK EXCLUDED N malformed data_review rows on GOOGLE`
(should fire until the backfill runs after 2026-04-10).

- [ ] **Step 5: No new commit unless manual fixes were required.**

---

## Self-review checklist (maintainer)

- Spec §Problem → Tasks 3, 5, 7 (watermark gate + mark_alerts_sent)
- Spec §Data flow step 1 (read watermark) → Task 5
- Spec §Data flow step 3 (filter) → Task 3
- Spec §Data flow step 4 (gap detection) → Task 3 (pure) + Task 7 (mail) + Task 8 (wiring)
- Spec §Data flow step 5-7 (insert/classify/alert) → Task 8 (rewire)
- Spec §Error handling BQ down → Task 8 step 1 (try/except → raise)
- Spec §Error handling watermark empty → Task 7 (`first_run_keys`) + Task 8
- Spec §Error handling malformed date → Task 3 (drop + log) + Task 5 (audit query)
- Spec §Error handling SMTP fail → Task 7 `mark_alerts_sent` called AFTER `send_alerts` returns; if `send_email` raises mid-loop, flagging skipped naturally
- Spec §Testing unit → Tasks 2, 4, 6
- Spec §Testing regression → Task 9
- Spec §Ricognizione preliminare → Task 1
- Spec §Limitazioni note v1 → ADR 0003 in Task 10
- Spec §Done criteria → covered across Tasks 3, 5, 7, 8, 9, 10, 11
