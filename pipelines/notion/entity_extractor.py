"""
Extract entity mentions from Notion markdown and update Obsidian ontology.

Quality rules:
- Only KNOWN entities (already in ontology) get updated → no garbage auto-created
- Unknown names → logged to _candidates.md for human review
- Every entity gets last_seen + status frontmatter kept up to date
- status lifecycle: draft → active → stale → archived
"""
import re
import os
from pathlib import Path
from datetime import date, timedelta
from typing import Optional
import yaml

VAULT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault",
))
ONTOLOGY_ROOT = VAULT / "HotelOps" / "ontology"
CANDIDATES_FILE = ONTOLOGY_ROOT / "_candidates.md"

# How many days without a mention before an entity becomes stale
STALE_DAYS = 60

# Alias map: lowercase alias → canonical file stem (must exist in ontology)
ALIASES: dict[str, str] = {
    # People
    "amalia": "Amalia_Pisacane",
    "amalia pisacane": "Amalia_Pisacane",
    "antonio russo": "Antonio_Russo",
    "masotti": "Masotti",
    "romita": "Rocco_Romita",
    "rocco romita": "Rocco_Romita",
    "serini": "Serini_Masotti",
    "dino": "Dino",
    "marco pignocchi": "Marco_Pignocchi",
    "savio": "Savio_Marigliano",
    "salvatore marigliano": "Savio_Marigliano",
    "marigliano": "Savio_Marigliano",
    "filippo covili": "Corso_Gasparotto",
    "corso gasparotto": "Corso_Gasparotto",
    "rosa": "Rosa",
    "anna ausiello": "Anna_Ausiello",
    "anna farina": "Anna_Farina",
    "anna capone": "Anna_Capone",
    # Companies
    "intur": "INTUR",
    "intur srl": "INTUR",
    "orti": "ORTI",
    "orti srl": "ORTI",
    "coperama": "SANTELIA",
    "stefano perlini": "SANTELIA",
    # Banks
    "mps": "MPS",
    "monte dei paschi": "MPS",
    "intesa": "Banca_Intesa",
    "intesa sanpaolo": "Banca_Intesa",
    "sella": "Sella",
    "banca sella": "Sella",
    # Projects
    "camere primo piano": "CamerePrimoPiano",
    "hpan25piano1": "CamerePrimoPiano",
    "piano 1": "CamerePrimoPiano",
    # Advisors
    "miano": "Antonio_Miano",
    "antonio miano": "Antonio_Miano",
}

# Ambiguous single-word names that need context — require at least one co-occurring keyword
AMBIGUOUS: dict[str, list[str]] = {
    "antonio": ["russo", "email", "riunione", "cantiere", "segnaletica", "risposta"],
    "marco": ["pignocchi", "preventivo", "riunione", "cantiere"],
    "anna": ["ausiello", "farina", "capone", "email"],
    "filippo": ["covili", "arredi", "armadi"],
    "salvatore": ["marigliano", "viabilità", "impiantistico"],
}


def _has_context(alias: str, text_lower: str, idx: int) -> bool:
    """For ambiguous names, check if any disambiguating keyword is nearby."""
    if alias not in AMBIGUOUS:
        return True
    window_start = max(0, idx - 150)
    window_end = min(len(text_lower), idx + 150)
    window = text_lower[window_start:window_end]
    return any(kw in window for kw in AMBIGUOUS[alias])


