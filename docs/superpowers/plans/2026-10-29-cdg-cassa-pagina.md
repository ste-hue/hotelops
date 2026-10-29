# CdG · pagina Cassa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La prima pagina viva di `cdg.panorama-host.com`: saldi mensili INTUR e ORTI dal PF di settembre promosso, canone e progetti come leve, scenari salvati con lineage in `hotelops_previsioni`.

**Architecture:** Motore Python puro (`cassa_motore`) che calcola saldi, minimi e consolidato da un `Input` esplicito, **in centesimi interi**; letture BigQuery isolate in `cassa_fonti`; scenario come documento JSON (`cdg-cassa-scenario/1`) che va e viene dalle tre tabelle `p_*`; builder sul modello di `build_canone_artifact` che incapsula payload + porting JS del motore in un HTML autonomo pubblicato su KV; Worker `cdg` clone di `canone`. Nessun write-path dal browser.

**Tech Stack:** Python ≥3.11, Pydantic, `google-cloud-bigquery` via `core.bq.client.get_client`, `bq_write_validated`, openpyxl (parser PF), HTML/JS senza dipendenze, Cloudflare Worker (`jose`, vitest), `node` per il test di parità JS/Python.

**Spec:** `docs/superpowers/specs/2026-10-29-cdg-cassa-pagina-design.md` (letta insieme a `docs/superpowers/specs/2026-10-28-cdg-controllo-finanziario-integrato-design.md`). Correzioni di Stefano del 29/10 incorporate: attestazione = quadratura per conto; fatti riconciliati per pagamento (anche parziali); gambe intercompany mancanti restano mancanti; parser PF prima del primo render; moneta in centesimi interi con parità di arrotondamento JS/Python.

## Global Constraints

