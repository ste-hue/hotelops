"""Tests for actions.materialize_reconciliation — synthetic datahub, no real data."""

import csv
import json
from datetime import date
from pathlib import Path

from actions.materialize_reconciliation import (
    _compute_status,
    materialize_reconciliation_state,
)


# -- Helpers to build synthetic datahub structures ----------------------------

BANK_COLS = [
    "id_movimento", "societa_id", "business_unit_id", "funzione_id",
    "location_id", "oggetto_id", "banca_id", "data_operazione",
    "data_valuta", "descrizione", "divisa", "importo_debito",
    "importo_credito", "importo_netto", "data_ingresso",
]

MATCH_COLS = [
    "bank_id", "bank_date", "bank_desc", "bank_amount",
    "bank_file", "bank_row", "ledger_id", "ledger_date",
    "ledger_desc", "ledger_amount", "ledger_file", "score",
]

NO_MATCH_COLS = [
    "bank_id", "bank_date", "bank_desc", "bank_amount",
    "bank_file", "bank_row",
]

RUNS_COLS = [
    "run_id", "societa", "conto", "date_from", "date_to", "status",
    "auto_rate", "started_at", "completed_at", "duration_seconds",
    "bank_transactions", "auto_matches",
]

DECISION_COLS = [
    "bank_id", "ledger_id", "decision", "decided_by", "decided_at", "note",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _make_bank_row(
    bank_id: str,
    societa: str = "INTUR",
    banca: str = "SELLA",
    data_op: str = "2025-01-15",
    importo: str = "-100.00",
    desc: str = "PAGAMENTO",
    ingresso: str = "2025-01-20",
) -> dict:
    return {
        "id_movimento": bank_id,
        "societa_id": societa,
        "business_unit_id": "HOTEL",
        "funzione_id": "FINANZA",
        "location_id": "N_A",
        "oggetto_id": f"CONTO_{societa}_{banca}",
        "banca_id": banca,
        "data_operazione": data_op,
        "data_valuta": data_op,
        "descrizione": desc,
        "divisa": "EUR",
        "importo_debito": importo if float(importo) < 0 else "",
        "importo_credito": importo if float(importo) >= 0 else "",
        "importo_netto": importo,
        "data_ingresso": ingresso,
    }


def _setup_bank_facts(datahub: Path, rows: list[dict]):
    _write_csv(datahub / "fatti" / "f_banche_movimenti.csv", BANK_COLS, rows)


def _setup_run(
    datahub: Path,
    run_id: str,
    completed_at: str,
    auto_rows: list[dict] | None = None,
    review_rows: list[dict] | None = None,
    no_match_rows: list[dict] | None = None,
):
    """Create a completed run with its CSV files and registry entry."""
    run_base = datahub / "meta" / "actions" / "reconcile_banca"
    run_dir = run_base / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # metrics.json
    with open(run_dir / "metrics.json", "w") as f:
        json.dump({"run_id": run_id, "status": "completed",
                    "completed_at": completed_at}, f)

    if auto_rows is not None:
        _write_csv(run_dir / "matches_auto.csv", MATCH_COLS, auto_rows)
    if review_rows is not None:
        _write_csv(run_dir / "matches_review.csv", MATCH_COLS, review_rows)
    if no_match_rows is not None:
        _write_csv(run_dir / "no_match.csv", NO_MATCH_COLS, no_match_rows)

    # Append to runs.csv
    runs_csv = run_base / "runs.csv"
    exists = runs_csv.exists()
    run_base.mkdir(parents=True, exist_ok=True)
    with open(runs_csv, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUNS_COLS)
        if not exists:
            w.writeheader()
        w.writerow({
            "run_id": run_id, "societa": "INTUR", "conto": "SELLA",
            "date_from": "2025-01-01", "date_to": "2025-01-31",
            "status": "completed", "auto_rate": "0.5",
            "started_at": completed_at, "completed_at": completed_at,
            "duration_seconds": "1.0", "bank_transactions": "1",
            "auto_matches": "1",
        })


def _setup_decisions(datahub: Path, rows: list[dict]):
    path = datahub / "meta" / "actions" / "reconcile_banca" / "decisions.csv"
    _write_csv(path, DECISION_COLS, rows)


# -- Unit tests: _compute_status ----------------------------------------------

def test_compute_status_pending():
    assert _compute_status("Pending", None) == "Pending"


def test_compute_status_auto_matched():
    assert _compute_status("AutoMatched", None) == "AutoMatched"


def test_compute_status_confirm_overrides_auto():
    assert _compute_status("AutoMatched", "confirm") == "Confirmed"


def test_compute_status_confirm_overrides_pending():
    assert _compute_status("Pending", "confirm") == "Confirmed"


def test_compute_status_reject_overrides_auto():
    assert _compute_status("AutoMatched", "reject") == "Rejected"


def test_compute_status_reject_overrides_pending():
    assert _compute_status("Pending", "reject") == "Rejected"


# -- Integration tests: materialize_reconciliation_state ----------------------

FIXED_TODAY = date(2025, 2, 1)


def test_bank_fact_no_match_is_pending(tmp_path):
    """Bank fact without any engine match -> Pending, days_pending > 0."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK001", ingresso="2025-01-20")])

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["total"] == 1
    assert summary["counts"]["Pending"] == 1

    rows = _read_output(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["bank_id"] == "BK001"
    assert row["status"] == "Pending"
    assert row["is_pending"] == "true"
    assert row["is_confirmed"] == "false"
    assert row["candidate_ledger_id"] == ""
    assert int(row["days_pending"]) == 12  # 2025-02-01 - 2025-01-20


def test_bank_fact_auto_match(tmp_path):
    """Bank fact with auto match -> AutoMatched, candidate populated."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK002")])
    _setup_run(
        tmp_path, run_id="run001", completed_at="2025-01-25T10:00:00",
        auto_rows=[{
            "bank_id": "BK002", "ledger_id": "LED099",
            "score": "0.8500", "bank_date": "", "bank_desc": "",
            "bank_amount": "", "bank_file": "", "bank_row": "",
            "ledger_date": "", "ledger_desc": "", "ledger_amount": "",
            "ledger_file": "",
        }],
    )

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["counts"]["AutoMatched"] == 1
    row = _read_output(tmp_path)[0]
    assert row["status"] == "AutoMatched"
    assert row["candidate_ledger_id"] == "LED099"
    assert row["candidate_score"] == "0.8500"
    assert row["confirmed_ledger_id"] == ""
    assert row["is_pending"] == "false"
    assert row["days_pending"] == "0"


