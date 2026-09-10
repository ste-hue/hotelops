# Freshness contract — `hotelops health` come lista della spesa per sorgente

**Data:** 2026-09-09 · **Stato:** design approvato in chat, spec da rivedere · **Origine:** audit
`docs/architecture/2026-09-09-audit-acquisition-layer.md` §6.1 e spec
`2026-06-14-acquisition-layer-design.md` §Freshness contract (mai implementata).

## 1. Problema

`hotelops health` misura la freschezza di ~10 tabelle con query e soglie hardcoded in
`verticals/condges/cli_commands.py::cmd_health` e non legge mai `core/source_registry.yaml` né
`f_raw_objects`. Sa dire "ORTI/MPS ferma da 20 giorni", non sa da quale sistema arriva il dato,
quale report va esportato, con quali filtri, da quale giorno, chi lo fa, quale comando lo consuma.
Vincolo di contesto: nessun accesso programmatico a Power BI, Esolver, banche o Hoxell nel breve;
l'export resta umano. La leva è rendere il click **guidato, corto e impossibile da dimenticare**.

## 2. Obiettivo

Un solo motore che, per ogni sorgente del registry, calcola stato di freschezza e compone la frase
"vai su X → esporta Y (filtri Z) → dal giorno W → owner → poi `hotelops capture`". Lo consumano
`hotelops health` (testo e `--json`) in questa slice; hub e nudge nelle slice successive, sullo
stesso motore.

## 3. Il contratto nel registry

Consolidamento su `core/source_registry.yaml`, nessun YAML nuovo. Due blocchi opzionali per source,
validati da Pydantic dentro `SourceDefinition` (`core/lineage/schemas.py`); le voci senza blocchi
continuano a caricare e compaiono in health come `NO_CONTRACT`.

```yaml
MPS_BANCA_ORTI_APPEND:
  # ...campi esistenti invariati...
  freshness:
    tier: E                        # R automatica | E export umano | M rara/manuale
    cadence: monthly               # daily | weekly | monthly | quarterly | adhoc
    grace_day: 10                  # solo monthly: giorno del mese entro cui il mese precedente è "in scadenza", non rosso
    grain: daily                   # daily | monthly | snapshot  (come leggere coverage)
    basis: canonical               # canonical (default) | raw
    coverage_column: data_operazione   # colonna o espressione SQL, es. LAST_DAY(DATE(anno, mese, 1))
    dims: [banca_id]               # colonne di raggruppamento oltre a societa_id
    dim_filter: {banca_id: [MPS, MPS_KROSS]}   # opzionale: valori di dims che appartengono a questa source
    dormant: null                  # stringa con motivo e data → stato DORMANT, mai rosso
  acquisition:
    mode: SEMI                     # AUTO | SEMI | MANUAL
    owner: Stefano                 # Stefano | Rosa | Antonio | job
    location: "Homebanking MPS"
    report: "Lista movimenti"
    filters: "mese pieno, un file per banca"
    format: xls
    job: null                      # per AUTO: pipeline_name registrato in f_pipeline_runs
```

Regole di validazione (test di configurazione, falliscono al load):
- `promotion_policy` AUTO o MANUAL ⇒ entrambi i blocchi presenti. RAW_ONLY ⇒ opzionali; se presenti, `basis: raw`.
- `mode: AUTO` ⇒ `job` valorizzato e `owner: job`.
- `basis: canonical` ⇒ `coverage_column` valorizzato; `basis: raw` ⇒ `coverage_column` e `dims` assenti.
- `societa_id` è sempre implicito nei dims e filtrato con `sd.societa` (tranne GROUP/VIGNA/STEFANO_PERSONALE, dove non si filtra).

## 4. Semantica dello stato

`covered_through` = ultimo giorno coperto: `MAX(coverage_column)` per combinazione di dims
(`basis: canonical`), oppure `MAX(intake_at)` da `f_raw_objects` per source (`basis: raw`).

