"""Orchestratore della rotation. Tie step 1+2+3+5 + file naming."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

from verticals.condges.pf_rotate.step1_saldi import write_saldi_banca, fetch_saldi_da_bq
from verticals.condges.pf_rotate.step2_azzera import azzera_mese
from verticals.condges.pf_rotate.step3_scadenzario import (
    UnmappedPolicy,
    apply_scadenzario,
)
from verticals.condges.pf_rotate.step5_controlli import verifica_controlli, CheckOutcome


@dataclass
class RotateResult:
    out_path: Path
    n_controlli_ok: int
    n_controlli_err: int
    n_controlli_indet: int
    failed_checks: list[str] = field(default_factory=list)
    scadenzario_summary: dict | None = None
    azzera_changes_count: int = 0
    failed: bool = False  # True se ci sono controlli ERR


def _output_path(out_dir: Path, societa: str, anno_mese: str, failed: bool) -> Path:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M")
    suffix = "_FAILED_CHECKS" if failed else ""
    return out_dir / f"{societa}_PF_{anno_mese}_post-rotate_{ts}{suffix}.xlsx"


def rotate(
    *,
    pf_path: Path,
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    societa: str,
    mese_chiuso: int,
    data_saldo: date,
    saldi: dict[str, float] | None = None,
    fornitori_csv: Path,
    out_dir: Path,
    unmapped_policy: UnmappedPolicy = UnmappedPolicy.FAIL,
) -> RotateResult:
    """Esegui il full ciclo: step 1 → 2 → 3 → 5.

    saldi: se None, tenta fetch da BQ via fetch_saldi_da_bq.
    """
    pf_bytes = pf_path.read_bytes()

    # Step 1: saldi
    wb = openpyxl.load_workbook(BytesIO(pf_bytes))
    if saldi is None:
        saldi = fetch_saldi_da_bq(societa, data_saldo)
    if not saldi:
        raise RuntimeError(
            "Saldi banca non disponibili (BQ vuota e nessun --banca passato)."
        )
    write_saldi_banca(wb, mese_chiuso=mese_chiuso, data_saldo=data_saldo, saldi=saldi)

    # Step 2: azzera
    changes = azzera_mese(wb, mese_chiuso=mese_chiuso)

    # Serialize after step 1+2 prima dello step 3 (write_pf legge bytes)
    buf = BytesIO()
    wb.save(buf)
    step12_bytes = buf.getvalue()

    # Step 3: scadenzario
    out_bytes, scad_summary = apply_scadenzario(
        pf_bytes=step12_bytes,
        scad_df=scad_df,
        bucket_months=bucket_months,
        societa=societa,
        fornitori_csv=fornitori_csv,
        policy=unmapped_policy,
    )

    # Step 5: controlli sul wb finale
    final_wb = openpyxl.load_workbook(BytesIO(out_bytes), data_only=False)
    report = verifica_controlli(final_wb, mese_chiuso=mese_chiuso)
    failed = report.n_err > 0
    failed_checks = [
        f"{r.check_id}: {r.title} — {r.detail}"
        for r in report.results
        if r.outcome == CheckOutcome.ERR
    ]

    # File output
    anno_mese = f"{data_saldo.year}-{data_saldo.month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _output_path(out_dir, societa, anno_mese, failed)
    out_path.write_bytes(out_bytes)

    return RotateResult(
        out_path=out_path,
        n_controlli_ok=report.n_ok,
        n_controlli_err=report.n_err,
        n_controlli_indet=report.n_indet,
        failed_checks=failed_checks,
        scadenzario_summary=scad_summary,
        azzera_changes_count=len(changes),
        failed=failed,
    )
