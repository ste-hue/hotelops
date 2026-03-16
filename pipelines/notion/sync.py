"""
notion-sync: fetch Notion journal entries and write to Obsidian vault.

Usage:
    python -m pipelines.notion.sync              # last 7 days
    python -m pipelines.notion.sync --days 30    # last 30 days
    python -m pipelines.notion.sync --from 2026-03-01 --to 2026-03-13
    python -m pipelines.notion.sync --today      # today only
    python -m pipelines.notion.sync --dry-run    # print without writing
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
import os

VAULT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
))
DAILY_DIR = VAULT / "Notion" / "daily"


def build_frontmatter(entry_date: date, title: str, tags: list[str], page_id: str) -> str:
    tags_str = ", ".join(f'"{t}"' for t in tags) if tags else ""
    return f"""---
date: {entry_date.isoformat()}
title: "{title}"
tags: [{tags_str}]
notion_id: "{page_id}"
source: notion
---
"""


def sync_entries(from_date: date, to_date: date, dry_run: bool = False) -> int:
    from pipelines.notion.client import iter_journal_entries, get_page_blocks, blocks_to_markdown
    from pipelines.notion.entity_extractor import extract_and_update

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    for page in iter_journal_entries(from_date, to_date):
        props = page["properties"]
        page_id = page["id"]

        title_parts = props["Name"]["title"]
        title = title_parts[0]["plain_text"] if title_parts else "(no title)"

        date_val = props["data"]["date"]
        if not date_val or not date_val.get("start"):
            continue
        raw_date = date_val["start"]
        # Handle both "2025-06-01" and "2025-05-31T09:25:00.000+02:00"
        entry_date = date.fromisoformat(raw_date[:10])

        tags = [t["name"] for t in props["Tags"]["multi_select"]]

        # Fetch content
        blocks = get_page_blocks(page_id)
        body = blocks_to_markdown(blocks)

        # Build the markdown file
        fm = build_frontmatter(entry_date, title, tags, page_id)
        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in "- " else "_" for c in title).strip()[:60]
        filename = f"{entry_date.isoformat()}_{safe_title}.md"
        dest = DAILY_DIR / filename

        full_content = fm + f"\n# {title}\n\n" + body

        if dry_run:
            print(f"[DRY] {dest.name}")
            print(full_content[:300])
            print("---")
        else:
            dest.write_text(full_content, encoding="utf-8")
            # Extract entities and update ontology
            updated = extract_and_update(entry_date, title, body, filename=filename)
            status = f"  entities: {', '.join(updated)}" if updated else ""
            print(f"✓ {dest.name}{status}")

        count += 1

    return count


def main():
    parser = argparse.ArgumentParser(description="Sync Notion journal → Obsidian vault")
    parser.add_argument("--days", type=int, default=7, help="Last N days (default: 7)")
    parser.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--today", action="store_true", help="Only today")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    today = date.today()

    if args.today:
        from_date = to_date = today
    elif args.from_date:
        from_date = date.fromisoformat(args.from_date)
        to_date = date.fromisoformat(args.to_date) if args.to_date else today
    else:
        from_date = today - timedelta(days=args.days)
        to_date = today

    print(f"Syncing Notion journal {from_date} → {to_date} {'[DRY RUN]' if args.dry_run else ''}")
    count = sync_entries(from_date, to_date, dry_run=args.dry_run)
    print(f"\nDone: {count} entries processed")


if __name__ == "__main__":
    main()
