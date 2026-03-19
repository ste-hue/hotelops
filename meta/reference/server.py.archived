#!/usr/bin/env python3
"""
Hotelops local API server.
n8n chiama questi endpoint invece di eseguire comandi shell direttamente.

Endpoints:
  POST /run/ingest   → esegue run_all.sh (asincrono, ritorna subito 202)
  GET  /status       → query v_ultima_data → JSON
  GET  /pl           → query v_pl_movimenti 2026 → JSON
  GET  /cashflow     → query v_cashflow_mensile 2026 → JSON
  GET  /health       → {"status": "ok"}

Avvio:
  python server.py
  # oppure con auto-reload:
  python -m uvicorn server:app --reload --port 8765
"""

import subprocess
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading

BASE_DIR = Path(__file__).parent
BQ = "/opt/homebrew/bin/bq"
PYTHON = sys.executable


def run_bq(query: str) -> list[dict]:
    result = subprocess.run(
        [BQ, "query", "--use_legacy_sql=false",
         "--project_id=hotelops-suite", "--format=json", query],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout or "[]")


def run_ingest_bg():
    subprocess.Popen(
        ["bash", str(BASE_DIR / "run_all.sh")],
        stdout=open(BASE_DIR / "logs" / "last_ingest.log", "w"),
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
    )


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silenzia access log

    def send_json(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok"})

            elif self.path == "/status":
                rows = run_bq(
                    "SELECT * FROM hotelops.v_ultima_data ORDER BY fonte, societa_id, conto"
                )
                self.send_json(200, {"rows": rows})

            elif self.path == "/pl":
                rows = run_bq(
                    "SELECT societa_id, anno, mese, categoria, business_unit_id, "
                    "ROUND(SUM(importo),0) AS importo "
                    "FROM hotelops.v_pl_movimenti WHERE anno=2026 "
                    "GROUP BY 1,2,3,4,5 ORDER BY societa_id, mese, categoria"
                )
                self.send_json(200, {"rows": rows})

            elif self.path == "/cashflow":
                rows = run_bq(
                    "SELECT societa_id, banca_id, "
                    "EXTRACT(YEAR FROM data_operazione) AS anno, "
                    "EXTRACT(MONTH FROM data_operazione) AS mese, "
                    "ROUND(SUM(importo_netto),2) AS flusso "
                    "FROM hotelops.f_banche_movimenti "
                    "WHERE EXTRACT(YEAR FROM data_operazione) = 2026 "
                    "GROUP BY 1,2,3,4 ORDER BY societa_id, banca_id, mese"
                )
                self.send_json(200, {"rows": rows})

            else:
                self.send_json(404, {"error": "not found"})

        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def do_POST(self):
        try:
            if self.path == "/run/ingest":
                (BASE_DIR / "logs").mkdir(exist_ok=True)
                threading.Thread(target=run_ingest_bg, daemon=True).start()
                self.send_json(202, {"status": "started", "log": "logs/last_ingest.log"})
            else:
                self.send_json(404, {"error": "not found"})
        except Exception as e:
            self.send_json(500, {"error": str(e)})


if __name__ == "__main__":
    port = 8765
    print(f"Hotelops API server → http://localhost:{port}")
    print("  POST /run/ingest  — avvia run_all.sh")
    print("  GET  /status      — ultime date")
    print("  GET  /pl          — P&L 2026")
    print("  GET  /cashflow    — cashflow 2026")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
