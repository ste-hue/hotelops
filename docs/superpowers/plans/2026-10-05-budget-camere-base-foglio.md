# Budget camere Panorama — base 2026 e foglio degli aumenti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `hotelops budget base` genera un foglio Excel con il 2026 dell'Hotel Panorama per mese × categoria (sul calendario 2027), dove Stefano scrive un aumento % per riga e vede subito ricavo 2027 e i quattro effetti.

**Architecture:** Un pacchetto nuovo `verticals/condges/budget_camere/` con quattro file: `modello.py` (funzioni pure), `fonti.py` (tre letture BigQuery con `query` iniettabile, come `canone_fonti.py`), `foglio.py` (scrittura xlsx con formule vive), `base.py` (li mette insieme). Solo lettura da BigQuery: nessuna tabella, nessuna vista, nessuna fonte nuova.

**Tech Stack:** Python ≥3.11, `openpyxl`, `google-cloud-bigquery` via `core.bq.client.get_client`, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-10-04-budget-camere-panorama-design.md` (sezioni Modello, Flusso punto 1, Due piani). Questo è il piano 1 di 2.

## Global Constraints

- Perimetro: `business_unit_id = 'HOTEL'`, società ORTI, anno base 2026, budget 2027.
- Calendario 2027: prima notte venduta 20 aprile, ultima 20 ottobre, estremi inclusi (184 giorni).
- Ricavo camere canonico = `f_produzione_pms`, classe `01ROOM`, `importo_imponibile`. Mai `f_pms_statistiche.revenue_room`.
- Notti = `f_pms_statistiche.camere_vendute`. Categoria = tipologia **venduta** di `f_bookings_tipologia`, decodificata con `d_camere` (`cod_camera` → `tipologia`).
- Un mese non osservato per intero dà raccordo vuoto, mai zero. Un totale con un mese vuoto è «n.d.».
- Nessuna scrittura su BigQuery. Nessun file generato dentro il repo (default `~/Downloads`).
- Niente `pip install -e` da un worktree. `git add` per nome, mai `git add .`.
- Prima del merge Stefano vede il foglio generato con i dati veri.

## Review Focus

1. Tipologia venduta con notti > 0 che non è in `d_camere` → errore che nomina il codice, non una riga persa in silenzio. (Task 1)
2. Mese con file per tipologia esportato prima della fine del mese, o con `01ROOM` non caricato per tutti i giorni → stato `stima`, raccordo vuoto, totale «n.d.». (Task 1, Task 3)
3. Categoria con zero notti di base in un mese (Luxury Suite ad aprile) → prezzo vuoto, nessuna divisione per zero, formule che danno 0 e non `#VALUE!`. (Task 1, Task 3)
4. Arrotondamento delle notti 2027: il totale del mese resta identico a quello di base. (Task 1)
5. File di progetto con una camera o una categoria che non esiste in `d_camere` → errore. (Task 1)

## File Structure

| File | Responsabilità |
| --- | --- |
| `verticals/condges/budget_camere/__init__.py` | vuoto |
| `verticals/condges/budget_camere/hpan26piano3.csv` | le 20 camere del terzo piano e la loro categoria 2027 |
| `verticals/condges/budget_camere/modello.py` | calendario, inventario, base per categoria, notti 2027, stato, effetti, `costruisci` |
| `verticals/condges/budget_camere/fonti.py` | `leggi_camere`, `leggi_categorie`, `leggi_pms` |
| `verticals/condges/budget_camere/foglio.py` | `scrivi(dati, path)` → xlsx con fogli Leggimi, Prezzi, Mesi |
| `verticals/condges/budget_camere/base.py` | `run(...)`: legge, costruisce, scrive, stampa il riepilogo |
| `cli.py` | sottocomando `budget base` |
| `tests/test_budget_camere.py` | tutti i test, con dati sintetici |

---

### Task 1: Modello puro

**Files:**
- Create: `verticals/condges/budget_camere/__init__.py` (vuoto)
- Create: `verticals/condges/budget_camere/hpan26piano3.csv`
- Create: `verticals/condges/budget_camere/modello.py`
- Test: `tests/test_budget_camere.py`

**Interfaces:**
- Consumes: niente.
- Produces:
  - `APERTURA_2027 = (4, 20)`, `CHIUSURA_2027 = (10, 20)`
  - `in_calendario(d: date, apertura: tuple[int, int], chiusura: tuple[int, int]) -> bool`
  - `giorni_apertura(anno: int, apertura, chiusura) -> dict[int, int]`
  - `carica_progetto(path: Path = PROGETTO_CSV) -> dict[str, str]`
  - `inventario(camere: list[dict], progetto: dict[str, str] | None = None) -> dict[str, int]`
  - `notti_2027(notti_base: dict[str, int], inv26: dict[str, int], inv27: dict[str, int]) -> dict[str, int]`
  - `effetti(righe: list[dict]) -> dict` — righe con chiavi `notti_base`, `prezzo_base`, `notti`, `prezzo`; ritorna `base`, `occupazione`, `mix`, `prezzo`, `budget`
  - `costruisci(camere, categorie_giorno, pms_giorno, progetto, anno_base=2026, apertura=APERTURA_2027, chiusura=CHIUSURA_2027) -> dict` con chiavi `anno_base`, `apertura`, `chiusura`, `righe`, `mesi`
  - forma degli ingressi: `camere` = `[{"room_id", "cod_camera", "tipologia"}]`; `categorie_giorno` = `[{"data": date, "codice": str, "notti": int, "ricavo": float, "caricato": date}]`; `pms_giorno` = `[{"data": date, "notti": int | None, "ricavo": float | None}]`
  - ogni elemento di `righe`: `mese, categoria, camere_2026, camere_2027, stato, notti_base, prezzo_base (float | None), notti_2027`
  - ogni elemento di `mesi`: `mese, stato, giorni_2026, giorni_2027, notti_reali, ricavo_reale, notti_calendario, ricavo_calendario, raccordo (float | None), camere`

- [ ] **Step 1: Scrivi il file di progetto**

`verticals/condges/budget_camere/hpan26piano3.csv` (fonte: fit-out Hospitality Project 01/09/2026 × `d_camere`; H323 resta Classic e non compare):

