#!/usr/bin/env python3
"""hotelops CLI — kernel commands only (verticals-v2 branch).

Subcomandi:
    hotelops intake      Lineage: registra un file (raw blob + RAW_INGESTED event)
    hotelops promote     Lineage: promuovi raw_object a canonical
    hotelops lineage     Lineage: ispeziona raw_object o lista con filtri
    hotelops reviews     Reviews vertical (preserved as-is)

I comandi dei verticali (CONDGES, ECONOMATO, ROOM DIVISION, GRUPPI) saranno
aggiunti man mano che ogni vertical viene disegnato e implementato sopra il
kernel. Vedi KERNEL.md.

Installazione:
    pip install -e .    (poi: hotelops intake --help)
    oppure: python -m cli intake

Richiede: gcloud auth (stefano@panoramagroup.it)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from repo root into os.environ (idempotent, no deps).

    Manual loader invece di `python-dotenv` o `export $(... | xargs)` perché
    quest'ultimo splitta su spazi i valori (es. Gmail App Password formato
    'xxxx xxxx xxxx xxxx') — bug reale che ci ha fatto perdere un'ora.
    Formato: KEY=VALUE per riga, `#` per commenti, quote opzionali.
    Non sovrascrive var già presenti (shell vince).
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# noqa: E402 — import after _load_dotenv() è intenzionale: i submodule possono
# leggere env var al toplevel, quindi .env va caricato prima.
from reviews.cli_commands import cmd_reviews  # noqa: E402
from workspace.cli_commands import cmd_workspace  # noqa: E402


# ── Lineage: intake / promote / lineage ─────────────────────────────────────


def cmd_intake(args):
    """Register a file in the lineage layer (no canonical write)."""
    from ingest.intake import intake_file

    result = intake_file(
        Path(args.file),
        source_name=args.source_name,
        actor="cli",
    )
    print(f"raw_object_id: {result.raw_object_id}")
    print(f"content_hash:  {result.content_hash}")
    print(f"source_name:   {result.source_name or '(none)'}")


def cmd_promote(args):
    """Promote a PROMOTABLE raw_object to canonical via its source policy."""
    from ingest.promotion import promote_raw_object

    if args.raw_object_id:
        r = promote_raw_object(args.raw_object_id, actor="cli")
        print(
            f"status={r.status} reason={r.reason or '-'} rows={r.rows_written} noop={r.noop}"
        )
        if r.status == "REJECTED":
            sys.exit(2)
        return

    print("--all-promotable not yet implemented in Phase 1 (use --raw-object-id)")
    sys.exit(1)


def cmd_lineage(args):
    """Inspect a raw_object: identity + event history + current status."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import (
        F_LINEAGE_EVENTS,
        F_RAW_OBJECTS,
        V_RAW_OBJECTS_CURRENT,
    )
    from google.cloud import bigquery

    client = get_client()
    p = bigquery.ScalarQueryParameter("id", "STRING", args.raw_object_id)
    qc = bigquery.QueryJobConfig(query_parameters=[p])

    print("\n  Identity:")
    rows = list(
        client.query(
            f"SELECT * FROM `{F_RAW_OBJECTS}` WHERE raw_object_id = @id",
            job_config=qc,
        ).result()
    )
    if not rows:
        print(f"  ❌ raw_object_id not found: {args.raw_object_id}")
        sys.exit(1)
    r = rows[0]
    for k in (
        "source_name",
        "societa_id",
        "file_name_original",
        "intake_at",
        "raw_uri",
    ):
        print(f"    {k}: {getattr(r, k, '-')}")

    print("\n  Current status:")
    cur = list(
        client.query(
            f"SELECT current_status, last_event_at FROM `{V_RAW_OBJECTS_CURRENT}` "
            f"WHERE raw_object_id = @id",
            job_config=qc,
        ).result()
    )
    if cur:
        print(f"    {cur[0].current_status}  (last event: {cur[0].last_event_at})")

    print("\n  Event history:")
    events = list(
        client.query(
            f"SELECT event_type, event_at, actor, from_status, to_status, reason "
            f"FROM `{F_LINEAGE_EVENTS}` WHERE raw_object_id = @id ORDER BY event_at",
            job_config=qc,
        ).result()
    )
    for ev in events:
        transition = (
            f"{ev.from_status or '∅'} → {ev.to_status}"
            if ev.to_status
            else "(no transition)"
        )
        reason = f"  [{ev.reason}]" if ev.reason else ""
        print(f"    {ev.event_at}  {ev.event_type:<22s} {transition}{reason}")
    print()


