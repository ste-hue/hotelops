"""Piano e verifica del rilascio dei Cloud Run Job. Non distribuisce niente.

Due verbi, nessun effetto:

    python -m scripts.cloud.rilascio_jobs piano --job pec-fetch --tag <TAG>
    python -m scripts.cloud.rilascio_jobs verifica --job pec-fetch --digest sha256:...

`piano` stampa, per i soli job CHIESTI: il commit da cui nasce l'immagine, il
digest di destinazione già risolto, il digest che quel job sta davvero
eseguendo e i due comandi — quello di aggiornamento e quello per tornare
indietro. Nessun job viene aggiornato per il solo fatto di stare
nell'inventario: i tag diversi oggi in uso possono essere deliberati.

`verifica` risponde a due domande dopo il rilascio: il job sta eseguendo il
digest che volevamo, e la ricevuta attesa è comparsa.

⚠️ Sul secondo punto c'è un limite che non si può aggirare e che non va
mascherato: `f_pipeline_runs` NON ha nessun campo che leghi una riga a una
esecuzione di Cloud Run. Ci sono `run_id`, generato dal processo, `started_at`
e `ended_at`. Quindi la correlazione esecuzione → ricevuta è **per finestra
temporale e nome**, cioè plausibile, non certa: una riga dentro la finestra
potrebbe venire da un'esecuzione manuale dello stesso comando. Questo
strumento lo dichiara in ogni risposta invece di inventare un collegamento che
il dato non ha.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[2]
INVENTARIO_PREDEFINITO = RADICE / "infra" / "jobs.yaml"

LIMITE_CORRELAZIONE = (
    "f_pipeline_runs non lega una riga a una esecuzione di Cloud Run: la "
    "corrispondenza è per nome e finestra temporale, quindi plausibile e non "
    "certa."
)


def carica_inventario(percorso: Path | None = None) -> dict:
    return yaml.safe_load((percorso or INVENTARIO_PREDEFINITO).read_text(encoding="utf-8"))


# ── Il confine verso il cloud, iniettabile ──────────────────────────────────
# Tutto ciò che legge dall'esterno sta qui dentro: i test ne passano una
# versione finta e non toccano nulla.


class Cloud:
    """Letture di metadati. Nessun verbo che modifichi qualcosa."""

    def __init__(self, progetto: str, regione: str):
        self.progetto, self.regione = progetto, regione

    def _gcloud(self, *args: str) -> str:
        esito = subprocess.run(
            ["gcloud", *args, f"--project={self.progetto}"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if esito.returncode != 0:
            raise RuntimeError(f"gcloud {' '.join(args[:3])}: {esito.stderr.strip()[:200]}")
        return esito.stdout.strip()

    def immagine_configurata(self, job: str) -> str:
        return self._gcloud(
            "run", "jobs", "describe", job, f"--region={self.regione}",
            "--format=value(spec.template.spec.template.spec.containers[0].image)",
        )

    def ultima_esecuzione(self, job: str) -> dict | None:
        """Nome, immagine RISOLTA e finestra dell'ultima esecuzione.

        L'immagine risolta è l'unica cosa osservata in esecuzione: quella
        configurata è l'intento e, se è un tag mobile, può essere già un'altra.
        """
        righe = self._gcloud(
            "run", "jobs", "executions", "list", f"--job={job}", f"--region={self.regione}",
            "--limit=1", "--format=value[separator=|](metadata.name,status.startTime,status.completionTime)",
        )
        if not righe:
            return None
        nome, inizio, fine = (righe.split("|") + ["", "", ""])[:3]
        immagine = self._gcloud(
            "run", "jobs", "executions", "describe", nome, f"--region={self.regione}",
            "--format=value(spec.template.spec.containers[0].image)",
        )
        return {"nome": nome, "immagine": immagine, "inizio": inizio, "fine": fine}

    def digest(self, immagine_con_tag: str) -> str | None:
        """Risolve un riferimento in `sha256:...`, o None se non esiste."""
        try:
            uscita = self._gcloud(
                "artifacts", "docker", "images", "describe", immagine_con_tag,
                "--format=value(image_summary.digest)",
            )
        except RuntimeError:
            return None
        return uscita or None

    def ricevute(self, pipeline_name: str, da: str, a: str) -> list[dict]:
        sql = (
            "SELECT run_id, status, started_at, ended_at FROM "
            "`hotelops-suite.hotelops.f_pipeline_runs` WHERE pipeline_name = @p "
            "AND started_at >= @da AND started_at <= @a ORDER BY started_at"
        )
        esito = subprocess.run(
            ["bq", f"--project_id={self.progetto}", "query", "--use_legacy_sql=false",
             "--format=json", f"--parameter=p::{pipeline_name}",
             f"--parameter=da:TIMESTAMP:{da}", f"--parameter=a:TIMESTAMP:{a}", sql],
            capture_output=True, text=True, timeout=300, check=False,
        )
        if esito.returncode != 0:
            raise RuntimeError(f"bq query: {esito.stderr.strip()[:200]}")
        return json.loads(esito.stdout or "[]")


# ── Piano ───────────────────────────────────────────────────────────────────


def _job_per_nome(inventario: dict) -> dict:
    return {j["nome"]: j for j in inventario["job"]}


def piano(cloud, inventario: dict, scelti: list[str], riferimento: str, commit: str) -> dict:
    """Che cosa accadrebbe, senza farlo accadere.

    `riferimento` è il tag appena costruito; viene risolto in digest prima di
    comparire in qualunque comando, perché un tag può spostarsi fra il piano e
    l'esecuzione e allora il piano non descriveva il rilascio.
    """
    per_nome = _job_per_nome(inventario)
    regione = inventario["regione"]
    progetto = inventario["progetto"]
    esito = {
        "commit": commit,
        "riferimento": riferimento,
        "digest_destinazione": None,
        "job": [],
        "rifiuti": [],
        "limite": LIMITE_CORRELAZIONE,
    }
    if not scelti:
        esito["rifiuti"].append("nessun job chiesto: il rilascio sceglie i job uno per uno")
        return esito

    digest = cloud.digest(riferimento)
    if not digest:
        esito["rifiuti"].append(f"{riferimento}: non esiste in Artifact Registry, niente da rilasciare")
        return esito
    esito["digest_destinazione"] = digest
    immagine_destinazione = f"{inventario['immagine']}@{digest}"

    for nome in scelti:
        if nome not in per_nome:
            esito["rifiuti"].append(f"{nome}: non è nell'inventario infra/jobs.yaml")
            continue
        try:
            configurata = cloud.immagine_configurata(nome)
        except RuntimeError as errore:
            esito["rifiuti"].append(f"{nome}: non leggibile in cloud ({errore})")
            continue
        # TRE stati, da non confondere mai fra loro:
        #  1. l'immagine CONFIGURATA adesso sul job (può essere un tag mobile);
        #  2. il digest a cui quel riferimento si risolve ORA — è ciò che il job
        #     eseguirebbe se partisse in questo istante, cioè la configurazione
        #     che un rollback deve ripristinare;
        #  3. il digest dell'ultima esecuzione OSSERVATA — ciò che ha girato
        #     davvero l'ultima volta, che può appartenere a una configurazione
        #     precedente (job aggiornato e non più eseguito, o tag spostato).
        # Se 2 e 3 non coincidono, tornare "all'ultimo eseguito" non ripristina
        # la configurazione precedente: propone un terzo stato. Qui il percorso
        # automatico si ferma e lascia decidere.
        risolto = (
            configurata.split("@", 1)[1]
            if "@" in configurata
            else cloud.digest(configurata)
        )
        esecuzione = cloud.ultima_esecuzione(nome)
        osservato_immagine = (esecuzione or {}).get("immagine") or ""
        osservato = osservato_immagine.split("@", 1)[1] if "@" in osservato_immagine else None

        if not risolto:
            esito["rifiuti"].append(
                f"{nome}: l'immagine configurata «{configurata}» non si risolve in un digest, "
                "quindi non so quale configurazione ripristinare"
            )
            continue
        if osservato is None:
            esito["rifiuti"].append(
                f"{nome}: nessuna esecuzione osservata con un digest. La configurazione attuale "
                f"risolve a {risolto}, ma non è mai stata vista girare: decidere a mano"
            )
            continue
        if osservato != risolto:
            esito["rifiuti"].append(
                f"{nome}: DIVERGENZA da decidere. Configurato «{configurata}» → {risolto}; "
                f"ultima esecuzione {esecuzione['nome']} ha girato {osservato}. "
                "Ripristinare l'ultimo eseguito NON riporterebbe alla configurazione attuale: "
                "sarebbe un terzo stato. Serve una decisione su quale dei due è quello buono"
            )
            continue

        esito["job"].append({
            "nome": nome,
            "ricevuta_attesa": per_nome[nome]["ricevuta"],
            "immagine_configurata": configurata,
            "digest_configurato": risolto,
            "digest_osservato": osservato,
            "esecuzione_osservata": esecuzione["nome"],
            # Coincidono: ripristinare questo digest riporta davvero alla
            # configurazione da cui si parte, e non a uno stato inventato.
            "ripristina_stato": risolto,
            "aggiorna": (
                f"gcloud run jobs update {nome} --project={progetto} --region={regione} "
                f"--image={immagine_destinazione}"
            ),
            "torna_indietro": (
                f"gcloud run jobs update {nome} --project={progetto} --region={regione} "
                f"--image={inventario['immagine']}@{risolto}"
            ),
        })
    return esito


# ── Verifica ────────────────────────────────────────────────────────────────


def verifica(cloud, inventario: dict, nome: str, digest_atteso: str) -> dict:
    per_nome = _job_per_nome(inventario)
    esito = {"nome": nome, "limite": LIMITE_CORRELAZIONE, "esiti": []}
    if nome not in per_nome:
        esito["esiti"].append(("ERRORE", f"{nome}: non è nell'inventario"))
        return esito

    esecuzione = cloud.ultima_esecuzione(nome)
    if not esecuzione:
        esito["esiti"].append(("IGNOTO", f"{nome}: nessuna esecuzione da osservare"))
        return esito
    in_esecuzione = (esecuzione.get("immagine") or "").split("@")[-1]
    atteso = digest_atteso if digest_atteso.startswith("sha256:") else f"sha256:{digest_atteso}"
    if in_esecuzione == atteso:
        esito["esiti"].append(("OK", f"{esecuzione['nome']} esegue il digest atteso"))
    else:
        esito["esiti"].append((
            "DIVERSO",
            f"{esecuzione['nome']} esegue {in_esecuzione or '<ignoto>'}, atteso {atteso}",
        ))
        return esito

    ricevuta = per_nome[nome]["ricevuta"]
    if ricevuta is None:
        esito["esiti"].append((
            "ATTESO",
            f"{nome} non apre nessuna ricevuta: l'assenza da f_pipeline_runs è dichiarata, non un guasto",
        ))
        return esito
    if not esecuzione.get("fine"):
        esito["esiti"].append(("IGNOTO", f"{esecuzione['nome']} non è conclusa: la ricevuta si cerca dopo"))
        return esito

    righe = cloud.ricevute(ricevuta, esecuzione["inizio"], esecuzione["fine"])
    if not righe:
        esito["esiti"].append((
            "MANCA",
            f"nessuna riga «{ricevuta}» nella finestra di {esecuzione['nome']}. "
            "L'insert è best-effort (core/pipeline_run.py): può essere il writer assente "
            "nell'immagine o il permesso negato, e questo controllo non li distingue",
        ))
    elif len(righe) == 1:
        esito["esiti"].append((
            "PLAUSIBILE",
            f"una riga «{ricevuta}» ({righe[0].get('status')}) nella finestra di {esecuzione['nome']}",
        ))
    else:
        esito["esiti"].append((
            "AMBIGUO",
            f"{len(righe)} righe «{ricevuta}» nella finestra: non so quale appartenga a questa esecuzione",
        ))
    return esito


# ── Superficie ──────────────────────────────────────────────────────────────


def _commit() -> str:
    esito = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, cwd=RADICE
    )
    return esito.stdout.strip() or "<ignoto>"


def stampa_piano(p: dict) -> None:
    print(f"commit sorgente:      {p['commit']}")
    print(f"riferimento chiesto:  {p['riferimento']}")
    print(f"digest destinazione:  {p['digest_destinazione'] or '<non risolto>'}")
    print(f"job selezionati:      {', '.join(j['nome'] for j in p['job']) or '<nessuno>'}")
    for j in p["job"]:
        print()
        print(f"  {j['nome']}")
        print(f"    configurato ora:  {j['immagine_configurata']}")
        print(f"    risolve a:        {j['digest_configurato']}   <- lo stato che un ritorno ripristina")
        print(f"    ultima esecuzione: {j['digest_osservato']}  (da {j['esecuzione_osservata']}) — coincide")
        print(f"    ricevuta attesa:  {j['ricevuta_attesa'] or '<nessuna, dichiarato>'}")
        print(f"    aggiorna:         {j['aggiorna']}")
        print(f"    torna indietro:   {j['torna_indietro']}")
    for r in p["rifiuti"]:
        print(f"  RIFIUTATO: {r}")
    print()
    print(f"limite: {p['limite']}")


def main(argv: list[str] | None = None) -> int:
    genitore = argparse.ArgumentParser(prog="rilascio_jobs", description=__doc__)
    sub = genitore.add_subparsers(dest="verbo", required=True)
    for verbo in ("piano", "verifica"):
        p = sub.add_parser(verbo)
        p.add_argument("--job", action="append", default=[], help="da ripetere: i job scelti")
        p.add_argument("--inventario", type=Path, default=None)
        if verbo == "piano":
            p.add_argument("--tag", required=True, help="il riferimento appena costruito")
            # Il workflow legge i comandi da qui invece di ricostruirli: due
            # posti che derivano lo stesso comando divergono al primo cambio.
            p.add_argument("--json", action="store_true", help="il piano come dati")
        else:
            p.add_argument("--digest", required=True)
    args = genitore.parse_args(argv)

    inventario = carica_inventario(args.inventario)
    cloud = Cloud(inventario["progetto"], inventario["regione"])
    if args.verbo == "piano":
        riferimento = f"{inventario['immagine']}:{args.tag}"
        p = piano(cloud, inventario, args.job, riferimento, _commit())
        if args.json:
            print(json.dumps(p, indent=1, ensure_ascii=False))
        else:
            stampa_piano(p)
        return 1 if p["rifiuti"] or not p["job"] else 0

    uscita = 0
    for nome in args.job:
        esito = verifica(cloud, inventario, nome, args.digest)
        for stato, messaggio in esito["esiti"]:
            print(f"[{stato}] {messaggio}")
            if stato in ("ERRORE", "DIVERSO", "MANCA", "AMBIGUO"):
                uscita = 1
        print(f"limite: {esito['limite']}")
    return uscita


if __name__ == "__main__":
    sys.exit(main())
