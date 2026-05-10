from __future__ import annotations

import sys

from .miners.capex_emails import mine_capex_project


def cmd_workspace(args):
    """Dispatch `hotelops workspace ...` subactions."""
    if args.workspace_action == "mine-capex":
        _mine_capex(args)
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
