"""La rilettura della forma di hotelops-hub, provata senza credenziali.

Il caso che conta è il nono: `minScale` assente vale **zero**, non
«sconosciuto», e un lettore che lo chiamasse `diverso` metterebbe un rosso falso
nell'unico percorso che pubblica. Gli altri test tengono ferme le due basi delle
quantità Kubernetes (2G ≠ 2Gi), i millicore, e la distinzione fra un campo che
non c'è perché vale il suo default e un campo che non c'è perché il lettore
guarda nel posto sbagliato.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.cloud.forma_servizio import (
    DIVERSO,
    NON_LETTO,
    UGUALE,
    confronta,
    leggi_forma,
    main,
    normalizza_cpu,
    normalizza_memoria,
)


def payload(memoria="2Gi", cpu="2", timeout=300, annotazioni=None,
            annotazioni_servizio=None, limiti=True):
    """Un `services describe --format=json` ridotto all'osso."""
    contenitore = {"image": "gcr.io/x/y"}
    if limiti:
        contenitore["resources"] = {"limits": {"memory": memoria, "cpu": cpu}}
    return {
        "metadata": {"name": "hotelops-hub",
                     "annotations": annotazioni_servizio or {}},
        "spec": {"template": {
            "metadata": {"annotations": annotazioni if annotazioni is not None else {}},
            "spec": {"containers": [contenitore], "timeoutSeconds": timeout},
        }},
    }


def esito_di(esiti, campo):
    return next(e for e in esiti if e["campo"] == campo)


# --- normalizzazione --------------------------------------------------------

@pytest.mark.parametrize("testo,atteso", [
    ("2Gi", 2 * 2**30),
    ("2048Mi", 2 * 2**30),
    ("2G", 2 * 10**9),
    ("512Mi", 512 * 2**20),
])
def test_la_memoria_ha_due_basi(testo, atteso):
    assert normalizza_memoria(testo) == atteso


def test_due_e_duegiga_non_sono_la_stessa_cosa():
    """2G (decimale) e 2Gi (binario) differiscono di ~147 MB: non si confondono."""
    assert normalizza_memoria("2G") != normalizza_memoria("2Gi")


@pytest.mark.parametrize("testo,atteso", [("2", 2000), ("2000m", 2000), ("1", 1000)])
def test_la_cpu_si_confronta_in_millicore(testo, atteso):
    assert normalizza_cpu(testo) == atteso


# --- i campi presenti -------------------------------------------------------

def test_le_bandiere_applicate_sono_uguali_anche_scritte_diversamente():
    esiti = confronta(
        {"memoria": "2Gi", "cpu": "2", "timeout": "300"},
        leggi_forma(payload(memoria="2048Mi", cpu="2000m", timeout=300)),
    )
    assert [e["esito"] for e in esiti] == [UGUALE, UGUALE, UGUALE]


def test_una_bandiera_non_applicata_e_diversa():
    esiti = confronta({"memoria": "2Gi"}, leggi_forma(payload(memoria="512Mi")))
    assert esito_di(esiti, "memoria")["esito"] == DIVERSO


def test_si_giudica_solo_cio_che_e_stato_chiesto():
    """Ciò che il rilascio non pinna non è materia di questo controllo."""
    esiti = confronta({"timeout": "300"}, leggi_forma(payload()))
    assert [e["campo"] for e in esiti] == ["timeout"]


# --- l'assenza che parla: minScale ------------------------------------------

def test_minscale_assente_vale_zero_non_sconosciuto():
    """Il caso per cui questo modulo esiste."""
    esiti = confronta({"min_istanze": "0"}, leggi_forma(payload(annotazioni={})))
    esito = esito_di(esiti, "min_istanze")
    assert esito["esito"] == UGUALE
    assert esito["letto"] == 0
    assert "assente" in esito["nota"]


def test_minscale_assente_contro_uno_chiesto_e_diverso():
    """L'equivalenza assente=0 non è un passa-tutto: se chiedo 1, 0 è diverso."""
    esiti = confronta({"min_istanze": "1"}, leggi_forma(payload(annotazioni={})))
    assert esito_di(esiti, "min_istanze")["esito"] == DIVERSO


def test_minscale_presente_si_confronta_come_numero():
    annotazioni = {"autoscaling.knative.dev/minScale": "1"}
    esiti = confronta({"min_istanze": "1"}, leggi_forma(payload(annotazioni=annotazioni)))
    assert esito_di(esiti, "min_istanze")["esito"] == UGUALE


