"""
Standardize all entity files to canonical template:

---
type: ...
status: active
role: ...          (if applicable)
societa: ...       (if applicable)
business_unit: ... (if applicable)
first_seen: ...
last_seen: ...
---

# Name

## Relazioni    ← merged from ## Related
## Fatti        ← merged from ## Timeline (if has content) + existing ## Fatti
## Note         ← merged from ## Notes + existing ## Note
"""
import re
import yaml
from pathlib import Path
import os

VAULT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault",
))
ONTOLOGY_ROOT = VAULT / "HotelOps" / "ontology"

FM_KEY_ORDER = ["type", "status", "role", "societa", "business_unit", "first_seen", "last_seen"]


def parse_fm(content: str) -> tuple[dict, str]:
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(content[4:end]) or {}
                return fm, content[end + 5:]
            except yaml.YAMLError:
                pass
    return {}, content


def render_fm(fm: dict) -> str:
    ordered = {}
    for k in FM_KEY_ORDER:
        if k in fm:
            ordered[k] = fm[k]
    for k, v in fm.items():
        if k not in ordered:
            ordered[k] = v
    return "---\n" + yaml.dump(ordered, allow_unicode=True, default_flow_style=False) + "---\n"


def extract_section(body: str, heading: str) -> str:
    """Extract content under a ## heading (until next ## or end)."""
    pattern = rf'## {re.escape(heading)}\n(.*?)(?=\n## |\Z)'
    m = re.search(pattern, body, re.DOTALL)
    return m.group(1).strip() if m else ""


def remove_section(body: str, heading: str) -> str:
    """Remove a ## heading and its content."""
    return re.sub(rf'\n## {re.escape(heading)}\n.*?(?=\n## |\Z)', '', body, flags=re.DOTALL)


def remove_embedded_fm(body: str) -> str:
    """Remove any stray ---...--- frontmatter blocks embedded in the body."""
    return re.sub(r'\n---\n.*?\n---\n', '\n', body, flags=re.DOTALL)


def is_empty(text: str) -> bool:
    return not text.strip()


def standardize_file(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    fm, body = parse_fm(content)

    if not fm:
        return False  # skip files without frontmatter

    changed = False

    # Fix embedded frontmatter in body (e.g. INTUR has a second ---...--- block)
    cleaned_body = remove_embedded_fm(body)
    if cleaned_body != body:
        body = cleaned_body
        changed = True

    # --- Merge ## Related → ## Relazioni ---
    related_content = extract_section(body, "Related")
    relazioni_content = extract_section(body, "Relazioni")
    if "## Related" in body:
        body = remove_section(body, "Related")
        merged_rel = "\n".join(filter(None, [relazioni_content, related_content])).strip()
        body = remove_section(body, "Relazioni")
        body = body.rstrip() + f"\n\n## Relazioni\n{merged_rel}\n" if merged_rel else body.rstrip() + "\n\n## Relazioni\n"
        changed = True

    # --- Merge ## Notes + ## Note → ## Note ---
    notes_content = extract_section(body, "Notes")
    note_content = extract_section(body, "Note")
    if "## Notes" in body:
        body = remove_section(body, "Notes")
        merged_note = "\n".join(filter(None, [note_content, notes_content])).strip()
        body = remove_section(body, "Note")
        body = body.rstrip() + f"\n\n## Note\n{merged_note}\n" if merged_note else body.rstrip() + "\n\n## Note\n"
        changed = True

    # --- Merge ## Timeline → ## Fatti (only if Timeline has content) ---
    timeline_content = extract_section(body, "Timeline")
    if "## Timeline" in body:
        body = remove_section(body, "Timeline")
        if not is_empty(timeline_content):
            fatti_content = extract_section(body, "Fatti")
            body = remove_section(body, "Fatti")
            merged_fatti = "\n".join(filter(None, [fatti_content, timeline_content])).strip()
            body = body.rstrip() + f"\n\n## Fatti\n{merged_fatti}\n"
        changed = True

    # --- Ensure canonical sections exist in order ---
    for section in ["## Relazioni", "## Fatti", "## Note"]:
        if section not in body:
            body = body.rstrip() + f"\n\n{section}\n"
            changed = True

    # --- Reorder sections: put canonical ones at end ---
    # Extract all three
    relazioni = extract_section(body, "Relazioni")
    fatti = extract_section(body, "Fatti")
    note = extract_section(body, "Note")

    # Remove them from body
    for s in ["Relazioni", "Fatti", "Note"]:
        body = remove_section(body, s)

    # Re-append in order
    body = body.rstrip()
    body += f"\n\n## Relazioni\n{relazioni}\n" if relazioni.strip() else "\n\n## Relazioni\n"
    body += f"\n## Fatti\n{fatti}\n" if fatti.strip() else "\n## Fatti\n"
    body += f"\n## Note\n{note}\n" if note.strip() else "\n## Note\n"

    if changed:
        path.write_text(render_fm(fm) + body, encoding="utf-8")

    return changed


def main():
    total = 0
    for md in sorted(ONTOLOGY_ROOT.rglob("*.md")):
        if md.stem.startswith("_"):
            continue
        if standardize_file(md):
            rel = md.relative_to(ONTOLOGY_ROOT)
            print(f"  ✓ {rel}")
            total += 1
    print(f"\nStandardized: {total} files")


if __name__ == "__main__":
    main()
