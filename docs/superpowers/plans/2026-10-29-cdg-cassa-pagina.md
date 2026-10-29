# CdG · pagina Cassa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La prima pagina viva di `cdg.panorama-host.com`: saldi mensili INTUR e ORTI dal PF di settembre promosso, canone e progetti come leve, scenari salvati con lineage in `hotelops_previsioni`.

**Architecture:** Motore Python puro (`cassa_motore`) che calcola saldi, minimi e consolidato da un `Input` esplicito; letture BigQuery isolate in `cassa_fonti`; scenario come documento JSON (`cdg-cassa-scenario/1`) che va e viene dalle tre tabelle `p_*`; builder sul modello di `build_canone_artifact` che incapsula payload + porting JS del motore in un HTML autonomo pubblicato su KV; Worker `cdg` clone di `canone`. Nessun write-path dal browser.

**Tech Stack:** Python ≥3.11, Pydantic, `google-cloud-bigquery` via `core.bq.client.get_client`, `bq_write_validated`, openpyxl (parser PF), HTML/JS senza dipendenze, Cloudflare Worker (`jose`, vitest), `node` per il test di parità JS/Python.

**Spec:** `docs/superpowers/specs/2026-10-29-cdg-cassa-pagina-design.md` (letta insieme a `docs/superpowers/specs/2026-10-28-cdg-controllo-finanziario-integrato-design.md`).

## Global Constraints

