#!/usr/bin/env python3
"""
Action: materialize_reconciliation

Builds a materialized view of reconciliation state — one row per bank
transaction with its formal status (Pending / AutoMatched / Confirmed / Rejected).

Output: {datahub}/meta/actions/reconcile_banca/materialized/reconciliation_transactions_v1.csv

Usage:
    python -m actions.materialize_reconciliation --datahub /path/to/hotelops_datahub
"""

import argparse
import csv
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from lib.datahub import read_facts


# -- Schema -------------------------------------------------------------------

OBJECT_COLS = [
    "bank_id", "societa_id", "banca_id", "data_operazione", "importo",
    "descrizione_banca", "candidate_ledger_id", "candidate_score",
    "confirmed_ledger_id", "status", "first_seen_at", "confirmed_at",
    "is_pending", "is_confirmed", "days_pending",
]


# -- Loaders ------------------------------------------------------------------

def _load_bank_facts(datahub: Path) -> dict[str, dict]:
    """bank_id -> {bank row fields needed for the materialized view}."""
    bank_path = datahub / "fatti" / "f_banche_movimenti.csv"
    if not bank_path.exists():
        return {}
    rows = read_facts(bank_path)
    result = {}
    for row in rows:
        bank_id = row.get("id_movimento", "")
        if not bank_id:
            continue
        result[bank_id] = {
            "societa_id": row.get("societa_id", ""),
            "banca_id": row.get("banca_id", ""),
            "data_operazione": row.get("data_operazione", ""),
            "importo": row.get("importo_netto", ""),
            "descrizione_banca": row.get("descrizione", ""),
            "first_seen_at": row.get("data_ingresso", ""),
        }
    return result


