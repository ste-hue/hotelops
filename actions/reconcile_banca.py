#!/usr/bin/env python3
"""
Action: reconcile_banca

Matches bank transactions (f_banche_movimenti) against ledger records
(f_ledger_movimenti) using the bank_reconcile engine.

Output: {datahub}/meta/actions/reconcile_banca/runs/{run_id}/
  - matches_auto.csv
  - matches_review.csv
  - no_match.csv
  - metrics.json

Usage:
    python -m actions.reconcile_banca \
        --datahub /path/to/hotelops_datahub \
        --societa INTUR --conto SELLA \
        --from 2025-01-01 --to 2025-01-31
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from bank_reconcile.reconcile_core import CascadeConfig, reconcile_cascade

from lib.datahub import read_facts


# -- Helpers ------------------------------------------------------------------

def _make_run_id(societa: str, conto: str, date_from: str, date_to: str) -> str:
    """Deterministic run ID. Same params -> same ID -> idempotent overwrite."""
    key = f"{societa}|{conto}|{date_from}|{date_to}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _filter_by_date(rows: list[dict], col: str, d_from: str, d_to: str) -> list[dict]:
    """Keep rows where col (ISO date string) falls within [d_from, d_to]."""
    return [r for r in rows if d_from <= r.get(col, "") <= d_to]


# -- Mappers: fact row -> bank_reconcile input format -------------------------

def _bank_to_txn(row: dict) -> dict:
    return {
        "date": row["data_operazione"],
        "description": row["descrizione"],
        "amount": row["importo_netto"],
        "id_movimento": row["id_movimento"],
    }


def _ledger_to_txn(row: dict) -> dict:
    return {
        "date": row["data_registrazione"],
        "description": row["descrizione"],
        "amount": row["importo"],
        "id_registrazione": row["id_registrazione"],
    }


# -- Output flatteners -------------------------------------------------------

MATCH_COLS = [
    "bank_id", "bank_date", "bank_desc", "bank_amount",
    "ledger_id", "ledger_date", "ledger_desc", "ledger_amount", "score",
]
NO_MATCH_COLS = ["bank_id", "bank_date", "bank_desc", "bank_amount"]


def _flatten_auto(bucket: list[dict]) -> list[dict]:
    return [{
        "bank_id": cs["bank_txn"].get("id_movimento", ""),
        "bank_date": cs["bank_txn"]["date"],
        "bank_desc": cs["bank_txn"]["description"],
        "bank_amount": cs["bank_txn"]["amount"],
        "ledger_id": cs["candidates"][0].get("id_registrazione", ""),
        "ledger_date": cs["candidates"][0]["date"],
        "ledger_desc": cs["candidates"][0]["description"],
        "ledger_amount": cs["candidates"][0]["amount"],
        "score": f"{cs['scores'][0]:.4f}",
    } for cs in bucket]


def _flatten_review(bucket: list[dict]) -> list[dict]:
    rows = []
    for cs in bucket:
        b = cs["bank_txn"]
        for erp, score in zip(cs["candidates"], cs["scores"]):
            rows.append({
                "bank_id": b.get("id_movimento", ""),
                "bank_date": b["date"],
                "bank_desc": b["description"],
                "bank_amount": b["amount"],
                "ledger_id": erp.get("id_registrazione", ""),
                "ledger_date": erp["date"],
                "ledger_desc": erp["description"],
                "ledger_amount": erp["amount"],
                "score": f"{score:.4f}",
            })
    return rows


def _flatten_no_match(bucket: list[dict]) -> list[dict]:
    return [{
        "bank_id": cs["bank_txn"].get("id_movimento", ""),
        "bank_date": cs["bank_txn"]["date"],
        "bank_desc": cs["bank_txn"]["description"],
        "bank_amount": cs["bank_txn"]["amount"],
    } for cs in bucket]


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# -- Main entry point ---------------------------------------------------------

def run_reconciliation(
    datahub_path: str,
    societa: str,
    conto: str,
    date_from: str,
    date_to: str,
) -> dict:
    datahub = Path(datahub_path)
    oggetto_id = f"CONTO_{societa}_{conto}"

    # Deterministic run — same params always produce same run_id
    run_id = _make_run_id(societa, conto, date_from, date_to)
    run_dir = datahub / "meta" / "actions" / "reconcile_banca" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # -- Bank side --
    bank_facts = read_facts(
        datahub / "fatti" / "f_banche_movimenti.csv",
        filters={"societa_id": societa, "oggetto_id": oggetto_id},
    )
    bank_facts = _filter_by_date(bank_facts, "data_operazione", date_from, date_to)
    bank_txns = [_bank_to_txn(r) for r in bank_facts]

    # -- Ledger side --
    ledger_facts = read_facts(
        datahub / "fatti" / "f_ledger_movimenti.csv",
        filters={"societa_id": societa},
    )
    ledger_facts = _filter_by_date(ledger_facts, "data_registrazione", date_from, date_to)
    ledger_txns = [_ledger_to_txn(r) for r in ledger_facts]

    # -- Engine --
    config = CascadeConfig(dayfirst=True)
    result = reconcile_cascade(bank_txns, ledger_txns, config=config)

    # -- Write outputs --
    n_auto = _write_csv(
        run_dir / "matches_auto.csv", _flatten_auto(result["auto"]), MATCH_COLS)
    n_review = _write_csv(
        run_dir / "matches_review.csv", _flatten_review(result["review"]), MATCH_COLS)
    n_no_match = _write_csv(
        run_dir / "no_match.csv", _flatten_no_match(result["no_match"]), NO_MATCH_COLS)

    # -- Metrics --
    total_bank = len(bank_txns)
    metrics = {
        "run_id": run_id,
        "societa": societa,
        "conto": conto,
        "oggetto_id": oggetto_id,
        "date_from": date_from,
        "date_to": date_to,
        "timestamp": datetime.now().isoformat(),
        "bank_transactions": total_bank,
        "ledger_transactions": len(ledger_txns),
        "auto_matches": n_auto,
        "review_matches": n_review,
        "no_matches": n_no_match,
        "auto_rate": round(n_auto / total_bank, 4) if total_bank else 0,
        "output_dir": str(run_dir),
    }

    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    return metrics


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reconcile bank transactions against ledger")
    parser.add_argument("--datahub", required=True)
    parser.add_argument("--societa", required=True)
    parser.add_argument("--conto", required=True)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    args = parser.parse_args()

    metrics = run_reconciliation(
        args.datahub, args.societa, args.conto, args.date_from, args.date_to)

    print(f"Run {metrics['run_id']} completed")
    print(f"  Bank txns:    {metrics['bank_transactions']}")
    print(f"  Ledger txns:  {metrics['ledger_transactions']}")
    print(f"  Auto matches: {metrics['auto_matches']}")
    print(f"  For review:   {metrics['review_matches']}")
    print(f"  No match:     {metrics['no_matches']}")
    print(f"  Auto rate:    {metrics['auto_rate']:.1%}")
    print(f"  Output:       {metrics['output_dir']}")


if __name__ == "__main__":
    main()