def cmd_lineage_list(args):
    """List raw_objects filtered by status / source / age."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import F_RAW_OBJECTS, V_RAW_OBJECTS_CURRENT
    from google.cloud import bigquery

    where = ["1 = 1"]
    params = []
    status = getattr(args, "status", None)
    if status is not None and status != "":
        where.append("COALESCE(c.current_status, 'RAW_ONLY') = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", args.status))
    source = getattr(args, "source", None)
    if source is not None and source != "":
        where.append("r.source_name = @source")
        params.append(bigquery.ScalarQueryParameter("source", "STRING", args.source))
    days = getattr(args, "days", None)
    if days is not None:
        where.append(
            "r.intake_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
        )
        params.append(bigquery.ScalarQueryParameter("days", "INT64", args.days))

    limit = int(getattr(args, "limit", None) or 20)
    sql = f"""
    SELECT
      r.raw_object_id,
      r.source_name,
      COALESCE(c.current_status, 'RAW_ONLY') AS current_status,
      r.intake_at,
      r.file_name_original
    FROM `{F_RAW_OBJECTS}` r
    LEFT JOIN `{V_RAW_OBJECTS_CURRENT}` c USING (raw_object_id)
    WHERE {' AND '.join(where)}
    ORDER BY r.intake_at DESC
    LIMIT {limit}
    """
    client = get_client()
    qc = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(client.query(sql, job_config=qc).result())

    if not rows:
        print("(no raw_objects match filters)")
        return

    print(
        f"{'raw_object_id':<38} {'status':<12} {'source':<32} {'intake_at':<25} file"
    )
    print("-" * 130)
    for row in rows:
        print(
            f"{row.raw_object_id:<38} "
            f"{str(row.current_status or '?'):<12} "
            f"{str(row.source_name or '-'):<32} "
            f"{str(row.intake_at):<25} "
            f"{row.file_name_original or '-'}"
        )


def cmd_lineage_dispatch(args):
    """Route --list vs single-id lineage inspection."""
    if getattr(args, "lineage_list", False):
        cmd_lineage_list(args)
        return
    if not args.raw_object_id:
        print(
            "ERROR: provide raw_object_id or use --list",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd_lineage(args)


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="hotelops",
        description="Control plane per il financial model Gruppo Panorama (kernel commands only — verticals-v2)",
    )
    sub = parser.add_subparsers(dest="command")

    # ── Lineage subcommands ────────────────────────────────────────────────
    p_intake = sub.add_parser(
        "intake",
        help="Lineage: registra un file (raw blob + RAW_INGESTED event)",
    )
    p_intake.add_argument("file", help="Path al file")
    p_intake.add_argument(
        "--source-name",
        default=None,
        help="source_name del registry (es. ESOLVER_BILANCINO_ORTI_SNAPSHOT)",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Lineage: promuovi raw_object a canonical (parser + bq_write_validated)",
    )
    p_promote.add_argument("--raw-object-id", required=True)

    p_lin = sub.add_parser(
        "lineage", help="Lineage: ispeziona raw_object o lista con filtri"
    )
    p_lin.add_argument(
        "raw_object_id",
        nargs="?",
        default=None,
        help="ID singolo (ometti con --list)",
    )
    p_lin.add_argument(
        "--list",
        dest="lineage_list",
        action="store_true",
        help="Modalità lista con filtri (richiede --status/--source/--days/--limit)",
    )
    p_lin.add_argument("--status", default=None, help="Filtra per current_status")
    p_lin.add_argument("--source", default=None, help="Filtra per source_name")
    p_lin.add_argument(
        "--days", type=int, default=None, help="Solo intake_at degli ultimi N giorni"
    )
    p_lin.add_argument("--limit", type=int, default=20, help="Default 20")

    # ── Reviews vertical (preserved) ────────────────────────────────────────
    p_reviews = sub.add_parser("reviews", help="Reviews ospiti: scrape, alert, stats")
    p_reviews.add_argument(
        "--scrape", action="store_true", help="Trigger scrape manuale"
    )
    p_reviews.add_argument(
        "--only",
        type=str,
        help="Solo questa piattaforma (booking, tripadvisor, google, expedia)",
    )
    p_reviews.add_argument(
        "--alert", action="store_true", help="Mostra review con alert"
    )
    p_reviews.add_argument("--stats", action="store_true", help="Statistiche review")
    p_reviews.add_argument("--mese", type=int, help="Mese per stats")
    p_reviews.add_argument("--anno", type=int, default=2026)
    p_reviews.add_argument(
        "--report", action="store_true", help="Invia report settimanale"
    )
    p_reviews.add_argument(
        "--start", type=str, help="Override start date report (YYYY-MM-DD)"
    )
    p_reviews.add_argument(
        "--end", type=str, help="Override end date report (YYYY-MM-DD)"
    )
    p_reviews.add_argument(
        "--dry-run", action="store_true", help="Preview senza azioni"
    )

    # ── Workspace (Gmail/Drive via DWD service account) ─────────────────────
    p_ws = sub.add_parser(
        "workspace",
        help="Workspace API ops (Gmail/Drive via service account DWD)",
    )
    ws_sub = p_ws.add_subparsers(dest="workspace_action")
    p_mc = ws_sub.add_parser(
        "mine-capex",
        help="Mine email threads + attachments for a CapEx project",
    )
    p_mc.add_argument(
        "--project", required=True, help="Project code (es. HPAN25PIANO1)"
    )
    p_mc.add_argument(
        "--mailboxes",
        required=True,
        help="Comma-separated emails (es. gm@panoramagroup.it,amministrazione@panoramagroup.it)",
    )
    p_mc.add_argument(
        "--output-folder",
        required=True,
        help="Drive folder ID (must be shared with workspace-controller SA as Editor)",
    )
    p_mc.add_argument(
        "--keywords",
        help="Comma-separated project keywords (default: project-specific built-in)",
    )
    p_mc.add_argument(
        "--fuzzy",
        help="Comma-separated fuzzy keywords for Pass 3 (es. preventivo,offerta). Off by default.",
    )
    p_mc.add_argument(
        "--extra",
        help="Extra Gmail query filter appended to passes (es. 'after:2024/01/01')",
    )
    p_mc.add_argument(
        "--dry-run", action="store_true", help="Search only, no Drive uploads"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "intake": cmd_intake,
        "promote": cmd_promote,
        "lineage": cmd_lineage_dispatch,
        "reviews": cmd_reviews,
        "workspace": cmd_workspace,
    }
    handler = handlers.get(args.command)
    if handler is None:
        print(f"Comando non implementato: {args.command}", file=sys.stderr)
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