| cadence | atteso | ✓ OK | ! DUE | 🔴 STALE |
|---|---|---|---|---|
| daily | oggi − 2 | covered ≥ atteso | — | covered < atteso |
| weekly | oggi − 10 | covered ≥ atteso | — | covered < atteso |
| monthly | ultimo giorno del mese precedente | covered ≥ atteso | giorno del mese ≤ `grace_day` e covered ≥ fine del mese prima ancora | altrimenti |
| quarterly | fine del trimestre precedente | covered ≥ atteso | entro 30 giorni dall'inizio trimestre | altrimenti |
| adhoc | — | mai colorato, mostrato con `·` | — | — |

Decisione 2026-09-09: mensile = mese di calendario. `grace_day` default 10 (banche, Power BI, tutto il
resto). Per le famiglie Esolver `grace_day: 20`: Rosa si mette in pari con la contabilità circa due
settimane dopo la fine del mese, e solo da lì il mese è esportabile.

Stati aggiuntivi:
- `DORMANT` (⏸): `dormant` valorizzato. Mai rosso, riga in coda.
- `JOB_DOWN` (🔴): `mode: AUTO` e nessun run `OK` di `job` in `f_pipeline_runs` nelle ultime 36 ore. Messaggio "job fermo".
- `DATA_STUCK` (🔴): `mode: AUTO`, job verde, ma coverage STALE. Messaggio "job verde, dati fermi: controlla la fonte" (caso Sheet coperti cancellato, 2026-08-15).
- `NO_CONTRACT` (?): source senza blocchi. Elencata in coda, senza colore.

Una source con più valori di dims produce una riga sola con lo stato peggiore; le combinazioni con
covered diverso sono elencate sotto, rientrate.

## 5. La frase azione

Composta da `acquisition` e dallo stato, solo per SEMI e MANUAL non OK:

```
→ <location> › <report> [› <filters>] › dal <covered_through + 1 giorno> [nota] › <owner>
  poi: hotelops capture <file>                       # se esiste un detector per detector_category
  poi: hotelops intake <file> --source-name <X> && hotelops promote --raw-object-id <id>   # altrimenti
```

Nota per lifecycle: APPEND → "sovrapporre qualche giorno è innocuo, dedup su hash"; SNAPSHOT → "fotografia a oggi, sostituisce la precedente".
Per `mode: AUTO` nessuna frase se OK; con JOB_DOWN → "controlla il job <job>"; con DATA_STUCK → "controlla la fonte <location>".
Dopo la frase: `blocca: <loop_targets>` se non vuoti. Il "dal" per `basis: raw` non si stampa (non conosciamo il periodo coperto).

## 6. Il motore — `core/freshness.py`

```python
@dataclass
class SourceFreshness:
    source_name: str; tier: str; mode: str; owner: str
    status: Literal["OK","DUE","STALE","DORMANT","JOB_DOWN","DATA_STUCK","NO_CONTRACT"]
    covered_through: date | None; expected_through: date | None; age_days: int | None
    last_raw_at: datetime | None
    per_dim: list[tuple[dict, date | None]]
    blocks: list[str]
    action: str | None

def compute(registry, query, today: date) -> list[SourceFreshness]
def status_for(contract, covered: date | None, today: date, job_ok: bool | None) -> str   # pura
def action_for(sd, fresh: SourceFreshness, has_detector: bool) -> str | None            # pura
def render_text(items) -> str
def to_json(items) -> list[dict]
```

Query BigQuery, tre in tutto:
1. Per ogni gruppo `(canonical_table, coverage_column, dims)`: `SELECT societa_id, <dims>, MAX(<expr>) FROM <table> GROUP BY ...`. Le source dello stesso gruppo si spartiscono le righe con `societa` e `dim_filter`.
2. `SELECT source_name, MAX(intake_at) FROM f_raw_objects GROUP BY 1`.
3. `SELECT pipeline_name, MAX(ended_at) FROM f_pipeline_runs WHERE status='OK' GROUP BY 1`.