def _load_latest_run_results(datahub: Path) -> dict[str, dict]:
    """bank_id -> {candidate_ledger_id, candidate_score, engine_status}.

    Scans all completed run dirs. Most recent run wins per bank_id.
    """
    runs_csv = datahub / "meta" / "actions" / "reconcile_banca" / "runs.csv"
    if not runs_csv.exists():
        return {}

    with open(runs_csv, "r", encoding="utf-8") as f:
        runs = list(csv.DictReader(f))

    completed = [r for r in runs if r.get("status") == "completed"]
    completed.sort(key=lambda r: r.get("completed_at", ""), reverse=True)

    result: dict[str, dict] = {}
    runs_base = datahub / "meta" / "actions" / "reconcile_banca" / "runs"

    for run in completed:
        run_id = run.get("run_id", "")
        if not run_id:
            continue
        run_dir = runs_base / run_id

        # matches_auto.csv -> AutoMatched
        auto_path = run_dir / "matches_auto.csv"
        if auto_path.exists():
            with open(auto_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    bid = row.get("bank_id", "")
                    if bid and bid not in result:
                        result[bid] = {
                            "candidate_ledger_id": row.get("ledger_id", ""),
                            "candidate_score": row.get("score", ""),
                            "engine_status": "AutoMatched",
                        }

        # matches_review.csv -> Pending with top candidate
        review_path = run_dir / "matches_review.csv"
        if review_path.exists():
            review_candidates: dict[str, dict] = {}
            with open(review_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    bid = row.get("bank_id", "")
                    if not bid or bid in result:
                        continue
                    score_str = row.get("score", "0")
                    try:
                        score = float(score_str)
                    except ValueError:
                        score = 0.0
                    existing = review_candidates.get(bid)
                    if existing is None or score > float(existing["candidate_score"]):
                        review_candidates[bid] = {
                            "candidate_ledger_id": row.get("ledger_id", ""),
                            "candidate_score": score_str,
                            "engine_status": "Pending",
                        }
            result.update(review_candidates)

    return result


def _load_latest_decisions(datahub: Path) -> dict[str, dict]:
    """bank_id -> {decision, ledger_id, decided_at} (last decision per bank_id wins)."""
    decisions_path = datahub / "meta" / "actions" / "reconcile_banca" / "decisions.csv"
    if not decisions_path.exists():
        return {}
    result: dict[str, dict] = {}
    with open(decisions_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bid = row.get("bank_id", "")
            if not bid:
                continue
            # Last row wins (append-only file, later = newer)
            result[bid] = {
                "decision": row.get("decision", ""),
                "ledger_id": row.get("ledger_id", ""),
                "decided_at": row.get("decided_at", ""),
            }
    return result


# -- State machine ------------------------------------------------------------

def _compute_status(engine_status: str, decision: str | None) -> str:
    """Resolve final status. Decisions override engine status."""
    if decision == "confirm":
        return "Confirmed"
    if decision == "reject":
        return "Rejected"
    return engine_status  # "AutoMatched" or "Pending"


# -- Main entry point ---------------------------------------------------------

def materialize_reconciliation_state(datahub_path: str, today: date | None = None) -> dict:
    """Build the materialized reconciliation view. Returns summary dict."""
    datahub = Path(datahub_path)
    if today is None:
        today = date.today()

    bank_facts = _load_bank_facts(datahub)
    run_results = _load_latest_run_results(datahub)
    decisions = _load_latest_decisions(datahub)

    output_rows = []
    counts = {"Pending": 0, "AutoMatched": 0, "Confirmed": 0, "Rejected": 0}

    for bank_id, bank in bank_facts.items():
        engine = run_results.get(bank_id, {})
        engine_status = engine.get("engine_status", "Pending")

        dec = decisions.get(bank_id, {})
        decision = dec.get("decision") or None

        status = _compute_status(engine_status, decision)
        counts[status] = counts.get(status, 0) + 1

        confirmed_ledger_id = ""
        confirmed_at = ""
        if decision == "confirm":
            confirmed_ledger_id = dec.get("ledger_id", "")
            confirmed_at = dec.get("decided_at", "")

        is_pending = status == "Pending"
        is_confirmed = status == "Confirmed"

        first_seen_at = bank.get("first_seen_at", "")
        days_pending = 0
        if is_pending and first_seen_at:
            try:
                seen = datetime.fromisoformat(first_seen_at).date()
                days_pending = (today - seen).days
            except ValueError:
                days_pending = 0

        output_rows.append({
            "bank_id": bank_id,
            "societa_id": bank.get("societa_id", ""),
            "banca_id": bank.get("banca_id", ""),
            "data_operazione": bank.get("data_operazione", ""),
            "importo": bank.get("importo", ""),
            "descrizione_banca": bank.get("descrizione_banca", ""),
            "candidate_ledger_id": engine.get("candidate_ledger_id", ""),
            "candidate_score": engine.get("candidate_score", ""),
            "confirmed_ledger_id": confirmed_ledger_id,
            "status": status,
            "first_seen_at": first_seen_at,
            "confirmed_at": confirmed_at,
            "is_pending": str(is_pending).lower(),
            "is_confirmed": str(is_confirmed).lower(),
            "days_pending": str(days_pending),
        })

    # Write output (full overwrite)
    output_dir = datahub / "meta" / "actions" / "reconcile_banca" / "materialized"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "reconciliation_transactions_v1.csv"

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OBJECT_COLS)
        w.writeheader()
        w.writerows(output_rows)

    return {
        "total": len(output_rows),
        "counts": counts,
        "output_path": str(output_path),
    }


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Materialize reconciliation state for all bank transactions")
    parser.add_argument("--datahub", required=True)
    args = parser.parse_args()

    datahub = Path(args.datahub)
    if not datahub.exists():
        print(f"Datahub not found: {datahub}")
        sys.exit(1)

    try:
        summary = materialize_reconciliation_state(args.datahub)
    except Exception:
        traceback.print_exc()
        sys.exit(1)

    total = summary["total"]
    counts = summary["counts"]
    print(f"Materialized {total} reconciliation transactions")
    print(f"  Pending:      {counts.get('Pending', 0)}")
    print(f"  AutoMatched:  {counts.get('AutoMatched', 0)}")
    print(f"  Confirmed:    {counts.get('Confirmed', 0)}")
    print(f"  Rejected:     {counts.get('Rejected', 0)}")
    print(f"  Output: {summary['output_path']}")


if __name__ == "__main__":
    main()
