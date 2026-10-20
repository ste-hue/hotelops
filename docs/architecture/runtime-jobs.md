# Cloud Run Job: rilascio, verifica, ritorno indietro

Sei job schedulati portano le pipeline automatiche: `pec-fetch`, `coperti`,
`spiaggia-corrispettivi`, `reviews-scrape`, `reviews-report`, `canone-push`.
Inventario: `infra/jobs.yaml`. Motore: `scripts/cloud/rilascio_jobs.py`.
Rilascio: `.github/workflows/deploy-jobs.yml`, solo a mano.

## La divergenza da cui nasce tutto questo

Il codice committato e il codice in esecuzione potevano separarsi senza che
niente lo segnalasse. Il caso provato:

| | |
|---|---|
| Versionato | `ingest/pec_fetch.py:244` apre `PipelineRun("pec_fetch")`, dal commit `b37ae64`, author date **2026-09-10** |
| In esecuzione | digest `sha256:0afbd6d1…` (tag `v5`), creato **2026-08-15T17:15:46** |
| Effetto | quindici esecuzioni dal 05/10 al 19/10, tutte riuscite, e **zero** righe `pec_fetch` in `f_pipeline_runs` |

L'immagine è anteriore di 26 giorni al codice che scrive la ricevuta: il job
lavora e non firma. La freschezza non può distinguere «job morto» da «job
muto», e l'unico «ultimo OK» che `hotelops health` mostrava era una riga
scritta dalla suite di test il 10/09.

Il percorso di rilascio contribuiva in tre modi: `pec-fetch` non era nella
lista dei job aggiornati; l'immagine era riferita per **tag mobile**, quindi
ciò che un job esegue non è deducibile da ciò che il tag diceva ieri; e non
esisteva né una verifica né un ritorno indietro riferiti al digest.

⚠️ Una cosa che **non** è provata, per non ripetere un'affermazione troppo
forte: il workflow precedente costruiva `jobs:prod` *prima* degli update,
quindi una build riuscita avrebbe creato quel tag. Il fatto che oggi il tag non
esista non dimostra che eseguirlo avrebbe puntato i job a un'immagine
inesistente.

## Rilasciare

1. Scegliere **quali** job aggiornare. Il pilota è `pec-fetch`. Comparire
   nell'inventario non è un ordine di distribuzione: i tag diversi oggi in uso
   — `v1`, `v2`, `v5`, `v7` — possono essere deliberati, e nessuno li allinea
   per il solo fatto che esistono.
2. Actions → `deploy-jobs` → Run workflow, con i job separati da spazio.
3. Il workflow costruisce l'immagine con un tag datato e legato al commit
   (`prod-<istante>-<sha12>`, mai riusato) e ne **risolve subito il digest**.
4. Stampa il **piano** e si ferma se qualcosa non torna (vedi sotto).
5. Aggiorna i soli job del piano, con `--image=…@sha256:…`. I comandi vengono
   letti dal piano, non ricostruiti nel workflow.
6. **Non esegue nessun job.** Stampa che cosa resta da verificare e come.

### Quando il piano si ferma

Tre stati che non vanno confusi:

1. l'immagine **configurata** adesso sul job (può essere un tag mobile);
2. il **digest a cui quel riferimento si risolve ora** — ciò che il job
   eseguirebbe se partisse in questo istante, cioè la configurazione che un
   ritorno indietro deve ripristinare;
3. il digest dell'**ultima esecuzione osservata** — ciò che ha girato davvero
   l'ultima volta.

Il 2 e il 3 possono differire: un job aggiornato e non più partito ha
un'ultima esecuzione che appartiene alla configurazione **precedente**; un tag
spostato produce lo stesso effetto. In quel caso tornare «all'ultimo eseguito»
non ripristina niente: propone un **terzo** stato. Il percorso automatico si
ferma, dichiara entrambi i digest e l'esecuzione da cui li ha letti, e lascia
decidere quale dei due sia quello buono.

Si ferma anche se: un job chiesto non è nell'inventario; la destinazione non
esiste in Artifact Registry; l'immagine configurata non si risolve in un
digest; non c'è nessuna esecuzione osservata con un digest, perché allora non
si sa da dove si tornerebbe.

## Verificare

Due domande, in questo ordine:

    python -m scripts.cloud.rilascio_jobs verifica --job pec-fetch --digest sha256:…

1. **Il job esegue il digest che volevamo?** Si guarda l'immagine risolta
   dell'ultima esecuzione. Va fatto **dopo la prima esecuzione schedulata**
   (per `pec-fetch`: le 04:00 di Roma): subito dopo l'update l'ultima
   esecuzione è ancora la precedente, e la risposta sarebbe `DIVERSO` a
   ragione.