- **Moneta = centesimi interi (`int`)** in motore, scenario JSON, payload e tabelle `p_*` (`*_cent INT64`). Il `float` di BigQuery entra una volta sola, al bordo, con `to_cent(x) = int(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)`; l'euro riappare solo nel formato a video. Percentuali (IVA) in interi: `lordo = (netto * (100 + aliquota) + 50) // 100` (half-up); in JS `Math.floor((netto * (100 + aliquota) + 50) / 100)`. Nessuna divisione in virgola mobile sui soldi.
- Ogni scrittura BigQuery passa da `core.bq.write.bq_write_validated` (I1); nessun `client.insert_rows` diretto.
- Ingest solo intake → promote; il parser nuovo rispetta il contratto `--file X --societa GROUP --raw-object-id Y` e accetta `--dry-run`.
- Nome source a 4 parti: `CDG_SCENARIOCASSA_GROUP_APPEND` (`GROUP` è l'unico valore ammesso da `SOCIETA_VALUES` per il gruppo).
- Tabelle previsioni: `hotelops-suite.hotelops_previsioni.p_scenari`, `.p_scenario_flussi`, `.p_progetti_pagamenti`; dataset in `EU`.
- Numeri aziendali fuori da git: fixture sintetiche nei test; snapshot in `.hotelops_state/cdg_cassa/`; HTML in `docs/reports/artifacts/` (entrambi gitignored). I test di replica sui dati veri si saltano se il file locale manca.
- **Nessuna gamba intercompany inventata**: un flusso presente su una sola società resta su quella società; il consolidato espone il residuo, mai un trasferimento fittizio.
- TDD: test prima, poi codice; `pytest` + `ruff check .` + `ruff format .` verdi su ogni commit.
- Lavorare su ramo `feat/cdg-cassa-pagina` in un worktree (`superpowers:using-git-worktrees`); stage per nome, mai `git add .`; messaggi di commit con le due righe di attribuzione della sessione.
- Baseline = una sola `file_sorgente` per società in `f_piano_finanziario_input` con `fonte='PIANO_FINANZIARIO'`; righe del mese chiuso (2026-09) escluse.
- Mesi: stringhe `YYYY-MM`; entrate e uscite sempre positive, il segno lo dà la direzione.
- Nessun merge su `main` finché Stefano non ha visto il render con dati reali (gate hub, Task 8).

## Review Focus

1. **PF con due versioni per una società** (ri-promozione a metà): il builder deve fermarsi con il nome dei due file, non sommare → test in Task 7.
2. **Pagamento di un progetto spento** modificato in pagina: non deve muovere i saldi e la riga deve dirlo → test JS in Task 8.
3. **Arrotondamenti**: 100.000,00 in 3 rate, IVA 22% su 10,01, canone 800.000 netto in 4 rate lorde — stesso centesimo in Python e JS → test in Task 1 e Task 8.
4. **Canone con una gamba sola** nel PF (ottobre 50.000 solo ORTI): il consolidato espone il residuo e INTUR non riceve nulla → test in Task 1 e Task 7.
5. **Fatto parziale** (acconto 70.000 su un pagamento previsto 72.300): il fatto conta nel suo mese, la previsione di quel pagamento scende a 2.300, gli altri pagamenti del progetto non si muovono → test in Task 2.

---

### Task 1: Motore — saldi, minimi, consolidato, distribuzione

**Files:**
- Create: `verticals/condges/cassa_motore.py`
- Test: `tests/test_cassa_motore.py`

**Interfaces:**
- Produces (dataclass `frozen=True` dove non indicato; ogni importo è `int` centesimi):
  - `ORIGINI = ("pf", "canone", "finanziamento", "progetto", "manuale", "fatto")`
  - `def to_cent(x: float | str | Decimal) -> int` · `def iva(netto: int, aliquota: int) -> int` (half-up)
  - `Ancora(societa: str, data: date, saldo: int, attestato: bool, conti: dict[str, "Conto"])`, `Conto(saldo: int, attestato: bool, motivo: str)`
  - `Riga(societa: str, voce_id: str, mese: str, importo: int, direzione: Literal["E", "U"], origine: str)`
  - `Flusso(nome: str, da: str, a: str, mese: str, importo: int, stato: str)` — `da`/`a` ∈ {"ORTI","INTUR","TERZI"}; `stato` ∈ {"pf","una_gamba","scenario"}
  - `Pagamento(nome: str, mesi: dict[str, int], aliquota_iva: int = 22, stato: str = "ipotesi", fornitore_id: str | None = None)` (mutable)
  - `Progetto(id: str, nome: str, societa: str, acceso: bool, stato: str, pagamenti: list[Pagamento])` (mutable)
  - `Finanziamento(id: str, nome: str, societa: str, erogazioni: dict[str, int], rate: dict[str, int], stato: str)`
  - `Fatto(societa: str, progetto_id: str, fornitore_id: str | None, mese: str, importo: int, evento_id: str)`
  - `Scenario(nome: str, progetti: list[Progetto], finanziamenti: list[Finanziamento], canone: "ScalettaCanone | None" = None, manuali: list[Riga] = [], soglia: int = 0)`
  - `Input(mesi: list[str], mesi_ipotetici: frozenset[str], ancore: dict[str, Ancora], pf: list[Riga], intercompany: list[Flusso], fatti: list[Fatto], scenario: Scenario)`
  - `RigaMese(mese: str, societa: str, ini: int, entrate: dict[str, int], uscite: dict[str, int], fin: int)` — chiavi di `entrate`/`uscite` = `ORIGINI`
  - `Minimo(mese: str, saldo: int, sotto_soglia: tuple[str, ...], coda_mese: str | None, coda_saldo: int | None)`
  - `Consolidato(mese: str, saldo: int, intercompany_nettato: int, residuo: int)`
  - `Risultato(righe: list[RigaMese], minimi: dict[str, Minimo], consolidato: list[Consolidato], non_riconciliati: list[Fatto])`
  - `def calcola(inp: Input) -> Risultato`
  - `def distribuisci(totale: int, da: str, n: int, mesi: list[str]) -> dict[str, int]`
  - `def to_dict(r: Risultato) -> dict` (JSON-serializzabile, stessi nomi dei campi)

- [ ] **Step 1: Write the failing tests** (fixture sintetica: 3 mesi `["2026-10","2026-11","2026-12"]`, ancore INTUR 100.000 / ORTI 500.000 in centesimi, PF: ORTI E 50.000 ott, U 20.000 ogni mese; INTUR U 10.000 ogni mese; helper `eur(x) = to_cent(x)`)

```python
def test_to_cent_half_up():
    assert to_cent(10.005) == 1001 and to_cent("0.1") + to_cent("0.2") == 30 and to_cent(1579384.97) == 157_938_497

def test_iva_half_up():
    assert iva(1001, 22) == 1221 and iva(1000, 0) == 1000 and iva(5, 10) == 6

def test_distribuisci_ultima_rata_assorbe_i_centesimi():
    assert distribuisci(10_000_000, "2026-10", 3, MESI) == {"2026-10": 3_333_333, "2026-11": 3_333_333, "2026-12": 3_333_334}

def test_distribuisci_oltre_orizzonte():
    with pytest.raises(ValueError, match="oltre l'orizzonte"):
        distribuisci(1_000_000, "2026-12", 2, MESI)

def test_saldo_finale_e_ancora_piu_entrate_meno_uscite():
    ris = calcola(inp_base())
    orti = [r for r in ris.righe if r.societa == "ORTI"]
    assert (orti[0].ini, orti[0].fin, orti[-1].fin) == (eur(500_000), eur(530_000), eur(490_000))
    assert ris.minimi["ORTI"].mese == "2026-12" and ris.minimi["ORTI"].saldo == eur(490_000)

def test_intercompany_stesso_mese_si_annulla_nel_consolidato():
    ris = calcola(inp_base(intercompany=[Flusso("canone", "ORTI", "INTUR", "2026-11", eur(24_400), "pf")]))
    nov = next(c for c in ris.consolidato if c.mese == "2026-11")
    assert nov.intercompany_nettato == eur(24_400) and nov.residuo == 0
    assert nov.saldo == sum(r.fin for r in ris.righe if r.mese == "2026-11")

def test_verso_terzi_non_e_intercompany():
    ott = next(c for c in calcola(inp_base(intercompany=[Flusso("fitto CVM", "ORTI", "TERZI", "2026-10", eur(50_000), "pf")])).consolidato if c.mese == "2026-10")
    assert ott.intercompany_nettato == 0 and ott.residuo == 0

def test_gamba_sola_resta_residuo_e_non_inventa_la_contropartita():
    ris = calcola(inp_base(intercompany=[Flusso("canone", "ORTI", "INTUR", "2026-10", eur(50_000), "una_gamba")]))
    ott = next(c for c in ris.consolidato if c.mese == "2026-10")
    intur_ott = next(r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-10")
    orti_ott = next(r for r in ris.righe if r.societa == "ORTI" and r.mese == "2026-10")
    assert orti_ott.uscite["canone"] == eur(50_000) and intur_ott.entrate["canone"] == 0
    assert ott.intercompany_nettato == 0 and ott.residuo == eur(50_000)

def test_minimo_coda_separato_dal_minimo_pf():
    m = calcola(inp_base(mesi_ipotetici={"2026-12"})).minimi["ORTI"]
    assert m.mese == "2026-11" and m.coda_mese == "2026-12"

def test_sotto_soglia_elenca_i_mesi():
    assert calcola(inp_base(soglia=eur(495_000))).minimi["ORTI"].sotto_soglia == ("2026-12",)
```

- [ ] **Step 2: Run tests to verify they fail** — `pytest tests/test_cassa_motore.py -v` → FAIL con `ModuleNotFoundError: verticals.condges.cassa_motore`.

- [ ] **Step 3: Implement `cassa_motore.py`** — dataclass come in Interfaces; `calcola` scorre `inp.mesi` in ordine, per società: `ini` = ancora al primo mese, poi `fin` precedente; `entrate[origine]`/`uscite[origine]` sommano `pf` (per `direzione`), `intercompany` (`a==societa` entrata, `da==societa` uscita, origine `canone`; con `stato="una_gamba"` conta solo il lato `da`), `scenario.finanziamenti` (erogazioni entrata, rate uscita, origine `finanziamento`), progetti accesi (`iva(pagamento.mesi[m], aliquota)`, origine `progetto`), `manuali`, `fatti` (origine `fatto`; riconciliazione in Task 2). Consolidato: `saldo` = Σ fin; `intercompany_nettato` = Σ flussi ORTI↔INTUR con `stato != "una_gamba"` del mese; `residuo` = Σ flussi `una_gamba` del mese. `Minimo`: minimo su mesi non ipotetici; `coda_*` sul minimo dei mesi ipotetici, `None` se non ce ne sono. `distribuisci`: `totale // n` per le prime n−1 rate, l'ultima = totale − somma; `ValueError("oltre l'orizzonte: …")` se `da`+n−1 esce da `mesi`.

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `git add verticals/condges/cassa_motore.py tests/test_cassa_motore.py && git commit -m "feat(cdg): motore cassa headless in centesimi — saldi per società, minimi, consolidato senza gambe inventate"`

---

### Task 2: Motore — scaletta canone, fatti riconciliati per pagamento, erogazioni

**Files:**
- Modify: `verticals/condges/cassa_motore.py`
- Test: `tests/test_cassa_motore.py`

**Interfaces:**
- Produces: `ScalettaCanone(netto_per_anno: dict[int, int], rate_n: int, da_mese: str, calendario: dict[str, int] | None = None, aliquota_iva: int = 22)`; `def flussi_canone(s: ScalettaCanone, mesi: list[str]) -> list[Flusso]` (lordi, `da="ORTI"`, `a="INTUR"`, `nome="Fitto Hotel (canone)"`, `stato="scenario"`); in `calcola`, quando `scenario.canone` è presente, i flussi `intercompany` con `nome` che inizia per `"Fitto Hotel"` **degli anni coperti dalla scaletta** vengono sostituiti da `flussi_canone`.
- **Riconciliazione fatti** (regola di Stefano): un `Fatto` di `progetto_id` P e `fornitore_id` F si riconcilia con i `Pagamento` del progetto P che hanno lo stesso `fornitore_id`, in ordine di mese; l'importo del fatto (lordo) riduce i `mesi` di quei pagamenti partendo dal più vecchio fino a esaurimento; il fatto conta nel proprio mese come `fatto`. Nessun altro pagamento del progetto cambia. Un fatto senza pagamento con lo stesso fornitore finisce in `Risultato.non_riconciliati`, conta comunque come `fatto`, non riduce nulla. Vale anche per progetti spenti (il fatto è un fatto).
- **Erogazioni**: le `Riga` PF con `voce_id == "ENTRATE_FINANZIAMENTI"` di una società vengono sostituite dalle `erogazioni` dei `Finanziamento` dello scenario della stessa società quando ne esistono; altrimenti restano con origine `finanziamento`.

- [ ] **Step 1: Write the failing tests**

```python
def test_flussi_canone_lordi_quattro_rate():
    fl = flussi_canone(ScalettaCanone({2027: eur(800_000)}, 4, "2027-03"), MESI_9)  # ott 2026 → giu 2027
    assert [f.mese for f in fl] == ["2027-03", "2027-04", "2027-05", "2027-06"]
    assert all(f.importo == eur(244_000) and f.da == "ORTI" and f.a == "INTUR" for f in fl)

def test_canone_rate_non_divisibili_quadrano_al_centesimo():
    fl = flussi_canone(ScalettaCanone({2027: eur(100_000)}, 3, "2027-03"), MESI_9)
    assert sum(f.importo for f in fl) == eur(122_000) and [f.importo for f in fl] == [4_066_666, 4_066_666, 4_066_668]

def test_calendario_libero_vince_sulle_rate():
    s = ScalettaCanone({2027: eur(800_000)}, 4, "2027-03", calendario={"2027-06": eur(800_000)})
    assert [(f.mese, f.importo) for f in flussi_canone(s, MESI_9)] == [("2027-06", eur(976_000))]

def test_scaletta_sostituisce_il_canone_pf_solo_negli_anni_coperti():
    inp = inp_base(intercompany=[Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", eur(244_000), "pf"),
                                 Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2027-06", eur(244_000), "pf")],
                   canone=ScalettaCanone({2027: eur(800_000)}, 4, "2027-03"))
    intur = {r.mese: r.entrate["canone"] for r in calcola(inp).righe if r.societa == "INTUR"}
    assert intur["2026-11"] == eur(244_000) and intur["2027-03"] == eur(244_000) and intur["2027-06"] == eur(244_000)

def test_progetto_120k_in_sei_rate_muove_sei_mesi():
    p = Progetto("x", "X", "INTUR", True, "ipotesi", [Pagamento("unica", distribuisci(eur(120_000), "2026-10", 6, MESI_9), 0)])
    usc = [r.uscite["progetto"] for r in calcola(inp_base(progetti=[p])).righe if r.societa == "INTUR"]
    assert usc[:6] == [eur(20_000)] * 6 and usc[6:] == [0, 0, 0]

def test_iva_per_aliquota_e_reverse_charge():
    p = Progetto("x", "X", "INTUR", True, "ipotesi", [Pagamento("arredi", {"2026-10": 1001}, 22), Pagamento("amcn", {"2026-10": 1000}, 0)])
    ott = next(r for r in calcola(inp_base(progetti=[p])).righe if r.societa == "INTUR" and r.mese == "2026-10")
    assert ott.uscite["progetto"] == 1221 + 1000

def test_progetto_spento_non_conta():
    p = Progetto("x", "X", "INTUR", False, "ipotesi", [Pagamento("a", {"2026-10": 1000}, 0)])
    assert all(r.uscite["progetto"] == 0 for r in calcola(inp_base(progetti=[p])).righe)

def test_fatto_parziale_riduce_solo_il_suo_pagamento():
    p = Progetto("p3", "P3", "INTUR", True, "ipotesi", [
        Pagamento("anticipo AMCN", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN"),
        Pagamento("SAL 1 AMCN", {"2026-12": eur(60_000)}, 0, fornitore_id="AMCN"),
        Pagamento("arredi", {"2026-10": eur(10_000)}, 0, fornitore_id="ARREDI")])
    inp = inp_base(progetti=[p], fatti=[Fatto("INTUR", "p3", "AMCN", "2026-10", eur(70_000), "ev1")])
    ris = calcola(inp)
    ott = next(r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-10")
    dic = next(r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-12")
    assert ott.uscite["fatto"] == eur(70_000) and ott.uscite["progetto"] == eur(2_300) + eur(10_000)
    assert dic.uscite["progetto"] == eur(60_000) and ris.non_riconciliati == []

def test_fatto_oltre_il_previsto_scala_sul_pagamento_successivo():
    p = Progetto("p3", "P3", "INTUR", True, "ipotesi", [
        Pagamento("anticipo", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN"),
        Pagamento("SAL 1", {"2026-12": eur(60_000)}, 0, fornitore_id="AMCN")])
    ris = calcola(inp_base(progetti=[p], fatti=[Fatto("INTUR", "p3", "AMCN", "2026-10", eur(80_000), "ev1")]))
    dic = next(r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-12")
    assert dic.uscite["progetto"] == eur(52_300)

def test_fatto_senza_pagamento_resta_non_riconciliato():
    p = Progetto("p3", "P3", "INTUR", True, "ipotesi", [Pagamento("anticipo", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN")])
    f = Fatto("INTUR", "p3", "SCONOSCIUTO", "2026-10", eur(5_000), "ev2")
    ris = calcola(inp_base(progetti=[p], fatti=[f]))
    ott = next(r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-10")
    assert ris.non_riconciliati == [f] and ott.uscite["fatto"] == eur(5_000) and ott.uscite["progetto"] == eur(72_300)

def test_erogazioni_scenario_sostituiscono_le_righe_pf_di_finanziamento():
    inp = inp_base(pf_extra=[Riga("INTUR", "ENTRATE_FINANZIAMENTI", "2026-11", eur(550_000), "E", "finanziamento")],
                   finanziamenti=[Finanziamento("mcc", "MCC", "INTUR", {"2026-12": eur(550_000)}, {}, "da verificare")])
    intur = {r.mese: r.entrate["finanziamento"] for r in calcola(inp).righe if r.societa == "INTUR"}
    assert intur["2026-11"] == 0 and intur["2026-12"] == eur(550_000)
```

- [ ] **Step 2: Run** → FAIL (`ScalettaCanone`, `Fatto` non definiti).
- [ ] **Step 3: Implement** — `flussi_canone`: per anno `distribuisci(iva(netto, aliquota), da_mese, rate_n, mesi)` oppure `{m: iva(v, aliquota)}` dal calendario; sostituzione in `calcola` per anno (`mese[:4]`); riconciliazione come da Interfaces (copia dei pagamenti prima di ridurli: `calcola` non muta lo scenario); erogazioni per società.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): canone a scaletta lorda, fatti riconciliati per pagamento (anche parziali), erogazioni dallo scenario"`

