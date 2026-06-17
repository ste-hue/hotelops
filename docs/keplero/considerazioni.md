# Keplero — Analisi preliminare conversazioni (considerazioni)

**Data:** 2026-06-13
**Autore:** analisi esplorativa data-driven (NLP)
**Dataset:** dump `~/Downloads/conversations 2/conversazioni_keplero/` — 2172 file `.tsv`
(1 file = 1 conversazione WhatsApp ospite ↔ bot "Emma" di Keplero).
**Natura:** preliminare. *Osserva → interpreta → propone.* **Non** è una FAQ, **non** è un system
prompt v2, **non** applica nulla a Keplero. Le risposte/regole citate sono osservate, non inventate.

---

## 0. Executive summary

- **65% delle conversazioni finisce con il bot che rimanda allo staff** (`info@panoramagroup.it`).
  È il segnale dominante. Ma è un **mix di tre cose diverse** che vanno separate: rimando
  legittimo (by-design), incapacità operativa del bot, e gap di conoscenza.
- Il canale è **WhatsApp**: il **10%** delle conversazioni contiene **allegati media** che il bot
  **non può vedere** (ricevute di pagamento, CV, email, documenti). È un limite **strutturale**,
  non un buco di FAQ.
- Traffico **multilingue**: ~53% IT, ~31% EN, ~21% con tracce ES. Il bot gestisce le tre lingue
  ma a volte **cambia lingua a metà** conversazione.
- Il **37%** delle conversazioni arriva alla consegna del **link di prenotazione**
  (bookingexpert.it): è il "lieto fine" tipico — ma il bot **non dà prezzi/disponibilità reali**,
  delega al motore di booking.
- Friction ricorrente (**26%**): la **regola età** (12+ = adulto, 4-11 = bambino, 0-3 = neonato)
  genera giri di chiarimenti e confusione.
- Solo **1% (14 conversazioni)** ha un **takeover umano** reale: rari ma preziosi — sono i punti
  dove lo staff ha dato la risposta fattuale che il bot non aveva.

