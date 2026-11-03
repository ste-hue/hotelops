"""La guida HTML per Rosa, generata dalla sezione «A. Rosa» di
docs/procedures/cashflow_mensile.md: una fonte sola, nessuna copia a mano.

    python -m verticals.condges.guida_rosa docs/procedures/cashflow_mensile.md --out guida_rosa.html

Converte solo ciò che la sezione usa: titoli, paragrafi, elenchi puntati e numerati, grassetto
e codice in linea. Nessuna dipendenza oltre la libreria standard.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

INIZIO = "## A. Rosa"
FINE = "## B. "

_CSS = (
    "body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;"
    "color:#1d1d1b;background:#fbfaf7}h1{font-size:1.6rem}h2{font-size:1.2rem;margin-top:1.6rem}"
    "code{background:#eee;padding:0 .25rem;border-radius:3px}li{margin:.25rem 0}"
)


def sezione_rosa(markdown: str) -> str:
    """Il testo fra «## A. Rosa» e «## B.», senza i titoli delle altre sezioni."""
    i = markdown.find(INIZIO)
    if i < 0:
        raise ValueError(f"sezione «{INIZIO}» non trovata")
    j = markdown.find(FINE, i)
    corpo = markdown[i : j if j > 0 else None]
    return corpo.replace("---", "").strip()


def _inline(testo: str) -> str:
    t = html.escape(testo, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def a_html(sezione: str, titolo: str = "Il file del mese — guida per Rosa") -> str:
    out = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(titolo)}</title>"]
    out.append(f"<style>{_CSS}</style><h1>{html.escape(titolo)}</h1>")
    lista: str | None = None
    para: list[str] = []

    def chiudi_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def chiudi_lista():
        nonlocal lista
        if lista:
            out.append(f"</{lista}>")
            lista = None

    for riga in sezione.splitlines():
        r = riga.rstrip()
        if not r.strip():
            chiudi_para()
            chiudi_lista()
            continue
        m = re.match(r"^(#{2,3})\s+(.*)$", r)
        if m:
            chiudi_para()
            chiudi_lista()
            if len(m.group(1)) == 2:
                continue  # «## A. Rosa — …» è il titolo della pagina, già scritto
            out.append(f"<h2>{_inline(m.group(2))}</h2>")
            continue
        m = re.match(r"^\s*(\d+)\.\s+(.*)$", r)
        if m:
            chiudi_para()
            if lista != "ol":
                chiudi_lista()
                out.append("<ol>")
                lista = "ol"
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        m = re.match(r"^\s*-\s+(.*)$", r)
        if m:
            chiudi_para()
            if lista != "ul":
                chiudi_lista()
                out.append("<ul>")
                lista = "ul"
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        if lista and r.startswith("   "):
            # continuazione di una voce di elenco
            out[-1] = out[-1][: -len("</li>")] + " " + _inline(r.strip()) + "</li>"
            continue
        if lista:
            chiudi_lista()
        para.append(r.strip())
    chiudi_para()
    chiudi_lista()
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("procedura", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.out.write_text(
        a_html(sezione_rosa(args.procedura.read_text(encoding="utf-8"))),
        encoding="utf-8",
    )
    print(f"scritto {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