---

### Task 3: Dataset previsioni — config, schemi Pydantic, DDL, gate EMPTY_PARSE

**Files:**
- Modify: `core/config.py` (dopo riga 7), `core/schemas.py` (in coda), `ingest/promotion.py:120-156`
- Create: `core/bq/load/create_previsioni_tables.py`
- Test: `tests/test_schemas_previsioni.py`, `tests/test_promotion_count_dataset.py`

**Interfaces:**
- Produces: `DATASET_PREVISIONI = "hotelops_previsioni"`, `def _p(name) -> str`, `P_SCENARI`, `P_SCENARIO_FLUSSI`, `P_PROGETTI_PAGAMENTI` (fully-qualified); modelli:
  - `ScenarioRow(scenario_id: str, nome: str, creato_il: str, autore: str, schema_doc: str, base: str (JSON), parametri: str (JSON), progetti_accesi: list[str], note: Optional[str], raw_object_id: str, hash_riga: str, data_caricamento: str)`
  - `ScenarioFlussoRow(scenario_id, societa_id: SocietaId, mese: str, voce_id: str, importo_cent: int, direzione: Literal["E","U"], origine: str, raw_object_id: str, hash_riga: str, data_caricamento: str)` con validator `origine in ORIGINI` e `mese` regex `^\d{4}-\d{2}$`
  - `ProgettoPagamentoRow(scenario_id, progetto_id, pagamento: str, mese: str, importo_netto_cent: int, aliquota_iva: int, stato: str, fornitore_id: Optional[str], societa_id: SocietaId, raw_object_id: str, hash_riga: str, data_caricamento: str)` con validator `aliquota_iva in (0, 10, 22)`
  - `_count_canonical_rows` accetta `canonical_table` con prefisso `dataset.` (`"hotelops_previsioni.p_scenari"` → `` `hotelops-suite.hotelops_previsioni.p_scenari` ``), altrimenti `PROJECT.DATASET` come oggi.