```csv
room_id,categoria_2027
H301,Classic
H302,Classic
H303,Classic
H304,Classic
H305,Classic
H306,Suite
H307,Deluxe
H308,Deluxe
H309,Deluxe
H310,Deluxe
H311,Deluxe
H312,Deluxe
H314,Deluxe
H315,Deluxe
H316,Deluxe
H318,Suite
H319,Executive
H320,Executive
H321,Executive
H322,Classic
```

Crea anche `verticals/condges/budget_camere/__init__.py` vuoto.

- [ ] **Step 2: Scrivi i test che falliscono**

`tests/test_budget_camere.py`:

```python
"""Budget camere per driver: modello, fonti, foglio. Dati SINTETICI."""

import calendar
from collections import Counter
from datetime import date

import pytest

from verticals.condges.budget_camere import modello as m

CAMERE = [
    {"room_id": "H101", "cod_camera": "DSTA", "tipologia": "Standard"},
    {"room_id": "H102", "cod_camera": "TSTA", "tipologia": "Standard"},
    {"room_id": "H301", "cod_camera": "DSTA", "tipologia": "Standard"},
    {"room_id": "H302", "cod_camera": "DSUP", "tipologia": "Superior"},
    {"room_id": "H201", "cod_camera": "DDLX", "tipologia": "Deluxe"},
]
PROGETTO = {"H301": "Deluxe"}
INV26 = {"Standard": 3, "Superior": 1, "Deluxe": 1}
INV27 = {"Standard": 2, "Superior": 1, "Deluxe": 2}
MAGGIO_GIUGNO = ((5, 1), (6, 30))


def _giorni(mese):
    return [date(2026, mese, g) for g in range(1, calendar.monthrange(2026, mese)[1] + 1)]


def _categorie(caricato=date(2026, 6, 10)):
    return [
        {"data": d, "codice": cod, "notti": n, "ricavo": n * p, "caricato": caricato}
        for d in _giorni(5) + _giorni(6)
        for cod, n, p in (("DSTA", 2, 100.0), ("TSTA", 1, 100.0), ("DSUP", 1, 200.0))
    ]


def _pms():
    return (
        [{"data": d, "notti": 4, "ricavo": 520.0} for d in _giorni(5)]
        + [{"data": d, "notti": 4, "ricavo": 520.0} for d in _giorni(6)[:9]]
        + [{"data": d, "notti": 4, "ricavo": None} for d in _giorni(6)[9:]]
    )


def test_giorni_apertura_2027():
    g = m.giorni_apertura(2027, m.APERTURA_2027, m.CHIUSURA_2027)
    assert g == {4: 11, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 20}
    assert sum(g.values()) == 184


def test_calendario_estremi_inclusi():
    a, c = m.APERTURA_2027, m.CHIUSURA_2027
    assert not m.in_calendario(date(2026, 4, 19), a, c)
    assert m.in_calendario(date(2026, 4, 20), a, c)
    assert m.in_calendario(date(2026, 10, 20), a, c)
    assert not m.in_calendario(date(2026, 10, 21), a, c)


def test_inventario_con_e_senza_progetto():
    assert m.inventario(CAMERE) == INV26
    assert m.inventario(CAMERE, PROGETTO) == INV27


def test_inventario_rifiuta_camera_o_categoria_sconosciuta():
    with pytest.raises(ValueError, match="H999"):
        m.inventario(CAMERE, {"H999": "Deluxe"})
    with pytest.raises(ValueError, match="Imperial"):
        m.inventario(CAMERE, {"H301": "Imperial"})


def test_progetto_terzo_piano():
    p = m.carica_progetto()
    assert len(p) == 20
    assert Counter(p.values()) == {"Deluxe": 9, "Classic": 6, "Executive": 3, "Suite": 2}


def test_notti_2027_conserva_il_totale():
    base = {"Standard": 100, "Superior": 50, "Deluxe": 31}
    out = m.notti_2027(base, INV26, INV27)
    assert out == {"Standard": 67, "Superior": 51, "Deluxe": 63}
    assert sum(out.values()) == sum(base.values())


def test_effetti_somma_esatta():
    e = m.effetti(
        [
            {"notti_base": 100, "prezzo_base": 100.0, "notti": 90, "prezzo": 110.0},
            {"notti_base": 50, "prezzo_base": 200.0, "notti": 70, "prezzo": 200.0},
        ]
    )
    assert e["base"] == pytest.approx(20000)
    assert e["occupazione"] == pytest.approx(1333.3333, abs=1e-3)
    assert e["mix"] == pytest.approx(1666.6667, abs=1e-3)
    assert e["prezzo"] == pytest.approx(900)
    assert e["base"] + e["occupazione"] + e["mix"] + e["prezzo"] == pytest.approx(e["budget"])


def test_effetti_categoria_senza_base():
    e = m.effetti([{"notti_base": 0, "prezzo_base": None, "notti": 10, "prezzo": 300.0}])
    assert e["base"] == 0
    assert e["base"] + e["occupazione"] + e["mix"] + e["prezzo"] == pytest.approx(3000)


def test_costruisci_righe_e_mesi():
    dati = m.costruisci(CAMERE, _categorie(), _pms(), PROGETTO, 2026, *MAGGIO_GIUGNO)
    assert len(dati["righe"]) == 2 * 3
    r = {(x["mese"], x["categoria"]): x for x in dati["righe"]}
    # DSTA + TSTA si fondono in Standard
    assert r[(5, "Standard")]["notti_base"] == 93
    assert r[(5, "Standard")]["prezzo_base"] == pytest.approx(100.0)
    assert r[(5, "Standard")]["notti_2027"] == 83
    assert r[(5, "Superior")]["notti_2027"] == 41
    # categoria senza vendite: prezzo vuoto, non zero
    assert r[(5, "Deluxe")]["notti_base"] == 0
    assert r[(5, "Deluxe")]["prezzo_base"] is None
    assert r[(5, "Deluxe")]["camere_2027"] == 2

    mesi = {x["mese"]: x for x in dati["mesi"]}
    assert mesi[5]["stato"] == "osservato"
    assert mesi[5]["raccordo"] == pytest.approx(1.04)
    assert mesi[5]["giorni_2027"] == 31
    assert mesi[5]["notti_reali"] == 124
    assert mesi[5]["ricavo_calendario"] == pytest.approx(31 * 520.0)
    # giugno: file per tipologia del 10/6 → stima, raccordo vuoto
    assert mesi[6]["stato"] == "stima"
    assert mesi[6]["raccordo"] is None


def test_raccordo_vuoto_se_01room_incompleto():
    # file per tipologia esportato dopo fine giugno, ma 01ROOM caricato solo per 9 giorni
    dati = m.costruisci(
        CAMERE, _categorie(date(2026, 7, 5)), _pms(), PROGETTO, 2026, *MAGGIO_GIUGNO
    )
    giugno = next(x for x in dati["mesi"] if x["mese"] == 6)
    assert giugno["stato"] == "stima"
    assert giugno["raccordo"] is None


def test_tipologia_sconosciuta_con_notti_esplode():
    cat = _categorie() + [
        {"data": date(2026, 5, 3), "codice": "XYZ", "notti": 2, "ricavo": 300.0,
         "caricato": date(2026, 6, 10)}
    ]
    with pytest.raises(ValueError, match="XYZ"):
        m.costruisci(CAMERE, cat, _pms(), PROGETTO, 2026, *MAGGIO_GIUGNO)


def test_tipologia_sconosciuta_senza_notti_e_fuori_calendario_ignorate():
    cat = _categorie() + [
        {"data": date(2026, 5, 3), "codice": "DEP", "notti": 0, "ricavo": 0.0,
         "caricato": date(2026, 6, 10)},
        {"data": date(2026, 7, 3), "codice": "DSUP", "notti": 9, "ricavo": 900.0,
         "caricato": date(2026, 6, 10)},
    ]
    dati = m.costruisci(CAMERE, cat, _pms(), PROGETTO, 2026, *MAGGIO_GIUGNO)
    assert sum(x["notti_base"] for x in dati["righe"]) == 4 * 61
```

