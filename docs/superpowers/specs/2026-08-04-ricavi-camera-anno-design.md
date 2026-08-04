# Parser `NUMEROCAMERACLIENTI` → `f_ricavi_camera_anno` — Design

**Data:** 2026-08-04 · **Stato:** decisioni prese con Stefano (sessione 2026-08-03)
**Predecessore:** `2026-08-03-motore-identificazione-content-first-design.md` — quel design fa
riconoscere questi file; questo li scrive in tabella.

## Contesto e obiettivo

Il 3 agosto abbiamo misurato la resa del blocco di 10 camere nuove su giugno+luglio: capacità
+13,2%, ricavo camere/giorno +13,5%, **RevPAR +0,3%**. Tutta la crescita è inventario. Contro le
camere isolabili del quarto piano il blocco nuovo sta al **69%**, e il divario è tutto occupazione
(ADR 297 vs 271; occupazione 54,6% vs 86,7%).

Ma quella misura è costruita su `f_bookings_tipologia`, che è a grana **tipologia venduta**, non
camera fisica. E la tipologia venduta non distingue i due mondi che ci interessano:

> `LSUI` al 36,1% di occupazione — **ma è una camera sola**, 22 notti. È vuota, o è occupata da
> ospiti che avevano prenotato una categoria inferiore e sono stati messi lì in upgrade?

Le due cause hanno rimedi opposti: camera vuota = problema di visibilità e distribuzione; camera
piena pagata come Superior = problema di cattura del prezzo. Oggi non sappiamo quale sia.

I 6 export `NUMEROCAMERACLIENTI` sono in GCS dal 21/07 e portano il rollup **per camera fisica**.
Obiettivo: promuoverli a canonical, così la domanda si può rispondere con un `GROUP BY camera`.

## I file (verificati, non assunti)

6 oggetti, 2025 e 2026 × 3 strutture. Foglio `Export`, 11 colonne, una riga per camera, una riga
`Total`, poi una riga vuota, poi — **non sempre** — la cella `Applied filters`.

```
Camera | Volte | ARB | Infant | ADR | Appartamento | Appartamento Extra | Extra | Totale | Media Camera | Media ARB
R101   |   148 | 315 |      9 | 151.468 | 22417.27 | 0 | 2933.57 | 25350.84 | 171.2895 | 80.4789
```

Fatti che decidono il design:

- **`Volte` = notti**, non arrivi. Verificato: `ADR × Volte = Appartamento` al centesimo
  (151,468 × 148 = 22.417,3 = 22.417,27).
- **`ADR`, `Media Camera`, `Media ARB` sono tutte derivate** dalle altre colonne.
- **I due file CVM non hanno il footer `Applied filters`.** Gli altri quattro sì. Quindi anno e
  struttura devono avere un fallback sul filename, che non è un lusso ma un requisito.
- **Panorama ha una riga con codice camera vuoto**: €62.577 nel 2026 (55.481 camera + 7.095 extra)
  con 0 notti, €1.982 di soli extra nel 2025. È il 2,3% del totale Panorama 2026.
- **Il file 2025 ha 76 camere Panorama, quello 2026 ne ha 86.** La differenza è esattamente
  `H115, H116, H118, H119, H120, H121, H122, H123, H124, H125` — tutte al primo piano, e tutte con
  produzione zero nel 2025. Le 10 camere nuove si identificano **dai dati**, senza liste a mano.
- `room_id` di `d_camere` (115 righe, con `piano` e `tipologia`) combacia esattamente con la
  colonna `Camera`. Il denominatore fisico esiste già.

## Il limite, dichiarato

Il filtro dell'export è `Anno is 2025` / `Anno is 2026`: è un **rollup annuale**, non mensile. Il
file 2026 è YTD alla data di estrazione.

Questo **non** replica la finestra giugno+luglio su cui è costruito l'artefatto pubblico. Risponde
a una domanda diversa e sufficiente: *dentro la stessa finestra 2026, la camera nuova ha meno notti
di una camera fisica comparabile?* Se sì è fisicamente vuota; se no, era riempita in upgrade. Il
mensile richiederebbe un export nuovo con filtro `Mese` ed è fuori scope (decisione Stefano).

## Il modello

Tabella `f_ricavi_camera_anno`, lifecycle **SNAPSHOT**, natural key `(business_unit_id, anno, camera)`.
Ricaricare un anno di una struttura sostituisce le sue righe.

| Colonna | Tipo | Da |
|---|---|---|
| `societa_id` | STRING | costante `ORTI` |
| `business_unit_id` | STRING | footer `CodiceHotel`, fallback filename |
| `anno` | INT64 | footer `Anno is`, fallback prefisso filename |
| `camera` | STRING | colonna `Camera`, oppure `NON_ASSEGNATA` |
| `notti` | INT64 | `Volte` |
| `arb` | INT64 | `ARB` |
| `infant` | INT64 | `Infant` |
| `ricavo_camera` | FLOAT64 | `Appartamento` |
| `ricavo_camera_extra` | FLOAT64 | `Appartamento Extra` |
| `ricavo_extra` | FLOAT64 | `Extra` |
| `ricavo_totale` | FLOAT64 | `Totale` |
| `data_estrazione` | DATE | vedi Decisione 3 |
| `file_sorgente`, `hash_riga`, `raw_object_id`, `data_caricamento` | | convenzione |

`Volte` prende il nome `notti` in tabella: la colonna del PMS è ambigua, la semantica verificata no.

## Decisioni

### 1. Rollup annuale, non mensile

