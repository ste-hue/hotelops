# Keplero Conversation Mining → FAQ candidate — design

**Data:** 2026-06-13
**Stato:** design approvato in brainstorming, pronto per writing-plans
**Vertical:** `verticals/keplero/` (nuovo, parallelo a `verticals/reviews/`)

## Contesto

Keplero AI (console.keplero.ai) è il chatbot di risposta automatica agli ospiti di
Gruppo Panorama ("Emma di Panorama Group"). Risponde via **knowledge base**: un set di
coppie `domanda ⟶ risposta` (formato 2 colonne `question <TAB> answer`, ~70 voci attuali)
più link al sito e documenti.

Abbiamo un dump di **2172 conversazioni reali** ospite ↔ bot
(`~/Downloads/conversations 2/conversazioni_keplero/`, file `conversation_<UUID>.tsv`).
Esistono dump più vecchi su Drive (account `panoramagroup.it`, non raggiungibile dall'account
Drive collegato qui) che potranno essere aggiunti come batch successivi.

## Goal

Minare le conversazioni reali per produrre **nuove righe `question ⟶ answer`** (stesso formato
della knowledge base esistente) che colmano i **gap di knowledge**: domande che gli ospiti
fanno davvero ma che la FAQ attuale non copre, o copre male.

**Due deliverable** (entrambi proposti, gate umano, mai push automatico):
1. **FAQ updated** (`keplero_faq_updated.tsv`) — la knowledge base, cosa il bot *sa*. Risposte
   **bozza + evidenza**: mai inventare policy o prezzi.
2. **System prompt v2** (`system_prompt_v2.md`) — come il bot *si comporta*. Redatto dopo aver
   studiato i fallimenti reali, partendo dal system prompt v1 (Appendice A).

### Tassonomia dei gap (cruciale per non confondere fallimenti con comportamento voluto)

Il system prompt v1 (Appendice A) prevede al caso 5 il rimando allo staff "in tutti gli altri
casi". Quindi molti rimandi a `info@panoramagroup.it` sono **by-design**, non gap. L'analisi
classifica ogni deviazione/handoff in:
- **deviazione_corretta** — il prompt vuole così (es. Ferragosto, disponibilità/conferma posti →
  solo staff). Nessuna azione.
- **gap_knowledge** — il bot ha deviato qualcosa che *dovrebbe* stare nella FAQ → candidato FAQ.
- **gap_comportamentale** — il bot ha sbagliato handling (non ha usato il tool prenotazione,
  validazione periodo errata, tono, loop) → raccomandazione per il **system prompt v2**.

## Dati

### Input — dump conversazioni
File TSV, header `sender <TAB> operator <TAB> message <TAB> timestamp`. Una riga per turno.
- `conversation_id` = UUID nel filename (`conversation_<UUID>.tsv`) → **dedup key naturale**.
- 3 tipi di mittente osservati su 2172 file (~21.7k messaggi, media 11 turni, max 164):
  - `assistant | keplero` (11.474) — risposta bot
  - `user | (vuoto)` (10.242) — messaggio ospite
  - `assistant | info@panoramagroup.it` (23) — **takeover umano**: il bot ha mollato, ha
    risposto una persona. Segnale d'oro di "dove Keplero fallisce".

### Baseline — FAQ esistente
~70 voci, formato 2 colonne `question <TAB> answer`. Mischia due stili:
- **keyword-topic**: "Wi-fi", "Colazione", "Coordinate bancarie"
- **domanda naturale**: "Le camere dell'Hotel Panorama hanno un mini frigo?"

I candidati nuovi vengono generati in **forma-domanda naturale** (stile delle voci recenti),
che è ciò che il retrieval del bot matcha meglio. La FAQ esistente serve a (a) matchare il
formato di output e (b) fare il gap-diff. **Va fornita dall'utente** prima della Fase 2
(non presente in repo al momento del design).

## Non-goals (YAGNI)

- Niente push automatico verso la console Keplero (revisione umana obbligatoria).
- Niente fine-tuning / dataset jsonl (deliverable = FAQ in formato CSV/TSV).
- Niente merge con il vertical `reviews` (decisione: verticals separati; helper NLP condiviso
  in `core/` solo se emerge overlap reale, non ora).
- Niente seconda tabella BQ per la classificazione: in BQ landa **solo** `f_keplero_messaggi`.
  Classificazione e candidati FAQ restano artefatti file.
- Niente scraper/connettore live: l'acquisizione è **dump file** (≠ Apify di reviews).

## Architettura

Nuovo vertical `verticals/keplero/`. Due fasi nette.