- [ ] **Step 3: Esegui i test e verifica che falliscano**

Run: `pytest tests/test_budget_camere.py -q`
Expected: FAIL in raccolta con `ModuleNotFoundError: No module named 'verticals.condges.budget_camere.modello'`

- [ ] **Step 4: Scrivi `modello.py`**

```python
"""Budget camere per driver — modello puro (nessun I/O verso BigQuery).

Spec: docs/superpowers/specs/2026-10-04-budget-camere-panorama-design.md
"""

from __future__ import annotations

import calendar
import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

APERTURA_2027 = (4, 20)  # prima notte venduta (Stefano, 2026-10-05)
CHIUSURA_2027 = (10, 20)  # ultima notte venduta
PROGETTO_CSV = Path(__file__).with_name("hpan26piano3.csv")
TUTTO_ANNO = ((1, 1), (12, 31))


def in_calendario(d: date, apertura: tuple[int, int], chiusura: tuple[int, int]) -> bool:
    return apertura <= (d.month, d.day) <= chiusura


def _ultimo_giorno(anno: int, mese: int, chiusura: tuple[int, int]) -> int:
    return chiusura[1] if mese == chiusura[0] else calendar.monthrange(anno, mese)[1]


def giorni_apertura(anno: int, apertura, chiusura) -> dict[int, int]:
    out = {}
    for mese in range(apertura[0], chiusura[0] + 1):
        primo = apertura[1] if mese == apertura[0] else 1
        out[mese] = _ultimo_giorno(anno, mese, chiusura) - primo + 1
    return out


def carica_progetto(path: Path = PROGETTO_CSV) -> dict[str, str]:
    with path.open(newline="") as f:
        return {r["room_id"]: r["categoria_2027"] for r in csv.DictReader(f)}


def inventario(camere: list[dict], progetto: dict[str, str] | None = None) -> dict[str, int]:
    """Camere per categoria; col progetto, le camere indicate cambiano categoria."""
    progetto = progetto or {}
    ids = {c["room_id"] for c in camere}
    categorie = {c["tipologia"] for c in camere}
    for room_id, cat in progetto.items():
        if room_id not in ids:
            raise ValueError(f"progetto: camera {room_id} non è in d_camere")
        if cat not in categorie:
            raise ValueError(f"progetto: categoria {cat!r} non esiste in d_camere")
    return dict(Counter(progetto.get(c["room_id"], c["tipologia"]) for c in camere))


def _base_per_categoria(giornaliero, codici, apertura, chiusura) -> dict:
    """(mese, categoria) → notti, ricavo; solo i giorni del calendario."""
    out: dict = defaultdict(lambda: {"notti": 0, "ricavo": 0.0})
    for r in giornaliero:
        if not r["notti"] or not in_calendario(r["data"], apertura, chiusura):
            continue
        if r["codice"] not in codici:
            raise ValueError(
                f"tipologia venduta {r['codice']!r} non è in d_camere "
                f"({r['notti']} notti il {r['data']})"
            )
        cella = out[(r["data"].month, codici[r["codice"]])]
        cella["notti"] += r["notti"]
        cella["ricavo"] += r["ricavo"]
    return dict(out)


def _totali_pms(giornaliero, apertura, chiusura) -> dict:
    """mese → notti, ricavo 01ROOM, giorni con ricavo caricato, giorni con vendite."""
    out: dict = defaultdict(lambda: {"notti": 0, "ricavo": 0.0, "giorni": 0, "venduti": 0})
    for r in giornaliero:
        if not in_calendario(r["data"], apertura, chiusura):
            continue
        cella = out[r["data"].month]
        cella["notti"] += r["notti"] or 0
        cella["venduti"] += 1 if r["notti"] else 0
        if r["ricavo"] is not None:
            cella["ricavo"] += r["ricavo"]
            cella["giorni"] += 1
    return dict(out)


def notti_2027(
    notti_base: dict[str, int], inv26: dict[str, int], inv27: dict[str, int]
) -> dict[str, int]:
    """Scala ogni categoria col rapporto camere 2027/2026, poi riporta al totale del mese.

    Resti assegnati col metodo del resto più alto: il totale è conservato esatto.
    """
    totale = sum(notti_base.values())
    grezzo = {c: n * inv27.get(c, 0) / inv26[c] for c, n in notti_base.items()}
    somma = sum(grezzo.values())
    if not somma:
        return dict.fromkeys(notti_base, 0)
    quote = {c: v * totale / somma for c, v in grezzo.items()}
    out = {c: int(q) for c, q in quote.items()}
    resto = totale - sum(out.values())
    for c in sorted(quote, key=lambda c: (out[c] - quote[c], c))[:resto]:
        out[c] += 1
    return out


def effetti(righe: list[dict]) -> dict:
    """Occupazione, mix, prezzo di un mese. base + i tre effetti = budget, esatto."""
    r0 = sum(r["notti_base"] * (r["prezzo_base"] or 0) for r in righe)
    t0 = sum(r["notti_base"] for r in righe)
    t1 = sum(r["notti"] for r in righe)
    a_prezzi_base = sum(r["notti"] * (r["prezzo_base"] or 0) for r in righe)
    budget = sum(r["notti"] * (r["prezzo"] or 0) for r in righe)
    medio = r0 / t0 if t0 else 0.0
    return {
        "base": r0,
        "occupazione": (t1 - t0) * medio,
        "mix": a_prezzi_base - t1 * medio,
        "prezzo": budget - a_prezzi_base,
        "budget": budget,
    }


def costruisci(
    camere: list[dict],
    categorie_giorno: list[dict],
    pms_giorno: list[dict],
    progetto: dict[str, str],
    anno_base: int = 2026,
    apertura: tuple[int, int] = APERTURA_2027,
    chiusura: tuple[int, int] = CHIUSURA_2027,
) -> dict:
    codici = {c["cod_camera"]: c["tipologia"] for c in camere}
    inv26 = inventario(camere)
    inv27 = inventario(camere, progetto)
    categorie = sorted(set(inv26) | set(inv27))
    base = _base_per_categoria(categorie_giorno, codici, apertura, chiusura)
    reale = _totali_pms(pms_giorno, *TUTTO_ANNO)
    cal = _totali_pms(pms_giorno, apertura, chiusura)
    giorni_base = giorni_apertura(anno_base, apertura, chiusura)
    giorni_budget = giorni_apertura(anno_base + 1, apertura, chiusura)

    caricati: dict = defaultdict(list)
    for r in categorie_giorno:
        if in_calendario(r["data"], apertura, chiusura):
            caricati[r["data"].month].append(r["caricato"])

    vuoto = {"notti": 0, "ricavo": 0.0, "giorni": 0, "venduti": 0}
    righe, mesi = [], []
    for mese in giorni_budget:
        fine = date(anno_base, mese, _ultimo_giorno(anno_base, mese, chiusura))
        c_mese, r_mese = cal.get(mese, vuoto), reale.get(mese, vuoto)
        osservato = (
            bool(caricati.get(mese))
            and min(caricati[mese]) > fine
            and c_mese["giorni"] == giorni_base[mese]
        )
        stato = "osservato" if osservato else "stima"
        nb = {c: base[(mese, c)]["notti"] for c in categorie if (mese, c) in base}
        n27 = notti_2027(nb, inv26, inv27)
        ricavo_cat = sum(base[(mese, c)]["ricavo"] for c in nb)
        for c in categorie:
            cella = base.get((mese, c))
            righe.append(
                {
                    "mese": mese,
                    "categoria": c,
                    "camere_2026": inv26.get(c, 0),
                    "camere_2027": inv27.get(c, 0),
                    "stato": stato,
                    "notti_base": cella["notti"] if cella else 0,
                    "prezzo_base": cella["ricavo"] / cella["notti"] if cella else None,
                    "notti_2027": n27.get(c, 0),
                }
            )
        mesi.append(
            {
                "mese": mese,
                "stato": stato,
                "giorni_2026": r_mese["venduti"],
                "giorni_2027": giorni_budget[mese],
                "notti_reali": r_mese["notti"],
                "ricavo_reale": r_mese["ricavo"],
                "notti_calendario": c_mese["notti"],
                "ricavo_calendario": c_mese["ricavo"],
                "raccordo": c_mese["ricavo"] / ricavo_cat if osservato and ricavo_cat else None,
                "camere": sum(inv27.values()),
            }
        )
    return {
        "anno_base": anno_base,
        "apertura": apertura,
        "chiusura": chiusura,
        "righe": righe,
        "mesi": mesi,
    }
```