- Ogni scrittura BigQuery passa da `core.bq.write.bq_write_validated` (I1); nessun `client.insert_rows` diretto.
- Ingest solo intake → promote; il parser nuovo rispetta il contratto `--file X --societa GROUP --raw-object-id Y` e accetta `--dry-run`.
- Nome source a 4 parti: `CDG_SCENARIOCASSA_GROUP_APPEND` (`GROUP` è l'unico valore ammesso da `SOCIETA_VALUES` per il gruppo).
- Tabelle previsioni: `hotelops-suite.hotelops_previsioni.p_scenari`, `.p_scenario_flussi`, `.p_progetti_pagamenti`; dataset in `EU`.
- Numeri aziendali fuori da git: fixture sintetiche nei test; snapshot in `.hotelops_state/cdg_cassa/`; HTML in `docs/reports/artifacts/` (entrambi gitignored). I test di replica sui dati veri si saltano se il file locale manca.
- TDD: test prima, poi codice; `pytest` + `ruff check .` + `ruff format .` verdi su ogni commit.
- Lavorare su ramo `feat/cdg-cassa-pagina` in un worktree (`superpowers:using-git-worktrees`); stage per nome, mai `git add .`; messaggi di commit con le due righe di attribuzione della sessione.
- Baseline = una sola `file_sorgente` per società in `f_piano_finanziario_input` con `fonte='PIANO_FINANZIARIO'`; righe del mese chiuso (2026-09) escluse.
- Mesi: stringhe `YYYY-MM`; importi in euro con due decimali; entrate e uscite sempre positive, il segno lo dà la direzione.
- Nessun merge su `main` finché Stefano non ha visto il render con dati reali (gate hub).

## Review Focus

1. **PF con due versioni per una società** (ri-promozione a metà): il builder deve fermarsi con il nome dei due file, non sommare → test in Task 6.
2. **Pagamento di un progetto spento** modificato in pagina: non deve muovere i saldi e la riga deve dirlo → test JS in Task 7.
3. **Somma delle rate ≠ totale** per arrotondamento (es. 100.000 in 3): l'ultima rata assorbe i centesimi, mai una rata in più → test in Task 1.
4. **Canone con una gamba sola** nel PF (ottobre 50.000 solo ORTI): il consolidato espone il residuo, non lo forza né lo scarta → test in Task 1.
5. **Scenario JSON con base diversa** da quella del payload corrente (PF ri-promosso dopo il salvataggio): la pagina lo mostra con l'avviso «base diversa», non lo applica in silenzio → test in Task 4 e Task 7.

---

### Task 1: Motore — saldi, minimi, consolidato, distribuzione

**Files:**
- Create: `verticals/condges/cassa_motore.py`
- Test: `tests/test_cassa_motore.py`

**Interfaces:**
- Produces (dataclass `frozen=True` dove non indicato):
  - `ORIGINI = ("pf", "canone", "finanziamento", "progetto", "manuale", "fatto")`
  - `Ancora(societa: str, data: date, saldo: float, attestato: bool, conti: dict[str, float])`
  - `Riga(societa: str, voce_id: str, mese: str, importo: float, direzione: Literal["E", "U"], origine: str)`
  - `Flusso(nome: str, da: str, a: str, mese: str, importo: float, stato: str)` — `da`/`a` ∈ {"ORTI","INTUR","TERZI"}
  - `Pagamento(nome: str, mesi: dict[str, float], aliquota_iva: int = 22, stato: str = "ipotesi")` (mutable)
  - `Progetto(id: str, nome: str, societa: str, acceso: bool, stato: str, pagamenti: list[Pagamento])` (mutable)
  - `Finanziamento(id: str, nome: str, societa: str, erogazioni: dict[str, float], rate: dict[str, float], stato: str)`
  - `Scenario(nome: str, progetti: list[Progetto], finanziamenti: list[Finanziamento], canone: "ScalettaCanone | None" = None, manuali: list[Riga] = [], soglia: float = 0.0)`
  - `Input(mesi: list[str], mesi_ipotetici: frozenset[str], ancore: dict[str, Ancora], pf: list[Riga], intercompany: list[Flusso], fatti: list[Riga], scenario: Scenario)`
  - `RigaMese(mese: str, societa: str, ini: float, entrate: dict[str, float], uscite: dict[str, float], fin: float)` — chiavi di `entrate`/`uscite` = `ORIGINI`
  - `Minimo(mese: str, saldo: float, sotto_soglia: tuple[str, ...], coda_mese: str | None, coda_saldo: float | None)`
  - `Consolidato(mese: str, saldo: float, intercompany_nettato: float, residuo: float)`
  - `Risultato(righe: list[RigaMese], minimi: dict[str, Minimo], consolidato: list[Consolidato])`
  - `def calcola(inp: Input) -> Risultato`
  - `def distribuisci(totale: float, da: str, n: int, mesi: list[str]) -> dict[str, float]`
  - `def to_dict(r: Risultato) -> dict` (JSON-serializzabile, stessi nomi dei campi)

- [ ] **Step 1: Write the failing tests** (fixture sintetica: 3 mesi `["2026-10","2026-11","2026-12"]`, ancore INTUR 100.000 / ORTI 500.000, PF: ORTI E 50.000 ott, U 20.000 ogni mese; INTUR U 10.000 ogni mese)

```python
def test_distribuisci_ultima_rata_assorbe_centesimi():
    r = distribuisci(100_000, "2026-10", 3, MESI)
    assert r == {"2026-10": 33_333.33, "2026-11": 33_333.33, "2026-12": 33_333.34}

def test_distribuisci_oltre_orizzonte_tronca_e_dichiara():
    with pytest.raises(ValueError, match="oltre l'orizzonte"):
        distribuisci(10_000, "2026-12", 2, MESI)

def test_saldo_finale_e_ancora_piu_entrate_meno_uscite():
    ris = calcola(inp_base())
    orti = [r for r in ris.righe if r.societa == "ORTI"]
    assert orti[0].ini == 500_000 and orti[0].fin == 530_000 and orti[-1].fin == 490_000
    assert ris.minimi["ORTI"].mese == "2026-12" and ris.minimi["ORTI"].saldo == 490_000

def test_intercompany_stesso_mese_si_annulla_nel_consolidato():
    inp = inp_base(intercompany=[Flusso("canone", "ORTI", "INTUR", "2026-11", 24_400, "pf")])
    ris = calcola(inp)
    nov = next(c for c in ris.consolidato if c.mese == "2026-11")
    assert nov.intercompany_nettato == 24_400 and nov.residuo == 0
    assert nov.saldo == sum(r.fin for r in ris.righe if r.mese == "2026-11")

def test_gamba_sola_resta_residuo():
    inp = inp_base(intercompany=[Flusso("fitto CVM", "ORTI", "TERZI", "2026-10", 50_000, "pf")])
    ott = next(c for c in calcola(inp).consolidato if c.mese == "2026-10")
    assert ott.intercompany_nettato == 0 and ott.residuo == 0  # verso terzi non è intercompany
    inp2 = inp_base(intercompany=[Flusso("canone", "ORTI", "INTUR", "2026-10", 50_000, "pf")],
                    pf_extra=[])  # una gamba sola: ORTI paga, INTUR non ha la riga → è il flusso stesso a dare entrambe le gambe
    # il residuo nasce solo da flussi dichiarati "una_gamba": vedi Step 3

def test_minimo_coda_separato_dal_minimo_pf():
    inp = inp_base(mesi_ipotetici={"2026-12"})
    m = calcola(inp).minimi["ORTI"]
    assert m.mese == "2026-11" and m.coda_mese == "2026-12"

def test_sotto_soglia_elenca_i_mesi():
    inp = inp_base(soglia=495_000)
    assert calcola(inp).minimi["ORTI"].sotto_soglia == ("2026-12",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cassa_motore.py -v`
Expected: FAIL con `ModuleNotFoundError: verticals.condges.cassa_motore`

- [ ] **Step 3: Implement `cassa_motore.py`** — dataclass come in Interfaces; `calcola` scorre `inp.mesi` in ordine, per società: `ini` = ancora al primo mese, poi `fin` precedente; `entrate[origine]`/`uscite[origine]` sommano `pf` (per `direzione`), `intercompany` (`a==societa` entrata, `da==societa` uscita, origine `canone`), `scenario.finanziamenti` (erogazioni entrata, rate uscita, origine `finanziamento`), progetti accesi (`sum(pagamento.mesi[m]) * (1 + aliquota_iva/100)`, origine `progetto`), `manuali`, `fatti` (origine `fatto`; la sostituzione delle ipotesi è Task 2). `Flusso` con `da`/`a` entrambi in {ORTI, INTUR} = intercompany: nel consolidato `intercompany_nettato` = somma di quei flussi del mese; `residuo` = Σ uscite intercompany ORTI − Σ entrate intercompany INTUR del mese **calcolate sulle righe PF di origine `canone` passate separatamente per gamba** (un `Flusso` con `a="INTUR"` e `stato="una_gamba"` conta solo l'uscita ORTI). `Minimo`: minimo su mesi non ipotetici; `coda_*` sul minimo dei mesi ipotetici, `None` se non ce ne sono. `distribuisci`: `round(totale/n, 2)` per le prime n−1 rate, l'ultima = totale − somma; `ValueError("oltre l'orizzonte: …")` se `da`+n−1 esce da `mesi`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cassa_motore.py -v` → PASS (il test della gamba sola va completato con `stato="una_gamba"` e `assert residuo == 50_000`).

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/cassa_motore.py tests/test_cassa_motore.py
git commit -m "feat(cdg): motore cassa headless — saldi per società, minimi, consolidato con intercompany nettato"
```

---

### Task 2: Motore — scaletta canone, fatti che sostituiscono ipotesi, IVA

**Files:**
- Modify: `verticals/condges/cassa_motore.py`
- Test: `tests/test_cassa_motore.py`

**Interfaces:**
- Produces: `ScalettaCanone(netto_per_anno: dict[int, float], rate_n: int, da_mese: str, calendario: dict[str, float] | None = None, iva: float = 0.22)`; `def flussi_canone(s: ScalettaCanone, mesi: list[str]) -> list[Flusso]` (lordi, `da="ORTI"`, `a="INTUR"`, `nome="Fitto Hotel (canone)"`, `stato="scenario"`); in `calcola`, quando `scenario.canone` è presente, i flussi `intercompany` con `nome` che inizia per `"Fitto Hotel"` **degli anni coperti dalla scaletta** vengono sostituiti da `flussi_canone`; `Riga` di origine `fatto` con `voce_id == progetto.id` nel mese M azzera i pagamenti di quel progetto in M prima di sommare il fatto.

- [ ] **Step 1: Write the failing tests**

```python
def test_flussi_canone_lordi_quattro_rate():
    s = ScalettaCanone({2027: 800_000}, rate_n=4, da_mese="2027-03")
    fl = flussi_canone(s, MESI_9)  # ott 2026 → giu 2027
    assert [f.mese for f in fl] == ["2027-03", "2027-04", "2027-05", "2027-06"]
    assert all(f.importo == 244_000 for f in fl) and all(f.da == "ORTI" and f.a == "INTUR" for f in fl)

def test_calendario_libero_vince_sulle_rate():
    s = ScalettaCanone({2027: 800_000}, 4, "2027-03", calendario={"2027-06": 800_000})
    assert [(f.mese, f.importo) for f in flussi_canone(s, MESI_9)] == [("2027-06", 976_000)]

def test_scaletta_sostituisce_il_canone_pf_solo_negli_anni_coperti():
    inp = inp_base(intercompany=[Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", 244_000, "pf"),
                                 Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2027-06", 244_000, "pf")],
                   canone=ScalettaCanone({2027: 800_000}, 4, "2027-03"))
    ris = calcola(inp)
    intur = {r.mese: r.entrate["canone"] for r in ris.righe if r.societa == "INTUR"}
    assert intur["2026-11"] == 244_000 and intur["2027-03"] == 244_000 and intur["2027-06"] == 244_000

def test_progetto_120k_in_sei_rate_muove_sei_mesi():
    p = Progetto("x", "X", "INTUR", True, "ipotesi", [Pagamento("unica", distribuisci(120_000, "2026-10", 6, MESI_9), aliquota_iva=0)])
    ris = calcola(inp_base(progetti=[p]))
    usc = [r.uscite["progetto"] for r in ris.righe if r.societa == "INTUR"]
    assert usc[:6] == [20_000] * 6 and usc[6:] == [0, 0, 0]

def test_iva_per_aliquota_e_reverse_charge():
    p = Progetto("x", "X", "INTUR", True, "ipotesi",
                 [Pagamento("arredi", {"2026-10": 1_000}, 22), Pagamento("amcn", {"2026-10": 1_000}, 0)])
    ott = next(r for r in calcola(inp_base(progetti=[p])).righe if r.societa == "INTUR" and r.mese == "2026-10")
    assert ott.uscite["progetto"] == 2_220

def test_progetto_spento_non_conta():
    p = Progetto("x", "X", "INTUR", False, "ipotesi", [Pagamento("a", {"2026-10": 1_000}, 0)])
    assert all(r.uscite["progetto"] == 0 for r in calcola(inp_base(progetti=[p])).righe)

def test_fatto_sostituisce_ipotesi_stesso_mese():
    p = Progetto("p3", "P3", "INTUR", True, "ipotesi", [Pagamento("anticipo", {"2026-10": 72_300}, 0)])
    inp = inp_base(progetti=[p], fatti=[Riga("INTUR", "p3", "2026-10", 70_000, "U", "fatto")])
    ott = next(r for r in calcola(inp).righe if r.societa == "INTUR" and r.mese == "2026-10")
    assert ott.uscite["progetto"] == 0 and ott.uscite["fatto"] == 70_000
```

- [ ] **Step 2: Run tests to verify they fail** — `pytest tests/test_cassa_motore.py -v` → FAIL (`ScalettaCanone` non definita).
- [ ] **Step 3: Implement** — `flussi_canone` usa `distribuisci(netto*(1+iva), da_mese, rate_n, mesi)` per anno, o `calendario` × (1+iva) se presente; sostituzione in `calcola` per anno (`mese[:4]`); regola dei fatti per `(progetto.id, mese)`.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): canone a scaletta lorda, IVA per aliquota, i fatti sostituiscono le ipotesi"`

---

### Task 3: Dataset previsioni — config, schemi Pydantic, DDL, gate EMPTY_PARSE

**Files:**
- Modify: `core/config.py` (dopo riga 7), `core/schemas.py` (in coda), `ingest/promotion.py:120-156`
- Create: `core/bq/load/create_previsioni_tables.py`
- Test: `tests/test_schemas_previsioni.py`, `tests/test_promotion_count_dataset.py`

**Interfaces:**
- Produces: `DATASET_PREVISIONI = "hotelops_previsioni"`, `def _p(name) -> str`, `P_SCENARI`, `P_SCENARIO_FLUSSI`, `P_PROGETTI_PAGAMENTI` (fully-qualified); modelli:
  - `ScenarioRow(scenario_id: str, nome: str, creato_il: str, autore: str, schema: str, base: dict, parametri: dict, progetti_accesi: list[str], note: Optional[str], raw_object_id: str, hash_riga: str)`
  - `ScenarioFlussoRow(scenario_id, societa_id: SocietaId, mese: str, voce_id: str, importo: float, direzione: Literal["E","U"], origine: str, raw_object_id: str, hash_riga: str)` con validator `origine in ORIGINI`
  - `ProgettoPagamentoRow(scenario_id, progetto_id, pagamento: str, mese: str, importo_netto: float, aliquota_iva: int, stato: str, fonte: Optional[str], societa_id: SocietaId, raw_object_id: str, hash_riga: str)` con validator `aliquota_iva in (0, 10, 22)` e `mese` regex `^\d{4}-\d{2}$`
  - `_count_canonical_rows` accetta `canonical_table` con prefisso `dataset.` (`"hotelops_previsioni.p_scenari"` → `` `hotelops-suite.hotelops_previsioni.p_scenari` ``), altrimenti `PROJECT.DATASET` come oggi.

- [ ] **Step 1: Write the failing tests**

```python
def test_tabelle_previsioni_qualificate():
    assert P_SCENARI == "hotelops-suite.hotelops_previsioni.p_scenari"

def test_scenario_flusso_rifiuta_origine_sconosciuta():
    with pytest.raises(ValidationError):
        ScenarioFlussoRow(scenario_id="a", societa_id="ORTI", mese="2026-10", voce_id="X", importo=1.0,
                          direzione="U", origine="boh", raw_object_id="r", hash_riga="h")

def test_pagamento_rifiuta_aliquota_fuori_lista():
    with pytest.raises(ValidationError):
        ProgettoPagamentoRow(..., aliquota_iva=4, ...)

def test_count_usa_dataset_del_prefisso(monkeypatch):
    catturato = {}
    class FakeJob:  # .result() → iter([Row(n=3)])
    class FakeClient:
        def query(self, sql, job_config=None): catturato["sql"] = sql; return FakeJob()
    monkeypatch.setattr("core.bq.client.get_client", lambda: FakeClient())
    assert _count_canonical_rows("hotelops_previsioni.p_scenari", "rid") == 3
    assert "`hotelops-suite.hotelops_previsioni.p_scenari`" in catturato["sql"]
```

- [ ] **Step 2: Run** → FAIL (import).
- [ ] **Step 3: Implement** config, schemi, `_count_canonical_rows` (split su `"."` una volta: se due parti → dataset esplicito), e `create_previsioni_tables.py` sul modello di `create_stampa_cassa_table.py`: `CREATE SCHEMA IF NOT EXISTS` con `OPTIONS(location="EU")` + tre `CREATE TABLE IF NOT EXISTS` con le colonne dei modelli (`creato_il TIMESTAMP`, `base JSON`, `parametri JSON`, `progetti_accesi ARRAY<STRING>`, `data_caricamento TIMESTAMP NOT NULL`), `--dry-run` stampa il DDL.
- [ ] **Step 4: Run** → PASS; `python -m core.bq.load.create_previsioni_tables --dry-run` stampa tre `CREATE TABLE`.
- [ ] **Step 5: Commit** — `git commit -m "feat(previsioni): dataset hotelops_previsioni, schemi p_scenari/p_scenario_flussi/p_progetti_pagamenti, gate EMPTY_PARSE su dataset esplicito"`

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
  - `def scenario_to_json(sc: Scenario, base: Base, nome: str | None = None, salvato_il: datetime | None = None) -> str`
  - `def scenario_from_json(raw: str | bytes) -> tuple[Scenario, Base, dict]` — il terzo è il meta (`nome`, `salvato_il`, `schema`); `ValueError` se `schema` diverso
  - `def scenario_id(raw: str | bytes) -> str` — sha256 del JSON canonico (chiavi ordinate, senza `salvato_il`), primi 16 hex
  - `def righe_p(raw: str | bytes, raw_object_id: str, now: datetime, autore: str) -> tuple[list[dict], list[dict], list[dict]]` — righe per `P_SCENARI`, `P_SCENARIO_FLUSSI` (una per mese × società × voce di ogni leva: canone, finanziamenti, manuali), `P_PROGETTI_PAGAMENTI` (una per progetto × pagamento × mese), già passate da `validate_batch`
  - `def scenario_da_righe(scenari: list[dict], flussi: list[dict], pagamenti: list[dict]) -> list[tuple[Scenario, Base, dict]]`
  - `def base_uguale(a: Base, b: Base) -> bool`
  - `def carica_seme(path: Path) -> tuple[Scenario, Base]` — legge `.hotelops_state/cdg_cassa/base_scenario.json` (stesso schema)

- [ ] **Step 1: Write the failing tests** (scenario sintetico: un progetto con due pagamenti, un finanziamento, canone 2027 800.000 in 4 da marzo)

```python
def test_round_trip_json_scenario():
    sc, base = scenario_sintetico()
    sc2, base2, meta = scenario_from_json(scenario_to_json(sc, base, nome="t"))
    assert sc2 == sc and base2 == base and meta["schema"] == SCHEMA and meta["nome"] == "t"

def test_scenario_id_ignora_data_salvataggio():
    sc, base = scenario_sintetico()
    a = scenario_to_json(sc, base, "t", datetime(2026, 1, 1)); b = scenario_to_json(sc, base, "t", datetime(2026, 2, 2))
    assert scenario_id(a) == scenario_id(b)

def test_righe_p_e_ritorno_danno_lo_stesso_risultato():
    sc, base = scenario_sintetico(); raw = scenario_to_json(sc, base, "t")
    s, f, p = righe_p(raw, "rid", datetime(2026, 10, 29), "stefano")
    assert len(s) == 1 and len(p) == 2 * 6 and all(r["raw_object_id"] == "rid" for r in f + p)
    (sc2, base2, _), = scenario_da_righe(s, f, p)
    assert to_dict(calcola(inp_base(scenario=sc2))) == to_dict(calcola(inp_base(scenario=sc)))

def test_schema_diverso_rifiutato():
    with pytest.raises(ValueError, match="cdg-cassa-scenario/1"):
        scenario_from_json(json.dumps({"schema": "altro"}))

def test_base_diversa_si_vede():
    assert not base_uguale({"ORTI": {"raw_object_id": "a"}}, {"ORTI": {"raw_object_id": "b"}})
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (serializzazione con `dataclasses.asdict`, mesi come chiavi stringa; `hash_riga` = sha256 dei campi di identità). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): scenario cassa come documento JSON versionato, andata e ritorno dalle tabelle p_*"`

---

### Task 5: Parser scenari, source nel registry, CLI `hotelops cdg scenario`

**Files:**
- Create: `ingest/flussi/ingest_scenario_cassa.py`
- Modify: `core/source_registry.yaml` (nuova entry sotto le source CDG/HOTELCUBE, stessa struttura di `HOTELCUBE_STAMPACASSA_ORTI_APPEND`), `cli.py` (nuovo `cmd_cdg` + `sub.add_parser("cdg")` con sottocomandi `scenario salva FILE [--nome N]`, `scenario lista`, `cassa [--aggiorna] [--push] [--out F]`), `verticals/condges/cli_commands.py`
- Test: `tests/test_ingest_scenario_cassa.py`, aggiornare i test del registry se contano le source (`tests/test_registry_*.py`)

**Interfaces:**
- Consumes: `righe_p`, `scenario_id` (Task 4); `bq_write_validated` (append) su `P_SCENARI`, `P_SCENARIO_FLUSSI`, `P_PROGETTI_PAGAMENTI`.
- Produces: `python -m ingest.flussi.ingest_scenario_cassa --file F --societa GROUP --raw-object-id R [--dry-run]`; `def ingest(path: Path, raw_object_id: str, dry_run: bool, autore: str) -> dict` con `{"scenario_id", "righe": {"p_scenari": n, ...}}`; registry `CDG_SCENARIOCASSA_GROUP_APPEND` (`system: CDG`, `dataset: SCENARIOCASSA`, `societa: GROUP`, `lifecycle: APPEND`, `canonical_table: hotelops_previsioni.p_scenari`, `parser_module: ingest.flussi.ingest_scenario_cassa`, `loop_targets: [cdg_cassa]`, `promotion_policy: AUTO`, `raw_storage.path_template: "cdg/scenari_cassa"`); `hotelops cdg scenario salva FILE` = intake + promote con `--source-name CDG_SCENARIOCASSA_GROUP_APPEND` riusando le funzioni chiamate da `cmd_capture` (`cli.py:770-870`), stampa `scenario_id` e stato lineage; `hotelops cdg scenario lista` legge `P_SCENARI` ordinata per `creato_il`.

- [ ] **Step 1: Write the failing tests** (parser con `bq_write_validated` monkeypatchato che cattura `table, rows, mode`)

```python
def test_dry_run_non_scrive(monkeypatch, tmp_path):
    chiamate = []; monkeypatch.setattr(mod, "bq_write_validated", lambda *a, **k: chiamate.append(a))
    out = ingest(file_scenario(tmp_path), "rid", dry_run=True, autore="t")
    assert chiamate == [] and out["righe"]["p_scenari"] == 1

def test_scrive_tre_tabelle_in_append_con_fk(monkeypatch, tmp_path):
    chiamate = []; monkeypatch.setattr(mod, "bq_write_validated", lambda t, rows, mode="append", **k: chiamate.append((t, mode, rows)))
    ingest(file_scenario(tmp_path), "rid", dry_run=False, autore="t")
    assert [c[0] for c in chiamate] == [P_SCENARI, P_SCENARIO_FLUSSI, P_PROGETTI_PAGAMENTI]
    assert all(c[1] == "append" for c in chiamate) and all(r["raw_object_id"] == "rid" for _, _, rows in chiamate for r in rows)

def test_societa_diversa_da_group_rifiutata(tmp_path):
    rc = subprocess.run([sys.executable, "-m", "ingest.flussi.ingest_scenario_cassa", "--file", str(file_scenario(tmp_path)),
                         "--societa", "ORTI", "--raw-object-id", "r", "--dry-run"], capture_output=True, text=True)
    assert rc.returncode == 2 and "GROUP" in rc.stderr

def test_source_nel_registry():
    d = load_registry()["CDG_SCENARIOCASSA_GROUP_APPEND"]
    assert d.canonical_table == "hotelops_previsioni.p_scenari" and d.loop_targets == ["cdg_cassa"]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** parser (logging come gli altri parser, exit 2 su società ≠ GROUP), entry registry (copiare `freshness`/`acquisition` minimi della source Stampa Cassa, `cadence: adhoc` se ammesso dai test del registry, altrimenti il valore che i test accettano), CLI. **Step 4: Run** `pytest tests/test_ingest_scenario_cassa.py tests/test_registry_*.py tests/test_source_registry_pilot.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): source CDG_SCENARIOCASSA_GROUP_APPEND, parser scenari → p_*, comandi hotelops cdg scenario"`

