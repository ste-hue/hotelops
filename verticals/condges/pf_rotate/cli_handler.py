"""CLI handler per `hotelops pf-rotate`."""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, datetime
from pathlib import Path

from verticals.condges.pf_rotate.excel_model import periodo
from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy

MESI_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def _parse_mese(s: str) -> int:
    s = s.strip().lower()
    if s in MESI_IT:
        return MESI_IT[s]
    return int(s)


def _parse_data(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _resolve_data_saldo(data_saldo: date | None, anno: int, mese_chiuso: int) -> date:
    """O-D: --data-saldo esplicito è override; altrimenti ultimo giorno di (anno, mese)."""
    if data_saldo is not None:
        return data_saldo
    last_day = calendar.monthrange(anno, mese_chiuso)[1]
    return date(anno, mese_chiuso, last_day)


def _parse_banca_overrides(items: list[str]) -> dict[str, float]:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise argparse.ArgumentTypeError(
                f"--banca atteso 'BANCA=IMPORTO', avuto '{it}'"
            )
        k, v = it.split("=", 1)
        out[k.strip()] = float(v)
    return out


def _parse_exclude(items: list[str]) -> set[int]:
    """Codici fornitore da escludere ad-hoc: comma-sep e/o ripetibile → set[int]."""
    out: set[int] = set()
    for it in items or []:
        for tok in str(it).split(","):
            tok = tok.strip()
            if tok:
                out.add(int(tok))
    return out


def _default_policy() -> UnmappedPolicy:
    return UnmappedPolicy.INTERACTIVE if sys.stdin.isatty() else UnmappedPolicy.FAIL


def add_subparser(subparsers: argparse._SubParsersAction):
    _add_normalize_intur_subparser(subparsers)
    _add_pf_extend_subparser(subparsers)
    p = subparsers.add_parser(
        "pf-rotate", help="Rotation mensile del Piano Finanziario."
    )
    p.add_argument("--pf", type=Path, required=True)
    p.add_argument("--scad", type=Path, required=True)
    p.add_argument(
        "--scad-tipo",
        choices=("riepilogo", "partite", "sintetica"),
        default="sintetica",
    )
    p.add_argument("--societa", choices=("ORTI", "INTUR"), required=True)
    p.add_argument("--mese-chiuso", type=_parse_mese, required=True)
    p.add_argument(
        "--data-saldo",
        type=_parse_data,
        default=None,
        help="Override esplicito. Default: ultimo giorno di (--anno, --mese-chiuso).",
    )
    p.add_argument(
        "--anno",
        type=int,
        default=None,
        help="Anno per derivare --data-saldo. Default: anno corrente.",
    )
    p.add_argument(
        "--banca",
        action="append",
        default=[],
        help="Override saldo: BANCA=IMPORTO (ripetibile).",
    )
    p.add_argument(
        "--unmapped-policy",
        choices=tuple(p.value for p in UnmappedPolicy),
        default=None,
        help="Default: 'interactive' se TTY, altrimenti 'fail'.",
    )
    p.add_argument("--out", type=Path, default=Path.cwd() / "pianfin-out")
    p.add_argument(
        "--fornitori-csv", type=Path, default=Path("core/bq/dimensioni/d_fornitori.csv")
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Codici fornitore da escludere da questa rotazione (comma-sep o ripetibile, "
        "es. --exclude 264,48). Si unisce agli is_excluded persistenti.",
    )
    p.add_argument(
        "--allow-partial-saldi",
        action="store_true",
        help="Genera un PF parziale (marcato _FAILED_CHECKS) anche se mancano conti "
        "saldo obbligatori, invece di hard-fail.",
    )
    p.set_defaults(func=_handle)
    return p


def _handle(args: argparse.Namespace) -> int:
    from io import BytesIO

    from verticals.condges.pf_rotate.rotate import ScadenzarioVuotoError
    from verticals.condges.pf_rotate.step1_saldi import SaldiIncompletiError
    from verticals.condges.scadenze_parse import parse_scadenze

    anno_cutoff = args.anno or date.today().year
    if args.mese_chiuso == 12:
        cutoff = (anno_cutoff + 1, 1)
    else:
        cutoff = (anno_cutoff, args.mese_chiuso + 1)
    with args.scad.open("rb") as f:
        scad_df, bucket_periodi = parse_scadenze(
            BytesIO(f.read()), primo_mese_aperto=cutoff
        )

    overrides = _parse_banca_overrides(args.banca)
    policy = (
        UnmappedPolicy(args.unmapped_policy)
        if args.unmapped_policy
        else _default_policy()
    )
    anno = args.anno or date.today().year
    data_saldo = _resolve_data_saldo(args.data_saldo, anno, args.mese_chiuso)
    extra_excluded = _parse_exclude(args.exclude)
    periodo_chiuso = periodo(anno, args.mese_chiuso)

    if policy == UnmappedPolicy.INTERACTIVE:
        from verticals.condges.pf_rotate.interactive_map import (
            resolve_unmapped_interactive,
        )

        resolved = resolve_unmapped_interactive(
            scad_df, args.fornitori_csv, args.societa
        )
        if resolved:
            print(f"{len(resolved)} fornitori mappati in {args.fornitori_csv}")
        # I non risolti ('s' = salta) devono fermare il run, non sparire in silenzio.
        policy = UnmappedPolicy.FAIL

    try:
        result = rotate(
            pf_path=args.pf,
            scad_df=scad_df,
            bucket_periodi=bucket_periodi,
            societa=args.societa,
            periodo_chiuso=periodo_chiuso,
            data_saldo=data_saldo,
            saldi=overrides or None,
            fornitori_csv=args.fornitori_csv,
            out_dir=args.out,
            unmapped_policy=policy,
            allow_partial_saldi=args.allow_partial_saldi,
            extra_excluded=extra_excluded,
        )
    except (SaldiIncompletiError, ScadenzarioVuotoError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 2

    print(f"Output: {result.out_path}")
    print(
        f"Controlli: OK={result.n_controlli_ok}  ERR={result.n_controlli_err}  INDET={result.n_controlli_indet}"
    )
    if result.failed_checks:
        print("\nFailed checks:")
        for c in result.failed_checks:
            print(f"  - {c}")
    if result.scadenzario_summary:
        print(
            f"\nFornitori scritti: {result.scadenzario_summary['totale_fornitori_scritti']}"
        )
    oltre = (result.scadenzario_summary or {}).get("oltre_orizzonte") or {}
    if oltre:
        tot = sum(oltre.values())
        print(
            f"\n⚠️ Oltre orizzonte (senza colonna nel PF): {len(oltre)} fornitori, {tot:,.2f} € NON scritti"
        )
    return 1 if result.failed else 0


def _parse_anno_mese(s: str) -> tuple[int, int]:
    try:
        anno_s, mese_s = s.split("-", 1)
        return int(anno_s), int(mese_s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--to atteso 'YYYY-MM', avuto '{s}'") from e


def _add_pf_extend_subparser(subparsers: argparse._SubParsersAction):
    p = subparsers.add_parser(
        "pf-extend",
        help="Allunga l'orizzonte del template PF fino al periodo target.",
    )
    p.add_argument("--pf", type=Path, required=True)
    p.add_argument("--to", type=str, required=True, help="Periodo target YYYY-MM.")
    p.add_argument("--out", type=Path, default=Path.cwd() / "pianfin-out")
    p.set_defaults(func=_handle_extend)
    return p


def _handle_extend(args: argparse.Namespace) -> int:
    import openpyxl

    from verticals.condges.pf_rotate.extend import extend_to

    anno, mese = _parse_anno_mese(args.to)
    wb = openpyxl.load_workbook(
        args.pf
    )  # copia in-memory: l'input su disco non si tocca
    changed = extend_to(wb, periodo(anno, mese))
    if not changed:
        print("Già coperto: nessuna colonna da aggiungere.")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M")
    out = args.out / f"{args.pf.stem}_extended_{args.to}_{ts}.xlsx"
    wb.save(out)
    print(f"Output: {out}\nColonne aggiunte/aggiornate: {len(changed)}")
    for c in changed[:20]:
        print(f"  + {c}")
    return 0


def _add_normalize_intur_subparser(subparsers: argparse._SubParsersAction):
    p = subparsers.add_parser(
        "pf-normalize-intur",
        help="Normalizza col A dei fogli dettaglio INTUR (step 0, una tantum).",
    )
    p.add_argument("--pf", type=Path, required=True)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Default: <pf>.normalized.xlsx accanto al file di input.",
    )
    p.add_argument(
        "--fornitori-csv",
        type=Path,
        default=Path("core/bq/dimensioni/d_fornitori.csv"),
    )
    p.set_defaults(func=_handle_normalize_intur)
    return p


def _handle_normalize_intur(args: argparse.Namespace) -> int:
    from verticals.condges.pf_rotate.step0_normalize_intur import normalize_intur

    pf_bytes = args.pf.read_bytes()
    out_bytes, overwrites, unmapped = normalize_intur(
        pf_bytes=pf_bytes, fornitori_csv=args.fornitori_csv
    )

    out_path = args.out or args.pf.with_suffix(".normalized.xlsx")
    out_path.write_bytes(out_bytes)

    print(f"Output: {out_path}")
    print(f"Col A overwrites: {len(overwrites)}")
    print(f"Fornitori non mappati (col A lasciata invariata): {len(unmapped)}")
    if unmapped:
        print("\nNon mappati (primi 20):")
        for u in unmapped[:20]:
            print(f"  - {u['foglio']!r:30s} r{u['riga']:<4d}  {u['nome_b']!r}")
        if len(unmapped) > 20:
            print(f"  ... e altri {len(unmapped) - 20}")
    return 0