- [ ] **Step 5: Esegui i test e verifica che passino**

Run: `pytest tests/test_budget_camere.py -q && ruff check verticals/condges/budget_camere tests/test_budget_camere.py`
Expected: `12 passed`, ruff senza errori.

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/budget_camere/__init__.py verticals/condges/budget_camere/hpan26piano3.csv verticals/condges/budget_camere/modello.py tests/test_budget_camere.py
git commit -m "feat(budget-camere): modello puro — calendario, inventario 2027, base per categoria, effetti"
```

---

### Task 2: Letture da BigQuery

**Files:**
- Create: `verticals/condges/budget_camere/fonti.py`
- Test: `tests/test_budget_camere.py` (aggiunta in fondo)

**Interfaces:**
- Consumes: `core.config.D_CAMERE`, `F_BOOKINGS_TIPOLOGIA`, `F_PMS_STATISTICHE`, `F_PRODUZIONE_PMS` (stringhe `progetto.dataset.tabella`).
- Produces:
  - `leggi_camere(query=_query) -> list[dict]` — `room_id, cod_camera, tipologia`
  - `leggi_categorie(anno: int, query=_query) -> list[dict]` — `data (date), codice, notti, ricavo, caricato (date)`
  - `leggi_pms(anno: int, query=_query) -> list[dict]` — `data (date), notti, ricavo` (`ricavo` è `None` se `01ROOM` non ha quel giorno)

- [ ] **Step 1: Scrivi i test che falliscono**

In fondo a `tests/test_budget_camere.py`:

```python
from verticals.condges.budget_camere import fonti as f  # noqa: E402


def test_fonti_interrogano_le_tabelle_giuste():
    viste = []

    def finta(sql):
        viste.append(sql)
        return [{"ok": 1}]

    assert f.leggi_camere(finta) == [{"ok": 1}]
    assert f.leggi_categorie(2026, finta) == [{"ok": 1}]
    assert f.leggi_pms(2026, finta) == [{"ok": 1}]
    camere, categorie, pms = viste
    assert "d_camere" in camere and "'HOTEL'" in camere
    assert "f_bookings_tipologia" in categorie and "ricavo_camera" in categorie
    assert "2026" in categorie
    assert "f_pms_statistiche" in pms and "camere_vendute" in pms
    assert "f_produzione_pms" in pms and "'01ROOM'" in pms
    assert "revenue_room" not in pms