- [ ] **Step 1: Write the failing tests**

```python
def test_tabelle_previsioni_qualificate():
    assert P_SCENARI == "hotelops-suite.hotelops_previsioni.p_scenari"

def test_scenario_flusso_rifiuta_origine_sconosciuta_e_importo_float():
    with pytest.raises(ValidationError): ScenarioFlussoRow(**riga_ok(origine="boh"))
    with pytest.raises(ValidationError): ScenarioFlussoRow(**riga_ok(importo_cent=10.5))

def test_pagamento_rifiuta_aliquota_fuori_lista():
    with pytest.raises(ValidationError): ProgettoPagamentoRow(**pag_ok(aliquota_iva=4))

def test_count_usa_dataset_del_prefisso(monkeypatch):
    catturato = {}
    monkeypatch.setattr("core.bq.client.get_client", lambda: FakeClient(catturato, n=3))
    assert _count_canonical_rows("hotelops_previsioni.p_scenari", "rid") == 3
    assert "`hotelops-suite.hotelops_previsioni.p_scenari`" in catturato["sql"]
```

- [ ] **Step 2: Run** → FAIL (import).
- [ ] **Step 3: Implement** config, schemi (`int` strict: `importo_cent: StrictInt`), `_count_canonical_rows` (split su `"."` una volta: se due parti → dataset esplicito), e `create_previsioni_tables.py` sul modello di `create_stampa_cassa_table.py`: `CREATE SCHEMA IF NOT EXISTS` con `OPTIONS(location="EU")` + tre `CREATE TABLE IF NOT EXISTS` con le colonne dei modelli (`creato_il TIMESTAMP`, `base JSON`, `parametri JSON`, `progetti_accesi ARRAY<STRING>`, `*_cent INT64`, `data_caricamento TIMESTAMP NOT NULL`), `--dry-run` stampa il DDL.
- [ ] **Step 4: Run** → PASS; `python -m core.bq.load.create_previsioni_tables --dry-run` stampa tre `CREATE TABLE`.
- [ ] **Step 5: Commit** — `git commit -m "feat(previsioni): dataset hotelops_previsioni, schemi p_* in centesimi, gate EMPTY_PARSE su dataset esplicito"`

---

### Task 4: Scenario JSON ↔ righe `p_*` ↔ `Scenario` del motore

**Files:**
- Create: `verticals/condges/cassa_scenario.py`
- Test: `tests/test_cassa_scenario.py`

**Interfaces:**
- Consumes: Task 1/2 dataclass; Task 3 modelli.
- Produces:
  - `SCHEMA = "cdg-cassa-scenario/1"`
  - `Base = dict[str, dict]` — per società `{"file_sorgente", "raw_object_id", "data_caricamento"}`
  - `def scenario_to_json(sc: Scenario, base: Base, nome: str | None = None, salvato_il: datetime | None = None) -> str` — importi in centesimi interi, chiave `importo_cent`
  - `def scenario_from_json(raw: str | bytes) -> tuple[Scenario, Base, dict]` — il terzo è il meta (`nome`, `salvato_il`, `schema`); `ValueError` se `schema` diverso o se un importo non è intero
  - `def scenario_id(raw: str | bytes) -> str` — sha256 del JSON canonico (chiavi ordinate, senza `salvato_il`), primi 16 hex
  - `def righe_p(raw: str | bytes, raw_object_id: str, now: datetime, autore: str) -> tuple[list[dict], list[dict], list[dict]]` — righe per `P_SCENARI`, `P_SCENARIO_FLUSSI` (una per mese × società × voce di ogni leva: canone, finanziamenti, manuali), `P_PROGETTI_PAGAMENTI` (una per progetto × pagamento × mese), già passate da `validate_batch`
  - `def scenario_da_righe(scenari: list[dict], flussi: list[dict], pagamenti: list[dict]) -> list[tuple[Scenario, Base, dict]]`
  - `def base_uguale(a: Base, b: Base) -> bool`
  - `def carica_seme(path: Path) -> tuple[Scenario, Base]` — legge `.hotelops_state/cdg_cassa/base_scenario.json` (stesso schema)

- [ ] **Step 1: Write the failing tests** (scenario sintetico: un progetto con due pagamenti con `fornitore_id`, un finanziamento, canone 2027 800.000 in 4 da marzo)

```python
def test_round_trip_json_scenario():
    sc, base = scenario_sintetico()
    sc2, base2, meta = scenario_from_json(scenario_to_json(sc, base, nome="t"))
    assert sc2 == sc and base2 == base and meta["schema"] == SCHEMA and meta["nome"] == "t"

def test_importo_non_intero_rifiutato():
    raw = scenario_to_json(*scenario_sintetico(), "t").replace('"importo_cent": 10000000', '"importo_cent": 10000000.5', 1)
    with pytest.raises(ValueError, match="centesimi"): scenario_from_json(raw)

def test_scenario_id_ignora_data_salvataggio():
    sc, base = scenario_sintetico()
    assert scenario_id(scenario_to_json(sc, base, "t", datetime(2026, 1, 1))) == scenario_id(scenario_to_json(sc, base, "t", datetime(2026, 2, 2)))

def test_righe_p_e_ritorno_danno_lo_stesso_risultato():
    sc, base = scenario_sintetico(); raw = scenario_to_json(sc, base, "t")
    s, f, p = righe_p(raw, "rid", datetime(2026, 10, 29), "stefano")
    assert len(s) == 1 and len(p) == 2 * 6 and all(r["raw_object_id"] == "rid" for r in f + p)
    (sc2, _, _), = scenario_da_righe(s, f, p)
    assert to_dict(calcola(inp_base(scenario=sc2))) == to_dict(calcola(inp_base(scenario=sc)))

def test_schema_diverso_rifiutato():
    with pytest.raises(ValueError, match="cdg-cassa-scenario/1"): scenario_from_json(json.dumps({"schema": "altro"}))

def test_base_diversa_si_vede():
    assert not base_uguale({"ORTI": {"raw_object_id": "a"}}, {"ORTI": {"raw_object_id": "b"}})
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (serializzazione con `dataclasses.asdict`, mesi come chiavi stringa; `hash_riga` = sha256 dei campi di identità). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): scenario cassa come documento JSON versionato in centesimi, andata e ritorno dalle tabelle p_*"`

---

### Task 5: Parser scenari, source nel registry, CLI `hotelops cdg scenario`

