"""Rilegge la forma di un servizio Cloud Run e la confronta con ciò che è stato chiesto.

Una bandiera pinnata che nessuno rilegge è una promessa, non una misura: il
rilascio di `hotelops-hub` dichiara memoria, cpu, timeout, min-instances e
affinità di sessione in `.github/workflows/deploy-hub.yml`, e questo modulo
risponde all'unica domanda che chiude il cerchio — il servizio è davvero così?

    python -m scripts.cloud.forma_servizio leggi --servizio hotelops-hub
    python -m scripts.cloud.forma_servizio confronta --payload describe.json \
        --memoria 2Gi --cpu 2 --timeout 300 --min-istanze 0 --affinita si

`leggi` è una lettura (`gcloud run services describe`) e non tocca niente.
`confronta` non parla con nessuno: prende il payload da un file o da stdin,
quindi si prova senza credenziali.

## Il punto delicato: l'assenza di un campo

`minScale` **assente** non è un errore e non è «sconosciuto»: vuol dire zero.
`sessionAffinity` assente vuol dire disattivata. Un controllo scritto come
`test "$MIN" = "0"` sul campo letto fallirebbe sul campo giusto per la ragione
sbagliata — la famiglia di difetti in cui un'assenza prende la forma di un
fatto.

Ma l'assenza non parla sempre. Memoria, cpu e timeout Cloud Run li materializza
sempre: se non li trovo, non è il servizio che non li ha, è questo lettore che
guarda nel posto sbagliato. Due assenze identiche alla sintassi, due significati
opposti — quindi qui sono due cose con due nomi:

  ASSENZA_PARLANTE  l'API definisce il valore dell'assenza  -> si confronta
  ASSENZA_MUTA      l'assenza è un difetto del lettore      -> `non_letto`

E `non_letto` è un terzo esito, non un `diverso`: dire «il servizio ha il valore
sbagliato» quando non si è riusciti a leggerlo sarebbe un rosso falso, che nel
solo percorso che pubblica costa quanto un verde falso.

## Perché il modo predefinito non blocca

I percorsi JSON qui sotto NON sono stati verificati su un payload vero: al
6/11/2026 il token gcloud su tong è scaduto e `services describe` risponde
«Reauthentication failed». Finché nessuno riporta una lettura vera, questo
controllo gira in modo `osserva`: stampa tutto e non fa fallire niente. Il
giorno che un payload conferma i percorsi, si passa a `pretendi` cambiando una
parola nel workflow. Mettere subito `pretendi` significherebbe far bloccare un
rilascio da un percorso che ho indovinato.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

ASSENZA_PARLANTE = "assenza_parlante"
ASSENZA_MUTA = "assenza_muta"

UGUALE, DIVERSO, NON_LETTO = "uguale", "diverso", "non_letto"

MOLTIPLICATORI = {"": 1, "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12,
                  "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}


def normalizza_memoria(valore) -> int:
    """'2Gi' -> 2147483648. Le quantità Kubernetes hanno due basi, e 2G ≠ 2Gi."""
    testo = str(valore).strip()
    for suffisso in sorted(MOLTIPLICATORI, key=len, reverse=True):
        if suffisso and testo.endswith(suffisso):
            return int(float(testo[: -len(suffisso)]) * MOLTIPLICATORI[suffisso])
    return int(float(testo))


def normalizza_cpu(valore) -> int:
    """'2' e '2000m' sono lo stesso valore: si confrontano in millicore."""
    testo = str(valore).strip()
    if testo.endswith("m"):
        return int(float(testo[:-1]))
    return int(float(testo) * 1000)


def normalizza_booleano(valore) -> bool:
    if isinstance(valore, bool):
        return valore
    return str(valore).strip().lower() in {"true", "si", "sì", "yes", "1", "on"}


def normalizza_intero(valore) -> int:
    return int(str(valore).strip())


# Dove guardare, cosa farne, e cosa vuol dire non trovarlo. `dove` è una lista
# perché non so, senza un payload vero, se l'affinità di sessione si annoti sul
# template della revisione o sul servizio: le cerco in entrambi e dico dove l'ho
# trovata, invece di indovinare un posto solo e chiamare «assente» l'altro.
CAMPI = {
    "memoria": {
        "dove": [("spec", "template", "spec", "containers", 0, "resources", "limits", "memory")],
        "normalizza": normalizza_memoria,
        "assenza": ASSENZA_MUTA,
    },
    "cpu": {
        "dove": [("spec", "template", "spec", "containers", 0, "resources", "limits", "cpu")],
        "normalizza": normalizza_cpu,
        "assenza": ASSENZA_MUTA,
    },
    "timeout": {
        "dove": [("spec", "template", "spec", "timeoutSeconds")],
        "normalizza": normalizza_intero,
        "assenza": ASSENZA_MUTA,
    },
    "min_istanze": {
        "dove": [("spec", "template", "metadata", "annotations", "autoscaling.knative.dev/minScale"),
                 ("metadata", "annotations", "autoscaling.knative.dev/minScale")],
        "normalizza": normalizza_intero,
        "assenza": ASSENZA_PARLANTE,
        "valore_se_assente": 0,
        "perche": "minScale assente = nessun minimo = 0 (non «sconosciuto»)",
    },
    "affinita_sessione": {
        "dove": [("spec", "template", "metadata", "annotations", "run.googleapis.com/sessionAffinity"),
                 ("metadata", "annotations", "run.googleapis.com/sessionAffinity")],
        "normalizza": normalizza_booleano,
        "assenza": ASSENZA_PARLANTE,
        "valore_se_assente": False,
        "perche": "sessionAffinity assente = disattivata",
    },
}


def _scava(payload, percorso):
    nodo = payload
    for passo in percorso:
        try:
            nodo = nodo[passo]
        except (KeyError, IndexError, TypeError):
            return None, False
    return nodo, True


def leggi_forma(payload: dict) -> dict:
    """{campo: {'valore', 'dove', 'assente'}} — nessun confronto, solo lettura."""
    letta = {}
    for campo, regola in CAMPI.items():
        for percorso in regola["dove"]:
            grezzo, trovato = _scava(payload, percorso)
            if trovato and grezzo is not None:
                letta[campo] = {"valore": grezzo, "dove": ".".join(str(p) for p in percorso),
                                "assente": False}
                break
        else:
            letta[campo] = {"valore": None, "dove": None, "assente": True}
    return letta


def confronta(attesa: dict, letta: dict) -> list[dict]:
    """Un esito per campo chiesto: uguale, diverso o non_letto.

    `attesa` tiene solo i campi che il rilascio ha davvero pinnato: ciò che
    nessuno ha chiesto non si giudica.
    """
    esiti = []
    for campo, chiesto in attesa.items():
        regola = CAMPI[campo]
        norma = regola["normalizza"]
        lettura = letta.get(campo) or {"assente": True, "valore": None, "dove": None}
        esito = {"campo": campo, "chiesto": chiesto, "dove": lettura["dove"]}

        if lettura["assente"]:
            if regola["assenza"] == ASSENZA_MUTA:
                esiti.append({**esito, "esito": NON_LETTO, "letto": None,
                              "nota": "campo non trovato nel payload. Cloud Run lo"
                                      " materializza sempre: non e' il servizio che non"
                                      " ce l'ha, e' questo lettore che guarda nel posto"
                                      " sbagliato. Difetto del controllo, non del"
                                      " servizio."})
                continue
            valore_letto = regola["valore_se_assente"]
            esito["nota"] = f"assente: {regola['perche']}"
        else:
            valore_letto = lettura["valore"]

        try:
            uguale = norma(valore_letto) == norma(chiesto)
        except (TypeError, ValueError) as errore:
            esiti.append({**esito, "esito": NON_LETTO, "letto": valore_letto,
                          "nota": f"valore illeggibile ({errore}): non lo giudico."})
            continue
        esiti.append({**esito, "esito": UGUALE if uguale else DIVERSO,
                      "letto": valore_letto})
    return esiti


def descrivi(servizio: str, progetto: str, regione: str) -> dict:
    """Lettura pura: `gcloud run services describe --format=json`."""
    comando = ["gcloud", "run", "services", "describe", servizio,
               f"--project={progetto}", f"--region={regione}", "--format=json"]
    fatto = subprocess.run(comando, capture_output=True, text=True, check=True)
    return json.loads(fatto.stdout)


def _stampa(esiti: list[dict]) -> None:
    for e in esiti:
        segno = {UGUALE: "=", DIVERSO: "!", NON_LETTO: "?"}[e["esito"]]
        print(f"  {segno} {e['campo']:<18} chiesto {e['chiesto']!s:<8}"
              f" letto {e['letto']!s:<8} {e['esito']}")
        if e.get("nota"):
            print(f"      {e['nota']}")
        if e.get("dove"):
            print(f"      letto da: {e['dove']}")


def main(argv=None) -> int:
    genitore = argparse.ArgumentParser(add_help=False)
    genitore.add_argument("--servizio", default="hotelops-hub")
    genitore.add_argument("--progetto", default="hotelops-suite")
    genitore.add_argument("--regione", default="europe-west1")

    radice = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sotto = radice.add_subparsers(dest="verbo", required=True)
    sotto.add_parser("leggi", parents=[genitore])

    c = sotto.add_parser("confronta", parents=[genitore])
    c.add_argument("--payload", help="file JSON di describe; '-' o assente = stdin"
                                     " se non si vuole chiamare gcloud")
    c.add_argument("--memoria")
    c.add_argument("--cpu")
    c.add_argument("--timeout")
    c.add_argument("--min-istanze", dest="min_istanze")
    c.add_argument("--affinita", help="si/no")
    c.add_argument("--modo", choices=["osserva", "pretendi"], default="osserva",
                   help="osserva (predefinito): stampa e non fa fallire niente."
                        " pretendi: esce 1 su 'diverso' e su 'non_letto'")

    a = radice.parse_args(argv)

    if a.verbo == "leggi":
        print(json.dumps(descrivi(a.servizio, a.progetto, a.regione), indent=2))
        return 0

    # Niente indovinelli su stdin: stdin si legge solo se e' stato chiesto con
    # `--payload -`. In CI stdin non e' un tty ed e' vuoto, quindi un lettore
    # che si regolasse su `isatty()` leggerebbe il vuoto invece di chiamare
    # gcloud, e fallirebbe parlando di JSON.
    if a.payload == "-":
        payload = json.load(sys.stdin)
    elif a.payload:
        with open(a.payload, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = descrivi(a.servizio, a.progetto, a.regione)

    attesa = {campo: valore for campo, valore in (
        ("memoria", a.memoria), ("cpu", a.cpu), ("timeout", a.timeout),
        ("min_istanze", a.min_istanze), ("affinita_sessione", a.affinita),
    ) if valore is not None}
    if not attesa:
        print("niente da confrontare: nessuna bandiera chiesta.", file=sys.stderr)
        return 2

    esiti = confronta(attesa, leggi_forma(payload))
    print(f"forma di {a.servizio} ({a.regione}), {len(esiti)} bandiere chieste:")
    _stampa(esiti)

    cattivi = [e for e in esiti if e["esito"] != UGUALE]
    if not cattivi:
        print("tutte le bandiere pinnate sono anche applicate.")
        return 0
    print(f"\n{len(cattivi)} bandiere non confermate: "
          + ", ".join(f"{e['campo']} ({e['esito']})" for e in cattivi))
    if a.modo == "osserva":
        print("modo 'osserva': non faccio fallire il rilascio. I percorsi JSON di"
              " questo lettore non sono ancora stati verificati su un payload vero,"
              " quindi un rosso qui potrebbe essere mio e non del servizio.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
