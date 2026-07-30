# Modello F&B "a regime" — Excel per Feliciani — design

**Data**: 2026-07-30 · **Stato**: design approvato (decisioni a+b confermate da Stefano)
**Eredita**: `2026-05-21-audit-consumi-fb-direzione-design.md` (matrice 6 layer, 3 outlet) ·
`2026-06-16-fb-dashboard-v2-revenue-manager-design.md` (margine/coperto, consumo ≠ vendita ≠ ricavo)
**Workstream**: FB (`workstreams/FB.md`)

## 1. Problema e obiettivo

Il report giornaliero POS (`verticals/fb/genera_report_feliciani.py`, 2026-07-30) copre solo
pranzo/cena/bar à la carte. Mancano: **breakfast** (il servizio più grande del gruppo: 38.462
coperti HOTEL 2025-04→2026-07), **consumi/costi** (economato), **mensa staff** (9.252 pasti,
costo senza ricavo) e i **costi unitari per piatto** (menu engineering).

Obiettivo: un **Excel-modello unico** con cui Feliciani (consulente F&B) fissa **standard e
target** per outlet; a regime il sistema confronta reale vs target da solo e lui si sfila.
Il modello NON è un report: è la coppia (numeri reali, target editabili) sulla stessa griglia.

## 2. Principio

Tre numeri per outlet governano l'F&B: **ricavo/coperto, costo merce/coperto, margine/coperto**
(il food cost % è derivato, mai metrica di testa — nasconde il soldo). Vincolo strutturale: i
consumi economato sono mensili → **il margine si chiude a mese chiuso**; il giornaliero serve
al controllo operativo (volumi, mix, coperto medio), non al margine.

## 3. Decisioni ratificate (2026-07-30, Stefano)

- **(a) Denominatore**: staff (DIPENDENTI) e COURTESY **esclusi** dal denominatore di
  ricavo/coperto e margine/coperto (mangiano, non pagano). Restano visibili come **riga di
  costo dedicata** (mensa = costo del personale F&B; courtesy = leakage tracciato).
- **(b) Base valore**: margini e food cost su base **netto/imponibile** (`f_vendite_fb`,
  `f_consumi_economato`, `f_ricavi_fb`). Il **lordo POS** (`f_ristocube_orders`) si usa SOLO
  per scontrino medio di cassa e controllo giornaliero. Mai mischiare le basi in un rapporto.

## 4. Fonti (tutte già in BQ salvo menu engineering)

| Dato | Tabella | Grana | Freschezza |
|---|---|---|---|
| Comande POS (coperti à la carte, lordo) | `f_ristocube_orders` | riga item | a export (oggi: 2026-07-30) |
| Vendite per articolo (netto, tipo_piatto) | `f_vendite_fb` | giorno × sala × articolo | a export (2026-07-29) |
| Coperti per pasto/ospite (incl. BRK, staff) | `f_coperti_giornalieri` | giorno × pasto × ospite | giornaliera (Hoxell) |
| Consumi per reparto (netto) | `f_consumi_economato` | mese × reparto × prodotto | mensile a mese chiuso |
| Ricavi PMS classe 02FB (netto, codici BRK) | `f_ricavi_fb` | mese × BU × codice | mensile |
| Costi unitari per piatto | **`f_menu_engineering`** (da creare) | snapshot × sala × piatto | a export |

**Promozione menu engineering**: la source `POWERBI_MENUENGINEERING_ORTI_SNAPSHOT` (oggi
RAW_ONLY, file 2026-07-30 in GCS) acquisisce il suo primo consumer → dichiarare
`loop_targets: [fb_model]`, flip `promotion_policy: AUTO`, parser
`ingest/flussi/ingest_menu_engineering.py`, canonical `f_menu_engineering` con
`snapshot_date` da intake_at (pattern OTB — il contenuto non dichiara il periodo).
Pre-creare la tabella (lezione chicken-egg PEC).

**Ponte consumi→outlet** (riusa la logica `v_fb_kpi`): BRK→Breakfast, CUCINA→Ristorante,
CANTINA→Bar, con le esclusioni articoli UoM-rotti già codificate. Scarichi banqueting/interni
isolati (consumo ≠ vendita ≠ ricavo).

