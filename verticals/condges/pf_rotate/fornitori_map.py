"""Loader / persister per d_fornitori.csv (schema v2 con societa_id + esclusione)."""

from __future__ import annotations

import csv
from pathlib import Path

from core.schemas import FornitoreMapRow


def _to_bool(s) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes")


def load_fornitori(csv_path: Path, societa: str) -> dict[int, FornitoreMapRow]:
    """Read d_fornitori.csv, filtered by societa_id. Returns {codice: row}."""
    result: dict[int, FornitoreMapRow] = {}
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("societa_id") or "").strip().upper() != societa.upper():
                continue
            row = FornitoreMapRow(
                codice_fornitore=int(r["codice_fornitore"]),
                nome_esolver=r.get("nome_esolver", "") or "",
                nome_pf=r.get("nome_pf", "") or "",
                voce_id=r.get("voce_id", "") or "",
                is_intercompany=_to_bool(r.get("is_intercompany", "False")),
                is_excluded=_to_bool(r.get("is_excluded", "False")),
                exclude_reason=r.get("exclude_reason", "") or "",
                societa_id=r["societa_id"],
            )
            result[row.codice_fornitore] = row
    return result


def append_fornitore(
    csv_path: Path,
    *,
    codice_fornitore: int,
    nome_esolver: str,
    nome_pf: str,
    voce_id: str,
    societa_id: str,
    is_excluded: bool = False,
    exclude_reason: str = "",
    is_intercompany: bool = False,
) -> None:
    """Append a new row. Validates via Pydantic before writing."""
    row = FornitoreMapRow(
        codice_fornitore=codice_fornitore,
        nome_esolver=nome_esolver,
        nome_pf=nome_pf,
        voce_id=voce_id,
        is_intercompany=is_intercompany,
        is_excluded=is_excluded,
        exclude_reason=exclude_reason,
        societa_id=societa_id,
    )
    line = (
        ",".join(
            [
                str(row.codice_fornitore),
                row.nome_esolver,
                row.nome_pf,
                row.voce_id,
                str(row.is_intercompany),
                str(row.is_excluded),
                row.exclude_reason,
                row.societa_id,
            ]
        )
        + "\n"
    )
    with Path(csv_path).open("a", encoding="utf-8") as f:
        f.write(line)
