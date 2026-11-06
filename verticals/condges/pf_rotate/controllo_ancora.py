"""Controllo d'ancora prima della promozione di un PF (procedura C5).

Legge nel foglio «Piano Finanziario» le righe «Saldo <banca>» (il saldo di fine mese per
conto, nella colonna C o nella cella «… €» accanto alla data) e la riga «SALDO MESE PRECED.»,
e li confronta con un file di riferimento JSON che sta FUORI dal repository (le cifre non si
versionano): percorso da `--riferimento` o dalla variabile d'ambiente
`HOTELOPS_ANCORA_RIFERIMENTO`. Forma del riferimento:

    {"rosse":  {"INTUR|INTESA": 1.0, ...},   # valori noti sbagliati del foglio dei saldi
     "attesi": {"INTUR|INTESA": 2.0, ...},   # ultimo saldo attestato (scarto > 1000 = rosso)
     "bq":     {"INTUR": {"INTESA": 2.0, "MPS": 3.0}, ...}}   # ancore BigQuery alla data

Rosso (uscita 1) se: un conto porta un valore «rosso»; un conto atteso si scosta oltre 1000;
un conto differisce dall'ancora BigQuery oltre 2 centesimi; nessuna colonna di «SALDO MESE
PRECED.» è la somma dei conti. Rosso = la promozione si ferma e si scrive nel verbale.
È uno strumento lanciato a mano: nessun passo automatico lo invoca.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import openpyxl

TOLL = 0.02
SCARTO_ATTESO = 1000.0
MESI = (
    "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
    "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
)  # fmt: skip
BANCHE = ("SELLA", "MPS", "INTESA", "KROSS", "UNICREDIT", "BCP")


def banca(label: str) -> str:
    s = label.upper()
    for k in BANCHE:
        if k in s:
            return k
    return s.replace("SALDO", "").strip()


def numero(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and "€" in v:
        t = v.replace("€", "").strip()
        try:
            return (
                float(t.replace(".", "").replace(",", "."))
                if t.count(",") == 1 and t.rfind(",") > t.rfind(".")
                else float(t.replace(",", ""))
            )
        except ValueError:
            return None
    return None


def leggi(
    path: str | Path,
) -> tuple[str, dict[str, float | None], dict[int, float], dict[int, str], object]:
    """(società, saldi per conto, SALDO MESE PRECED. per colonna, mesi per colonna, data dell'ancora)."""
    soc = "INTUR" if "INTUR" in str(path).upper() else "ORTI"
    ws = openpyxl.load_workbook(str(path), data_only=True, read_only=True)[
        "Piano Finanziario"
    ]
    saldi: dict[str, float | None] = {}
    prec: dict[int, float] = {}
    mesi: dict[int, str] = {}
    data = None
    for row in ws.iter_rows(min_row=1, max_row=80):
        a = row[0].value
        if (
            not mesi
            and sum(
                isinstance(c.value, str) and c.value.strip().upper() in MESI
                for c in row
            )
            >= 3
        ):
            mesi = {
                i: c.value.strip().upper()
                for i, c in enumerate(row)
                if isinstance(c.value, str) and c.value.strip().upper() in MESI
            }
        if (
            data is None
        ):  # la data in testa al foglio (INTUR: C1), se non c'è accanto ai saldi
            for c in row[:3]:
                if isinstance(c.value, (dt.datetime, dt.date)):
                    data = (
                        c.value
                        if isinstance(c.value, dt.date)
                        and not isinstance(c.value, dt.datetime)
                        else c.value.date()
                    )
        if not isinstance(a, str):
            continue
        testa = a.strip().upper()
        if testa.startswith("SALDO MESE PRECED"):
            prec = {
                i: n for i, c in enumerate(row) if (n := numero(c.value)) is not None
            }
        elif testa.startswith("SALDO ") and "PERIODO" not in testa:
            for c in row[1:4]:
                if isinstance(c.value, (dt.datetime, dt.date)):
                    data = (
                        c.value.date() if isinstance(c.value, dt.datetime) else c.value
                    )
                elif (
                    isinstance(c.value, str)
                    and c.value.count("/") == 2
                    and len(c.value) == 10
                ):
                    data = c.value
            euro = next(
                (
                    numero(c.value)
                    for c in row[1:]
                    if isinstance(c.value, str) and "€" in c.value
                ),
                None,
            )
            saldi[banca(a)] = (
                euro
                if euro is not None
                else next(
                    (numero(c.value) for c in row[1:] if numero(c.value) is not None),
                    None,
                )
            )
    return soc, saldi, prec, mesi, data


def controlla(path: str | Path, riferimento: dict) -> tuple[bool, list[str]]:
    """(rosso, righe di esito) per un file PF contro il riferimento."""
    soc, saldi, prec, mesi, data = leggi(path)
    rosse = riferimento.get("rosse") or {}
    attesi = riferimento.get("attesi") or {}
    bq = (riferimento.get("bq") or {}).get(soc) or {}
    somma = sum(v for v in saldi.values() if v is not None)
    quadra = [mesi.get(i, f"col{i}") for i, v in prec.items() if abs(v - somma) <= TOLL]
    righe = [
        f"{Path(path).name} ({soc}) · data dell'ancora nel file: {data} · somma dei conti {somma:,.2f} · SALDO MESE PRECED. uguale alla somma in: {', '.join(quadra) or 'NESSUNA colonna'}"
    ]
    rosso = not quadra
    for b, v in saldi.items():
        k = f"{soc}|{b}"
        flag = ""
        if v is None:
            flag = "VUOTO"
        elif k in rosse and abs(v - rosse[k]) <= TOLL:
            flag, rosso = (
                f"ROSSO: è il valore noto sbagliato del foglio dei saldi ({rosse[k]:,.2f})",
                True,
            )
        elif k in attesi and abs(v - attesi[k]) > SCARTO_ATTESO:
            flag, rosso = f"ROSSO: atteso ~{attesi[k]:,.2f}, trovato {v:,.2f}", True
        ref = bq.get(b)
        if ref is not None and v is not None and abs(v - ref) > TOLL:
            flag, rosso = (
                f"{flag} · BQ dice {ref:,.2f} (scarto {v - ref:+,.2f})".strip(" ·"),
                True,
            )
        righe.append(f"   {b:10s} {'—' if v is None else f'{v:,.2f}':>16s}  {flag}")
    return rosso, righe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Controllo d'ancora dei saldi per conto in un PF (C5)."
    )
    ap.add_argument("file", nargs="+", type=Path)
    ap.add_argument(
        "--riferimento",
        type=Path,
        default=None,
        help="JSON fuori repo; default $HOTELOPS_ANCORA_RIFERIMENTO",
    )
    args = ap.parse_args(argv)
    rif_path = args.riferimento or (
        Path(os.environ["HOTELOPS_ANCORA_RIFERIMENTO"])
        if os.environ.get("HOTELOPS_ANCORA_RIFERIMENTO")
        else None
    )
    if rif_path is None:
        print(
            "serve --riferimento <json> o HOTELOPS_ANCORA_RIFERIMENTO (le cifre stanno fuori dal repo)",
            file=sys.stderr,
        )
        return 2
    riferimento = json.loads(Path(rif_path).read_text(encoding="utf-8"))
    rosso = False
    for f in args.file:
        r, righe = controlla(f, riferimento)
        rosso = rosso or r
        print("\n".join(righe))
    print(
        "\nESITO:",
        "FERMATI, non promuovere — scrivilo nel verbale"
        if rosso
        else "nessuna bandiera rossa sull'ancora per conto",
    )
    return 1 if rosso else 0


if __name__ == "__main__":
    raise SystemExit(main())
