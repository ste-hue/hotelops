from __future__ import annotations

import sys

from .miners.capex_emails import mine_capex_project


def cmd_workspace(args):
    """Dispatch `hotelops workspace ...` subactions."""
    if args.workspace_action == "mine-capex":
        _mine_capex(args)
    elif args.workspace_action == "mine-dossier":
        _mine_dossier(args)
    else:
        print(f"Unknown workspace action: {args.workspace_action}", file=sys.stderr)
        sys.exit(1)


def _mine_capex(args):
    mailboxes = [m.strip() for m in args.mailboxes.split(",") if m.strip()]
    project_keywords = (
        [k.strip() for k in args.keywords.split(",")] if args.keywords else None
    )
    fuzzy_keywords = (
        [k.strip() for k in args.fuzzy.split(",")] if args.fuzzy else None
    )

    print(f"\n{'═' * 70}")
    print(f"  CapEx mine — project: {args.project}")
    print(f"  Mailboxes: {mailboxes}")
    print(f"  Drive parent: {args.output_folder}")
    if args.dry_run:
        print("  DRY RUN")
    print(f"{'═' * 70}")

    result = mine_capex_project(
        project_code=args.project,
        mailboxes=mailboxes,
        drive_parent_id=args.output_folder,
        write_as=args.write_as,
        project_keywords=project_keywords,
        fuzzy_keywords=fuzzy_keywords,
        extra_filters=args.extra or "",
        dry_run=args.dry_run,
    )

    print(f"\n{'─' * 70}")
    print(f"  Run folder: {result['run_folder_name']}")
    for r in result["mailboxes"]:
        if r.get("dry_run"):
            print(
                f"  {r['mailbox']:<40s} "
                f"P1: {r.get('pass1_messages', 0)} msg / "
                f"{r.get('pass1_threads', 0)} threads, "
                f"P3: {r.get('pass3_threads', 0)} threads (dry-run)"
            )
        else:
            print(
                f"  {r['mailbox']:<40s} "
                f"Certo: {r.get('pass1_threads', 0)} threads, "
                f"Rivedere: {r.get('pass3_threads', 0)}, "
                f"Att: {r.get('attachments', 0)}"
            )
    print(f"{'─' * 70}\n")


def _mine_dossier(args):
    from pathlib import Path

    from .directory import enumerate_domain_users
    from .dossier_config import COMPANIES, DIRECTORY_SUBJECT, DOSSIER_STATE_DIR
    from .miners.dossier_apply import apply_census
    from .miners.dossier_census import run_census
    from .miners.dossier_index import build_index_xlsx, upload_index

    company = COMPANIES[args.company.upper()]
    out_dir = Path(args.out) if args.out else DOSSIER_STATE_DIR
    census_path = out_dir / f"census_{company.company_id}.jsonl"

    if args.apply:
        result = apply_census(company, census_path, dry_run=args.dry_run)
        print(f"\n  applied={result['applied']} planned={result.get('planned')} "
              f"skipped={result['skipped']} failed={len(result['failed'])}")
        for f in result["failed"]:
            print(f"  FAIL {f['name']}: {f['error']}")
        return

    if args.users:
        users = [{"email": u.strip(), "suspended": False}
                 for u in args.users.split(",") if u.strip()]
    else:
        users = enumerate_domain_users(DIRECTORY_SUBJECT)
    print(f"  Census {company.company_id} su {len(users)} utenti…")
    res = run_census(company, users, out_dir)
    print(f"  {len(res['items'])} documenti unici → {res['census_path']}")
    for cat, n in sorted(res["by_category"].items()):
        print(f"    {cat:<22s} {n}")
    if res["inaccessible"]:
        print(f"  Non accessibili: {', '.join(res['inaccessible'])}")
    xlsx = build_index_xlsx(res["items"], res["inaccessible"])
    file_id = upload_index(company, xlsx)
    print(f"  Indice caricato: https://drive.google.com/file/d/{file_id}/view")