```
DUMP (.tsv)  --intake-->  GCS raw  -->  f_raw_objects (AUTO, loop keplero_faq, dedup conversation_id)
                                              |
                                       parser TSV
                                              v
                                   f_keplero_messaggi (BQ, APPEND, dedup hash_riga)   [FASE 1: landing]
                                              |
                              ===============================================
                                              |
                          read BQ + FAQ baseline (file)
                                              v
              [1] analisi NLP — classify per conversazione (Claude Sonnet)
                                              v
                       conversazioni_classificate.jsonl  (artefatto)
                                              v
              [2] considerazioni — sintesi ragionata Claude sull'aggregato       [FASE 2: mining]
                                              v
                       considerazioni.md  (temi, gap prioritizzati, raccomandazioni)
                                              v
              [3] candidati — cluster domande-gap, dedup vs baseline, bozza+evidenza
                                              v
                       keplero_faq_candidates.tsv  (proposte concrete)
                                              v
              ─────────── GATE UMANO: revisione/edit dei candidati ───────────
                                              v
              [4] merge — baseline + candidati approvati
                                              v
                       keplero_faq_updated.tsv  (DELIVERABLE: da ricaricare in Keplero)
```

**Il processo (cosa lo distingue da un dump→FAQ diretto):** lo stadio [2] *considerazioni* è il
ragionamento esplicito che collega l'analisi NLP alle decisioni sulla knowledge base — non un
report di conteggi, ma una sintesi che dice *dove* il bot fallisce, *quali* gap contano e *cosa*
aggiungere/modificare. I candidati [3] sono proposte; il deliverable finale [4] è la **FAQ
aggiornata**, prodotta solo **dopo** la revisione umana.

### Fase 1 — Landing (la fonte dati dedupata)

1. **Source lineage** `KEPLERO_CONVERSATIONS_PANORAMA_DUMP` in `core/source_registry.yaml`:
   - `promotion_policy: AUTO`, `loop_targets: [keplero_faq]`. Correzione vs prima bozza
     (`RAW_ONLY`): con `RAW_ONLY` il `policy_gate` blocca la promozione canonica e
     `f_keplero_messaggi` non si popolerebbe via `promote`. `loop_targets` è lista libera
     (non set chiuso); `keplero_faq` è il loop che questa fonte alimenta. L'invariante
     `loop_targets == [] ⇔ RAW_ONLY` resta soddisfatta.
   - naming grammar 4 parti: `KEPLERO_CONVERSATIONS_PANORAMA_DUMP`
     (`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`).

2. **Intake**: `hotelops intake <batch> --source-name KEPLERO_CONVERSATIONS_PANORAMA_DUMP`
   → GCS `gs://hotelops-raw` + `f_raw_objects`. Dedup a livello oggetto per `conversation_id`.
   Più batch = più intake; i duplicati collassano (così il folder Drive vecchio si aggiunge
   come secondo batch quando disponibile in locale).

   Nota: l'intake oggi opera per-file. L'ingest di 2172 file è un batch loop — da gestire nel
   piano (probabile estensione/wrapper, non un nuovo path di scrittura).

3. **Parser** `ingest/flussi/ingest_keplero_conversazioni.py`: TSV → righe messaggio →
   `bq_write_validated(append)` su **`f_keplero_messaggi`**.

   Schema `f_keplero_messaggi` (APPEND, dedup `hash_riga`):
   | campo | tipo | note |
   |---|---|---|
   | `hash_riga` | str | MD5 dedup (conversation_id+seq+message+ts) |
   | `conversation_id` | str | UUID dal filename |
   | `seq` | int | ordine del turno nella conversazione |
   | `sender` | str | `user` / `assistant` |
   | `operator` | str | `keplero` / `info@panoramagroup.it` / vuoto |
   | `message` | str | testo del turno |
   | `ts` | str | ISO timestamp |
   | `data_ingest` | str | ISO timestamp ingest |
   | `raw_object_id` | str | FK lineage (I9) |

   Le 5 dimensioni canoniche **non si applicano** a questa fonte (non è un fatto finanziario);
   verificare in `core/schemas.py` se il contratto le richiede o se la fonte va esentata
   esplicitamente — decisione da fissare nel piano (probabile: schema dedicato senza le 5 dim,
   come `f_reviews` che porta solo `societa_id`/`business_unit_id`).

### Fase 2 — Mining (intelligenza + deliverable)