def test_leggi_categorie_senza_righe_esplode():
    with pytest.raises(ValueError, match="f_bookings_tipologia"):
        f.leggi_categorie(2026, lambda sql: [])
```

- [ ] **Step 2: Esegui e verifica che falliscano**

Run: `pytest tests/test_budget_camere.py -q`
Expected: FAIL con `ImportError: cannot import name 'fonti'`

- [ ] **Step 3: Scrivi `fonti.py`**

```python
"""Budget camere per driver — letture da BigQuery (sola lettura).

`query` è iniettabile, come in verticals/condges/canone_fonti.py.
"""

from __future__ import annotations

from core.config import D_CAMERE, F_BOOKINGS_TIPOLOGIA, F_PMS_STATISTICHE, F_PRODUZIONE_PMS

BU = "HOTEL"


def _query(sql: str) -> list[dict]:
    from core.bq.client import get_client

    return [dict(r) for r in get_client().query(sql).result()]


def leggi_camere(query=_query) -> list[dict]:
    return query(
        f"SELECT room_id, cod_camera, tipologia FROM `{D_CAMERE}` "
        f"WHERE business_unit_id = '{BU}' ORDER BY room_id"
    )


def leggi_categorie(anno: int, query=_query) -> list[dict]:
    """Venduto giornaliero per tipologia VENDUTA; `caricato` = giorno dell'esportazione."""
    righe = query(
        f"""
        SELECT data, tipologia AS codice, SUM(camere) AS notti,
               SUM(ricavo_camera) AS ricavo, MIN(DATE(data_caricamento)) AS caricato
        FROM `{F_BOOKINGS_TIPOLOGIA}`
        WHERE business_unit_id = '{BU}' AND EXTRACT(YEAR FROM data) = {anno}
        GROUP BY data, tipologia
        """
    )
    if not righe:
        raise ValueError(f"f_bookings_tipologia: nessuna riga {BU} {anno}")
    return righe


def leggi_pms(anno: int, query=_query) -> list[dict]:
    """Notti dalle statistiche, ricavo camere dalla classe 01ROOM (base canonica)."""
    return query(
        f"""
        WITH s AS (
          SELECT DATE(data) AS data, SUM(camere_vendute) AS notti
          FROM `{F_PMS_STATISTICHE}`
          WHERE business_unit_id = '{BU}' AND EXTRACT(YEAR FROM data) = {anno}
          GROUP BY 1
        ), p AS (
          SELECT data, SUM(importo_imponibile) AS ricavo
          FROM `{F_PRODUZIONE_PMS}`
          WHERE business_unit_id = '{BU}' AND classe = '01ROOM'
            AND EXTRACT(YEAR FROM data) = {anno}
          GROUP BY 1
        )
        SELECT COALESCE(s.data, p.data) AS data, s.notti, p.ricavo
        FROM s FULL JOIN p USING (data)
        ORDER BY data
        """
    )
```

- [ ] **Step 4: Esegui e verifica che passino**

Run: `pytest tests/test_budget_camere.py -q && ruff check verticals/condges/budget_camere tests/test_budget_camere.py`
Expected: `14 passed`, ruff senza errori.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/budget_camere/fonti.py tests/test_budget_camere.py
git commit -m "feat(budget-camere): letture BigQuery — camere, venduto per tipologia, notti e 01ROOM"
```

---

### Task 3: Il foglio

**Files:**
- Create: `verticals/condges/budget_camere/foglio.py`
- Test: `tests/test_budget_camere.py` (aggiunta in fondo)

**Interfaces:**
- Consumes: il dict di `modello.costruisci` (chiavi e forme elencate nel Task 1).
- Produces: `scrivi(dati: dict, path: Path) -> Path`. Fogli: `Leggimi`, `Prezzi`, `Mesi`.

Colonne di `Prezzi` (riga 1 = intestazioni, una riga per mese × categoria):

| Col | Contenuto | Tipo |
| --- | --- | --- |
| A | Mese (numero) | valore |
| B | Nome mese | valore |
| C | Categoria | valore |
| D | Camere 2026 | valore |
| E | Camere 2027 | valore |
| F | Stato base | valore |
| G | Notti 2026 (calendario 2027) | valore |
| H | Prezzo medio 2026 | valore, vuoto se G = 0 |
| I | Notti 2027 | **input**, precompilato |
| J | Aumento % | **input**, precompilato 0 |
| K | Prezzo 2027 | `=IF(H="","",H*(1+J))` |
| L | Ricavo base | `=IF(H="",0,G*H)` |
| M | Ricavo 2027 a prezzi 2026 | `=IF(H="",0,I*H)` |
| N | Ricavo 2027 | `=IF(K="",0,I*K)` |
| O | Prezzo base Lybra | **input**, vuoto |
| P | Ragione | **input**, vuoto |

Colonne di `Mesi` (una riga per mese, poi il totale): A Mese · B Nome · C Stato · D Giorni 2026 · E Giorni 2027 · F Notti 2026 reali · G Ricavo camere 2026 reale · H Ricavo 2026 sul calendario 2027 · I Effetto calendario · J Notti base · K Ricavo base · L Notti 2027 · M Ricavo 2027 · N Effetto occupazione · O Effetto mix · P Effetto prezzo · Q Raccordo 01ROOM · R Budget 2027 su base 01ROOM · S Occupazione 2027.

- [ ] **Step 1: Scrivi i test che falliscono**

In fondo a `tests/test_budget_camere.py`:

```python
from openpyxl import load_workbook  # noqa: E402

from verticals.condges.budget_camere import foglio  # noqa: E402


@pytest.fixture
def libro(tmp_path):
    dati = m.costruisci(CAMERE, _categorie(), _pms(), PROGETTO, 2026, *MAGGIO_GIUGNO)
    return load_workbook(foglio.scrivi(dati, tmp_path / "budget.xlsx"))


def test_foglio_prezzi(libro):
    ws = libro["Prezzi"]
    assert ws.max_row == 1 + 6
    riga = {ws.cell(1, c).value: ws.cell(2, c).value for c in range(1, 17)}
    # prima riga: maggio, Deluxe (categorie in ordine alfabetico), nessuna vendita
    assert (riga["Mese"], riga["Categoria"]) == (5, "Deluxe")
    assert riga["Prezzo medio 2026"] is None
    assert riga["Prezzo 2027"] == '=IF(H2="","",H2*(1+J2))'
    assert riga["Ricavo base"] == '=IF(H2="",0,G2*H2)'
    assert riga["Ricavo 2027 a prezzi 2026"] == '=IF(H2="",0,I2*H2)'
    assert riga["Ricavo 2027"] == '=IF(K2="",0,I2*K2)'
    assert riga["Aumento %"] == 0
    # seconda riga: maggio, Standard
    assert ws["C3"].value == "Standard"
    assert ws["G3"].value == 93
    assert ws["H3"].value == pytest.approx(100.0)
    assert ws["I3"].value == 83
    # le celle di input sono colorate, quelle calcolate no
    assert ws["J3"].fill.fgColor.rgb.endswith("FFF2CC")
    assert not ws["K3"].fill.fgColor.rgb.endswith("FFF2CC")


def test_foglio_mesi(libro):
    ws = libro["Mesi"]
    assert [ws["A2"].value, ws["A3"].value, ws["A4"].value] == [5, 6, "Totale"]
    assert ws["C2"].value == "osservato" and ws["C3"].value == "stima"
    assert ws["I2"].value == "=H2-G2"
    assert ws["J2"].value == "=SUMIF(Prezzi!$A$2:$A$7,A2,Prezzi!$G$2:$G$7)"
    assert ws["N2"].value == "=IF(J2=0,0,(L2-J2)*K2/J2)"
    assert ws["O2"].value == (
        "=SUMIF(Prezzi!$A$2:$A$7,A2,Prezzi!$M$2:$M$7)-IF(J2=0,0,L2*K2/J2)"
    )
    assert ws["P2"].value == "=M2-SUMIF(Prezzi!$A$2:$A$7,A2,Prezzi!$M$2:$M$7)"
    assert ws["Q2"].value == pytest.approx(1.04)
    assert ws["Q3"].value is None  # giugno è una stima: raccordo vuoto, non zero
    assert ws["R2"].value == '=IF(Q2="","n.d.",M2*Q2)'
    assert ws["R4"].value == '=IF(COUNTBLANK(Q2:Q3)>0,"n.d.",SUM(R2:R3))'
    assert ws["S2"].value == "=L2/(5*E2)"
    assert ws["M4"].value == "=SUM(M2:M3)"


def test_foglio_leggimi(libro):
    testo = " ".join(str(r[0].value) for r in libro["Leggimi"].iter_rows() if r[0].value)
    assert "1 maggio" in testo and "30 giugno" in testo
    assert "giugno" in testo and "stima" in testo
```

- [ ] **Step 2: Esegui e verifica che falliscano**

Run: `pytest tests/test_budget_camere.py -q`
Expected: FAIL con `ImportError: cannot import name 'foglio'`

- [ ] **Step 3: Scrivi `foglio.py`**