def test_affinita_assente_vale_disattivata():
    esiti = confronta({"affinita_sessione": "si"}, leggi_forma(payload(annotazioni={})))
    esito = esito_di(esiti, "affinita_sessione")
    assert esito["esito"] == DIVERSO
    assert esito["letto"] is False


def test_affinita_attiva_e_uguale_a_si():
    annotazioni = {"run.googleapis.com/sessionAffinity": "true"}
    esiti = confronta({"affinita_sessione": "si"}, leggi_forma(payload(annotazioni=annotazioni)))
    assert esito_di(esiti, "affinita_sessione")["esito"] == UGUALE


def test_annotazione_trovata_sul_servizio_invece_che_sul_template():
    """Non so, senza un payload vero, su quale dei due livelli si annoti: cerco
    in entrambi e dico dove l'ho trovata."""
    esiti = confronta(
        {"affinita_sessione": "si"},
        leggi_forma(payload(annotazioni={},
                            annotazioni_servizio={"run.googleapis.com/sessionAffinity": "true"})),
    )
    esito = esito_di(esiti, "affinita_sessione")
    assert esito["esito"] == UGUALE
    assert esito["dove"] == "metadata.annotations.run.googleapis.com/sessionAffinity"


# --- l'assenza muta: un difetto del lettore, non del servizio ---------------

def test_memoria_introvabile_e_non_letto_non_diverso():
    """Se il percorso è sbagliato il controllo lo dice di sé, non del servizio."""
    esiti = confronta({"memoria": "2Gi"}, leggi_forma(payload(limiti=False)))
    esito = esito_di(esiti, "memoria")
    assert esito["esito"] == NON_LETTO
    assert esito["esito"] != DIVERSO
    assert "lettore" in esito["nota"]


def test_valore_illeggibile_non_viene_giudicato():
    esiti = confronta({"timeout": "300"}, leggi_forma(payload(timeout="trecento")))
    assert esito_di(esiti, "timeout")["esito"] == NON_LETTO


# --- i due modi -------------------------------------------------------------

def _scrivi(tmp_path, dati):
    percorso = tmp_path / "describe.json"
    percorso.write_text(json.dumps(dati), encoding="utf-8")
    return str(percorso)


def test_modo_osserva_non_fa_fallire_un_rilascio(tmp_path, capsys):
    """Finché i percorsi non sono verificati su un payload vero, un rosso qui
    potrebbe essere del lettore: non blocca."""
    uscita = main(["confronta", "--payload", _scrivi(tmp_path, payload(memoria="512Mi")),
                   "--memoria", "2Gi", "--modo", "osserva"])
    assert uscita == 0
    assert "non confermate" in capsys.readouterr().out


def test_modo_pretendi_blocca(tmp_path):
    uscita = main(["confronta", "--payload", _scrivi(tmp_path, payload(memoria="512Mi")),
                   "--memoria", "2Gi", "--modo", "pretendi"])
    assert uscita == 1


def test_modo_pretendi_passa_sulle_cinque_bandiere_del_rilascio(tmp_path):
    """La forma che `deploy-hub.yml` chiede oggi, riletta: deve passare."""
    dati = payload(memoria="2Gi", cpu="2", timeout=300,
                   annotazioni={"run.googleapis.com/sessionAffinity": "true"})
    uscita = main(["confronta", "--payload", _scrivi(tmp_path, dati),
                   "--memoria", "2Gi", "--cpu", "2", "--timeout", "300",
                   "--min-istanze", "0", "--affinita", "si", "--modo", "pretendi"])
    assert uscita == 0


def test_senza_payload_si_chiede_a_gcloud_non_a_stdin(monkeypatch, capsys):
    """In CI stdin non è un tty ed è vuoto: un lettore che si regolasse su
    `isatty()` leggerebbe il vuoto e fallirebbe parlando di JSON."""
    chiamate = []

    def finto_describe(servizio, progetto, regione):
        chiamate.append((servizio, progetto, regione))
        return payload()

    monkeypatch.setattr("scripts.cloud.forma_servizio.descrivi", finto_describe)
    monkeypatch.setattr("sys.stdin", None)  # toccarlo sarebbe un errore

    assert main(["confronta", "--timeout", "300", "--modo", "pretendi"]) == 0
    assert chiamate == [("hotelops-hub", "hotelops-suite", "europe-west1")]


# --- il workflow stesso, eseguito con un gcloud finto -----------------------
#
# I due passi di `deploy-hub.yml` leggono le stesse variabili di job: se un
# giorno divergessero, il controllo confronterebbe la propria copia e non
# verificherebbe più niente senza dirlo. Qui i blocchi bash dei due passi
# vengono ESEGUITI davvero, con `gcloud` sostituito da uno specchio, quindi un
# errore di battitura in un percorso che non posso provare in altro modo cade
# qui e non su un rilascio.

