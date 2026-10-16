"""Estrazione verificabile dei bilanci di verifica PROVVISORI al 30/09/2026 dai PDF.

DERIVATO, non export Esolver originale. Nessuna scrittura su BigQuery.

Il PDF espone solo "Saldo finale Dare" e "Saldo finale Avere": non contiene
movimenti Dare/Avere di periodo. Le colonne dare/avere qui sotto sono quindi
saldi finali per sezione, e saldo = dare - avere.
"""

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

CONTO = re.compile(r"^(?P<conto>\d{2}(?:\.\d{2})*)\s{2,}(?P<rest>.+)$")
NUM = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")


def importo(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def colonne_importi(pagina: str) -> tuple[int, int] | None:
    """Offset di inizio delle due colonne importo, dal titolo "Saldo finale".

    Serve a due scopi: scartare i numeri che compaiono DENTRO la descrizione
    (es. "Acquisto beni strumentali inf.516,46") e distinguere Dare da Avere.
    """
    for line in pagina.splitlines():
        pos = [m.start() for m in re.finditer("Saldo finale", line)]
        if len(pos) == 2:
            return pos[0], pos[1]
    return None


def intestazione(pagina: str) -> dict:
    out = {}
    m = re.search(r"ESERCIZIO\s+(\d{4})", pagina)
    if m:
        out["esercizio"] = m.group(1)
    m = re.search(r"al\s+(\d{2}/\d{2}/\d{2})", pagina)
    if m:
        out["periodo_fine"] = m.group(1)
    m = re.search(r"Data\s+(\d{2}/\d{2}/\d{4})", pagina)
    if m:
        out["data_stampa"] = m.group(1)
    # Natura provvisoria: il corpo del PDF dice "Bilancio di verifica" e NON
    # contiene la parola PROVVISORIO — quella sta nel nome file e nell'oggetto
    # della mail. Registro entrambi i segnali separatamente, senza fonderli.
    out["titolo_documento"] = (
        "Bilancio di verifica" if "Bilancio di verifica" in pagina else None
    )
    out["provvisorio_nel_corpo"] = "PROVVISORIO" in pagina.upper()
    out["periodo_inizio_dichiarato"] = bool(re.search(r"Dal\s+\d", pagina))
    return out


def estrai(pdf: Path) -> tuple[list[dict], dict]:
    testo = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    righe: list[dict] = []
    meta: dict = {}
    for n_pag, pagina in enumerate(testo.split("\f"), start=1):
        if not pagina.strip():
            continue
        if not meta:
            meta = intestazione(pagina)
        cols = colonne_importi(pagina)
        if cols is None:
            raise RuntimeError(
                f"{pdf.name} pag.{n_pag}: intestazione colonne non trovata"
            )
        col_dare, col_avere = cols
        for line in pagina.splitlines():
            m = CONTO.match(line)
            if not m:
                continue
            conto = m.group("conto")
            # Importo = numero che CADE nelle colonne di destra. I numeri che
            # finiscono prima dell'inizio della colonna Dare sono testo della
            # descrizione, non valori.
            numeri = [
                (x.start(), x.group()) for x in NUM.finditer(line) if x.end() > col_dare
            ]
            if not numeri:
                continue
            dare = avere = 0.0
            for pos, val in numeri:
                if pos >= col_avere - 3:
                    avere += importo(val)
                else:
                    dare += importo(val)
            fine_descr = min(p for p, _ in numeri)
            descr = line[m.end("conto") : fine_descr].strip()
            righe.append(
                {
                    "pagina": n_pag,
                    "codice_conto": conto,
                    "livello": conto.count(".") + 1,
                    "descrizione": descr,
                    "dare": round(dare, 2),
                    "avere": round(avere, 2),
                    "saldo": round(dare - avere, 2),
                }
            )
    return righe, meta


def marca_natura(righe: list[dict]) -> None:
    """Un conto e' SUBTOTALE se esiste un altro conto che lo ha come prefisso."""
    codici = {r["codice_conto"] for r in righe}
    for r in righe:
        pref = r["codice_conto"] + "."
        r["natura"] = (
            "SUBTOTALE" if any(c.startswith(pref) for c in codici) else "DETTAGLIO"
        )


def riconcilia(righe: list[dict]) -> list[dict]:
    """Per ogni subtotale: confronto con la somma dei suoi discendenti foglia."""
    per_codice = {r["codice_conto"]: r for r in righe}
    esiti = []
    for r in righe:
        if r["natura"] != "SUBTOTALE":
            continue
        pref = r["codice_conto"] + "."
        foglie = [
            x
            for x in righe
            if x["natura"] == "DETTAGLIO" and x["codice_conto"].startswith(pref)
        ]
        somma = round(sum(x["saldo"] for x in foglie), 2)
        delta = round(r["saldo"] - somma, 2)
        esiti.append(
            {
                "codice_conto": r["codice_conto"],
                "descrizione": r["descrizione"],
                "dichiarato": r["saldo"],
                "somma_foglie": somma,
                "n_foglie": len(foglie),
                "delta": delta,
                "quadra": abs(delta) < 0.01,
            }
        )
    assert per_codice
    return esiti


def main() -> int:
    dest = Path.home() / "Backups/hotelops/2026-10-16-bilanci-2026-09-30"
    pdfs = {
        "ORTI": dest / "ORTI BILANCIO PROVVISORIO AL 30092026.pdf",
        "INTUR": dest / "INTUR PROVVISORIO AL 300926.pdf",
    }
    ricevuta = {
        "generato_da": "scratchpad/estrai_bilancio_pdf.py",
        "natura": "DERIVATO dai PDF provvisori — non e' un export Esolver originale",
        "scritture_bigquery": "nessuna",
        "societa": {},
    }

    for societa, pdf in pdfs.items():
        righe, meta = estrai(pdf)
        marca_natura(righe)
        esiti = riconcilia(righe)

        csv_out = dest / f"{societa}_bilancio_provvisorio_2026-09-30_estratto.csv"
        with csv_out.open("w", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "pagina",
                    "codice_conto",
                    "livello",
                    "natura",
                    "descrizione",
                    "dare",
                    "avere",
                    "saldo",
                ],
            )
            w.writeheader()
            for r in righe:
                w.writerow({k: r[k] for k in w.fieldnames})

        dettaglio = [r for r in righe if r["natura"] == "DETTAGLIO"]
        non_quadra = [e for e in esiti if not e["quadra"]]
        ricevuta["societa"][societa] = {
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "pdf_nome": pdf.name,
            "intestazione": meta,
            "provvisorio_da_nome_file": "PROVVISORIO" in pdf.name.upper(),
            "righe_totali": len(righe),
            "conti_dettaglio": len(dettaglio),
            "subtotali": len(esiti),
            "somma_saldi_dettaglio": round(sum(r["saldo"] for r in dettaglio), 2),
            "subtotali_che_quadrano": len(esiti) - len(non_quadra),
            "subtotali_che_non_quadrano": [
                {
                    k: e[k]
                    for k in (
                        "codice_conto",
                        "descrizione",
                        "dichiarato",
                        "somma_foglie",
                        "delta",
                    )
                }
                for e in non_quadra
            ],
            "csv": str(csv_out),
        }
        print(
            f"{societa}: {len(righe)} righe, {len(dettaglio)} dettaglio, "
            f"{len(esiti)} subtotali, {len(non_quadra)} non quadrano -> {csv_out.name}"
        )

    ric_out = dest / "ricevuta_estrazione.json"
    ric_out.write_text(json.dumps(ricevuta, indent=2, ensure_ascii=False))
    print(f"ricevuta: {ric_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