---

### Task 6: Fonti BigQuery — ancore, baseline con guardia, fatti, scenari, snapshot

**Files:**
- Create: `verticals/condges/cassa_fonti.py`
- Test: `tests/test_cassa_fonti.py`

**Interfaces:**
- Consumes: dataclass Task 1; `scenario_da_righe` Task 4; costanti `core.config`.
- Produces (ogni funzione prende `query: Callable[[str], list[dict]]` così i test passano una finta; `def query_bq(sql: str) -> list[dict]` è l'implementazione vera con `get_client`):
  - `class BaselineNonUnica(RuntimeError)`
  - `def leggi_ancore(query) -> dict[str, Ancora]` — ultima `data_riferimento` di `F_SALDI_BANCA_CHIUSURA_MENSILE` per società; `attestato` = esiste in `F_BANCHE_MOVIMENTI` una riga di quel conto (`societa_id`, `banca_id`) con `data_operazione >= data_riferimento`
  - `def leggi_baseline(query) -> tuple[list[Riga], list[Flusso], Base, list[str]]` — righe PF `fonte='PIANO_FINANZIARIO'` con `anno*12+mese > periodo dell'ancora`; `BaselineNonUnica("ORTI: 2 file_sorgente: a.xlsx, b.xlsx")` se più di una per società; le voci della coppia canone (`USCITE_CANONE_PASSIVO` ↔ `ENTRATE_AFFITTI_INTUR`) e `USCITE_GODIMENTO_BENI` escono dalle righe e diventano `Flusso` (stesso mese e importo su entrambe le gambe → un `Flusso` ORTI→INTUR `stato="pf"`; gamba sola → `stato="una_gamba"` con `da`/`a` della gamba presente; godimento residuo → `a="TERZI"`); il quarto elemento è la lista `mesi` dell'orizzonte (dal mese dopo l'ancora all'ultimo mese con righe PF)
  - `def leggi_fatti(query) -> list[Riga]` — `F_PROGETTO_EVENTI` con `tipo_evento='PAGAMENTO'`, `voce_id = progetto_id`, mese da `data_evento`
  - `def leggi_scenari(query) -> list[tuple[Scenario, Base, dict]]` — dalle tre `p_*`
  - `def mesi_ipotetici(mesi: list[str], coda: int = 6) -> tuple[list[str], frozenset[str]]` — allunga di `coda` mesi
  - `def coda_ripetuta(pf: list[Riga], mesi_coda: list[str]) -> list[Riga]` — copia le righe del mese omologo dell'anno prima con `origine="pf"`
  - `def salva_snapshot(dati: dict, home: Path) -> Path` / `def carica_snapshot(home: Path) -> dict` — `home/snapshot_<YYYY-MM-DDTHH-MM>.json` + `home/latest.json`; `home` default `.hotelops_state/cdg_cassa/`

- [ ] **Step 1: Write the failing tests** (finta `query` che risponde per sottostringa della SQL)

```python
def test_baseline_rifiuta_due_file_per_societa():
    q = finta({"f_piano_finanziario_input": righe_pf(file={"ORTI": ["a.xlsx", "b.xlsx"]})})
    with pytest.raises(BaselineNonUnica, match="ORTI.*a.xlsx.*b.xlsx"):
        leggi_baseline(q)

def test_baseline_esclude_il_mese_chiuso_e_isola_il_canone():
    righe, flussi, base, mesi = leggi_baseline(finta_pf_settembre())  # sintetico: ott/nov, canone 244 su entrambe le gambe a nov, godimento 50 ott
    assert mesi == ["2026-10", "2026-11"] and all(r.mese != "2026-09" for r in righe)
    assert not any(r.voce_id in ("USCITE_CANONE_PASSIVO", "ENTRATE_AFFITTI_INTUR", "USCITE_GODIMENTO_BENI") for r in righe)
    assert Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", 244_000, "pf") in flussi
    assert Flusso("Godimento beni di terzi", "ORTI", "TERZI", "2026-10", 50_000, "pf") in flussi

def test_gamba_sola_marcata():
    _, flussi, _, _ = leggi_baseline(finta_pf(canone_orti={"2026-10": 50_000}, canone_intur={}))
    assert flussi[0].stato == "una_gamba" and flussi[0].da == "ORTI"

def test_ancora_attestata_solo_con_movimenti_che_coprono_la_data():
    a = leggi_ancore(finta({"f_saldi_banca_chiusura_mensile": saldi(), "f_banche_movimenti": movimenti(fino="2026-09-08")}))
    assert a["ORTI"].attestato is False and a["ORTI"].saldo == 1_500.0 and a["ORTI"].conti == {"MPS": 1_000.0, "INTESA": 500.0}

def test_coda_ripete_il_mese_omologo():
    coda = coda_ripetuta([Riga("ORTI", "USCITE_SALARI", "2026-10", 10.0, "U", "pf")], ["2027-10"])
    assert coda == [Riga("ORTI", "USCITE_SALARI", "2027-10", 10.0, "U", "pf")]

def test_snapshot_latest(tmp_path):
    p = salva_snapshot({"a": 1}, tmp_path); assert carica_snapshot(tmp_path) == {"a": 1} and p.name.startswith("snapshot_")
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (SQL con backtick e nomi da `core.config`; nessuna logica di calcolo qui). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cdg): fonti cassa — ancore con attestazione, baseline PF a versione unica, canone isolato per gamba, snapshot"`

---

### Task 7: Builder, template HTML, porting JS, CLI `hotelops cdg cassa` — primo render per Stefano

**Files:**
- Create: `verticals/condges/build_cassa_artifact.py`, `verticals/condges/cassa_template.html`
- Modify: `cli.py` (`cmd_cdg` sottocomando `cassa`), `.gitignore` se serve per `docs/reports/artifacts/`
- Test: `tests/test_build_cassa_artifact.py`

**Interfaces:**
- Consumes: Task 1/2 (`calcola`, `to_dict`), Task 4 (`scenario_to_json`, `base_uguale`), Task 6 (fonti, snapshot).
- Produces:
  - `def build_payload(snapshot: dict, scenari: list[tuple[Scenario, Base, dict]], generato_il: datetime | None = None) -> dict` — chiavi: `generato_il`, `mesi`, `mesi_ipotetici`, `ancore` (con `attestato`, `conti`), `base` (versioni), `pf` (righe), `intercompany`, `fatti`, `seme` (scenario iniziale «Base 29/10» da `carica_seme`), `scenari` (salvati, ciascuno con `base_uguale` → `compatibile: bool`), `baseline` (= `to_dict(calcola(...))` con scenario vuoto), `limiti` (lista di frasi: saldi dichiarati, mesi ipotetici, IVA per aliquota, rate nuovi finanziamenti assenti, finanziamenti da verificare)
  - `def render_html(payload: dict) -> str` — `cassa_template.html` letto accanto al modulo, `__DATA__` sostituito come in canone
  - `KV_KEY = "cassa_html"`, `KV_DATA_KEY = "cassa_data"`; `def push_to_kv(html: str, data_json: str, env: dict) -> None` con `CDG_KV_NAMESPACE_ID` da env (`PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CDG_KV_NAMESPACE_ID")`), bulk PUT come canone
  - `def run(out: Path = Path("docs/reports/artifacts/cassa.html"), aggiorna: bool = False, push: bool = False) -> Path`
  - JS nel template: `const MOTORE = {calcola(payload, scenario) → {righe, minimi, consolidato}, distribuisci, flussiCanone}` con la **stessa aritmetica** del Python; `window.MOTORE` esportato anche in node (`if (typeof module !== "undefined") module.exports = MOTORE`) dentro `<script id="motore">`; UI: due riquadri minimi (società, mese, saldo, tre voci più grandi del mese), grafico SVG saldi baseline tratteggiata / scenario piena / coda grigia, tabella per società con dettaglio voce a richiesta, colonna leve (canone: anno, netto, rate, da mese, oppure calendario; progetti: interruttore, società, pagamenti con griglia mese per mese editabile + «spalma da X in N», pagamento di progetto spento grigio con testo «non conta finché il progetto è spento»; finanziamenti con stato «da verificare»), banner limiti, bottone «Esporta scenario» (download JSON `cdg-cassa-scenario/1` con `base` del payload), selettore scenari salvati con etichetta «base diversa» quando `compatibile` è falso; tema chiaro/scuro via `prefers-color-scheme`; larghezza telefono senza scroll orizzontale.

- [ ] **Step 1: Write the failing tests**

```python
def test_payload_porta_limiti_e_versioni():
    p = build_payload(snapshot_sintetico(), [])
    assert "dichiarat" in " ".join(p["limiti"]).lower() and p["base"]["ORTI"]["file_sorgente"] == "ORTI_PF_2026-09.xlsx"
    assert p["baseline"]["minimi"]["ORTI"]["mese"] == "2026-12"

def test_scenario_salvato_con_base_diversa_marcato():
    sc, base = scenario_sintetico(); base["ORTI"]["raw_object_id"] = "altro"
    p = build_payload(snapshot_sintetico(), [(sc, base, {"nome": "x"})])
    assert p["scenari"][0]["compatibile"] is False

def test_render_html_incapsula_dati_e_motore():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "__DATA__" not in html and '<script id="motore">' in html and "Esporta scenario" in html

def test_js_uguale_a_python(tmp_path):
    if shutil.which("node") is None: pytest.skip("node non installato")
    p = build_payload(snapshot_sintetico(), []); sc, _ = scenario_sintetico()
    motore_js = estrai_script(render_html(p), "motore")  # regex come tests/test_canone_sim.py:260-280
    (tmp_path / "m.js").write_text(motore_js)
    (tmp_path / "run.js").write_text('const M=require("./m.js");const p=%s;const s=%s;console.log(JSON.stringify(M.calcola(p,s)));'
                                     % (json.dumps(p), json.dumps(json.loads(scenario_to_json(sc, p["base"])))))
    out = json.loads(subprocess.run(["node", "run.js"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout)
    atteso = to_dict(calcola(input_da_payload(p, sc)))
    assert out["minimi"] == atteso["minimi"] and [round(r["fin"], 2) for r in out["righe"]] == [round(r["fin"], 2) for r in atteso["righe"]]

def test_js_progetto_spento_non_muove(tmp_path):  # Review Focus 2: come sopra con progetto acceso=false → righe identiche alla baseline

def test_push_to_kv_bulk(monkeypatch):  # come tests/test_build_bilancini_artifact.py::test_push_to_kv_bulk_payload, due chiavi

def test_replica_cassa_panorama():
    f = Path(".hotelops_state/cdg_cassa/replica_cassa_panorama.json")
    if not f.exists(): pytest.skip("snapshot locale assente")
    d = json.loads(f.read_text()); ris = to_dict(calcola(input_da_dict(d["input"])))
    assert round(ris["minimi"]["INTUR"]["saldo"]) == d["atteso"]["INTUR"] and round(ris["minimi"]["ORTI"]["saldo"]) == d["atteso"]["ORTI"]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** builder, template, porting JS (dieci righe di aritmetica: stessa sequenza di `calcola`; arrotondamento `Math.round(x*100)/100` dove il Python usa `round(x, 2)`), `cmd_cdg cassa`. Il file `replica_cassa_panorama.json` lo prepara il costruttore dallo scratchpad di sessione (`tong_cassa_app/cassa-app/casi.json` + `voci.json`: atteso INTUR −381.074 giugno, ORTI 675.380 gennaio) e resta fuori da git.
- [ ] **Step 4: Run** `pytest tests/test_build_cassa_artifact.py -v` → PASS (il test node gira: `node` è in `/opt/homebrew/bin`).
- [ ] **Step 5: Render reale** — `python -m core.bq.load.create_previsioni_tables` (una volta, Stefano o il costruttore con le credenziali `stefano@`), poi `hotelops cdg cassa --aggiorna` → `docs/reports/artifacts/cassa.html`; aprirlo, screenshot in chat, **fermarsi qui finché Stefano non ha visto il render**. Se `BaselineNonUnica` scatta, riportare il messaggio senza aggirarlo.
- [ ] **Step 6: Commit** — `git commit -m "feat(cdg): builder della pagina Cassa, template con motore JS verificato contro il Python, hotelops cdg cassa"`

---

### Task 8: Parser PF — canone isolato nel dettaglio ORTI, voce `ENTRATE_FINANZIAMENTI`

**Files:**
- Modify: `ingest/flussi/ingest_piano_finanziario_xlsx.py:107-122` (mappa voci) e `:277-300` (`INTERCOMPANY_DETTAGLIO` → `dict[str, list[tuple[str, str, str, str]]]`), `core/bq/dimensioni/d_voci_piano_finanziario.csv` (riga `ENTRATE_FINANZIAMENTI`, label «Erogazioni finanziamenti (fonti, da verificare)», societa `NULL`, sezione `ENTRATE`)
- Test: `tests/test_pf_riclassifica_dettaglio.py` (estendere), `tests/test_parse_pf.py` o nuovo `tests/test_pf_voce_finanziamenti.py`

**Interfaces:**
- Produces: nel PF ORTI la riga del foglio «Godimento Beni di Terzi» con etichetta contenente `fitto hotel` o `ramo d'azienda` passa da `USCITE_GODIMENTO_BENI` a `USCITE_CANONE_PASSIVO` mese per mese (stesso meccanismo del ribaltamento: WARNING e nessuno spostamento se il totale del mese non lo contiene); riga principale «Finanziamento …» (prefisso, case-insensitive) → `ENTRATE_FINANZIAMENTI`. `cassa_fonti.leggi_baseline` (Task 6) tratta `ENTRATE_FINANZIAMENTI` come `Flusso`? **No**: resta `Riga` con `origine="finanziamento"` e il motore la sostituisce con le erogazioni dello scenario quando lo scenario ne dichiara per la stessa società (aggiungere il test in `tests/test_cassa_motore.py`: `test_erogazioni_scenario_sostituiscono_le_righe_pf_di_finanziamento`).

- [ ] **Step 1: Write the failing tests** (workbook sintetico con openpyxl come in `tests/test_pf_riclassifica_dettaglio.py`)

```python
def test_fitto_hotel_passa_a_canone_passivo():
    records = parse(workbook_orti(godimento={"Fitto Hotel ramo d'azienda": {"2026-11": 244_000}, "Fitto CVM": {"2026-10": 50_000}}))
    assert importo(records, "USCITE_CANONE_PASSIVO", 2026, 11) == 244_000
    assert importo(records, "USCITE_GODIMENTO_BENI", 2026, 11) == 0 and importo(records, "USCITE_GODIMENTO_BENI", 2026, 10) == 50_000

def test_riga_finanziamento_mappata():
    records = parse(workbook_intur(riga_extra=("Finanziamento MPS 550K ARREDI", {"2026-11": 550_000})))
    assert importo(records, "ENTRATE_FINANZIAMENTI", 2026, 11) == 550_000

def test_utenze_intur_continua_a_funzionare():  # regressione del ribaltamento esistente
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (lista di regole per società; `_riclassifica_dettaglio` cicla la lista). **Step 4: Run** `pytest tests/test_pf_riclassifica_dettaglio.py tests/test_parse_pf.py tests/test_cassa_motore.py -v` → PASS; `python -m ingest.flussi.ingest_piano_finanziario_xlsx --file <ORTI Drive attuale> --societa ORTI --dry-run` mostra `USCITE_CANONE_PASSIVO` e nessun WARNING «UNMAPPED Finanziamento» sul file INTUR.
- [ ] **Step 5: Commit** — `git commit -m "feat(pf): canone ORTI isolato nel dettaglio (USCITE_CANONE_PASSIVO) e voce ENTRATE_FINANZIAMENTI per le erogazioni"`
- [ ] **Step 6 (fuori dal ramo, con Stefano):** caricare la voce nel catalogo con il loader usato in `e3d2d63`; quando Stefano ha finito di modificare il PF INTUR: `hotelops intake` dei due file da Drive (versione ricalcolata se senza cache) → `hotelops promote`; ricevuta: una `file_sorgente` per società, `USCITE_CANONE_PASSIVO` presente, `ENTRATE_FINANZIAMENTI` 550.000 nov. Procedura in `docs/procedures/cdg_cassa.md` (Task 11).

---

### Task 9: Hub — tile CdG come porta all'edge app, grant a Rosa e al padre

**Files:**
- Modify: `verticals/hub/pages_/cdg.py` (riscritta sul modello di `pages_/mutui.py`, `CDG_URL = "https://cdg.panorama-host.com/"`), `verticals/hub/registry.py:73` (`kind="page"`, `target=cdg.render`, descrizione «controllo di gestione · Cassa (edge app)», `sensitive=True`), `verticals/hub/roles.py:66-75` (aggiungere `"cdg"` a `amministrazione@` e `stedepi@`)
- Test: `tests/test_hub_roles.py` (`"cdg" in _resolve("stedepi@gmail.com")`, idem Rosa; resta `"cdg" not in FINANZA`), `tests/test_hub_cdg_mount.py` (render non chiama `set_page_config`; se il test attuale importa `app_cdg`, adattarlo alla pagina-link)

- [ ] **Step 1: Write the failing tests** — [ ] **Step 2: Run** → FAIL — [ ] **Step 3: Implement** — [ ] **Step 4: Run** `pytest tests/test_hub_roles.py tests/test_hub_cdg_mount.py tests/test_hub_registry.py -v` → PASS (se `streamlit` manca nel venv, `pip install -e ".[dashboard]"` prima).
- [ ] **Step 5: Commit** — `git commit -m "feat(hub): CdG torna vivo come porta verso cdg.panorama-host.com; grant a Rosa e al padre"`

---

### Task 10: Worker `cdg` in panorama_apps e provisioning per Stefano

**Files:**
- Create in `/Users/stefanodellapietra/dev/Projects/panorama_apps/cdg/`: `wrangler.jsonc` (name `cdg`, route `cdg.panorama-host.com` custom_domain, binding `CONTENT` con `id: "<KV_ID>"` da sostituire, vars `ACCESS_TEAM_DOMAIN` uguale a canone, `ACCESS_AUD: "<AUD>"` da sostituire), `src/index.js`, `src/access.js` (copia di canone), `test/access.test.js`, `test/routes.test.js`, `package.json` (name `cdg`), `README.md`
- Create in hotelops: `scripts/provision_cdg.sh` — **non lo esegue il costruttore**: stampa i comandi `cf` che Stefano lancia con `!`, con il token letto da 1Password in pipe (`op item get aj7ieimu2jdwzfp6qzyw2migxq --vault work --fields password --reveal | …`), mai a video

**Interfaces:**
- Produces: route `/` → KV `cassa_html` (`text/html`), `/cassa/data.json` → KV `cassa_data` (`application/json`), `/competenza` e `/impegno` → 200 con pagina statica «in arrivo» (link al mandato), altro → 404; 403 senza JWT valido; 503 se KV vuoto (testo di canone). Provisioning: KV namespace `cdg-content`, Worker deploy, custom domain, app Access «CdG» con la policy `29a16983-8bb2-4104-bb0e-653dae8ef650`; dopo la creazione Stefano riporta KV id e AUD, il costruttore li scrive in `wrangler.jsonc` e `CDG_KV_NAMESPACE_ID` nel `.env` di hotelops.

- [ ] **Step 1: Write the failing tests** (vitest, come `canone/test/routes.test.js`: `/` serve KV, `/cassa/data.json` content-type json, `/competenza` 200 contiene «in arrivo», `/x` 404, POST 405, senza JWT 403)
- [ ] **Step 2: Run** `npm install && npm test` in `panorama_apps/cdg` → FAIL (file assenti)
- [ ] **Step 3: Implement** Worker + README (stesso schema di `canone/README.md`: URL, route, KV, Access, «Aggiornare la pagina: `hotelops cdg cassa --aggiorna --push`», dev)
- [ ] **Step 4: Run** `npm test` → PASS
- [ ] **Step 5: Commit** in panorama_apps (repo proprio) — `git commit -m "feat(cdg): Worker cdg.panorama-host.com — Cassa da KV, Competenza e Impegno in arrivo"`; in hotelops `git add scripts/provision_cdg.sh` → `git commit -m "chore(cdg): comandi di provisioning Cloudflare per Stefano (token da 1Password in pipe)"`

---

### Task 11: Procedura, STATUS, README del hub

**Files:**
- Create: `docs/procedures/cdg_cassa.md` — come si aggiorna la pagina (`hotelops cdg cassa --aggiorna --push`), come si salva uno scenario (esporta dal browser → `hotelops cdg scenario salva FILE --nome N`), come si ri-promuove un PF (intake → promote, ricevuta attesa), cosa significano «dichiarato», «ipotetico», «da verificare», «base diversa»
- Modify: `STATUS.md` (nota in testa: pagina Cassa, cosa è vivo, cosa resta: archivio Fase 1, scostamenti, rate nuovi finanziamenti, attestazione saldi), `verticals/hub/README.md` (riga CdG)
- [ ] **Step 1: Write** — [ ] **Step 2: Verify** `ruff check . && pytest -q` verdi — [ ] **Step 3: Commit** `git commit -m "docs(cdg): procedura pagina Cassa, STATUS"`

---

## Self-review (fatta il 29/10)

- **Copertura spec**: requisiti 1–6 → Task 1/2 (saldi, minimi, canone, progetti, distribuzione), Task 4/5 (salvataggio versionato via lineage), Task 7 (confronto baseline/scenario, UI); baseline unica → Task 6; limiti visibili → Task 6/7; canone isolato per fornitore → Task 6 (gambe) + Task 8 (parser); `ENTRATE_FINANZIAMENTI` → Task 8 + motore; hub e grant → Task 9; edge app e Access → Task 10; procedura → Task 11; test di quadratura 1–8 della spec → Task 1, 6, 7, 2, 2, 4, 2, 6/7.
- **Tipi**: `Riga.direzione` `"E"/"U"` ovunque; `Flusso.stato` ∈ {"pf","una_gamba","scenario","ipotesi"}; `Base` = dict per società con `file_sorgente`, `raw_object_id`, `data_caricamento`; `ORIGINI` include `fatto` e `finanziamento`, usati da Task 2, 6, 8.
- **Review Focus**: 1 → Task 6 `test_baseline_rifiuta_due_file_per_societa`; 2 → Task 7 `test_js_progetto_spento_non_muove`; 3 → Task 1 `test_distribuisci_ultima_rata_assorbe_centesimi`; 4 → Task 1 gamba sola + Task 6 `test_gamba_sola_marcata`; 5 → Task 4 `test_base_diversa_si_vede` + Task 7 `test_scenario_salvato_con_base_diversa_marcato`.
- **Proporzione**: il piano fissa firme, nomi e asserzioni; nessun corpo di funzione oltre le regole che i test non determinano.