## 5. L'Excel — 7 fogli

1. **Cruscotto** — mese × outlet (Breakfast / Ristorante / Bar / Mensa staff): coperti,
   ricavo/cop, costo/cop, **margine/cop**, food cost %, colonne **Target** (editabili da
   Feliciani, v1 manuali) e scostamento con segno leggibile (✓/✗, mai numero grigio).
   Solo mesi chiusi lato costi; mese corrente marcato "(in corso — senza costi)".
2. **Giornaliero servizio** — l'attuale riepilogo POS (pranzo/cena/bar): coperti, coperto
   medio lordo, articoli/cop, breakdown categorie per coperto, bottiglie vino/10 cop.
3. **Coperti completi** — giorno × pasto (BRK/LUNCH/DINNER) × tipo ospite (HOTEL/RESIDENCE/
   CVM/ESTERNI/DIPENDENTI/COURTESY/PM), con totale "paganti" vs "non paganti" per riga.
4. **Breakfast** — mese: coperti BRK per BU, costo economato BRK, **costo/coperto** (metrica
   di testa — il ricavo è dentro la tariffa camera), ricavo esplicito codici `SCBKF*`/`BRK*`
   da `f_ricavi_fb` come contesto. YoY sulla stagione precedente.
5. **Consumi** — mese × reparto (33 reparti, raggruppati per outlet): €, €/coperto outlet,
   Δ% vs stesso mese anno prima; riga scarichi interni/banqueting isolata.
6. **Menu engineering** — per piatto (ultima foto): qty venduta (da `f_vendite_fb`, periodo
   allineato), prezzo netto, costo unitario, **margine unitario e totale**, quadrante
   Star/Cavallo/Enigma/Cane (soglie = mediane popolarità × margine).
7. **Definizioni** — mezza pagina: base lordo vs netto per foglio, chi sta nel denominatore,
   periodo dati per fonte, cosa NON dice il modello (breakfast senza valore-board, mese
   corrente senza costi).

## 6. Architettura implementazione

- **Viste BQ additive** (nessun nuovo storage oltre `f_menu_engineering`):
  - `v_fb_coperti_giornaliero` — pivot `f_coperti_giornalieri` (foglio 3, denominatori foglio 1).
  - `v_fb_modello_mensile` — mese × outlet: coperti paganti/non, ricavo netto, costo, margine
    (fogli 1, 4, 5). Ponte reparti→outlet qui, UNA volta.
- **Generatore**: estendere `verticals/fb/genera_report_feliciani.py` (stesso CLI, stessi
  helper `_write_sheet`). Dei 4 fogli attuali: Riepilogo+Breakdown → foglio 2, Top Articoli
  → assorbito dal foglio 6 (menu engineering = top articoli + margini), **Trend Settimanale
  resta come 8° foglio** (grana settimanale, guard buchi stagionali già implementato).
  Target v1: colonne vuote formattate.
- **Test**: logica pura per quadranti menu engineering, split paganti/non paganti, gating
  mese chiuso. Pattern esistente `tests/test_fb_report_feliciani.py`.

## 7. Non-obiettivi (v1)

- Persistenza target su BQ (`d_fb_target`): v2, quando Feliciani avrà compilato la prima serie.
- Valore-board del breakfast nella tariffa camera (richiede scelta di pricing interno).
- Ricette/distinta base per piatto (costo unitario = quello dichiarato dal POS).
- Alert automatici (layer 6 della matrice): arrivano col monitoraggio a regime, non nell'Excel.

## 8. Rischi/trappole note

- Dedup float `f_vendite_fb` sui re-export con overlap (visto 2026-07-30: 7.454 righe doppie
  rimosse) — finché non si fixa l'hash, ogni ingest vendite va verificato per doppioni logici.
- `f_ricavi_fb` e `f_consumi_economato` arrivano con lag mensile: il Cruscotto deve gestire
  mesi senza costi senza mostrare margini falsi (gating esplicito).
- Menu engineering: qty del file cumulate su periodo filtro ignoto → le qty per i quadranti
  si prendono da `f_vendite_fb` sul periodo dichiarato, il file dà solo i costi unitari.
