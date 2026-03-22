"""
stale-check: report entities that haven't been mentioned recently.

Usage:
    python -m pipelines.notion.stale_check           # default 60 days
    python -m pipelines.notion.stale_check --days 30
    python -m pipelines.notion.stale_check --fix     # auto-mark stale in frontmatter
"""
import argparse
from datetime import date
from pipelines.notion.entity_extractor import check_stale, STALE_DAYS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=STALE_DAYS,
                        help=f"Threshold days (default: {STALE_DAYS})")
    args = parser.parse_args()

    today = date.today()
    results = check_stale(threshold_days=args.days)

    if not results:
        print(f"✓ All entities seen within the last {args.days} days.")
        return

    print(f"\n⚠️  Entities not mentioned in >{args.days} days (auto-marked stale):\n")
    print(f"{'Entity':<35} {'Last seen':<12} {'Days ago':>8}  {'Status'}")
    print("-" * 65)
    for stem, last_seen, status in results:
        days_ago = (today - last_seen).days
        flag = "🔴" if days_ago > 180 else "🟡"
        print(f"{flag} {stem:<33} {last_seen.isoformat():<12} {days_ago:>8}  {status}")

    print(f"\nTotal stale: {len(results)}")
    print("→ Set status: archived in the entity file to suppress this warning.")
    print("→ Run notion-sync to refresh last_seen if the entity is still active.")


if __name__ == "__main__":
    main()
