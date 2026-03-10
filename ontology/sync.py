#!/usr/bin/env python3
"""
obsidian_sync - Parse Obsidian vault into knowledge.db (SQLite).

Reads all .md files from the HotelOps Obsidian vault, extracts:
- YAML frontmatter -> node attributes
- [[wiki links]] -> edges between nodes
- Folder location -> fallback entity type

Output: knowledge.db with two tables (nodes, edges).
Fully regenerable - deletes and rebuilds on every run.

Usage:
    python -m ontology.sync --vault /path/to/vault --db /path/to/knowledge.db
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import yaml


# -- Config -------------------------------------------------------------------

# Files/folders to skip (not entities)
SKIP_FILES = {"_index.md"}
SKIP_FOLDERS = {"strategia", "events", "decisions"}

# Frontmatter type → canonical entity type normalization
TYPE_NORMALIZE = {
    "company": "Societa",
    "person": "Persona",
    "bank": "Banca",
    "banca": "Banca",
    "department": "Reparto",
    "financial_instrument": "Strumento_Finanziario",
    "financial_analysis": "Strumento_Finanziario",
    "advisor": "Consulente",
    "consulente": "Consulente",
    "project": "Progetto",
    "progetto": "Progetto",
    "contract": "Contratto",
    "fornitore": "Fornitore",
    "supplier": "Fornitore",
    "struttura": "Struttura",
    "asset": "Struttura",
    "gruppo_consolidato": "Societa",
    "executive_summary": "Documento",
    "relationship_map": "Documento",
    "procedure": "Documento",
    "protocol": "Documento",
    "entity_review": "Documento",
    "strategy": "Documento",
    "supplier_strategy": "Documento",
}

# Folder → fallback type (from schema.yaml folder_type_map)
FOLDER_TYPE_MAP = {
    "companies": "Societa",
    "banks": "Banca",
    "people": "Persona",
    "advisors": "Consulente",
    "departments": "Reparto",
    "financial": "Strumento_Finanziario",
    "loans": "Strumento_Finanziario",
    "projects": "Progetto",
    "assets": "Struttura",
    "relationships": "Documento",
    "procedures": "Documento",
    "protocols": "Documento",
}


# -- Schema -------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    source_file TEXT NOT NULL,
    metadata JSON
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT DEFAULT 'references',
    context TEXT,
    UNIQUE(source_id, target_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
"""


# -- Parsing ------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def slugify(name: str) -> str:
    """Convert a note name to a stable ID."""
    s = name.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    s = s.strip("_")
    return s


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content."""
    m = FRONTMATTER_RE.search(content)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def extract_links(content: str) -> list[str]:
    """Extract all [[wiki links]] from markdown content."""
    return WIKILINK_RE.findall(content)


def infer_type_from_folder(file_path: Path, vault_root: Path) -> str:
    """Infer entity type from the file's parent folder."""
    rel = file_path.relative_to(vault_root)
    parts = rel.parts
    # Look for ontology subfolder: ontology/companies/X.md → "companies"
    if "ontology" in parts:
        idx = parts.index("ontology")
        if idx + 1 < len(parts) - 1:  # there's a subfolder after "ontology"
            folder = parts[idx + 1]
            return FOLDER_TYPE_MAP.get(folder, "Sconosciuto")
    # Top-level files
    for part in parts[:-1]:
        if part in FOLDER_TYPE_MAP:
            return FOLDER_TYPE_MAP[part]
    return "Documento"


def resolve_type(frontmatter: dict, file_path: Path, vault_root: Path) -> str:
    """Resolve entity type: frontmatter > folder > fallback."""
    fm_type = frontmatter.get("type", "")
    if fm_type:
        normalized = TYPE_NORMALIZE.get(fm_type.lower().strip(), fm_type)
        return normalized
    return infer_type_from_folder(file_path, vault_root)


def resolve_status(frontmatter: dict) -> str:
    """Resolve status from frontmatter."""
    raw = str(frontmatter.get("status", "active")).lower().strip()
    # Normalize emoji-prefixed statuses
    if "attivo" in raw or "active" in raw:
        return "active"
    if "inattivo" in raw or "inactive" in raw:
        return "inactive"
    if "candidate" in raw:
        return "candidate"
    return raw or "active"


def infer_relation(target_name: str, context_line: str, source_type: str) -> str:
    """Try to infer relation type from surrounding text context."""
    ctx = context_line.lower()

    # Explicit patterns
    if any(w in ctx for w in ("proprietario", "owner", "owns", "possiede")):
        return "owns"
    if any(w in ctx for w in ("operates", "gestisce", "gestito da", "operator")):
        return "operates"
    if any(w in ctx for w in ("employs", "dipendente", "head", "capo")):
        return "employs"
    if any(w in ctx for w in ("advises", "advisor", "consulente", "controller")):
        return "advises"
    if any(w in ctx for w in ("supplies", "fornitore", "contractor")):
        return "supplies"
    if any(w in ctx for w in ("lends", "lender", "banca", "finanziamento")):
        return "lends_to"
    if any(w in ctx for w in ("part_of", "parent", "division")):
        return "part_of"
    if any(w in ctx for w in ("tenant", "affitto", "rent")):
        return "tenant_of"
    if any(w in ctx for w in ("guarantees", "garanzia", "fideiussione", "garante", "guarantor")):
        return "guarantees"
    if any(w in ctx for w in ("manages", "project manager", "dl", "direzione lavori")):
        return "manages"
    if any(w in ctx for w in ("socio", "shareholder", "azionista", "capital")):
        return "shareholder"
    if any(w in ctx for w in ("borrower", "mutuatario")):
        return "borrows_from"

    return "references"