```python
"""Budget camere per driver — il foglio dove Stefano scrive gli aumenti.

Valori = base 2026 da BigQuery. Formule = tutto ciò che dipende dagli input
(celle gialle): cambiando un aumento, ricavo ed effetti si aggiornano in Excel.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

INPUT = PatternFill("solid", fgColor="FFF2CC")
GRASSETTO = Font(bold=True)
MESI = {
    1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
    7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre",
}
COL_PREZZI = [
    "Mese", "Nome mese", "Categoria", "Camere 2026", "Camere 2027", "Stato base",
    "Notti 2026 (calendario 2027)", "Prezzo medio 2026", "Notti 2027", "Aumento %",
    "Prezzo 2027", "Ricavo base", "Ricavo 2027 a prezzi 2026", "Ricavo 2027",
    "Prezzo base Lybra", "Ragione",
]
COL_MESI = [
    "Mese", "Nome mese", "Stato", "Giorni 2026", "Giorni 2027", "Notti 2026 reali",
    "Ricavo camere 2026 reale (01ROOM)", "Ricavo 2026 sul calendario 2027 (01ROOM)",
    "Effetto calendario", "Notti base", "Ricavo base", "Notti 2027", "Ricavo 2027",
    "Effetto occupazione", "Effetto mix", "Effetto prezzo", "Raccordo 01ROOM",
    "Budget 2027 su base 01ROOM", "Occupazione 2027",
]


def _intesta(ws, colonne: list[str]) -> None:
    ws.append(colonne)
    for cella in ws[1]:
        cella.font = GRASSETTO
    ws.freeze_panes = "A2"


def _prezzi(ws, righe: list[dict]) -> None:
    _intesta(ws, COL_PREZZI)
    for i, r in enumerate(righe, start=2):
        ws.append(
            [
                r["mese"], MESI[r["mese"]], r["categoria"], r["camere_2026"],
                r["camere_2027"], r["stato"], r["notti_base"], r["prezzo_base"],
                r["notti_2027"], 0,
                f'=IF(H{i}="","",H{i}*(1+J{i}))',
                f'=IF(H{i}="",0,G{i}*H{i})',
                f'=IF(H{i}="",0,I{i}*H{i})',
                f'=IF(K{i}="",0,I{i}*K{i})',
                None, None,
            ]
        )
        for col in "IJOP":
            ws[f"{col}{i}"].fill = INPUT
        for col in "HKO":
            ws[f"{col}{i}"].number_format = "#,##0.00"
        for col in "LMN":
            ws[f"{col}{i}"].number_format = "#,##0"
        ws[f"J{i}"].number_format = "0.0%"


def _mesi(ws, mesi: list[dict], ultima_prezzi: int) -> None:
    _intesta(ws, COL_MESI)

    def somma(col: str, i: int) -> str:
        return (
            f"SUMIF(Prezzi!$A$2:$A${ultima_prezzi},A{i},"
            f"Prezzi!${col}$2:${col}${ultima_prezzi})"
        )

    for i, x in enumerate(mesi, start=2):
        ws.append(
            [
                x["mese"], MESI[x["mese"]], x["stato"], x["giorni_2026"], x["giorni_2027"],
                x["notti_reali"], x["ricavo_reale"], x["ricavo_calendario"],
                f"=H{i}-G{i}",
                f"={somma('G', i)}", f"={somma('L', i)}",
                f"={somma('I', i)}", f"={somma('N', i)}",
                f"=IF(J{i}=0,0,(L{i}-J{i})*K{i}/J{i})",
                f"={somma('M', i)}-IF(J{i}=0,0,L{i}*K{i}/J{i})",
                f"=M{i}-{somma('M', i)}",
                x["raccordo"],
                f'=IF(Q{i}="","n.d.",M{i}*Q{i})',
                f"=L{i}/({x['camere']}*E{i})",
            ]
        )
    fine = len(mesi) + 1
    t = fine + 1
    camere = mesi[0]["camere"]
    ws.append(
        ["Totale", None, None]
        + [f"=SUM({col}2:{col}{fine})" for col in "DEFGHIJKLMNOP"]
        + [
            None,
            f'=IF(COUNTBLANK(Q2:Q{fine})>0,"n.d.",SUM(R2:R{fine}))',
            f"=L{t}/({camere}*E{t})",
        ]
    )
    for cella in ws[t]:
        cella.font = GRASSETTO
    for riga in ws.iter_rows(min_row=2, max_row=t):
        for cella in riga:
            lettera = cella.column_letter
            if lettera in "GHIKMNOPR":
                cella.number_format = "#,##0"
            elif lettera == "Q":
                cella.number_format = "0.0000"
            elif lettera == "S":
                cella.number_format = "0.0%"


def _leggimi(ws, dati: dict) -> None:
    (am, ag), (cm, cg) = dati["apertura"], dati["chiusura"]
    base, budget = dati["anno_base"], dati["anno_base"] + 1
    stime = [MESI[x["mese"]] for x in dati["mesi"] if x["stato"] == "stima"]
    righe = [
        f"Budget camere Hotel Panorama {budget} — base {base}",
        f"Calendario {budget}: dal {ag} {MESI[am]} al {cg} {MESI[cm]} (estremi inclusi).",
        "Foglio Prezzi: scrivi solo nelle celle gialle. Aumento % sul prezzo medio "
        f"{base} della categoria in quel mese; Ragione = perché.",
        f"Notti {budget} precompilate: le notti {base} di ogni categoria, scalate col "
        f"rapporto camere {budget}/{base}, a parità di notti totali del mese. "
        "Correggile se sai di più.",
        "Foglio Mesi: effetto calendario, occupazione, mix e prezzo si aggiornano da soli.",
        "Prezzi su base gestionale (rapporto per tipologia venduta); la colonna Raccordo "
        "riporta il totale alla base 01ROOM.",
    ]
    if stime:
        righe.append(
            "Mesi in stato stima (base non ancora osservata per intero, raccordo vuoto): "
            + ", ".join(stime)
            + "."
        )
    for testo in righe:
        ws.append([testo])
    ws["A1"].font = GRASSETTO
    ws.column_dimensions["A"].width = 120


def scrivi(dati: dict, path: Path) -> Path:
    wb = Workbook()
    _leggimi(wb.active, dati)
    wb.active.title = "Leggimi"
    _prezzi(wb.create_sheet("Prezzi"), dati["righe"])
    _mesi(wb.create_sheet("Mesi"), dati["mesi"], ultima_prezzi=len(dati["righe"]) + 1)
    wb.save(path)
    return path
```

- [ ] **Step 4: Esegui e verifica che passino**

Run: `pytest tests/test_budget_camere.py -q && ruff check verticals/condges/budget_camere tests/test_budget_camere.py`
Expected: `17 passed`, ruff senza errori.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/budget_camere/foglio.py tests/test_budget_camere.py
git commit -m "feat(budget-camere): foglio degli aumenti con formule vive per ricavo e quattro effetti"
```

---

### Task 4: Comando `hotelops budget base` e controllo sui dati veri

**Files:**
- Create: `verticals/condges/budget_camere/base.py`
- Modify: `cli.py` — una funzione `cmd_budget` accanto a `cmd_canone` (riga ~205); il parser dopo il blocco `# canone` (riga ~1067); una voce `"budget": cmd_budget` nel dict `handlers` (riga ~1450)
- Test: `tests/test_budget_camere.py` (aggiunta in fondo)

**Interfaces:**
- Consumes: `fonti.leggi_camere/leggi_categorie/leggi_pms`, `modello.costruisci/carica_progetto/effetti/APERTURA_2027/CHIUSURA_2027`, `foglio.scrivi`.
- Produces: `base.run(out_dir: Path, apertura=APERTURA_2027, chiusura=CHIUSURA_2027, anno_base=2026, query=fonti._query, adesso: datetime | None = None) -> Path`; `base.giorno(testo: str) -> tuple[int, int]` (`"04-20"` → `(4, 20)`).

- [ ] **Step 1: Scrivi i test che falliscono**

In fondo a `tests/test_budget_camere.py`:

```python
from datetime import datetime  # noqa: E402

from verticals.condges.budget_camere import base  # noqa: E402


def _finta(sql):
    if "d_camere" in sql:
        return CAMERE
    if "f_bookings_tipologia" in sql:
        return _categorie()
    return _pms()


def test_run_scrive_il_foglio_e_riepiloga(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(m, "carica_progetto", lambda: PROGETTO)
    path = base.run(
        tmp_path, *MAGGIO_GIUGNO, query=_finta, adesso=datetime(2026, 10, 5, 9, 30)
    )
    assert path == tmp_path / "budget_camere_HOTEL_2027_base_20261005-0930.xlsx"
    assert load_workbook(path).sheetnames == ["Leggimi", "Prezzi", "Mesi"]
    out = capsys.readouterr().out
    assert "maggio" in out and "osservato" in out
    assert "giugno" in out and "stima" in out
    assert str(path) in out


def test_giorno():
    assert base.giorno("04-20") == (4, 20)
    with pytest.raises(ValueError):
        base.giorno("20 aprile")
```

- [ ] **Step 2: Esegui e verifica che falliscano**

Run: `pytest tests/test_budget_camere.py -q`
Expected: FAIL con `ImportError: cannot import name 'base'`

- [ ] **Step 3: Scrivi `base.py`**