4. **Carica FAQ baseline** (file fornito dall'utente, 2 colonne) → lista di Q→A esistenti.

5. **Classificazione** `verticals/keplero/classify.py` — Claude **Sonnet** (`claude-sonnet-4-6`),
   pattern mutuato da `verticals/reviews/classify.py` (`anthropic.Anthropic()`,
   `client.messages.create`, JSON strutturato). Una conversazione per chiamata (conversazioni
   lunghe/ambigue → no batch aggressivo come reviews). Output per conversazione:
   - `intent` (categoria della richiesta: preventivo / info_servizi / prenotazione / ecc.)
   - `sentiment`
   - `struttura` (HOTEL / RESIDENCE / CVM / LIDO / n.d.)
   - `domande_estratte[]` — le domande concrete poste dall'ospite, normalizzate
   - `esito` — `risolto_da_bot` / `handoff_umano` / `abbandonata`
   - `flag_gap` — true se il bot non ha soddisfatto la richiesta (ha deviato su
     `info@panoramagroup.it` o c'è stato takeover umano)
   - `tipo_gap` — quando `flag_gap=true`, uno tra: `deviazione_corretta` (il system prompt v1
     vuole il rimando allo staff — vedi Appendice A), `gap_knowledge` (mancava nella FAQ →
     candidato FAQ), `gap_comportamentale` (il bot ha gestito male → fix system prompt). La
     classificazione riceve nel prompt un estratto delle regole del system prompt v1 per
     distinguere i tre casi.

   Artefatto: `keplero_conversazioni_classificate.jsonl` (una riga per conversazione).

6. **Considerazioni** `verticals/keplero/considerazioni.py` — **lo stadio ragionato** che
   collega l'analisi NLP alle decisioni. Sintesi Claude sull'aggregato delle classificazioni
   (+ statistiche calcolate: intent frequenti, % handoff, distribuzione `tipo_gap`). Artefatto
   `considerazioni.md`: temi ricorrenti, *dove* e *perché* il bot fallisce, gap prioritizzati,
   separati per knowledge vs comportamentale, con raccomandazioni concrete (aggiungi FAQ X /
   modifica regola system prompt Y). Non è un report di conteggi: è il ragionamento che motiva
   sia i candidati FAQ sia il system prompt v2.

   Da questo stadio escono **due flussi**: i `gap_knowledge` → candidati FAQ (stadio 7); i
   `gap_comportamentale` → raccomandazioni per il **system prompt v2** (stadio 7-bis).

7-bis. **System prompt v2** `verticals/keplero/system_prompt.py`: dato il prompt v1 (Appendice A)
   + le considerazioni sui `gap_comportamentale`, Claude redige una versione 2 proposta del
   system prompt (`system_prompt_v2.md`) che corregge i comportamenti sbagliati osservati,
   mantenendo intatte le regole corrette (Ferragosto, validazione periodi, rimando staff
   legittimo). **Gate umano**: è una proposta, non si applica da sola.

7. **Candidati FAQ** `verticals/keplero/distill_faq.py`:
   - raccoglie le `domande_estratte` dalle conversazioni con `tipo_gap == gap_knowledge`
   - clusterizza domande semanticamente equivalenti (Claude) → una domanda canonica per cluster,
     con `support_count` (quante conversazioni) e `evidence_conversation_ids`
   - **dedup contro la FAQ baseline**: scarta cluster già coperti da una voce esistente
   - per ogni cluster nuovo, bozza una **risposta candidata** da: risposte dei takeover umani +
     buone risposte bot del cluster. **Mai inventare** policy/prezzi: se l'evidenza non contiene
     la risposta fattuale, il campo answer resta `[DA COMPILARE]` con le evidenze allegate.
   - Output `keplero_faq_candidates.tsv` — colonne: `question · answer · support_count ·
     evidence_conversation_ids`.

   **── GATE UMANO ──**: Stefano/team revisiona ed edita i candidati (correggge risposte,
   completa i `[DA COMPILARE]`, scarta i falsi gap). Produce un file di candidati **approvati**
   (stesso formato, 2 colonne minime `question · answer`).

8. **Merge → FAQ updated** `verticals/keplero/merge_faq.py`: unisce la FAQ baseline con i
   candidati approvati (dedup finale per domanda canonica) → **`keplero_faq_updated.tsv`**
   (2 colonne `question <TAB> answer`), il **deliverable** da ricaricare nella knowledge di
   Keplero. È uno stadio separato, eseguito **dopo** il gate umano (non nello stesso run del
   mining).

## Error handling

- **Intake**: file malformato (header diverso, encoding) → skip + log, non blocca il batch.
- **Parser**: riga senza i 4 campi → skip riga + warn; conversazione vuota → skip file.
- **Classificazione**: risposta Claude non-JSON → retry una volta, poi marca conversazione
  `errore_classificazione` e prosegue (non blocca il batch). Pattern già presente in reviews.
- **Distillazione**: cluster senza risposta fattuale nell'evidenza → answer = `[DA COMPILARE]`,
  non scartato (è comunque un gap utile da segnalare).

## Testing

- `test_ingest_keplero.py` — parser TSV: dedup hash_riga, conteggio turni, riconoscimento
  takeover umano (`operator == info@panoramagroup.it`), file malformato → skip.
- `test_keplero_classify.py` — builder del prompt + parsing della risposta JSON (mock client,
  come `test_reviews_classify.py`).
- `test_keplero_distill.py` — dedup contro FAQ baseline (un cluster già coperto viene scartato),
  answer `[DA COMPILARE]` quando l'evidenza non contiene la risposta, `support_count` corretto.
- `test_keplero_merge.py` — merge baseline + approvati: nessun duplicato per domanda canonica,
  le voci baseline si conservano, le nuove si aggiungono.

## Open items (da risolvere nel piano o con l'utente)

1. **FAQ baseline file**: l'utente deve fornire il CSV/TSV esistente (~70 voci) prima della Fase 2.
2. **5 dimensioni canoniche**: confermare che `f_keplero_messaggi` può avere schema dedicato
   senza le 5 dimensioni (precedente: `f_reviews`).
3. **Intake batch di 2172 file**: confermare il wrapper/loop sull'`intake` per-file esistente.
4. **Clustering**: Claude vs embedding per il raggruppamento domande — decidere nel piano in base
   a costo/qualità sul volume reale.