RADICE = Path(__file__).resolve().parents[1]
WORKFLOW = RADICE / ".github" / "workflows" / "deploy-hub.yml"


def _lavoro_deploy():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["deploy"]


def _passo(nome_che_inizia_con):
    for passo in _lavoro_deploy()["steps"]:
        if (passo.get("name") or "").startswith(nome_che_inizia_con):
            return passo
    raise AssertionError(f"passo non trovato: {nome_che_inizia_con}")


def _finto_gcloud(tmp_path, stampa=""):
    cestino = tmp_path / "bin"
    cestino.mkdir(exist_ok=True)
    finto = cestino / "gcloud"
    finto.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/argv"\n'
        f"cat <<'FINE'\n{stampa}\nFINE\n",
        encoding="utf-8",
    )
    finto.chmod(0o755)
    return cestino


def _esegui(run, cestino, extra=None):
    ambiente = {**os.environ, "PATH": f"{cestino}:{os.environ['PATH']}",
                "GITHUB_SHA": "0" * 40, **_lavoro_deploy()["env"], **(extra or {})}
    # check=False deliberato: il codice d'uscita del passo E' il soggetto del
    # test, non un incidente da far scoppiare qui.
    return subprocess.run(["bash", "-c", run], cwd=RADICE, env=ambiente,
                          capture_output=True, text=True, check=False)


def test_il_passo_di_rilascio_passa_davvero_le_cinque_bandiere(tmp_path):
    cestino = _finto_gcloud(tmp_path)
    fatto = _esegui(_passo("Deploy hotelops-hub")["run"], cestino)
    assert fatto.returncode == 0, fatto.stderr
    argv = (tmp_path / "argv").read_text(encoding="utf-8").splitlines()
    env = _lavoro_deploy()["env"]
    assert f"--memory={env['HUB_MEMORIA']}" in argv
    assert f"--cpu={env['HUB_CPU']}" in argv
    assert f"--timeout={env['HUB_TIMEOUT']}" in argv
    assert f"--min-instances={env['HUB_MIN_ISTANZE']}" in argv
    assert "--session-affinity" in argv


def test_affinita_no_diventa_la_bandiera_negativa_non_un_silenzio():
    """`--no-session-affinity` dichiara una scelta; l'omissione dichiarerebbe
    un'eredità dalla revisione precedente."""
    with tempfile.TemporaryDirectory() as grezzo:
        tmp_path = Path(grezzo)
        cestino = _finto_gcloud(tmp_path)
        fatto = _esegui(_passo("Deploy hotelops-hub")["run"], cestino,
                        extra={"HUB_AFFINITA": "no"})
        assert fatto.returncode == 0, fatto.stderr
        argv = (tmp_path / "argv").read_text(encoding="utf-8").splitlines()
        assert "--no-session-affinity" in argv
        assert "--session-affinity" not in argv


def test_il_passo_di_rilettura_gira_e_conferma_la_forma_chiesta(tmp_path):
    """Il passo intero, con un `describe` finto che risponde la forma chiesta."""
    env = _lavoro_deploy()["env"]
    annotazioni = {"run.googleapis.com/sessionAffinity": "true"} if env["HUB_AFFINITA"] == "si" else {}
    if env["HUB_MIN_ISTANZE"] != "0":
        annotazioni["autoscaling.knative.dev/minScale"] = env["HUB_MIN_ISTANZE"]
    finto = payload(memoria=env["HUB_MEMORIA"], cpu=env["HUB_CPU"],
                    timeout=int(env["HUB_TIMEOUT"]), annotazioni=annotazioni)
    cestino = _finto_gcloud(tmp_path, stampa=json.dumps(finto))

    fatto = _esegui(_passo("Rileggi la forma applicata")["run"], cestino)
    assert fatto.returncode == 0, fatto.stderr + fatto.stdout
    assert "tutte le bandiere pinnate sono anche applicate" in fatto.stdout


def test_il_passo_di_rilettura_dice_quando_la_forma_non_torna(tmp_path):
    """Con una memoria diversa il passo lo stampa, e in modo `osserva` non
    blocca: finché i percorsi non sono verificati, un rosso potrebbe essere suo."""
    finto = payload(memoria="512Mi")
    cestino = _finto_gcloud(tmp_path, stampa=json.dumps(finto))
    fatto = _esegui(_passo("Rileggi la forma applicata")["run"], cestino)
    assert fatto.returncode == 0, fatto.stderr
    assert "non confermate" in fatto.stdout
    assert "memoria (diverso)" in fatto.stdout