```python
"""`hotelops budget base` — legge il 2026 da BigQuery e genera il foglio degli aumenti."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from verticals.condges.budget_camere import foglio, fonti, modello


def giorno(testo: str) -> tuple[int, int]:
    """'04-20' → (4, 20)."""
    d = datetime.strptime(testo, "%m-%d")
    return d.month, d.day


def run(
    out_dir: Path,
    apertura: tuple[int, int] = modello.APERTURA_2027,
    chiusura: tuple[int, int] = modello.CHIUSURA_2027,
    anno_base: int = 2026,
    query=fonti._query,
    adesso: datetime | None = None,
) -> Path:
    adesso = adesso or datetime.now()
    dati = modello.costruisci(
        fonti.leggi_camere(query),
        fonti.leggi_categorie(anno_base, query),
        fonti.leggi_pms(anno_base, query),
        modello.carica_progetto(),
        anno_base,
        apertura,
        chiusura,
    )
    nome = f"budget_camere_HOTEL_{anno_base + 1}_base_{adesso:%Y%m%d-%H%M}.xlsx"
    path = foglio.scrivi(dati, Path(out_dir) / nome)

    print(f"\n  {'mese':<10}{'stato':<11}{'notti':>7}{'ricavo base':>13}{'effetto mix':>13}")
    for x in dati["mesi"]:
        righe = [
            {
                "notti_base": r["notti_base"],
                "prezzo_base": r["prezzo_base"],
                "notti": r["notti_2027"],
                "prezzo": r["prezzo_base"],
            }
            for r in dati["righe"]
            if r["mese"] == x["mese"]
        ]
        e = modello.effetti(righe)
        notti = sum(r["notti_base"] for r in righe)
        print(
            f"  {foglio.MESI[x['mese']]:<10}{x['stato']:<11}{notti:>7}"
            f"{e['base']:>13,.0f}{e['mix']:>13,.0f}"
        )
    stime = [foglio.MESI[x["mese"]] for x in dati["mesi"] if x["stato"] == "stima"]
    if stime:
        print(f"\n  ⚠ base non osservata per intero: {', '.join(stime)}")
    print(f"\n  ✓ {path}")
    return path
```

- [ ] **Step 4: Aggancia il comando in `cli.py`**

Dopo `cmd_canone` (la funzione che finisce con `run(aggiorna=True, push=args.push)`):

```python
def cmd_budget(args):
    """Budget per driver: genera il foglio della base camere."""
    from pathlib import Path

    from verticals.condges.budget_camere import base

    if args.budget_cmd != "base":
        print("uso: hotelops budget base [--out DIR] [--apertura MM-GG] [--chiusura MM-GG]")
        sys.exit(1)
    base.run(
        Path(args.out).expanduser(),
        apertura=base.giorno(args.apertura),
        chiusura=base.giorno(args.chiusura),
    )
```

Dopo il blocco `# canone` del parser (dopo `p_canone.add_argument("--push", ...)`):

```python
    # budget
    p_budget = sub.add_parser("budget", help="Budget per driver (camere Hotel Panorama)")
    budget_sub = p_budget.add_subparsers(dest="budget_cmd")
    pb_base = budget_sub.add_parser(
        "base", help="Genera il foglio: base 2026 per mese × categoria, aumenti da scrivere"
    )
    pb_base.add_argument("--out", default="~/Downloads", help="Cartella di uscita")
    pb_base.add_argument("--apertura", default="04-20", help="Prima notte venduta, MM-GG")
    pb_base.add_argument("--chiusura", default="10-20", help="Ultima notte venduta, MM-GG")
```

Nel dict `handlers`, dopo `"canone": cmd_canone,`:

```python
        "budget": cmd_budget,
```

- [ ] **Step 5: Esegui tutti i test**

Run: `pytest tests/test_budget_camere.py -q && ruff check cli.py verticals/condges/budget_camere tests/test_budget_camere.py && hotelops budget base --help`
Expected: `19 passed`, ruff senza errori, l'aiuto mostra `--out`, `--apertura`, `--chiusura`.

- [ ] **Step 6: Controllo sui dati veri (BigQuery, sola lettura)**

Run: `hotelops budget base --out "$TMPDIR"`

Atteso con i dati caricati al 2026-10-05 (file per tipologia del 2 agosto):

| mese | stato | notti base | ricavo base | effetto mix |
| --- | --- | --- | --- | --- |
| aprile | osservato | 451 | 70.702 | circa +750 |
| maggio | osservato | 2.334 | 434.852 | circa +18.200 |
| giugno | osservato | 2.168 | 468.382 | circa +22.700 |
| luglio | osservato | 2.333 | 473.531 | circa +14.600 |
| agosto, settembre, ottobre | stima | — | — | — |

Le notti e i ricavi di base devono coincidere all'euro; l'effetto mix può differire di qualche decina di euro (le notti 2027 sono intere). Apri il file e controlla nel foglio `Mesi`: raccordo aprile ≈ 1,064, maggio ≈ 1,007, giugno ≈ 1,080, luglio ≈ 1,068; agosto–ottobre vuoti; `R` del totale = «n.d.»; `N + O + P = M − K` su ogni riga. Nel foglio `Prezzi`, colonna E sommata su un mese = 86, con Deluxe 20, Classic 16, Superior 16, Standard 11, Executive 9, Suite 4, Comfort 3.

Se un numero non torna: fermati e riporta la differenza, non correggere il test.

- [ ] **Step 7: Commit**

```bash
git add verticals/condges/budget_camere/base.py cli.py tests/test_budget_camere.py
git commit -m "feat(budget-camere): hotelops budget base — genera il foglio degli aumenti dal 2026 osservato"
```

- [ ] **Step 8: Gate di lettura**

Manda a Stefano il file generato al passo 6 (non una descrizione). Il merge aspetta che l'abbia aperto e abbia detto se la regola delle notti 2027 precompilate gli torna (punto aperto 1 della spec).

---

## Fuori da questo piano

- Intake e promote del foglio compilato, `f_budget_driver`, `f_budget_versioni`, approvazione, le tre viste per il Management OS: piano 2, da scrivere su un foglio compilato vero.
- Volume per segmento e prezzi base Lybra: quando arrivano le due esportazioni.
- Spegnimento delle letture del budget vecchio: cambio separato, già deciso.
- La costante di 76 camere in `ingest/flussi/ingest_occupazione_pms.py`: segnalata, non toccata qui.