`query` è iniettata (stessa firma di `cli.query`), così `compute` si testa con righe finte. `status_for`
e `action_for` sono pure e coprono tutti i casi della tabella §4.

## 7. `hotelops health`

- Nuovo blocco **SORGENTI** in testa, al posto di BANCHE, MOVIMENTI CONTABILI, IMPEGNO, SCHEDA CONTABILE.
  Ordinamento: STALE/JOB_DOWN/DATA_STUCK, poi DUE, poi OK, poi DORMANT, poi NO_CONTRACT; a parità, più
  loop bloccati prima. RAW_ONLY nascoste salvo `--all`.
- Restano invariati: BUDGET, PIANO FINANZIARIO INPUT, dimensioni, SCHEMA DRIFT, STALE WATERMARKS,
  STALE PIPELINES, DOCS FRESHNESS.
- Flag nuovi: `--json` (solo il blocco SORGENTI, lista di dict = `to_json`), `--source <NOME>` (una sola
  riga, con tutte le dims), `--all`.
- Exit code invariato (0). Nessun nudge in questa slice.

Formato di riga (esempio, larghezze fisse):

```
  SORGENTI — 2026-09-09 (mensile: mese precedente pieno entro il giorno di grazia, 10 o 20)

  🔴 ESOLVER_PARTITE_ORTI_SNAPSHOT     coperto 30/06 · atteso 31/07 · 71gg
     → Esolver › Situazione partite sintetica per fornitori › senza filtri › fotografia a oggi › Stefano
       poi: hotelops capture <file>   blocca: cash_control, monthly_close
  !  MPS_BANCA_ORTI_APPEND             coperto 20/08 · atteso 31/08 · in scadenza (grazia fino al 10)
       MPS 20/08 · MPS_KROSS 20/08
     → Homebanking MPS › Lista movimenti › mese pieno, un file per banca › dal 21/08 (sovrapporre è innocuo) › Stefano
       poi: hotelops capture <file>
  ✓  RT_CORRISPETTIVISPIAGGIA_INTUR    coperto 31/08 · job spiaggia-corrispettivi OK oggi
  ⏸  INTESA_BANCA_ORTI_APPEND          dormiente: conto senza flussi (deciso 2026-06-30)
```

## 8. Strumentare i fetcher automatici

`ingest/drive_fetch.py` e `ingest/pec_fetch.py` oggi registrano solo `ingest_intake`/`promotion`,
e un raw object non atterra se il contenuto è invariato: "il job è verde" non è leggibile. Entrambi
aprono un `PipelineRun` col nome del job (`drive_fetch:<SOURCE>`, `pec_fetch`) attorno all'esecuzione,
come già fa `ingest_coperti`. `acquisition.job` nel registry usa quei nomi; per coperti `ingest_coperti`,
per reviews non c'è source nel registry (resta nel blocco watermark).

## 9. Popolamento del registry

Compilato da me per tutte le 48 source a partire dalla mappa dell'audit; Stefano corregge owner e
nomi report in review. Default per famiglia:

