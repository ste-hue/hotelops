#!/usr/bin/env python3
"""
Reconcile Banca — W3C Reconciliation API v0.2 for OpenRefine.

Serves the ERP mastrino (f_ledger_movimenti.csv) as reconciliation target.
Load bank transactions into OpenRefine, reconcile against this service.

Usage:
    python -m services.reconcile_api --datahub /path/to/hotelops_datahub
    python -m services.reconcile_api --datahub /path/to/datahub --port 8000
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from bank_reconcile.reconcile_core import (
    CascadeConfig,
    parse_amount,
    score_candidates,
)

from lib.datahub import read_facts

# -- App state ----------------------------------------------------------------

LEDGER_TRANSACTIONS: list[dict] = []
LEDGER_BY_AMOUNT: dict[float, list[dict]] = {}
LEARNED_MAPPINGS: list[dict] = []
DECISIONS: list[dict] = []

# Paths set at startup
DATAHUB: Path = Path(".")
DECISIONS_PATH: Path = Path(".")
MAPPINGS_PATH: Path = Path(".")

app = FastAPI(title="Reconcile Banca — OpenRefine API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Data loading -------------------------------------------------------------

def _load_ledger(datahub: Path) -> list[dict]:
    """Read all ledger facts and normalize to bank_reconcile format."""
    path = datahub / "fatti" / "f_ledger_movimenti.csv"
    facts = read_facts(path)
    txns = []
    for row in facts:
        txns.append({
            "id": row["id_registrazione"],
            "date": row["data_registrazione"],
            "description": row["descrizione"],
            "amount": row["importo"],
            "societa_id": row.get("societa_id", ""),
            "banca_id": row.get("banca_id", ""),
            "file_sorgente": row.get("file_sorgente", ""),
            "riga_sorgente": row.get("riga_sorgente", ""),
            "riferimento": row.get("riferimento_registrazione", ""),
        })
    return txns


def _build_amount_index(txns: list[dict]) -> dict[float, list[dict]]:
    index: dict[float, list[dict]] = {}
    for txn in txns:
        amount = round(parse_amount(txn["amount"]), 2)
        index.setdefault(amount, []).append(txn)
    return index


def _load_mappings(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_decisions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def init_data(datahub: Path, port: int):
    """Load all data at startup."""
    global LEDGER_TRANSACTIONS, LEDGER_BY_AMOUNT, LEARNED_MAPPINGS, DECISIONS
    global DATAHUB, DECISIONS_PATH, MAPPINGS_PATH

    DATAHUB = datahub

    run_base = datahub / "meta" / "actions" / "reconcile_banca"
    DECISIONS_PATH = run_base / "decisions.csv"
    MAPPINGS_PATH = run_base / "learned_mappings.csv"

    LEDGER_TRANSACTIONS = _load_ledger(datahub)
    LEDGER_BY_AMOUNT = _build_amount_index(LEDGER_TRANSACTIONS)
    LEARNED_MAPPINGS = _load_mappings(MAPPINGS_PATH)
    DECISIONS = _load_decisions(DECISIONS_PATH)

    print(f"Loaded {len(LEDGER_TRANSACTIONS)} ledger transactions")
    print(f"Loaded {len(LEARNED_MAPPINGS)} learned mappings")
    print(f"Loaded {len(DECISIONS)} prior decisions")


# -- W3C Reconciliation API v0.2 ---------------------------------------------

BASE_URL = "http://localhost:8000"


@app.get("/")
@app.get("/manifest")
@app.get("/reconcile")
def manifest():
    return {
        "versions": ["0.2"],
        "name": "Hotelops — Riconcilia Banca",
        "identifierSpace": f"{BASE_URL}/entity/",
        "schemaSpace": f"{BASE_URL}/schema/",
        "defaultTypes": [{"id": "LedgerEntry", "name": "Registrazione Mastrino"}],
        "view": {"url": f"{BASE_URL}/entity/{{{{id}}}}"},
        "preview": {
            "url": f"{BASE_URL}/preview/{{{{id}}}}",
            "width": 400,
            "height": 120,
        },
        "suggest": {
            "entity": {"service_url": BASE_URL, "service_path": "/suggest/entity"},
            "property": {"service_url": BASE_URL, "service_path": "/suggest/property"},
        },
        "extend": {
            "propose_properties": {
                "service_url": BASE_URL,
                "service_path": "/properties",
            },
            "property_settings": [],
        },
    }


@app.get("/properties")
def propose_properties(type: str = "LedgerEntry", limit: int = 10):
    return {
        "properties": [
            {"id": "amount", "name": "Importo"},
            {"id": "date", "name": "Data Valuta"},
            {"id": "societa", "name": "Societa"},
        ]
    }


@app.post("/")
@app.post("/reconcile")
async def reconcile(request: Request, queries: Optional[str] = Form(None)):
    if queries is None:
        try:
            form_data = await request.form()
            queries = form_data.get("queries")
        except Exception:
            pass

    if not queries:
        return manifest()

    try:
        queries_dict = json.loads(queries)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400, content={"error": "Invalid JSON in queries parameter"}
        )

    results = {}
    for query_id, query_obj in queries_dict.items():
        query_text = query_obj.get("query", "")
        limit = query_obj.get("limit", 5)
        properties = {p["pid"]: p["v"] for p in query_obj.get("properties", [])}

        bank_txn = {
            "description": query_text,
            "date": properties.get("date", "2000-01-01"),
            "amount": properties.get("amount", "0"),
        }

        # Amount blocking
        if "amount" in properties:
            amount_key = round(parse_amount(properties["amount"]), 2)
            candidates = LEDGER_BY_AMOUNT.get(amount_key, [])
        else:
            candidates = LEDGER_TRANSACTIONS

        # Societa hard gate
        if "societa" in properties:
            soc = str(properties["societa"]).strip().upper()
            candidates = [c for c in candidates if c.get("societa_id", "").upper() == soc]

        config = CascadeConfig(
            dayfirst=True,
            date_weight=0.8,
            text_weight=0.2,
            use_date_scoring="date" in properties,
            use_text_scoring=True,
        )

        scored = score_candidates(
            bank_txn, candidates, config, learned_mappings=LEARNED_MAPPINGS
        )

        result_list = []
        for ledger_txn, score in scored:
            result_list.append({
                "id": ledger_txn["id"],
                "name": f"{ledger_txn['description']} | {ledger_txn['date']} | {ledger_txn['amount']}",
                "score": round(score * 100, 2),
                "match": score > 0.85,
                "type": [{"id": "LedgerEntry", "name": "Registrazione Mastrino"}],
            })

        results[query_id] = {"result": result_list[:limit]}

    return results


@app.get("/entity/{entity_id}")
def get_entity(entity_id: str):
    for txn in LEDGER_TRANSACTIONS:
        if txn["id"] == entity_id:
            return {
                "id": entity_id,
                "name": txn["description"],
                "type": "LedgerEntry",
                "properties": {
                    "date": txn["date"],
                    "amount": txn["amount"],
                    "description": txn["description"],
                    "riferimento": txn.get("riferimento", ""),
                    "file_sorgente": txn.get("file_sorgente", ""),
                },
            }
    return JSONResponse(status_code=404, content={"error": "Entity not found"})


@app.get("/preview/{entity_id}", response_class=HTMLResponse)
def preview_entity(entity_id: str):
    for txn in LEDGER_TRANSACTIONS:
        if txn["id"] == entity_id:
            return f"""<html><head><style>
                body {{ font-family: Arial, sans-serif; padding: 8px; margin: 0; }}
                .id {{ color: #888; font-size: 11px; }}
                .desc {{ font-weight: bold; margin: 4px 0; }}
                .amt {{ color: #007700; font-weight: bold; }}
            </style></head><body>
                <div class="id">{entity_id}</div>
                <div class="desc">{txn['description']}</div>
                <div><span class="amt">{txn['amount']}</span> | {txn['date']}</div>
                <div style="font-size:11px;color:#666">{txn.get('riferimento', '')}</div>
            </body></html>"""
    return "<html><body>Not found</body></html>"


@app.get("/suggest/property")
def suggest_property(prefix: str = "", query: str = ""):
    term = (query or prefix).lower()
    props = [
        {"id": "amount", "name": "Importo", "description": "Importo transazione"},
        {"id": "date", "name": "Data Valuta", "description": "Data valuta (piu vicina alla data ERP)"},
        {"id": "societa", "name": "Societa", "description": "Societa ID (ORTI, INTUR)"},
    ]
    if not term:
        return {"result": props}
    return {"result": [p for p in props if term in p["name"].lower()]}


@app.get("/suggest/entity")
def suggest_entity(prefix: str = "", query: str = ""):
    term = (query or prefix).lower()
    if not term:
        return {"result": []}
    results = []
    for txn in LEDGER_TRANSACTIONS:
        if term in txn["description"].lower():
            results.append({
                "id": txn["id"],
                "name": txn["description"],
                "description": f"{txn['amount']} | {txn['date']}",
            })
        if len(results) >= 10:
            break
    return {"result": results}


# -- HotelOps extensions: decisions + work queue ------------------------------

DECISION_COLS = [
    "bank_id", "ledger_id", "decision", "decided_by", "decided_at", "note",
]


@app.post("/decision")
async def post_decision(request: Request):
    """Persist a human reconciliation decision (confirm/reject)."""
    body = await request.json()

    bank_id = body.get("bank_id", "")
    ledger_id = body.get("ledger_id", "")
    decision = body.get("decision", "")  # confirm / reject
    decided_by = body.get("decided_by", "openrefine")
    note = body.get("note", "")

    if not bank_id or not decision:
        return JSONResponse(status_code=400, content={"error": "bank_id and decision required"})

    row = {
        "bank_id": bank_id,
        "ledger_id": ledger_id,
        "decision": decision,
        "decided_by": decided_by,
        "decided_at": datetime.now().isoformat(),
        "note": note,
    }

    exists = DECISIONS_PATH.exists()
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DECISION_COLS)
        if not exists:
            w.writeheader()
        w.writerow(row)

    DECISIONS.append(row)

    return {"status": "ok", "decisions_total": len(DECISIONS)}


@app.get("/decisions")
def get_decisions():
    """Return all recorded decisions."""
    return {"decisions": DECISIONS, "total": len(DECISIONS)}


@app.post("/reload")
def reload_all():
    """Hot-reload ledger data, mappings, and decisions from disk."""
    global LEDGER_TRANSACTIONS, LEDGER_BY_AMOUNT, LEARNED_MAPPINGS, DECISIONS
    LEDGER_TRANSACTIONS = _load_ledger(DATAHUB)
    LEDGER_BY_AMOUNT = _build_amount_index(LEDGER_TRANSACTIONS)
    LEARNED_MAPPINGS = _load_mappings(MAPPINGS_PATH)
    DECISIONS = _load_decisions(DECISIONS_PATH)
    return {
        "status": "ok",
        "ledger_transactions": len(LEDGER_TRANSACTIONS),
        "learned_mappings": len(LEARNED_MAPPINGS),
        "decisions": len(DECISIONS),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ledger_loaded": len(LEDGER_TRANSACTIONS),
        "learned_mappings": len(LEARNED_MAPPINGS),
        "decisions": len(DECISIONS),
    }


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Banca — OpenRefine Reconciliation Service")
    parser.add_argument("--datahub", required=True, help="Path to hotelops_datahub")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    datahub = Path(args.datahub)
    if not datahub.exists():
        print(f"Datahub not found: {datahub}")
        sys.exit(1)

    global BASE_URL
    BASE_URL = f"http://localhost:{args.port}"

    init_data(datahub, args.port)

    print()
    print("Reconcile Banca — OpenRefine Service")
    print(f"  Add in OpenRefine: {BASE_URL}/reconcile")
    print(f"  Manifest:          {BASE_URL}/manifest")
    print(f"  Health:            {BASE_URL}/health")
    print()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