# -- Main sync ----------------------------------------------------------------

def scan_vault(vault_root: Path) -> list[dict]:
    """Scan all .md files and extract nodes + raw links."""
    nodes = []
    for md_file in sorted(vault_root.rglob("*.md")):
        if md_file.name in SKIP_FILES:
            continue
        rel = md_file.relative_to(vault_root)
        if any(part in SKIP_FOLDERS for part in rel.parts):
            continue

        content = md_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        note_name = md_file.stem
        node_id = slugify(note_name)

        entity_type = resolve_type(fm, md_file, vault_root)
        status = resolve_status(fm)

        # Metadata: everything from frontmatter except type/status
        metadata = {k: v for k, v in fm.items() if k not in ("type", "status")}

        # Extract links with context
        links_with_context = []
        for line in content.split("\n"):
            for link_target in WIKILINK_RE.findall(line):
                links_with_context.append((link_target, line))

        nodes.append({
            "id": node_id,
            "name": note_name.replace("_", " "),
            "type": entity_type,
            "status": status,
            "source_file": str(rel),
            "metadata": metadata,
            "links": links_with_context,
        })

    return nodes


def build_db(nodes: list[dict], db_path: Path) -> dict:
    """Write nodes and edges to SQLite. Returns summary stats."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Drop and rebuild
    conn.execute("DROP TABLE IF EXISTS edges")
    conn.execute("DROP TABLE IF EXISTS nodes")
    conn.executescript(SCHEMA)

    # Build node ID lookup for resolving links
    node_ids = {n["id"]: n for n in nodes}
    # Also build name → id map for link resolution
    name_to_id: dict[str, str] = {}
    for n in nodes:
        name_to_id[n["name"].lower()] = n["id"]
        name_to_id[n["id"]] = n["id"]
        # Also map the raw stem (with underscores)
        name_to_id[n["name"].lower().replace(" ", "_")] = n["id"]

    # Insert nodes
    for n in nodes:
        conn.execute(
            "INSERT OR REPLACE INTO nodes (id, name, type, status, source_file, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (n["id"], n["name"], n["type"], n["status"], n["source_file"],
             json.dumps(n["metadata"], ensure_ascii=False) if n["metadata"] else None),
        )

    # Insert edges
    edge_count = 0
    dangling = set()
    for n in nodes:
        for link_target, context_line in n["links"]:
            target_id = slugify(link_target)
            # Try to resolve
            resolved = name_to_id.get(target_id) or name_to_id.get(link_target.lower())
            if resolved:
                target_id = resolved

            relation = infer_relation(link_target, context_line, n["type"])

            if target_id not in node_ids:
                dangling.add(target_id)

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_id, relation, context) "
                    "VALUES (?, ?, ?, ?)",
                    (n["id"], target_id, relation, context_line.strip()[:200]),
                )
                edge_count += 1
            except sqlite3.IntegrityError:
                pass

    conn.commit()

    # Stats
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    type_counts = conn.execute(
        "SELECT type, COUNT(*) FROM nodes GROUP BY type ORDER BY COUNT(*) DESC"
    ).fetchall()
    relation_counts = conn.execute(
        "SELECT relation, COUNT(*) FROM edges GROUP BY relation ORDER BY COUNT(*) DESC"
    ).fetchall()

    conn.close()

    return {
        "nodes": node_count,
        "edges": edge_count,
        "dangling_targets": len(dangling),
        "types": dict(type_counts),
        "relations": dict(relation_counts),
        "dangling_sample": sorted(dangling)[:10],
    }


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sync Obsidian vault to knowledge.db")
    parser.add_argument(
        "--vault", required=True,
        help="Path to Obsidian HotelOps vault root")
    parser.add_argument(
        "--db", required=True,
        help="Path to output knowledge.db")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser()
    db_path = Path(args.db).expanduser()

    if not vault.exists():
        print(f"Vault not found: {vault}")
        sys.exit(1)

    print(f"Scanning vault: {vault}")
    nodes = scan_vault(vault)
    print(f"  Found {len(nodes)} notes")

    print(f"Building knowledge.db: {db_path}")
    stats = build_db(nodes, db_path)

    print()
    print(f"  Nodes: {stats['nodes']}")
    print(f"  Edges: {stats['edges']}")
    print(f"  Dangling targets: {stats['dangling_targets']}")
    print()
    print("  Types:")
    for t, c in stats["types"].items():
        print(f"    {t}: {c}")
    print()
    print("  Relations:")
    for r, c in stats["relations"].items():
        print(f"    {r}: {c}")

    if stats["dangling_sample"]:
        print()
        print("  Dangling targets (notes linked but not found):")
        for d in stats["dangling_sample"]:
            print(f"    - {d}")


if __name__ == "__main__":
    main()