def test_auto_match_plus_confirm(tmp_path):
    """Auto match + confirm decision -> Confirmed."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK003")])
    _setup_run(
        tmp_path, run_id="run001", completed_at="2025-01-25T10:00:00",
        auto_rows=[_auto_row("BK003", "LED100", "0.9000")],
    )
    _setup_decisions(tmp_path, [{
        "bank_id": "BK003", "ledger_id": "LED100",
        "decision": "confirm", "decided_by": "user",
        "decided_at": "2025-01-26T12:00:00", "note": "",
    }])

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["counts"]["Confirmed"] == 1
    row = _read_output(tmp_path)[0]
    assert row["status"] == "Confirmed"
    assert row["confirmed_ledger_id"] == "LED100"
    assert row["confirmed_at"] == "2025-01-26T12:00:00"
    assert row["is_confirmed"] == "true"
    assert row["days_pending"] == "0"


def test_auto_match_plus_reject(tmp_path):
    """Auto match + reject decision -> Rejected."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK004")])
    _setup_run(
        tmp_path, run_id="run001", completed_at="2025-01-25T10:00:00",
        auto_rows=[_auto_row("BK004", "LED101", "0.7000")],
    )
    _setup_decisions(tmp_path, [{
        "bank_id": "BK004", "ledger_id": "LED101",
        "decision": "reject", "decided_by": "user",
        "decided_at": "2025-01-26T14:00:00", "note": "wrong match",
    }])

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["counts"]["Rejected"] == 1
    row = _read_output(tmp_path)[0]
    assert row["status"] == "Rejected"
    assert row["confirmed_ledger_id"] == ""


