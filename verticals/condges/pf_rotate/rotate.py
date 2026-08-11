"""PF rotation — RENDER/EXPORT ADAPTER.

Non possiede stato: l'authority del cash/PF è BigQuery (vedi
docs/superpowers/specs/2026-06-09-cash-pf-engine-consolidation-design.md).
Questo modulo produce l'artefatto Excel post-rotate a partire dai dati BQ;
non è la fonte di verità della proiezione. Le scritture canonical passano
dal service (cash_pf_service → gate I1), mai da qui.

Orchestratore della rotation. Tie step 1+2+3+5 + file naming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

from verticals.condges.pf_rotate.excel_model import require_periodo
from verticals.condges.pf_rotate.step1_saldi import (
    fetch_saldi_da_bq,
    preflight_saldi,
    write_saldi_banca,
)
from verticals.condges.pf_rotate.controlli_sheet import advance_controlli
from verticals.condges.pf_rotate.step2_azzera import azzera_mese
from verticals.condges.pf_rotate.step3_scadenzario import (
    UnmappedPolicy,
    apply_scadenzario,
)
from verticals.condges.pf_rotate.step5_controlli import verifica_controlli, CheckOutcome


class ScadenzarioVuotoError(RuntimeError):
    """Scadenziario parsato a 0 righe: quasi certamente un export Esolver sbagliato.

    Proseguire cancellerebbe le uscite pianificate dei mesi aperti (pulizia
    idempotente di write_pf) senza riscrivere nulla — hard fail prima di toccare il PF.
    """


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
    bucket_periodi: list[int],
    societa: str,
    periodo_chiuso: int,
    data_saldo: date,
    saldi: dict[str, float] | None = None,
    fornitori_csv: Path,
    out_dir: Path,
    unmapped_policy: UnmappedPolicy = UnmappedPolicy.FAIL,
    allow_partial_saldi: bool = False,
    extra_excluded: set[int] | None = None,
) -> RotateResult:
    """Esegui il full ciclo: step 1 → 2 → 3 → 5.

    saldi: se None, tenta fetch da BQ via fetch_saldi_da_bq.
    allow_partial_saldi: se True, non hard-fail su conti obbligatori mancanti — scrive
        un PF parziale marcato _FAILED_CHECKS (escape hatch del gate O-A).
    """
    require_periodo(periodo_chiuso, "periodo_chiuso")
    if scad_df.empty:
        raise ScadenzarioVuotoError(
            "Scadenziario con 0 scadenze: probabile export sbagliato — serve la "
            "'Situazione partite sintetica per fornitori' di Esolver (con data "
            "scadenza e saldo scadenza), non un registro documenti."
        )

    pf_bytes = pf_path.read_bytes()

    # Step 1: saldi
    wb = openpyxl.load_workbook(BytesIO(pf_bytes))
    if saldi is None:
        saldi = fetch_saldi_da_bq(societa, data_saldo)
    saldi = saldi or {}

    # Preflight gate (O-A): hard-fail su conti obbligatori mancanti PRIMA di scrivere.
    saldi_mancanti = preflight_saldi(
        societa, saldi, data_saldo, allow_partial=allow_partial_saldi
    )
    if not saldi and not allow_partial_saldi:
        raise RuntimeError(
            "Saldi banca non disponibili (BQ vuota e nessun --banca passato)."
        )
    write_saldi_banca(
        wb, periodo_chiuso=periodo_chiuso, data_saldo=data_saldo, saldi=saldi
    )

    # Step 2: azzera
    changes = azzera_mese(wb, periodo_chiuso)

    # Step 2b: allinea i controlli in-foglio al nuovo mese chiuso
    # (altrimenti restano ancorati al mese della rotation precedente → ERRORE finti)
    advance_controlli(wb, periodo_chiuso)

    # Serialize after step 1+2 prima dello step 3 (write_pf legge bytes)
    buf = BytesIO()
    wb.save(buf)
    step12_bytes = buf.getvalue()

    # Step 3: scadenzario — scaduto ancorato al primo periodo aperto, non a oggi
    primo_periodo_aperto = periodo_chiuso + 1
    out_bytes, scad_summary = apply_scadenzario(
        pf_bytes=step12_bytes,
        scad_df=scad_df,
        bucket_periodi=bucket_periodi,
        societa=societa,
        fornitori_csv=fornitori_csv,
        policy=unmapped_policy,
        extra_excluded=extra_excluded,
        scaduto_periodo=primo_periodo_aperto,
    )

    # Step 5: controlli sul wb finale
    final_wb = openpyxl.load_workbook(BytesIO(out_bytes), data_only=False)
    report = verifica_controlli(final_wb, periodo_chiuso=periodo_chiuso)
    # saldi_mancanti è non-vuoto solo in modalità allow_partial (altrimenti preflight
    # avrebbe già sollevato): marca il PF come parziale/difettoso.
    partial = bool(saldi_mancanti)
    failed = report.n_err > 0 or partial
    failed_checks = [
        f"{r.check_id}: {r.title} — {r.detail}"
        for r in report.results
        if r.outcome == CheckOutcome.ERR
    ]
    if partial:
        failed_checks.insert(
            0,
            "SALDI: conti obbligatori mancanti (PF parziale): "
            + ", ".join(saldi_mancanti),
        )

    # File output — il nome indica il primo mese aperto (data_saldo + 1 mese):
    # il PF post-rotazione di aprile parte dai saldi al 30/04 ed è il file "di maggio".
    anno = data_saldo.year + (1 if data_saldo.month == 12 else 0)
    mese_aperto = data_saldo.month % 12 + 1
    anno_mese = f"{anno}-{mese_aperto:02d}"
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