2. **La ricevuta attesa è comparsa?** Si cercano le righe con quel
   `pipeline_name` dentro la finestra dell'esecuzione. Quattro esiti:
   `PLAUSIBILE` una riga, `MANCA` nessuna, `AMBIGUO` più di una, e `ATTESO` per
   i job che dichiarano `ricevuta: null`.

⚠️ **Il limite, dichiarato in ogni risposta invece di essere aggirato.**
`f_pipeline_runs` non ha nessun campo che leghi una riga a una esecuzione di
Cloud Run: ci sono `run_id`, generato dal processo, `started_at` e `ended_at`.
La corrispondenza è quindi **per nome e finestra temporale**: plausibile, non
certa. Una riga dentro la finestra può venire da un'esecuzione manuale dello
stesso comando. Nessun collegamento è stato inventato per far sembrare certa
una cosa che non lo è.

E su `MANCA` non si conclude la causa: l'insert è best-effort
(`core/pipeline_run.py:127-138`), quindi writer assente nell'immagine e
permesso negato producono lo stesso silenzio, e questo controllo non li
distingue. Il primo rilascio di `pec-fetch` è anche il primo momento in cui si
saprà quale dei due era.

## Tornare indietro

Il piano stampa, per ogni job, il comando esatto con il digest di partenza:

    gcloud run jobs update <job> --project=hotelops-suite --region=europe-west1 \
      --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs@sha256:…

Se un passo del workflow fallisce, quei comandi vengono ristampati. Se il
fallimento è arrivato **prima** del piano, il workflow dichiara che nessun job
è stato aggiornato e non offre comandi: un rollback senza digest sarebbe un
comando rotto porto nel momento peggiore per accorgersene.

Lo scheduler non viene toccato dal rilascio: resta quello che è
(`gcloud scheduler jobs list`), e i sei orari versionati negli script
coincidono con i sei live, verificato il 20/10, tutti `ENABLED`.

## Permessi: verificato, niente da ampliare

`github-deployer@hotelops-suite` ha già `roles/run.admin`,
`roles/artifactregistry.writer`, `roles/cloudbuild.builds.editor` a livello
progetto, e `roles/iam.serviceAccountUser` su `drive-audit@` e su
`hotelops-jobs@`, cioè sui service account dei sei job. Letto il 20/10.
Aggiornare un job richiede proprio quell'`actAs`: c'è. **Nessun IAM è stato
modificato né va modificato** per questo percorso.

## Controlli automatici

Tutti offline, su file versionati:

- `tests/test_jobs_inventory.py` — l'inventario è completo; lo script di
  provisioning esiste e crea quel nome; l'entrypoint riferisce moduli che
  esistono; nessun tag o digest dentro l'inventario; **ogni ricevuta dichiarata
  ha il suo `PipelineRun` nel codice e ogni `null` non ce l'ha**; le sorgenti
  `AUTO` del registry servite da questi job combaciano e nessuna è rivendicata
  da due job. Le pipeline che non girano su Cloud Run non sono bloccate.
- `tests/test_rilascio_jobs.py` — il piano sulle sue classi di guasto, con un
  cloud finto: job aggiornato e mai più eseguito, tag spostato, immagine già
  pinnata, nessuna esecuzione, configurazione non risolvibile, destinazione
  inesistente, nessun job chiesto, job fuori inventario; e i quattro esiti
  della verifica della ricevuta.
- `tests/test_deploy_jobs.py` — il workflow parte solo a mano e chiede quali
  job; nessun tag mobile e nessun nome di job scritto nei comandi; il digest
  viene risolto e non può essere vuoto; il piano precede l'aggiornamento e i
  comandi vengono da lì; il rilascio non esegue job; dice che cosa verificare e
  come tornare indietro.

## Che cosa resta aperto

- Il deploy dei job **non** pretende che la suite sia passata su quel commit,
  a differenza del hub (`docs/architecture/runtime-deploy.md`). È un'asimmetria
  da decidere, non una scelta: qui non è stata affrontata.
- La ricostruzione dell'immagine di `pec-fetch` è il primo rilascio reale, e va
  deciso da chi coordina. Fino a quel momento la divergenza descritta sopra
  resta: **questa pagina non la chiude, la rende rilasciabile e verificabile.**
- `canone-push` e `reviews-report` dichiarano `ricevuta: null`. È dichiarato,
  non risolto: se un domani si volesse osservarli in `f_pipeline_runs`, va
  aperto un `PipelineRun` nel loro percorso e aggiornato l'inventario — il test
  lo pretende nei due versi.
