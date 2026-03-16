"""
Fix broken Obsidian links in entity files.

Old format: [[Notion/daily/2024-04-20|Title]]
New format: [[Notion/daily/2024-04-20_Safe_Title|Title]]
"""
import re
from pathlib import Path
import os

VAULT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault",
))
DAILY_DIR = VAULT / "Notion" / "daily"
ONTOLOGY_ROOT = VAULT / "HotelOps" / "ontology"

# Build date → filename stem map (one date may have multiple files — pick first)
def build_date_map() -> dict[str, str]:
    date_map: dict[str, str] = {}
    for f in sorted(DAILY_DIR.glob("*.md")):
        date_prefix = f.stem[:10]  # YYYY-MM-DD
        if date_prefix not in date_map:
            date_map[date_prefix] = f.stem
    return date_map

# Regex: [[Notion/daily/YYYY-MM-DD|...]]  (no underscore after date = broken)
BROKEN_LINK = re.compile(r'\[\[Notion/daily/(\d{4}-\d{2}-\d{2})\|([^\]]*)\]\]')

def fix_file(path: Path, date_map: dict[str, str]) -> int:
    content = path.read_text(encoding="utf-8")
    fixes = 0

    def replace(m: re.Match) -> str:
        nonlocal fixes
        date = m.group(1)
        label = m.group(2)
        if date in date_map:
            stem = date_map[date]
            fixes += 1
            return f"[[Notion/daily/{stem}|{label}]]"
        return m.group(0)  # leave unchanged if no file found

    new_content = BROKEN_LINK.sub(replace, content)
    if fixes:
        path.write_text(new_content, encoding="utf-8")
    return fixes

def main():
    date_map = build_date_map()
    print(f"Date map: {len(date_map)} dates → files")

    total = 0
    for md in ONTOLOGY_ROOT.rglob("*.md"):
        fixed = fix_file(md, date_map)
        if fixed:
            print(f"  ✓ {md.name}: {fixed} link(s) fixed")
            total += fixed

    print(f"\nTotal links fixed: {total}")

if __name__ == "__main__":
    main()