**Tesi (MISURATA e poi CORRETTA — vedi §11):** la prima passata dava "65% rimandi → 62% incapacità".
Una verifica (grazie a un'obiezione di Stefano) ha mostrato che quel 65% era **contaminato**: il
bot mette `info@` come footer standard, e consegnare il link di preventivo È il comportamento
voluto (non un fallimento), ma veniva contato come deviazione. Sul corpus **pulito** il quadro reale è:
**≈36% fallimento vero** (non 65%), di cui **57% incapacità operativa · 41% gap conoscenza · 2%
legittimo**. Capability resta la leva maggiore, ma su una base molto più piccola del previsto;
il knowledge pesa ~15% del totale conversazioni.

---

## 1. Dataset overview

| Metrica | Valore |
|---|---|
| Conversazioni | 2172 |
| Turni totali | 23.904 (media 11, mediana 8, max 164) |
| Messaggi utente | 12.406 |
| Messaggi bot | 11.498 |
| Mittenti | `user` (ospite), `assistant/keplero` (bot), `assistant/info@panoramagroup.it` (umano) |
| Lingua (euristica) | IT ~53% · EN ~31% · tracce ES ~21% (overlap) |
| Canale | WhatsApp (allegati `attachment:https://v2.api.keplero.ai/.../whatsapp/media/...`) |

Distribuzione lunghezza: 1-2 turni 362 · 3-5 turni 318 · 6-10 turni 656 · 11-20 turni 594 ·
21+ turni 242. Le conversazioni **con** rimando sono mediamente più lunghe (12,3 turni) di quelle
**senza** (8,6): il bot rimanda **dopo aver arrancato**, non subito.

---

## 2. Schema entità trovate

Entità ricorrenti estraibili dalle conversazioni (candidate per un futuro entity-extraction):

| Entità | Valori / forma | Note |
|---|---|---|
| `struttura` | Hotel Panorama · Angelina Residence · Casa Vacanze Maiori | + `Panorama Roof Terrace` (ristorante/bar), `Panorama Beach` (lido) |
| `date_soggiorno` | check-in / check-out, range | spesso parziali o ambigue ("dal 3 al 10 o solo weekend") |
| `composizione` | adulti, bambini (4-11), neonati (0-3) | **12+ contato come adulto** → fonte di confusione |
| `n_camere` / `tipo_camera` | doppia, tripla, executive double, family, suite, vista mare, balcone | |
| `trattamento` | colazione / B&B / mezza pensione / cena | |
| `servizi` | parcheggio (cat. A/B/C + tariffe), spiaggia/lido (1 ombrellone+2 lettini, file 1-6), piscina rooftop, wifi, teli mare, deposito cauzionale (€100), navetta/transfer, deposito bagagli | |
| `dati_cliente` | nome, email, telefono | |
| `codice_prenotazione` | es. `2ZTQLP`, `998804759` | per gestione prenotazioni esistenti |
| `pagamento` | bonifico/acconto, contanti al check-in, contabile/ricevuta | il bot **non verifica** pagamenti |
| `lingua` | IT / EN / ES | |
| `allegato` | foto/PDF via WhatsApp | ricevute, CV, email, documenti |
| `evento` | pool party, Ferragosto, beach club | gestiti solo staff |
| `logistica` | Capri, traghetti Travelmar, Salerno, Roma, SITA | richieste "come arrivare" |

---

## 3. Proposta iniziale di tassonomia / labels

Tassonomia **emersa dai dati** (induttiva), su 3 dimensioni ortogonali. È un punto di partenza da
raffinare, non definitiva.

```yaml
# label_taxonomy (v0 — proposta da analisi preliminare)
intent:                       # cosa vuole l'ospite
  - preventivo_disponibilita  # quote/availability → tipicamente sfocia in link booking
  - info_servizi              # parcheggio, spiaggia, colazione, wifi, check-in/out, piscina
  - gestione_prenotazione     # ha già prenotato: modifica/conferma/codice
  - conferma_pagamento        # invia ricevuta/contabile, chiede conferma
  - assistenza_checkin        # web check-in fallito, arrivo, orari
  - logistica_trasporti       # come arrivare, traghetti, transfer, shuttle
  - evento_speciale           # pool party, Ferragosto, beach club
  - lavoro_hr                 # candidatura/CV (raro)
  - small_talk                # saluti, ringraziamenti

tema:                         # argomento (può coesistere con intent)
  - alloggio | spiaggia_lido | parcheggio | colazione_ristorazione | piscina
  - pagamenti | check_in_out | wifi | trasporti | eventi | hr

esito:                        # come finisce
  - link_booking_consegnato   # ~37%
  - info_fornita_dal_bot      # risposta soddisfacente senza rimando
  - rimando_staff             # ~65% (da scomporre, vedi §9)
  - takeover_umano            # ~1%
  - abbandonata | loop_irrisolto

canale: [whatsapp]
lingua: [it, en, es]

# segnali trasversali utili per il triage
flags:
  - allegato_presente         # ~10% — il bot è cieco agli allegati
  - friction_regola_eta       # ~26%
  - loop_ripetizione          # ~1%
  - cambio_lingua_midconv
```

---

## 4. Pattern di esito

- **Happy path preventivo** (~37%): ospite → struttura → date → composizione → **link
  bookingexpert.it**. Il bot **non** quota prezzi reali: consegna il link al motore di booking.
  Va deciso se questo conta come "successo" o come deflection morbida.
- **Info fornita dal bot**: domande secche su servizi (wifi, colazione, parcheggio, orari) →
  risposta corretta dalla knowledge. Funziona bene quando l'informazione esiste.
- **Rimando staff** (~65%): vedi §9 per la scomposizione.
- **Loop irrisolto** (~1%, 14 conv): il bot ri-chiede la stessa cosa mentre l'ospite ripete lo
  stesso messaggio (es. conv 31 turni: re-domanda "neonati?" all'infinito). Nessuna loop-detection.

---

## 5. Analisi handoff / takeover umano

- **14 conversazioni (1%)** con risposta umana (`info@panoramagroup.it`). Rare ma di alto valore:
  sono i casi dove lo staff dà la **risposta fattuale puntuale** che il bot non aveva.
- Esempi reali osservati: **orari precisi dei traghetti per Capri** (8:20 / 8:55), **piano della
  colazione** (5° piano), **info pool party**, "offerta inviata via email".
- Lettura: il takeover umano è il **gold standard** per capire cosa manca — ma il volume è troppo
  basso per generare da solo un dataset. Il segnale grosso è invece nei **rimandi automatici** (§9).

---

## 6. Cluster emergenti

Macro-cluster ricorrenti (dal campione + frequenze):
1. **Preventivo famiglia estate** — date agosto/luglio, 2 adulti + bambini, scelta struttura,
   regola età, link booking. È il cluster più numeroso.
2. **Info servizi pre-arrivo** — parcheggio (categorie/tariffe), spiaggia/lido (inclusa o no),
   colazione, check-in/out, wifi.
3. **Gestione prenotazione esistente** — codice prenotazione, modifica, "ho prenotato e…",
   web check-in fallito → il bot non accede → rimando.
4. **Pagamento/contabile** — ospite invia ricevuta (spesso allegato), chiede conferma → il bot
   non verifica → rimando.
5. **Internazionale ES/EN** — clientela estera, stesse intent ma in lingua; rischio cambio lingua.
6. **Logistica Costiera** — come arrivare, traghetti, transfer da Roma/Salerno.
7. **Eventi speciali** — pool party, Ferragosto: by-design solo staff.

---

## 7. Anomalie

1. **Cecità agli allegati (strutturale, ~10%)** — su WhatsApp gli ospiti mandano foto di ricevute,
   CV, email, documenti. Il bot risponde sistematicamente "non posso visualizzare allegati". È la
   singola anomalia con più impatto pratico: non è un buco di FAQ, è una **capability mancante**.
2. **Loop di ripetizione (~1%)** — nessuna rilevazione del fatto che ospite/bot stanno ripetendo
   lo stesso turno. UX frustrante, potenzialmente un fix di comportamento.
3. **Friction regola età (~26%)** — "2 adulti 2 bambini 18 & 13" → il bot riclassifica i 13-18enni
   come adulti e ri-chiede, generando confusione. Regola corretta ma comunicata male.
4. **Cambio lingua mid-conversazione** — conversazioni iniziate in EN/ES che ricevono risposte in
   IT (e viceversa). Coerenza linguistica da migliorare.
5. **Link booking come scappatoia** — il bot non dà disponibilità/prezzi reali, consegna il link.
   Per molte richieste è adeguato, ma maschera l'assenza di una vera capability di quoting.
6. **Token-rumore** — `attachment:`/URL `api.keplero.ai` nel testo: vanno normalizzati come entità
   `allegato`, non trattati come contenuto.

---

## 8. Topic dei rimandi a staff (scomposizione del 65%)

Conteggio **non esclusivo** (una conversazione può toccare più topic), su 1413 conversazioni che
rimandano a `info@`. Keyword-based ⇒ **approssimato** (l'HR è stato corretto: il match `posizion`
contava "posizione", l'HR reale è ~1-2%):

| Topic presente nelle deviate | % delle deviate |
|---|---|
| email/contatto staff (definitorio: la deviazione *è* il rimando) | 92% |
| disponibilità/preventivo | 78% |
| spiaggia/lido | 35% |
| gestione prenotazione esistente | 29% |
| parcheggio | 24% |
| pagamento | 18% |
| **attachment-blindness** | 14% |
| trasporto | 12% |
| evento speciale | 3% |
| lavoro/HR (reale) | ~1-2% |

> ⚠️ Questi sono *topic co-presenti*, non lo split causale {legittimo/incapacità/gap-conoscenza}.
> Quello split richiede una classificazione per conversazione (vedi raccomandazione R1).

---

## 9. Ipotesi operative

- **H1 — Il 65% di rimandi è gonfiato da incapacità, non solo da gap di conoscenza.** Una fetta
  consistente nasce da cose che il bot *non può fare* (vedere allegati, verificare pagamenti,
  accedere a prenotazioni, quotare prezzi reali), non da cose che *non sa*. → Aggiungere FAQ
  ridurrebbe i rimandi meno di quanto si pensi.
- **H2 — Gli allegati sono un canale informativo perso.** Il 10% delle conversazioni porta media
  che il bot ignora; spesso sono esattamente l'informazione che serve (ricevuta, documento).
- **H3 — La regola età è una causa di attrito evitabile** (26% la tocca): comunicarla in anticipo
  o accettare la formulazione dell'ospite ridurrebbe i turni.
- **H4 — Esiste domanda multilingue strutturale** (EN+ES ≈ metà del traffico): la coerenza
  linguistica e una knowledge multilingue contano più del previsto.
- **H5 — Il "link booking" non è un vero successo di quoting**: il bot delega; se l'obiettivo è
  conversione, manca una capability di prezzo/disponibilità reale.

---

## 10. Raccomandazioni — cosa costruire dopo

In ordine di valore/sforzo. **Nessuna è "scrivi la FAQ definitiva" o "scrivi il system prompt v2":
sono passi di analisi/strumentazione che rendono quelle decisioni informate.**

- **R1 — Classificazione per conversazione (lo split del 65%).** Etichettare ogni conversazione che
  rimanda a staff con `tipo_rimando ∈ {legittimo_by_design, incapacità_operativa, gap_conoscenza}`,
  usando la tassonomia §3. È **il** prerequisito per decidere dove investire. Campione 200-300
  conversazioni con Claude, poi estendere. *(Output: numeri reali, non keyword.)*
- **R2 — Landing dedupata in BQ** (`f_keplero_messaggi`, idempotente via `hash_riga`): rende il
  dataset interrogabile e ri-eseguibile sui dump futuri. Già progettato; abilita R1/R3 a regime.
- **R3 — Quantificare le capability mancanti** (allegati, verifica pagamento, accesso prenotazioni):
  se pesano molto sul 65%, la leva non è la FAQ ma l'**integrazione** (vision sugli allegati, hook
  a booking/PMS). Decisione di prodotto, non di knowledge.
- **R4 — Catalogo gap di conoscenza** (solo i `gap_conoscenza` di R1): da qui — e solo da qui —
  nasce un eventuale lavoro FAQ. Tema candidati più frequenti: spiaggia/lido inclusione, parcheggio
  dettagli, check-out tardo, transfer/trasporti, info eventi.
- **R5 — Quick win comportamentali** da validare con lo staff (NON applicati): pre-spiegare la
  regola età; loop-detection; coerenza linguistica IT/EN/ES; gestione esplicita degli allegati.

**Prossimo passo suggerito:** eseguire **R1** su un campione e riportare lo split del 65%. Da quel
numero si decide se il fronte è knowledge, capability o comportamento — oggi è solo un'ipotesi.

---

## 11. R1 — Split del fallimento (MISURATO e CORRETTO)

### 11.0 — Correzione metodologica (catch di Stefano)
La **prima** passata (R1) classificava 200 conversazioni "deviate", dove "deviata" = qualsiasi
messaggio con `info@panoramagroup.it`. Dava 62% incapacità / 34% knowledge. **Era contaminata** per
due motivi, emersi da una verifica:
1. Il bot usa `info@` anche come **footer/firma**: conversazioni risolte venivano contate come deviate.
2. **Consegnare il link di preventivo bookingexpert È il comportamento voluto** (è il modo in cui
   Emma "quota"), ma Claude — non potendo seguire il link — lo marcava come "incapacità: non può
   calcolare prezzi reali". L'**81%** dei casi "incapacità × preventivo" aveva in realtà **consegnato
   il link**. Globalmente, **515/1413 (36%) delle "deviate" avevano consegnato il link** = successi.

### 11.1 — Fotografia corretta (R1b, corpus pulito)
Ricalcolo escludendo i successi-via-link e facendo giudicare a Claude anche i falsi positivi
(`info@` come footer). Popolazione "candidati fallimento" = conversazioni **senza link + con info@**
= 898; campione 200.

| esito reale | quota campione |
|---|---|
| fallito | 88% |
| risolto (info@ era footer) | 12% |

Proiettando su tutte le **2172** conversazioni:

| outcome | conv | % |
|---|---|---|
| ✅ successo via link preventivo | 809 | **37%** |
| ✅ risolto (falso positivo info@) | ~108 | 5% |
| ❌ **fallimento vero** | ~790 | **36%** |
| → incapacità operativa | ~449 | 21% |
| → gap conoscenza | ~323 | 15% |
| → legittimo by-design | ~16 | 1% |
| ◻︎ né link né info@ (Q&A brevi / small talk / abbandonate) | 465 | 21% |

**Il fallimento reale è ~36%, non 65%.** Tra i fallimenti: **57% incapacità · 41% knowledge · 2%
legittimo**.

### 11.2 — Cosa serve per il bucket INCAPACITÀ (57% dei fallimenti, ~21% del totale)
Nel corpus pulito le incapacità sono **genuine** (niente più artefatto-link). Per intent:
`gestione_prenotazione` (44 — il bot non accede/verifica/inoltra prenotazioni o richieste allo
staff), `conferma_pagamento` (16), `preventivo` senza link (15 — qui davvero non l'ha generato),
assistenza check-in, trasporti. → Sono **integrazioni** (accesso booking/PMS, verifica pagamenti,
inoltro allo staff, vision allegati), non FAQ.

### 11.3 — Shortlist FAQ-addressable (41% dei fallimenti, ~15% del totale)
Dai `motivo` reali del bucket `gap_conoscenza`:
1. **Spiaggia / lido** — gap #1: prezzo servizio spiaggia, ombrellone+lettini inclusi o a pagamento,
   accesso senza soggiorno, gratuito o no.
2. **Colazione / ristorazione** — menù/prezzi cena, prezzo mezza pensione, accesso esterni al roof bar.
3. **Piscina** — accesso esterni, orari, riscaldamento.
4. **Trasporti** — prezzi transfer (Napoli/aeroporto), navetta/partner convenzionati.
5. **Alloggio (info statiche)** — triple/suite/ascensore, vista/piano camere, soggiorni lunghi.
6. **Altro** — codici sconto/promozioni, carte di credito accettate, late check-out, buoni regalo.

Dati per-conversazione: `/tmp/keplero_r1.jsonl` (R1, contaminato) e `/tmp/keplero_r1b.jsonl`
(R1b, pulito — quello valido).

---

### Appendice — metodo e caveat

- Analisi su corpus pieno (2172 file) per i conteggi + lettura ravvicinata di un campione
  stratificato di 26 conversazioni (handoff, allegati, corte/medie/lunghe, EN) per la parte induttiva.
- I breakdown per topic sono **keyword-based e approssimati**; un caso (HR via `posizion`) è stato
  individuato e corretto. Le percentuali vanno lette come ordini di grandezza, non misure esatte.
- La classificazione per conversazione (R1) sostituirà le euristiche con label vere.
