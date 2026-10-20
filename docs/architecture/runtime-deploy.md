# Rilascio e ritorno indietro

Come si pubblica, come si verifica e come si torna alla versione precedente.
Una regola sola, da cui discende il resto: **la pubblicazione è una decisione,
quindi ha un momento in cui qualcuno la prende.** Non è un effetto collaterale
di un merge.

## Hub (Cloud Run service `hotelops-hub`)

### Com'era, e perché è cambiato

`deploy-hub.yml` partiva anche su `push` su `main`, con `paths-ignore` su
`docs/**`, `meta/**`, `vault/**` e `**.md`. Quell'elenco esclude le modifiche
documentali, quindi un merge di **codice** pubblicava da sé: chi integrava una
PR pubblicava senza dirlo e senza guardare un piano. Ora il workflow ha il solo
`workflow_dispatch`.

### Rilasciare

1. Assicurarsi che il workflow `test` sia **passato su quell'esatto commit**.
   Se è passato su un commit vicino non vale: il verde di un altro albero non
   dice niente su questo.
2. Lanciare `deploy-hub` a mano (Actions → deploy-hub → Run workflow) sul ramo
   o sul tag che si vuole pubblicare.
3. Il workflow si ferma da sé se non trova una esecuzione **conclusa e
   riuscita** di `test` per quel `head_sha`, e si ferma anche se non riesce a
   interrogare l'API: non sapere non è un via libera. Attenzione: `test` parte
   su push su `main` e sulle pull request e **non ha un `workflow_dispatch`**,
   quindi non esiste un «lancia test» da premere. Le due vie sono riusare la
   run già esistente per quel commit (Actions → test → Re-run) oppure portare
   il commit su `main` o in una pull request, dove `test` parte da sé.
4. Prima di toccare il servizio legge **tutta la distribuzione del traffico** e
   stampa il comando per tornare indietro: è il piano di rollback, letto prima
   e non ricostruito dopo. Si **ferma prima del deploy** se la distribuzione non
   è esattamente un target al 100% con un nome — vedi sotto.
5. Dopo il deploy verifica che il cancello IAP risponda ancora `302` a una GET
   anonima.

### Tornare indietro

Il traffico si ripunta alla revisione precedente, senza ricostruire né
ridistribuire niente:

    gcloud run services update-traffic hotelops-hub \
      --project=hotelops-suite --region=europe-west1 \
      --to-revisions=<REVISIONE>=100

`<REVISIONE>` è quella stampata dal passo «Piano di rollback» della run che ha
pubblicato.

**Perché il workflow si ferma su un traffico diviso.** `--to-revisions=<rev>=100`
non riporta allo stato precedente un servizio che serviva traffico su più
revisioni: lo porta in uno stato nuovo, mai esistito. Prima leggeva solo il
primo target e forzava comunque il 100%, quindi con uno split prometteva un
ritorno che non era un ritorno, e con nessun target esportava un rollback
vuoto senza accorgersene. Ora pretende la forma che sa ripristinare — un solo
target, al 100%, con un nome — e altrimenti si ferma **prima** del deploy
stampando la distribuzione osservata. In quel caso si rilascia a mano e si
ripristina con un solo comando che elenca tutte le revisioni:

    gcloud run services update-traffic hotelops-hub \
      --project=hotelops-suite --region=europe-west1 \
      --to-revisions=<REV_A>=50,<REV_B>=50

Se quella run non è a portata di mano:

    gcloud run revisions list --service=hotelops-hub \
      --project=hotelops-suite --region=europe-west1 \
      --format='table(metadata.name, metadata.creationTimestamp, status.conditions[0].status)'

### Modalità manuale (break-glass)

Resta documentata e non è stata toccata:

    gcloud run deploy hotelops-hub --source . --region=europe-west1

Va usata quando GitHub Actions non è disponibile. Chi la usa **non ha il
cancello sui test**: la suite va lanciata a mano prima, e la revisione
precedente va annotata prima di partire.

## Che cosa questi controlli NON dimostrano

- Che il codice pubblicato sia corretto: dimostrano che la suite è passata su
  quel commit, che è un'altra affermazione.
- Che la pubblicazione sia andata a buon fine oltre al `302` del cancello: una
  sola risposta attesa su una sola rotta non è un collaudo dell'applicazione.
- Niente sui Cloud Run **job** schedulati (`pec-fetch`, `coperti`,
  `reviews-*`, `spiaggia-corrispettivi`, `canone-push`): hanno un percorso
  separato, `deploy-jobs.yml`, e un difetto diverso — l'immagine è riferita per
  tag mobile, `pec-fetch` non è nella lista aggiornata e non c'è una verifica
  né un ritorno indietro riferiti al digest. È il lavoro successivo, non è
  chiuso qui e non va dato per risolto leggendo questa pagina.

## Controlli automatici

`tests/test_workflows.py` verifica sui file versionati, senza chiamare nessun
servizio: che nessun workflow di deploy parta su `push` o a orologio; che il
deploy del hub dipenda da un cancello ancorato a `head_sha` con conclusione
riuscita; che il piano di rollback venga letto **prima** del deploy.

Quei controlli però guardavano il testo degli script, e un controllo verificato
per sottostringhe può essere verde senza bloccare niente: `exit 1` presente nel
testo non dice che venga raggiunto. Quindi i due passi vengono **estratti dal
YAML ed eseguiti** con `gh` e `gcloud` finti, senza rete e senza token, sulle
classi di guasto: nessuna run su quel commit, run fallita, run riuscita,
errore dell'API; e per il rollback un solo target al 100%, nessun target,
traffico diviso in due o in tre, nome vuoto, percentuale diversa da 100. Sono
le classi di guasto già incontrate, non la forma dei file.
