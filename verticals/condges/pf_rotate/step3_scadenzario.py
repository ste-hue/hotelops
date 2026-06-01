"""Step 3 — applicazione scadenzario sul PF, con policy esplicita su unmapped.

Riusa il motore di scrittura esistente `app_scadenzario.write_pf` ma:
- usa il nuovo loader filtrato per società (con is_excluded),
- impone una policy esplicita per i fornitori non mappati (no silent skip).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import pandas as pd

from verticals.condges.app_scadenzario import write_pf
from verticals.condges.pf_rotate.fornitori_map import load_fornitori


class UnmappedPolicy(str, Enum):
    FAIL = "fail"  # default per non-TTY
    REPORT = "report"  # solo report, no scrittura PF
    INTERACTIVE = "interactive"  # prompt CLI / UI bloccante (gestito dal caller)
    SKIP = "skip"  # salta unmapped (legacy)


class UnmappedFornitoriError(RuntimeError):
    def __init__(self, codici: list[int], detail: list[dict] | None = None):
        super().__init__(f"{len(codici)} fornitori non mappati: {codici[:5]}…")
        self.codici = codici
        self.detail = detail or []


def _build_legacy_fornitori_map(fornitori) -> dict[int, dict]:
    """Convert dict[int, FornitoreMapRow] -> dict[int, {voce_id, nome_pf}] per write_pf."""
    return {
        cod: {"voce_id": row.voce_id, "nome_pf": row.nome_pf}
        for cod, row in fornitori.items()
        if not row.is_excluded  # excluded → trattati come unmapped/skip da write_pf
    }


def apply_scadenzario(
    *,
    pf_bytes: bytes,
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    societa: str,
    fornitori_csv: Path,
    policy: UnmappedPolicy,
    extra_excluded: set[int] | None = None,
) -> tuple[bytes, dict]:
    """Applica lo scadenzario al PF, ritorna (xlsx bytes, summary dict)."""
    fornitori = load_fornitori(fornitori_csv, societa=societa)
    known_codici = set(fornitori.keys())
    excluded_codici = {c for c, r in fornitori.items() if r.is_excluded}

    scad_codici = {int(c) for c in scad_df["codice_fornitore"]}
    unmapped = sorted(scad_codici - known_codici)

    if unmapped:
        if policy == UnmappedPolicy.FAIL:
            detail = [
                {
                    "codice": c,
                    "nome": scad_df.loc[scad_df["codice_fornitore"] == c, "nome"].iloc[
                        0
                    ],
                    "totale": float(
                        scad_df.loc[scad_df["codice_fornitore"] == c, "totale"].iloc[0]
                    ),
                }
                for c in unmapped
            ]
            raise UnmappedFornitoriError(unmapped, detail)
        if policy == UnmappedPolicy.REPORT:
            # Caller dovrà gestire l'esportazione del report; qui solleva con dati.
            raise UnmappedFornitoriError(unmapped)
        if policy == UnmappedPolicy.INTERACTIVE:
            raise RuntimeError(
                "INTERACTIVE policy va gestita dal caller (CLI o app) prima di apply_scadenzario."
            )
        # SKIP: prosegui

    legacy_map = _build_legacy_fornitori_map(fornitori)
    adhoc_excluded = set(extra_excluded or set())
    excluded_set = (
        excluded_codici
        | (set(unmapped) if policy == UnmappedPolicy.SKIP else set())
        | adhoc_excluded
    )

    updated_bytes, write_summary = write_pf(
        pf_bytes=pf_bytes,
        scad_df=scad_df,
        bucket_months=bucket_months,
        fornitori_map=legacy_map,
        excluded=excluded_set,
    )
    summary = {
        "skipped_unmapped": unmapped if policy == UnmappedPolicy.SKIP else [],
        "excluded_persisted": sorted(excluded_codici),
        "excluded_adhoc": sorted(adhoc_excluded),
        "voci_aggiornate": list(write_summary.keys()),
        "totale_fornitori_scritti": sum(len(v) for v in write_summary.values()),
    }
    return updated_bytes, summary