**Files:**
- Create: `ingest/flussi/ingest_scenario_cassa.py`
- Modify: `core/source_registry.yaml` (nuova entry, stessa struttura di `HOTELCUBE_STAMPACASSA_ORTI_APPEND`), `cli.py` (nuovo `cmd_cdg` + `sub.add_parser("cdg")` con sottocomandi `scenario salva FILE [--nome N]`, `scenario lista`, `cassa [--aggiorna] [--push] [--out F]`), `verticals/condges/cli_commands.py`
- Test: `tests/test_ingest_scenario_cassa.py`, test del registry se contano le source

**Interfaces:**
- Consumes: `righe_p`, `scenario_id` (Task 4); `bq_write_validated` (append) su `P_SCENARI`, `P_SCENARIO_FLUSSI`, `P_PROGETTI_PAGAMENTI`.
- Produces: `python -m ingest.flussi.ingest_scenario_cassa --file F --societa GROUP --raw-object-id R [--dry-run]`; `def ingest(path: Path, raw_object_id: str, dry_run: bool, autore: str) -> dict` con `{"scenario_id", "righe": {"p_scenari": n, ...}}`; registry `CDG_SCENARIOCASSA_GROUP_APPEND` (`system: CDG`, `dataset: SCENARIOCASSA`, `societa: GROUP`, `lifecycle: APPEND`, `canonical_table: hotelops_previsioni.p_scenari`, `parser_module: ingest.flussi.ingest_scenario_cassa`, `loop_targets: [cdg_cassa]`, `promotion_policy: AUTO`, `raw_storage.path_template: "cdg/scenari_cassa"`); `hotelops cdg scenario salva FILE` = intake + promote con `--source-name CDG_SCENARIOCASSA_GROUP_APPEND` riusando le funzioni chiamate da `cmd_capture` (`cli.py:770-870`), stampa `scenario_id` e stato lineage; `hotelops cdg scenario lista` legge `P_SCENARI` ordinata per `creato_il`.

- [ ] **Step 1: Write the failing tests**

```python
def test_dry_run_non_scrive(monkeypatch, tmp_path):
    chiamate = []; monkeypatch.setattr(mod, "bq_write_validated", lambda *a, **k: chiamate.append(a))
    out = ingest(file_scenario(tmp_path), "rid", dry_run=True, autore="t")
    assert chiamate == [] and out["righe"]["p_scenari"] == 1

def test_scrive_tre_tabelle_in_append_con_fk(monkeypatch, tmp_path):
    chiamate = []; monkeypatch.setattr(mod, "bq_write_validated", lambda t, rows, mode="append", **k: chiamate.append((t, mode, rows)))
    ingest(file_scenario(tmp_path), "rid", dry_run=False, autore="t")
    assert [c[0] for c in chiamate] == [P_SCENARI, P_SCENARIO_FLUSSI, P_PROGETTI_PAGAMENTI]
    assert all(c[1] == "append" for c in chiamate) and all(r.raw_object_id == "rid" for _, _, rows in chiamate for r in rows)

def test_societa_diversa_da_group_rifiutata(tmp_path):
    rc = subprocess.run([sys.executable, "-m", "ingest.flussi.ingest_scenario_cassa", "--file", str(file_scenario(tmp_path)),
                         "--societa", "ORTI", "--raw-object-id", "r", "--dry-run"], capture_output=True, text=True)
    assert rc.returncode == 2 and "GROUP" in rc.stderr

def test_source_nel_registry():
    d = load_registry()["CDG_SCENARIOCASSA_GROUP_APPEND"]
    assert d.canonical_table == "hotelops_previsioni.p_scenari" and d.loop_targets == ["cdg_cassa"]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** parser (logging come gli altri parser, exit 2 su società ≠ GROUP), entry registry (copiare `freshness`/`acquisition` minimi della source Stampa Cassa, con i valori che i test del registry accettano), CLI. **Step 4: Run** `pytest tests/test_ingest_scenario_cassa.py tests/test_registry_*.py tests/test_source_registry_pilot.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): source CDG_SCENARIOCASSA_GROUP_APPEND, parser scenari → p_*, comandi hotelops cdg scenario"`

---

### Task 6: Parser PF — canone isolato nel dettaglio ORTI, voce `ENTRATE_FINANZIAMENTI` (anticipato: serve al primo render)

**Files:**
- Modify: `ingest/flussi/ingest_piano_finanziario_xlsx.py:107-122` (mappa voci) e `:277-300` (`INTERCOMPANY_DETTAGLIO` → `dict[str, list[tuple[str, str, str, str]]]`), `core/bq/dimensioni/d_voci_piano_finanziario.csv` (riga `ENTRATE_FINANZIAMENTI`, label «Erogazioni finanziamenti (fonti, da verificare)», societa vuota, sezione `ENTRATE`, categoria `Finanziamenti`, fonte `MANUALE`)
- Test: `tests/test_pf_riclassifica_dettaglio.py` (estendere), `tests/test_pf_voce_finanziamenti.py`

**Interfaces:**
- Produces: nel PF ORTI la riga del foglio «Godimento Beni di Terzi» con etichetta contenente `fitto hotel` o `ramo d'azienda` (case-insensitive) passa da `USCITE_GODIMENTO_BENI` a `USCITE_CANONE_PASSIVO` mese per mese (stesso meccanismo del ribaltamento: WARNING e nessuno spostamento se il totale del mese non la contiene); riga principale con etichetta che inizia per «Finanziamento» → `ENTRATE_FINANZIAMENTI`. Nessun'altra voce cambia.

- [ ] **Step 1: Write the failing tests** (workbook sintetico con openpyxl come in `tests/test_pf_riclassifica_dettaglio.py`)

