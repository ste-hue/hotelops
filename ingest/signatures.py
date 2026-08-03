#!/usr/bin/env python3
"""Valutatore di firme dichiarative da core/registry.yaml.

Identifica un file dal contenuto — nome foglio + prefisso della riga d'header —
invece che dal nome, che negli export Power BI è rumore del browser
("data.xlsx", "Data from Power BI (3).xlsx").

Gira DAVANTI ai detector Python di `ingest.classify`: se nessuna firma matcha,
il vecchio percorso resta la rete.

Grammatiche supportate: `sheets` (foglio richiesto) e `structure.header_prefix`
(prefisso esatto della prima riga). Una entry che usa qualsiasi altro tipo —
`columns`, `filename`, `content`, `structure.header_0_2` — viene SALTATA: sono
le categorie legacy, che restano ai loro detector Python finché non migrano.

Spec: docs/superpowers/specs/2026-08-03-motore-identificazione-content-first-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("ingest.signatures")

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "core" / "registry.yaml"

_SUPPORTED_TYPES = {"sheets", "structure"}
_SUPPORTED_STRUCTURE_KEYS = {"header_prefix"}


class AmbiguousSignature(Exception):
    """Due o più entry matchano lo stesso file — il registry è incoerente."""


@dataclass(frozen=True)
class _View:
    """Ciò che una firma può leggere: foglio effettivo + riga d'header."""

    sheet_used: str
    header: tuple[str, ...]


def load_file_types(path: Optional[Path] = None) -> dict:
    """Carica la sezione `file_types` di core/registry.yaml."""
    p = path or REGISTRY_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("file_types") or {}


def _entry_is_supported(entry: dict) -> bool:
    """True se TUTTE le firme della entry usano grammatiche che sappiamo valutare."""
    sigs = entry.get("signatures") or []
    if not sigs:
        return False
    for sig in sigs:
        if sig.get("type") not in _SUPPORTED_TYPES:
            return False
        if sig["type"] == "structure":
            if not (set(sig) - {"type"}) <= _SUPPORTED_STRUCTURE_KEYS:
                return False
    return True


def _required_sheet(entry: dict) -> Optional[str]:
    for sig in entry["signatures"]:
        if sig.get("type") == "sheets":
            required = sig.get("required") or []
            if required:
                return required[0]
    return None


def _read_view(path: Path, sheet: Optional[str]) -> Optional[_View]:
    # Import locale: ingest.classify importa questo modulo, un import a livello
    # di modulo creerebbe un ciclo a import-time.
    from ingest.classify import _read_xlsx_sample

    rows, used = _read_xlsx_sample(path, sheet_name=sheet, max_rows=1)
    if not rows:
        return None
    header = tuple(str(c).strip() if c is not None else "" for c in rows[0])
    return _View(sheet_used=used, header=header)


def matches(path: Path, entry: dict, _cache: Optional[dict] = None) -> bool:
    """True se il file soddisfa TUTTE le firme della entry.

    `_cache` evita di riaprire il file per ogni entry: `identify` ne passa uno
    condiviso, indicizzato per nome foglio richiesto.
    """
    if not _entry_is_supported(entry):
        return False
    formats = entry.get("formats") or []
    if formats and path.suffix.lower() not in [f.lower() for f in formats]:
        return False

    sheet = _required_sheet(entry)
    if _cache is None:
        _cache = {}
    if sheet not in _cache:
        _cache[sheet] = _read_view(path, sheet)
    view = _cache[sheet]
    if view is None:
        return False

    for sig in entry["signatures"]:
        if sig["type"] == "sheets":
            required = sig.get("required") or []
            if required and view.sheet_used != required[0]:
                return False
        elif sig["type"] == "structure":
            prefix = sig["header_prefix"]
            if list(view.header[: len(prefix)]) != list(prefix):
                return False
    return True


def identify(path: Path, file_types: Optional[dict] = None) -> Optional[str]:
    """Ritorna la detector_category che matcha il file, o None.

    Solleva AmbiguousSignature se più di una entry matcha: due report
    indistinguibili sono un errore di configurazione, non un tie-break.
    """
    ft = file_types if file_types is not None else load_file_types()
    cache: dict = {}
    hits = [cat for cat, entry in ft.items() if matches(path, entry, cache)]
    if len(hits) > 1:
        raise AmbiguousSignature(f"{path.name} matcha più categorie: {sorted(hits)}")
    return hits[0] if hits else None