I 6 file sono già in casa e rispondono alla domanda viva. Il mensile costerebbe un export nuovo,
un giro in più e una natural key diversa `(bu, anno, mese, camera)`, per replicare una finestra che
serviva a un artefatto già pubblicato. (Stefano, 08-03)

### 2. Le colonne derivate non si scrivono

`ADR`, `Media Camera`, `Media ARB` sono ricalcolabili esattamente dalle altre. Salvarle significa
tenere in tabella tre numeri che possono divergere dalle loro componenti. Si derivano in vista.

### 3. `data_estrazione` derivata dal raw object

Il file 2026 è YTD, ma nessuna colonna lo dice: chi legge `anno = 2026` fra sei mesi non distingue
un anno chiuso da uno a metà.

La data viene da `f_raw_objects.intake_at` del `--raw-object-id` che `hotelops promote` già passa,
con override manuale `--data-estrazione`. **Non** dal giorno in cui gira il comando: è il difetto
che il 3 agosto ha misdatato 3.690 righe di `f_prenotazioni_otb`, marcandole `2026-08-03` invece di
`2026-08-01`. La data viene dal file registrato, non dall'orologio.

Resta una colonna stampata, non parte della natural key: l'ultimo export di un anno è la verità
migliore per quell'anno, e ricaricarlo deve sostituire.

### 4. La riga senza codice camera si tiene come `NON_ASSEGNATA`

€62.577 nel 2026 Panorama. Scartarla renderebbe il totale della tabella inferiore al vero **senza
che nessuno se ne accorga**; tenerla con un codice esplicito fa quadrare la somma con il `Total`
del file e con `f_produzione_pms`, e chi analizza per camera la filtra via consapevolmente.
Non fa join con `d_camere`, ed è corretto così: non è una camera.

### 5. Identificazione content-first, filename come rete

Struttura e anno si leggono dal footer `Applied filters` (`CodiceHotel is X`, `Anno is YYYY`); se
il footer manca — i due file CVM — si cade sul prefisso del filename (`2025_CVM_...`). È la stessa
forma del commit `9a5e6ec` su `ingest_occupazione_pms`.

Se **entrambi** falliscono, il parser solleva. Un file di cui non si conosce l'anno non si scrive:
finirebbe a sovrascrivere l'anno sbagliato via natural key.

Un export multi-struttura (`CodiceHotel` con più valori nel footer) viene rifiutato, come già fa
`detect_bu_from_footer`: l'aggregato finirebbe etichettato su una BU sola.

### 6. Il `Total` del file è un test, non una riga

La riga `Total` non si scrive. Si usa per verificare il parse: la somma di `ricavo_totale` delle
righe scritte deve coincidere con il `Totale` della riga `Total` entro un centesimo. Se non
coincide, il parser solleva — significa che abbiamo saltato o duplicato righe.

È un controllo gratuito che la fonte ci regala, e l'unico modo per accorgersi di una deriva del
layout senza aspettare che un numero sbagliato arrivi in una pagina.

**Verificato sui 6 file**: la somma coincide col `Total` al centesimo in tutti e sei. E coincide
*perché* la riga senza codice camera è inclusa — sui due file Panorama c'è, e il totale torna
comunque. Il controllo di Decisione 6 e la scelta di Decisione 4 si reggono a vicenda: se
scartassimo `NON_ASSEGNATA`, la quadratura fallirebbe di €62.577 sul 2026.

### 7. Registry: `RAW_ONLY` → `MANUAL`, loop `season_forecast`

L'invariante `loop_targets == [] ⇔ RAW_ONLY` impone di dichiarare a quale loop serve la source.
`season_forecast` è lo stesso di `BOOKINGSTIPOLOGIA` e `ANDAMENTOPRENOTAZIONI`, che sono già la
spina dati della lettura di stagione. Nessun concetto nuovo. `promotion_policy: MANUAL` come i
gemelli: la promote resta un gesto deliberato.

## Fuori scope (dichiarato)

- **Grana mensile** — richiede un export nuovo (Decisione 1).
- **`anno_apertura` in `d_camere`.** «Quali sono le 10 camere nuove» oggi si deduce dal diff fra i
  due anni. Renderlo un attributo dell'asset è la scelta giusta, ma è una modifica alla dimensione,
  non al parser, e `d_camere` non ha un ingest. Domanda aperta, non risolta qui.
- **Viste di analisi.** Questo design scrive la tabella. `v_ricavi_camera` con ADR/RevPAR per
  camera e join a `d_camere` viene dopo, quando i numeri sono dentro e guardabili.
- **Backfill di altri anni.** Ci sono 2025 e 2026. Se serviranno 2023-2024, sono altri export.
- **La risposta alla domanda su `LSUI`.** Questo design la rende *possibile*, non la dà.

## Conseguenze

Dopo questo lavoro, `GROUP BY camera` su `f_ricavi_camera_anno` con join a `d_camere` dice, per
ogni camera fisica dell'albergo, quante notti ha fatto e quanto ha reso — e la domanda «la `LSUI`
è vuota o è data in upgrade?» diventa un confronto fra due numeri invece che una congettura.

Il conto delle source `RAW_ONLY` scende da 7 a 6.

## Riferimenti

- Sessione: `vault/HotelOps/sessions/2026-08-03_bp32_atterraggio_camere_nuove_ingest.md`
- Design gemello: `docs/superpowers/specs/2026-08-03-motore-identificazione-content-first-design.md`
- Precedente content-first: commit `9a5e6ec`
- Workstream: `vault/HotelOps/workstreams/PRENOTAZIONI.md`, `vault/HotelOps/workstreams/REVMAN.md`
- Invariante toccata: `loop_targets == [] ⇔ RAW_ONLY` — rispettata dal flip di Decisione 7