# ── Frontmatter helpers ────────────────────────────────────────────────────────

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_without_frontmatter)."""
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(content[4:end]) or {}
                return fm, content[end + 5:]
            except yaml.YAMLError:
                pass
    return {}, content


def _render_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n"


def _ensure_frontmatter(path: Path, today: date) -> tuple[dict, str]:
    """Read entity file, ensure frontmatter exists with lifecycle fields."""
    content = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(content)

    # Add missing lifecycle fields
    if "status" not in fm:
        fm["status"] = "active"
    if "first_seen" not in fm:
        fm["first_seen"] = today.isoformat()
    if "last_seen" not in fm:
        fm["last_seen"] = today.isoformat()

    return fm, body


def _write_entity(path: Path, fm: dict, body: str):
    path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")


# ── Candidate logging ──────────────────────────────────────────────────────────

def _log_candidate(name: str, context: str, entry_date: date):
    """Log an unknown entity mention to _candidates.md."""
    CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {entry_date.isoformat()} | `{name}` | {context[:100]}\n"

    if CANDIDATES_FILE.exists():
        existing = CANDIDATES_FILE.read_text(encoding="utf-8")
        # Don't duplicate
        if name.lower() in existing.lower():
            return
        CANDIDATES_FILE.write_text(existing + line, encoding="utf-8")
    else:
        header = "# Entity Candidates\n\nNomi non ancora in ontologia. Revisione manuale necessaria.\n\n"
        CANDIDATES_FILE.write_text(header + line, encoding="utf-8")


# ── Main extraction ────────────────────────────────────────────────────────────

def load_known_entities() -> dict[str, Path]:
    """Return {stem: Path} for all .md files in ontology (excluding underscored meta files)."""
    entities: dict[str, Path] = {}
    if not ONTOLOGY_ROOT.exists():
        return entities
    for md in ONTOLOGY_ROOT.rglob("*.md"):
        if not md.stem.startswith("_"):
            entities[md.stem] = md
    return entities


def extract_mentions(text: str, known: dict[str, Path]) -> list[tuple[str, Path]]:
    """Return (alias, path) for each known entity found in text, with quality gates."""
    text_lower = text.lower()
    found: list[tuple[str, Path]] = []
    seen_stems: set[str] = set()

    # Longer aliases first to avoid partial matches
    for alias in sorted(ALIASES.keys(), key=len, reverse=True):
        idx = text_lower.find(alias)
        if idx == -1:
            continue
        if not _has_context(alias, text_lower, idx):
            continue
        stem = ALIASES[alias]
        if stem in seen_stems:
            continue
        path = known.get(stem)
        if path and path.exists():
            found.append((alias, path))
            seen_stems.add(stem)

    return found


def _clean_snippet(text: str, alias: str, idx: int) -> str:
    """Extract a clean, readable sentence fragment around the alias."""
    # Find sentence boundaries
    start = max(0, idx - 60)
    end = min(len(text), idx + len(alias) + 100)
    snippet = text[start:end].replace("\n", " ").strip()
    # Remove leading partial word
    if start > 0 and snippet and not snippet[0].isupper() and snippet[0] != '-':
        space = snippet.find(' ')
        if space != -1 and space < 20:
            snippet = snippet[space + 1:]
    return snippet[:140]


def touch_entity(path: Path, event_date: date):
    """Update last_seen and status only — no raw event appending."""
    fm, body = _ensure_frontmatter(path, event_date)

    # Only advance last_seen, never go back
    current_last = fm.get("last_seen")
    if not current_last or event_date.isoformat() > str(current_last):
        fm["last_seen"] = event_date.isoformat()
    # first_seen = earliest known date
    current_first = fm.get("first_seen")
    if not current_first or event_date.isoformat() < str(current_first):
        fm["first_seen"] = event_date.isoformat()
    if fm.get("status") == "stale":
        fm["status"] = "active"

    _write_entity(path, fm, body)


def extract_and_update(entry_date: date, title: str, markdown: str, filename: str = "") -> list[str]:
    """
    Scan markdown for entity mentions → update Obsidian files.
    Returns list of updated entity stems.
    """
    known = load_known_entities()
    mentions = extract_mentions(markdown, known)
    updated = []

    for alias, path in mentions:
        touch_entity(path, entry_date)
        updated.append(path.stem)

    return updated


# ── Staleness check ────────────────────────────────────────────────────────────

def check_stale(threshold_days: int = STALE_DAYS) -> list[tuple[str, date, str]]:
    """
    Scan all entity files and return list of (stem, last_seen, status)
    for entities that haven't been mentioned recently.
    """
    today = date.today()
    known = load_known_entities()
    stale: list[tuple[str, date, str]] = []

    for stem, path in known.items():
        content = path.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(content)
        last_seen_raw = fm.get("last_seen")
        status = fm.get("status", "unknown")

        if status == "archived":
            continue  # archived are intentionally inactive

        if last_seen_raw:
            last_seen = date.fromisoformat(str(last_seen_raw))
            days_ago = (today - last_seen).days
            if days_ago > threshold_days:
                stale.append((stem, last_seen, status))
                # Auto-mark as stale in the file
                if status == "active":
                    fm["status"] = "stale"
                    body_content = content
                    _, body = _parse_frontmatter(body_content)
                    _write_entity(path, fm, body)

    return sorted(stale, key=lambda x: x[1])