def test_multiple_decisions_last_wins(tmp_path):
    """Confirm then reject -> last decision (reject) wins."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK005")])
    _setup_run(
        tmp_path, run_id="run001", completed_at="2025-01-25T10:00:00",
        auto_rows=[_auto_row("BK005", "LED102", "0.8000")],
    )
    _setup_decisions(tmp_path, [
        {
            "bank_id": "BK005", "ledger_id": "LED102",
            "decision": "confirm", "decided_by": "user",
            "decided_at": "2025-01-26T10:00:00", "note": "",
        },
        {
            "bank_id": "BK005", "ledger_id": "LED102",
            "decision": "reject", "decided_by": "user",
            "decided_at": "2025-01-27T10:00:00", "note": "changed mind",
        },
    ])

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["counts"]["Rejected"] == 1
    row = _read_output(tmp_path)[0]
    assert row["status"] == "Rejected"


def test_multiple_runs_latest_wins(tmp_path):
    """Two runs with different candidates -> latest run's candidate wins."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK006")])

    # Older run
    _setup_run(
        tmp_path, run_id="run_old", completed_at="2025-01-20T10:00:00",
        auto_rows=[_auto_row("BK006", "LED_OLD", "0.6000")],
    )
    # Newer run
    _setup_run(
        tmp_path, run_id="run_new", completed_at="2025-01-25T10:00:00",
        auto_rows=[_auto_row("BK006", "LED_NEW", "0.9500")],
    )

    materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    row = _read_output(tmp_path)[0]
    assert row["candidate_ledger_id"] == "LED_NEW"
    assert row["candidate_score"] == "0.9500"
    assert row["status"] == "AutoMatched"


def test_review_match_stays_pending_with_candidate(tmp_path):
    """Bank fact in matches_review -> Pending but with candidate info."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK007", ingresso="2025-01-10")])
    _setup_run(
        tmp_path, run_id="run001", completed_at="2025-01-25T10:00:00",
        review_rows=[
            _review_row("BK007", "LED_A", "0.4000"),
            _review_row("BK007", "LED_B", "0.5500"),
        ],
    )

    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    assert summary["counts"]["Pending"] == 1
    row = _read_output(tmp_path)[0]
    assert row["status"] == "Pending"
    assert row["candidate_ledger_id"] == "LED_B"  # highest score
    assert row["candidate_score"] == "0.5500"
    assert row["is_pending"] == "true"
    assert int(row["days_pending"]) == 22  # 2025-02-01 - 2025-01-10


def test_empty_datahub(tmp_path):
    """No bank facts file -> empty output, no crash."""
    summary = materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)
    assert summary["total"] == 0
    assert summary["counts"] == {
        "Pending": 0, "AutoMatched": 0, "Confirmed": 0, "Rejected": 0,
    }


def test_output_has_all_columns(tmp_path):
    """Output CSV has exactly the 15 expected columns."""
    _setup_bank_facts(tmp_path, [_make_bank_row("BK008")])
    materialize_reconciliation_state(str(tmp_path), today=FIXED_TODAY)

    output = (tmp_path / "meta" / "actions" / "reconcile_banca"
              / "materialized" / "reconciliation_transactions_v1.csv")
    with open(output, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert list(reader.fieldnames) == [
            "bank_id", "societa_id", "banca_id", "data_operazione", "importo",
            "descrizione_banca", "candidate_ledger_id", "candidate_score",
            "confirmed_ledger_id", "status", "first_seen_at", "confirmed_at",
            "is_pending", "is_confirmed", "days_pending",
        ]


# -- Helpers ------------------------------------------------------------------

def _auto_row(bank_id: str, ledger_id: str, score: str) -> dict:
    return {
        "bank_id": bank_id, "ledger_id": ledger_id, "score": score,
        "bank_date": "", "bank_desc": "", "bank_amount": "",
        "bank_file": "", "bank_row": "",
        "ledger_date": "", "ledger_desc": "", "ledger_amount": "",
        "ledger_file": "",
    }


def _review_row(bank_id: str, ledger_id: str, score: str) -> dict:
    return _auto_row(bank_id, ledger_id, score)


def _read_output(datahub: Path) -> list[dict]:
    output = (datahub / "meta" / "actions" / "reconcile_banca"
              / "materialized" / "reconciliation_transactions_v1.csv")
    with open(output, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))