| Famiglia | tier | cadence | grain | basis | mode | owner |
|---|---|---|---|---|---|---|
| Banche ×5 | E | monthly | daily | canonical `data_operazione`, dims `banca_id` | SEMI | Stefano |
| Esolver movimenti ×2 | E | monthly, grace 20 | daily | canonical `data_registrazione` | SEMI | Stefano |
| Esolver scheda ×2 | E | monthly, grace 20 | snapshot | canonical `data_snapshot`, dims `banca_id` | SEMI | Stefano |
| Esolver partite ×2 | E | monthly, grace 20 | snapshot | canonical `data_snapshot` | SEMI | Stefano |
| Esolver bilancino ×2 | E | monthly, grace 20 | monthly | canonical `LAST_DAY(PARSE_DATE('%Y-%m', mese))` (`mese` è STRING 'YYYY-MM') | SEMI | Stefano |
| Esolver fatture ×4 | E | monthly, grace 20 | — | raw | MANUAL | Stefano |
| Esolver budget, PF ×2 | M / E | adhoc / monthly | — | raw | SEMI | Stefano |
| Accodamenti HotelCube | E | monthly | daily | canonical `data_registrazione`, dims `business_unit_id` | SEMI | Stefano |
| Stampa cassa ×2, semantic model, cruscotto, dettaglio prenotazioni, numero camera, consprev pax | M | adhoc | — | raw | MANUAL | Stefano |
| Coperti | R | daily | daily | canonical `data_servizio` | AUTO `ingest_coperti` | job |
| Economato ORTI | E | monthly | — | raw | SEMI | Stefano |
| PBI consumi | E | monthly | monthly | canonical `LAST_DAY(DATE(anno, mese, 1))` | SEMI | Stefano |
| PBI ricavi FB | E | monthly | monthly | canonical `LAST_DAY(DATE(anno, mese, 1))`, dims `business_unit_id` | SEMI | Stefano |
| PBI vendite FB, RistoCube orders, Moolty | E | monthly | daily | canonical `data_servizio`/`data` | MANUAL | Stefano |
| PBI produzione, occupazione | E | monthly | daily | canonical `data`, dims `business_unit_id` | MANUAL | Stefano |
| PBI andamento prenotazioni | E | weekly | snapshot | canonical `snapshot_date`, dims `business_unit_id` | MANUAL | Stefano |
| PBI bookings tipologia, consprev | E | monthly | snapshot | canonical | MANUAL | Stefano |
| PBI menu engineering | E | adhoc | snapshot | canonical `snapshot_date` | MANUAL | Stefano |
| PEC ×3 | R | daily | daily | canonical `data_evento`, dims `entity_id` | AUTO `pec_fetch` | job |
| PEC personale | M | adhoc | — | raw | MANUAL | Stefano |
| RT corrispettivi | R | monthly | daily | canonical `data` | AUTO `drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT` | job |
| Spiagge.it | M | adhoc | — | raw | MANUAL | Stefano |
| SDI XML | E | quarterly | — | raw | MANUAL | Stefano |

Dormienti dichiarate: `INTESA_BANCA_ORTI_APPEND`, `INTESA_BANCA_INTUR_APPEND` (decisione 2026-06-30,
conti senza flussi). Le 2 chiavi morte `ESOLVER_PARTITE_APERTE_*` fuori da `sources:` non si toccano in questa slice.

## 10. Test

- Unit puri su `status_for` (tutte le celle della tabella §4, bordi: giorno `grace_day` e il successivo con 10 e 20, fine mese, dormant,
  job down, data stuck) e su `action_for` (SEMI vs MANUAL, APPEND vs SNAPSHOT, raw senza "dal").
- `compute` con `query` finta: raggruppamento per tabella, spartizione per `dim_filter`, source senza righe.
- Test di configurazione sul registry reale: ogni source promuovibile ha il contratto; AUTO ha `job`;
  `basis` coerente con `coverage_column`.
- Smoke reale: `hotelops health` e `hotelops health --json` su BigQuery prima di dichiarare chiuso,
  con output incollato in STATUS.

## 11. Fuori scope, con motivo

- `period_from/period_to` su `f_raw_objects`: richiede che ogni parser dichiari il periodo; slice successiva.
- Pagina Ingest del hub e `verticals/hub/freshness.py` sullo stesso motore: slice successiva, il motore nasce già con `to_json` per questo.
- Nudge settimanale per owner: dipende da `--json`, slice successiva.
- Spia "lag contabilità" homebanking − mastrino: metrica derivata, non un contratto.
- Dettaglio per-source (conteggio partite, totale euro): scartato il 2026-09-09, resta in `hotelops saldo`/scadenzario.
- Rebase PR #117: task separato.