```python
def test_fitto_hotel_passa_a_canone_passivo():
    records = parse(workbook_orti(godimento={"Fitto Hotel ramo d'azienda": {"2026-11": 244_000}, "Fitto CVM": {"2026-10": 50_000}}))
    assert importo(records, "USCITE_CANONE_PASSIVO", 2026, 11) == 244_000
    assert importo(records, "USCITE_GODIMENTO_BENI", 2026, 11) == 0 and importo(records, "USCITE_GODIMENTO_BENI", 2026, 10) == 50_000

def test_totale_che_non_contiene_la_riga_non_sposta_e_avvisa(caplog):  # come il test esistente del ribaltamento

def test_riga_finanziamento_mappata():
    records = parse(workbook_intur(riga_extra=("Finanziamento MPS 550K ARREDI", {"2026-11": 550_000})))
    assert importo(records, "ENTRATE_FINANZIAMENTI", 2026, 11) == 550_000

def test_utenze_intur_continua_a_funzionare():  # regressione del ribaltamento esistente
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (lista di regole per società; `_riclassifica_dettaglio` cicla la lista). **Step 4: Run** `pytest tests/test_pf_riclassifica_dettaglio.py tests/test_parse_pf.py tests/test_pf_voce_finanziamenti.py -v` → PASS; dry-run sui due file Drive dello scratchpad di sessione (`scratchpad/pf_sheet_orti/*.xlsx`): ORTI mostra `USCITE_CANONE_PASSIVO`, INTUR nessun WARNING «UNMAPPED Finanziamento».
- [ ] **Step 5: Commit** — `git commit -m "feat(pf): canone ORTI isolato nel dettaglio (USCITE_CANONE_PASSIVO) e voce ENTRATE_FINANZIAMENTI per le erogazioni"`

---

### Task 7: Fonti BigQuery — ancore con quadratura per conto, baseline con guardia, fatti, scenari, snapshot

**Files:**
- Create: `verticals/condges/cassa_fonti.py`
- Test: `tests/test_cassa_fonti.py`

**Interfaces:**
- Consumes: dataclass Task 1 (`Ancora`, `Conto`, `Riga`, `Flusso`, `Fatto`, `to_cent`); `scenario_da_righe` Task 4; costanti `core.config`.
- Produces (ogni funzione prende `query: Callable[[str], list[dict]]`; `def query_bq(sql: str) -> list[dict]` è l'implementazione vera con `get_client`):
  - `class BaselineNonUnica(RuntimeError)`
  - `def leggi_ancore(query) -> dict[str, Ancora]` — ultima `data_riferimento` D di `F_SALDI_BANCA_CHIUSURA_MENSILE` per società, un `Conto` per `banca_id`. **Quadratura per conto** (regola di Stefano): `attestato=True` solo se esiste la chiusura precedente D0 dello stesso conto e `saldo(D0) + Σ importo_netto(F_BANCHE_MOVIMENTI, data_operazione in (D0, D])` = `saldo(D)` al centesimo, con `max(data_operazione) ≥ D` (i movimenti coprono il periodo); `motivo` ∈ {"quadra con movimenti dal <D0>", "nessuna chiusura precedente", "movimenti fino al <data>", "scostamento <cent>"}. Società attestata ⇔ tutti i conti attestati. La sola presenza di movimenti non attesta nulla.
  - `def leggi_baseline(query) -> tuple[list[Riga], list[Flusso], Base, list[str]]` — righe PF `fonte='PIANO_FINANZIARIO'` con `anno*12+mese > periodo dell'ancora`; `BaselineNonUnica("ORTI: 2 file_sorgente: a.xlsx, b.xlsx")` se più di una per società; le voci `USCITE_CANONE_PASSIVO`, `ENTRATE_AFFITTI_INTUR`, `USCITE_GODIMENTO_BENI` escono dalle righe e diventano `Flusso`: stesso mese e importo su entrambe le gambe → un `Flusso` ORTI→INTUR `stato="pf"`; importo presente su una sola gamba (o differenza tra le gambe) → `Flusso` `stato="una_gamba"` sul lato presente (`da="ORTI", a="INTUR"` se paga ORTI; `da="TERZI", a="INTUR"` se incassa solo INTUR); godimento → `a="TERZI"`. **Mai creare la gamba mancante.** Quarto elemento = `mesi` dell'orizzonte (dal mese dopo l'ancora all'ultimo con righe PF). `ENTRATE_FINANZIAMENTI` resta `Riga` con `origine="finanziamento"`.
  - `def leggi_fatti(query) -> list[Fatto]` — `F_PROGETTO_EVENTI` con `tipo_evento='PAGAMENTO'`, importo = `to_cent(importo_eur)`, mese da `data_evento`, società dal `progetto_id` tramite mappa `PROGETTI_SOCIETA` (costante nel modulo: `{"hpan26-piano3": "INTUR"}`; progetto sconosciuto → `ValueError`)
  - `def leggi_scenari(query) -> list[tuple[Scenario, Base, dict]]` — dalle tre `p_*`
  - `def mesi_ipotetici(mesi: list[str], coda: int = 6) -> tuple[list[str], frozenset[str]]`
  - `def coda_ripetuta(pf: list[Riga], mesi_coda: list[str]) -> list[Riga]` — copia le righe del mese omologo dell'anno prima
  - `def salva_snapshot(dati: dict, home: Path) -> Path` / `def carica_snapshot(home: Path) -> dict` — `home/snapshot_<YYYY-MM-DDTHH-MM>.json` + `home/latest.json`; `home` default `.hotelops_state/cdg_cassa/`

- [ ] **Step 1: Write the failing tests** (finta `query` che risponde per sottostringa della SQL)

```python
def test_baseline_rifiuta_due_file_per_societa():
    with pytest.raises(BaselineNonUnica, match="ORTI.*a.xlsx.*b.xlsx"):
        leggi_baseline(finta({"f_piano_finanziario_input": righe_pf(file={"ORTI": ["a.xlsx", "b.xlsx"]})}))

def test_baseline_esclude_il_mese_chiuso_e_isola_il_canone():
    righe, flussi, base, mesi = leggi_baseline(finta_pf_settembre())  # ott/nov, canone 244k su entrambe le gambe a nov, godimento 50k ott
    assert mesi == ["2026-10", "2026-11"] and all(r.mese != "2026-09" for r in righe)
    assert not any(r.voce_id in ("USCITE_CANONE_PASSIVO", "ENTRATE_AFFITTI_INTUR", "USCITE_GODIMENTO_BENI") for r in righe)
    assert Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", eur(244_000), "pf") in flussi
    assert Flusso("Godimento beni di terzi", "ORTI", "TERZI", "2026-10", eur(50_000), "pf") in flussi
    assert all(isinstance(r.importo, int) for r in righe)

def test_gamba_sola_marcata_e_non_completata():
    _, flussi, _, _ = leggi_baseline(finta_pf(canone_orti={"2026-10": 50_000}, canone_intur={}))
    assert flussi == [Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-10", eur(50_000), "una_gamba")]

def test_gambe_diverse_danno_pf_piu_residuo():
    _, flussi, _, _ = leggi_baseline(finta_pf(canone_orti={"2026-11": 379_000}, canone_intur={"2026-11": 244_000}))
    assert sorted(f.stato for f in flussi) == ["pf", "una_gamba"] and {f.importo for f in flussi} == {eur(244_000), eur(135_000)}

def test_ancora_attestata_solo_se_quadra_per_conto():
    q = finta({"f_saldi_banca_chiusura_mensile": saldi(MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}, INTESA={"2026-09-30": 500.0}),
               "f_banche_movimenti": movimenti(MPS=[("2026-09-10", 100.0)], fino="2026-10-02")})
    a = leggi_ancore(q)["ORTI"]
    assert a.saldo == eur(1500) and a.conti["MPS"].attestato is True and a.conti["INTESA"].attestato is False and a.attestato is False
    assert "nessuna chiusura precedente" in a.conti["INTESA"].motivo

def test_movimenti_che_non_coprono_la_data_non_attestano():
    q = finta({"f_saldi_banca_chiusura_mensile": saldi(MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}),
               "f_banche_movimenti": movimenti(MPS=[("2026-09-10", 100.0)], fino="2026-09-10")})
    assert leggi_ancore(q)["ORTI"].conti["MPS"].attestato is False

def test_scostamento_di_un_centesimo_non_attesta():
    q = finta({"f_saldi_banca_chiusura_mensile": saldi(MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}),
               "f_banche_movimenti": movimenti(MPS=[("2026-09-10", 99.99)], fino="2026-10-02")})
    c = leggi_ancore(q)["ORTI"].conti["MPS"]
    assert c.attestato is False and "scostamento" in c.motivo

def test_fatti_in_centesimi_con_societa_del_progetto():
    f, = leggi_fatti(finta({"f_progetto_eventi": [evento("hpan26-piano3", "2026-10-27", "72300.00", "AMCN")]}))
    assert f == Fatto("INTUR", "hpan26-piano3", "AMCN", "2026-10", eur(72_300), f.evento_id)

def test_coda_ripete_il_mese_omologo():
    assert coda_ripetuta([Riga("ORTI", "USCITE_SALARI", "2026-10", 1000, "U", "pf")], ["2027-10"]) == [Riga("ORTI", "USCITE_SALARI", "2027-10", 1000, "U", "pf")]

def test_snapshot_latest(tmp_path):
    p = salva_snapshot({"a": 1}, tmp_path); assert carica_snapshot(tmp_path) == {"a": 1} and p.name.startswith("snapshot_")
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (SQL con backtick e nomi da `core.config`; nessuna logica di calcolo qui oltre la quadratura). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): fonti cassa — ancore attestate per quadratura conto, baseline PF a versione unica, canone per gamba senza contropartite inventate"`

---

### Task 8: Builder, template HTML, porting JS, CLI `hotelops cdg cassa` — primo render per Stefano

**Files:**
- Create: `verticals/condges/build_cassa_artifact.py`, `verticals/condges/cassa_template.html`
- Modify: `cli.py` (`cmd_cdg` sottocomando `cassa`), `.gitignore` se serve per `docs/reports/artifacts/`
- Test: `tests/test_build_cassa_artifact.py`

**Interfaces:**
- Consumes: Task 1/2 (`calcola`, `to_dict`, `iva`, `distribuisci`), Task 4 (`scenario_to_json`, `base_uguale`, `carica_seme`), Task 7 (fonti, snapshot).
- Produces:
  - `def input_da_snapshot(snapshot: dict, scenario: Scenario) -> Input`
  - `def build_payload(snapshot: dict, scenari: list[tuple[Scenario, Base, dict]], generato_il: datetime | None = None) -> dict` — chiavi: `generato_il`, `mesi`, `mesi_ipotetici`, `ancore` (con `attestato`, `conti` e `motivo`), `base` (versioni), `pf`, `intercompany`, `fatti`, `seme` (scenario iniziale «Base 29/10»), `scenari` (salvati, ciascuno con `compatibile: bool`), `baseline` (= `to_dict(calcola(...))` con scenario vuoto), `limiti` (frasi: saldi dichiarati per conto, mesi ipotetici, IVA per aliquota, rate nuovi finanziamenti assenti, finanziamenti da verificare, fatti non riconciliati). Tutti gli importi `int` centesimi.
  - `def render_html(payload: dict) -> str` — `cassa_template.html` letto accanto al modulo, `__DATA__` sostituito come in canone
  - `KV_KEY = "cassa_html"`, `KV_DATA_KEY = "cassa_data"`; `def push_to_kv(html: str, data_json: str, env: dict) -> None` con `PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CDG_KV_NAMESPACE_ID")`, bulk PUT come canone
  - `def run(out: Path = Path("docs/reports/artifacts/cassa.html"), aggiorna: bool = False, push: bool = False) -> Path`
  - JS nel template, dentro `<script id="motore">`: `const MOTORE = {calcola(payload, scenario), distribuisci, iva, flussiCanone}` con la **stessa aritmetica intera** del Python (`Math.floor((n*(100+a)+50)/100)`, `Math.trunc(tot/n)`); `if (typeof module !== "undefined") module.exports = MOTORE`. Formato euro solo in `fmt(cent)`. UI: due riquadri minimi (società, mese, saldo, tre voci più grandi del mese, badge «dichiarato/attestato» per conto), grafico SVG saldi baseline tratteggiata / scenario piena / coda grigia, tabella per società con dettaglio voce a richiesta, colonna leve (canone: anno, netto, rate, da mese, oppure calendario; progetti: interruttore, società, pagamenti con griglia mese per mese editabile + «spalma da X in N», pagamento di progetto spento grigio con testo «non conta finché il progetto è spento»; finanziamenti con stato «da verificare»), banner limiti, bottone «Esporta scenario» (download JSON `cdg-cassa-scenario/1` con `base` del payload), selettore scenari salvati con etichetta «base diversa» quando `compatibile` è falso; tema chiaro/scuro via `prefers-color-scheme`; larghezza telefono senza scroll orizzontale.

- [ ] **Step 1: Write the failing tests**

```python
def test_payload_porta_limiti_versioni_e_interi():
    p = build_payload(snapshot_sintetico(), [])
    assert "dichiarat" in " ".join(p["limiti"]).lower() and p["base"]["ORTI"]["file_sorgente"] == "ORTI_PF_2026-09.xlsx"
    assert p["baseline"]["minimi"]["ORTI"]["mese"] == "2026-12" and all(isinstance(r["fin"], int) for r in p["baseline"]["righe"])

def test_scenario_salvato_con_base_diversa_marcato():
    sc, base = scenario_sintetico(); base["ORTI"]["raw_object_id"] = "altro"
    assert build_payload(snapshot_sintetico(), [(sc, base, {"nome": "x"})])["scenari"][0]["compatibile"] is False

def test_render_html_incapsula_dati_e_motore():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "__DATA__" not in html and '<script id="motore">' in html and "Esporta scenario" in html

def test_js_uguale_a_python(tmp_path):  # se node manca → skip; estrazione script come tests/test_canone_sim.py:260-280
    p = build_payload(snapshot_sintetico(), []); sc, _ = scenario_sintetico()
    out = esegui_node(tmp_path, render_html(p), p, scenario_to_json(sc, p["base"]))
    assert out == to_dict(calcola(input_da_snapshot(snapshot_sintetico(), sc)))  # uguaglianza intera, nessun round

def test_js_arrotondamenti(tmp_path):
    js = esegui_node_fn(tmp_path, render_html(build_payload(snapshot_sintetico(), [])),
                        "JSON.stringify([M.iva(1001,22), M.iva(5,10), M.distribuisci(10000000,'2026-10',3,['2026-10','2026-11','2026-12']), M.flussiCanone({netto_per_anno:{2027:10000000},rate_n:3,da_mese:'2027-03',calendario:null,aliquota_iva:22}, MESI_9).map(f=>f.importo)])")
    assert json.loads(js) == [1221, 6, {"2026-10": 3333333, "2026-11": 3333333, "2026-12": 3333334}, [4066666, 4066666, 4066668]]

def test_js_progetto_spento_non_muove(tmp_path):  # Review Focus 2: progetto acceso=false → righe identiche alla baseline

def test_push_to_kv_bulk(monkeypatch):  # come tests/test_build_bilancini_artifact.py::test_push_to_kv_bulk_payload, due chiavi

def test_replica_cassa_panorama():
    f = Path(".hotelops_state/cdg_cassa/replica_cassa_panorama.json")
    if not f.exists(): pytest.skip("snapshot locale assente")
    d = json.loads(f.read_text()); ris = to_dict(calcola(input_da_dict(d["input"])))
    assert ris["minimi"]["INTUR"]["saldo"] // 100 == d["atteso"]["INTUR"] and ris["minimi"]["ORTI"]["saldo"] // 100 == d["atteso"]["ORTI"]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** builder, template, porting JS (stessa sequenza di `calcola`, interi ovunque), `cmd_cdg cassa`. Il file `replica_cassa_panorama.json` lo prepara il costruttore dallo scratchpad di sessione (`tong_cassa_app/cassa-app/casi.json` + `voci.json`: atteso INTUR −381.074 giugno, ORTI 675.380 gennaio) e resta fuori da git.
- [ ] **Step 4: Run** `pytest tests/test_build_cassa_artifact.py -v` → PASS (node in `/opt/homebrew/bin`).
- [ ] **Step 5: Dati reali, nell'ordine** (credenziali `stefano@`; se un comando viene negato dal classificatore, riportarlo e fermarsi, non aggirarlo):
  1. `python -m core.bq.load.load_voci_piano_finanziario` (catalogo con `ENTRATE_FINANZIAMENTI`), poi `python -m core.bq.load.create_previsioni_tables`.
  2. Ri-promozione dei PF di settembre con il parser di Task 6: `hotelops intake` dei due file Drive correnti (ORTI versione di Rosa 07:23; INTUR versione corrente) con `--source-name ESOLVER_PF_<SOC>_SNAPSHOT`, poi `hotelops promote`. Ricevuta: una `file_sorgente` per società, `USCITE_CANONE_PASSIVO` presente in ORTI, `ENTRATE_FINANZIAMENTI` 550.000 nov in INTUR, totali ORTI/INTUR stampati e confrontati con il dry-run.
  3. `hotelops cdg cassa --aggiorna` → `docs/reports/artifacts/cassa.html`; `hotelops cdg scenario salva .hotelops_state/cdg_cassa/base_scenario.json --nome "Base 29/10"`; nuovo `--aggiorna`.
  4. Screenshot della pagina (riquadri minimi, grafico, leve) + tabella «baseline per società e mese» + esito dei test di quadratura in chat. **Fermarsi qui finché Stefano non ha visto il render.** Se `BaselineNonUnica` scatta, riportare il messaggio.
- [ ] **Step 6: Commit** — `git commit -m "feat(cdg): builder della pagina Cassa, template con motore JS intero verificato contro il Python, hotelops cdg cassa"`

---

### Task 9: Hub — tile CdG come porta all'edge app, grant a Rosa e al padre

**Files:**
- Modify: `verticals/hub/pages_/cdg.py` (riscritta sul modello di `pages_/mutui.py`, `CDG_URL = "https://cdg.panorama-host.com/"`), `verticals/hub/registry.py:73` (`kind="page"`, `target=cdg.render`, descrizione «controllo di gestione · Cassa (edge app)», `sensitive=True`), `verticals/hub/roles.py:66-75` (aggiungere `"cdg"` a `amministrazione@` e `stedepi@`)
- Test: `tests/test_hub_roles.py` (`"cdg" in _resolve("stedepi@gmail.com")`, idem Rosa; resta `"cdg" not in FINANZA`), `tests/test_hub_cdg_mount.py` (render non chiama `set_page_config`; adattarlo alla pagina-link)

- [ ] **Step 1: Write the failing tests** — [ ] **Step 2: Run** → FAIL — [ ] **Step 3: Implement** — [ ] **Step 4: Run** `pytest tests/test_hub_roles.py tests/test_hub_cdg_mount.py tests/test_hub_registry.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(hub): CdG torna vivo come porta verso cdg.panorama-host.com; grant a Rosa e al padre"`

---

### Task 10: Worker `cdg` in panorama_apps e provisioning per Stefano

**Files:**
- Create in `/Users/stefanodellapietra/dev/Projects/panorama_apps/cdg/`: `wrangler.jsonc` (name `cdg`, custom domain `cdg.panorama-host.com`, binding `CONTENT` con `id: "<KV_ID>"`, vars `ACCESS_TEAM_DOMAIN` uguale a canone, `ACCESS_AUD: "<AUD>"`), `src/index.js`, `src/access.js` (copia di canone), `test/access.test.js`, `test/routes.test.js`, `package.json` (name `cdg`), `README.md`
- Create in hotelops: `scripts/provision_cdg.sh` — **non lo esegue il costruttore**: stampa i comandi `cf` che Stefano lancia con `!`, con il token letto da 1Password in pipe (`op item get aj7ieimu2jdwzfp6qzyw2migxq --vault work --fields password --reveal | …`), mai a video

**Interfaces:**
- Produces: route `/` → KV `cassa_html` (`text/html`), `/cassa/data.json` → KV `cassa_data` (`application/json`), `/competenza` e `/impegno` → 200 pagina statica «in arrivo», altro → 404; 403 senza JWT valido; 503 se KV vuoto. Provisioning: KV namespace `cdg-content`, Worker deploy, custom domain, app Access «CdG» con la policy `29a16983-8bb2-4104-bb0e-653dae8ef650`; dopo la creazione Stefano riporta KV id e AUD, il costruttore li scrive in `wrangler.jsonc` e `CDG_KV_NAMESPACE_ID` nel `.env` di hotelops.

- [ ] **Step 1: Write the failing tests** (vitest, come `canone/test/routes.test.js`) — [ ] **Step 2: Run** `npm install && npm test` → FAIL — [ ] **Step 3: Implement** Worker + README — [ ] **Step 4: Run** `npm test` → PASS
- [ ] **Step 5: Commit** in panorama_apps — `git commit -m "feat(cdg): Worker cdg.panorama-host.com — Cassa da KV, Competenza e Impegno in arrivo"`; in hotelops `git add scripts/provision_cdg.sh && git commit -m "chore(cdg): comandi di provisioning Cloudflare per Stefano (token da 1Password in pipe)"`

---

### Task 11: Procedura, STATUS, README del hub

**Files:**
- Create: `docs/procedures/cdg_cassa.md` — aggiornare la pagina (`hotelops cdg cassa --aggiorna --push`), salvare uno scenario (esporta dal browser → `hotelops cdg scenario salva FILE --nome N`), ri-promuovere un PF (intake → promote, ricevuta attesa), significato di «dichiarato», «attestato (quadratura per conto)», «ipotetico», «da verificare», «base diversa», «non riconciliato»
- Modify: `STATUS.md`, `verticals/hub/README.md`
- [ ] **Step 1: Write** — [ ] **Step 2: Verify** `ruff check . && pytest -q` verdi — [ ] **Step 3: Commit** `git commit -m "docs(cdg): procedura pagina Cassa, STATUS"`

---

## Self-review (29/10, dopo le correzioni di Stefano)

- **Copertura spec + correzioni**: requisiti 1–6 → Task 1/2/4/5/8; baseline unica → Task 7; limiti visibili → Task 7/8; canone isolato → Task 6 (parser) + Task 7 (gambe); erogazioni → Task 6 + Task 2; hub/grant → Task 9; edge app → Task 10; procedura → Task 11. Correzione 1 → `leggi_ancore` quadratura (Task 7, tre test). Correzione 2 → riconciliazione per `fornitore_id` (Task 2, tre test). Correzione 3 → `una_gamba` senza contropartita (Task 1 + Task 7). Correzione 4 → parser PF ora Task 6, ri-promozione nel passo 5 di Task 8. Correzione 5 → centesimi interi in ogni interfaccia, `to_cent`/`iva` testati, parità JS su arrotondamenti (Task 8).
- **Tipi**: tutti gli importi `int`; `Fatto` sostituisce la `Riga` di origine `fatto` nell'Input; `Pagamento.fornitore_id` usato da Task 2, 4, 7; `Conto.motivo` usato da Task 7 e 8.
- **Proporzione**: firme, nomi e asserzioni; corpi solo dove i test non determinano la regola (riconciliazione, quadratura).
