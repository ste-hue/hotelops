"""
Clean entity files in Obsidian ontology:
- Remove raw ## Eventi dump sections
- Add 'type' to frontmatter from schema folder mapping
- Ensure standard sections: Relazioni, Fatti, Note
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

FOLDER_TYPE = {
    "people":    "Persona",
    "companies": "Societa",
    "banks":     "Banca",
    "advisors":  "Consulente",
    "departments": "Reparto",
    "projects":  "Progetto",
    "loans":     "Strumento_Finanziario",
    "financial": "Strumento_Finanziario",
    "assets":    "Struttura",
}

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
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n"

def strip_eventi(body: str) -> str:
    """Remove ## Eventi section and everything under it until next ## or end."""
    return re.sub(r'\n## Eventi\n.*?(?=\n## |\Z)', '', body, flags=re.DOTALL).rstrip()

def ensure_sections(body: str) -> str:
    """Ensure ## Relazioni, ## Fatti, ## Note exist (add if missing)."""
    for section in ["## Relazioni", "## Fatti", "## Note"]:
        if section not in body:
            body = body.rstrip() + f"\n\n{section}\n"
    return body

def clean_file(path: Path, entity_type: str) -> bool:
    content = path.read_text(encoding="utf-8")
    fm, body = parse_fm(content)

    changed = False

    # Add type if missing
    if "type" not in fm:
        fm["type"] = entity_type
        changed = True

    # Remove status/first_seen/last_seen from frontmatter display clutter
    # Keep them — they're useful for agents

    # Strip ## Eventi
    new_body = strip_eventi(body)
    if new_body != body:
        changed = True
        body = new_body

    # Ensure standard sections
    new_body = ensure_sections(body)
    if new_body != body:
        changed = True
        body = new_body

    if changed:
        path.write_text(render_fm(fm) + body + "\n", encoding="utf-8")

    return changed

def main():
    total = 0
    for folder, etype in FOLDER_TYPE.items():
        folder_path = ONTOLOGY_ROOT / folder
        if not folder_path.exists():
            continue
        for md in sorted(folder_path.glob("*.md")):
            if md.stem.startswith("_"):
                continue
            if clean_file(md, etype):
                print(f"  ✓ {folder}/{md.name}")
                total += 1
    print(f"\nCleaned: {total} entity files")

if __name__ == "__main__":
    main()
