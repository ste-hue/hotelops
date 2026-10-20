"""L'inventario dei Cloud Run Job come oggetto di test.

Il difetto che questi controlli chiudono: il codice committato e il codice in
esecuzione possono divergere senza che niente lo segnali, e la ricevuta che il
repo promette può non esistere in `f_pipeline_runs` perché quel `PipelineRun`
non è nell'immagine distribuita. Qui si verifica la metà che si può verificare
offline — che l'inventario sia coerente col codice e col registry — su file
versionati, senza chiamare Google.

Perimetro: i Cloud Run Job dichiarati in `infra/jobs.yaml`. Le pipeline che non
girano su Cloud Run non vengono bloccate da qui.
"""

import os
from pathlib import Path

import pytest
import yaml

RADICE = Path(__file__).resolve().parents[1]
# Il percorso è sovrascrivibile: serve al rilascio e alle prove di mutazione,
# che devono poter dimostrare che questi controlli sanno diventare rossi.
PERCORSO = Path(os.environ.get("HOTELOPS_JOBS_INVENTORY", RADICE / "infra" / "jobs.yaml"))
INVENTARIO = yaml.safe_load(PERCORSO.read_text(encoding="utf-8"))
JOB = INVENTARIO["job"]
NOMI = [j["nome"] for j in JOB]

# Il codice Python del repo, una volta: i controlli sulle ricevute lo cercano.
SORGENTI = {
    p: p.read_text(encoding="utf-8")
    for p in RADICE.rglob("*.py")
    if "tests" not in p.parts and ".venv" not in p.parts and "scratchpad" not in p.parts
}


def ricevute_dichiarate():
    return {j["nome"]: j["ricevuta"] for j in JOB}


def test_ogni_job_e_descritto_per_intero():
    """Un campo assente non è verificabile: qui si pretende che ci sia."""
    assert NOMI, "inventario vuoto"
    assert len(NOMI) == len(set(NOMI)), "due job con lo stesso nome"
    for j in JOB:
        for campo in ("nome", "entrypoint", "moduli", "service_account", "scheduler", "provisioning"):
            assert j.get(campo), f"{j.get('nome')}: manca {campo}"
        assert "ricevuta" in j, f"{j['nome']}: `ricevuta` va dichiarata, anche se nulla"
        assert j["entrypoint"].get("command") and j["entrypoint"].get("args"), j["nome"]
        for chiave in ("nome", "schedule", "fuso"):
            assert j["scheduler"].get(chiave), f"{j['nome']}: scheduler senza {chiave}"


def test_lo_script_di_provisioning_esiste_e_nomina_quel_job():
    for j in JOB:
        percorso = RADICE / j["provisioning"]
        assert percorso.exists(), f"{j['nome']}: {j['provisioning']} non esiste"
        testo = percorso.read_text(encoding="utf-8")
        assert f"jobs create {j['nome']} " in testo, (
            f"{j['nome']}: {j['provisioning']} non crea un job con questo nome"
        )


def test_l_entrypoint_riferisce_moduli_che_esistono():
    """Un entrypoint che punta a un modulo inesistente è un job che fallisce
    al primo avvio, e lo si scopre dal cloud invece che qui."""
    for j in JOB:
        comando = " ".join([j["entrypoint"]["command"], *j["entrypoint"]["args"]])
        for modulo in j["moduli"]:
            assert f"-m {modulo}" in comando, f"{j['nome']}: {modulo} non è nell'entrypoint"
            atteso = RADICE / (modulo.replace(".", "/") + ".py")
            assert atteso.exists(), f"{j['nome']}: il modulo {modulo} non esiste ({atteso})"


def test_l_immagine_non_e_pinnata_nell_inventario():
    """Il riferimento immutabile si risolve al rilascio.

    Un tag scritto qui tornerebbe mobile, che è metà del difetto di partenza.
    """
    immagine = INVENTARIO["immagine"]
    assert ":" not in immagine.split("/")[-1], f"{immagine}: nessun tag nell'inventario"
    assert "@" not in immagine, f"{immagine}: nessun digest nell'inventario"
    for j in JOB:
        osservato = j.get("osservato", {})
        assert osservato.get("il"), f"{j['nome']}: l'osservazione va datata"


@pytest.mark.parametrize("nome,ricevuta", sorted(ricevute_dichiarate().items()))
def test_la_ricevuta_dichiarata_corrisponde_al_codice(nome, ricevuta):
    """Il controllo centrale, nei due versi.

    Se l'inventario dichiara una ricevuta, nel repo deve esserci il
    `PipelineRun` che la scrive. Se dichiara `null`, non deve esserci: così un
    null messo per distrazione viene fuori qui e non dopo mesi di silenzio.
    """
    if ricevuta is None:
        return  # il viceversa si verifica una volta sola, nel test seguente
    prefisso = ricevuta.split(":")[0] if ":" in ricevuta else ricevuta
    # Nome composto (`drive_fetch:<source>`): nel codice è una f-string, quindi
    # si cerca il prefisso; nome semplice: si cerca la stringa esatta.
    attesi = (
        [f'PipelineRun(\n            f"{prefisso}:', f'PipelineRun(f"{prefisso}:']
        if ":" in ricevuta
        else [f'PipelineRun("{ricevuta}"', f'PipelineRun(\n        "{ricevuta}"']
    )
    trovato = any(a in testo for testo in SORGENTI.values() for a in attesi)
    assert trovato, f"{nome}: dichiara la ricevuta «{ricevuta}» ma nessun PipelineRun la scrive"


def test_i_null_sono_davvero_senza_ricevuta():
    """Un `ricevuta: null` sbagliato è un buco silenzioso: va provato.

    Controllo nel verso opposto: i file dei moduli dichiarati nell'entrypoint
    non devono aprire un PipelineRun. Se qualcuno ne aggiunge uno e lascia il
    null, il test lo dice qui — invece di lasciare la ricevuta attesa a zero e
    la freschezza a indovinare.
    """
    for j in JOB:
        if j["ricevuta"] is not None:
            continue
        for modulo in j["moduli"]:
            percorso = RADICE / (modulo.replace(".", "/") + ".py")
            testo = percorso.read_text(encoding="utf-8") if percorso.exists() else ""
            assert "PipelineRun(" not in testo, (
                f"{j['nome']}: dichiara `ricevuta: null` ma {modulo} apre un PipelineRun"
            )


def registry_auto():
    percorso = RADICE / "core" / "source_registry.yaml"
    sorgenti = yaml.safe_load(percorso.read_text(encoding="utf-8"))["sources"]
    fuori = {}
    for nome, s in sorgenti.items():
        acq = s.get("acquisition") or {}
        if acq.get("mode") == "AUTO" and acq.get("job"):
            fuori.setdefault(acq["job"], []).append(nome)
    return fuori


def test_le_sorgenti_automatiche_servite_da_questi_job_combaciano():
    """Nel perimetro: le pipeline che NON girano su Cloud Run non sono bloccate.

    Si verifica che ciò che l'inventario e il registry dicono della stessa
    pipeline non si contraddica, e che nessun job del registry sia rivendicato
    da due job diversi.
    """
    auto = registry_auto()
    dichiarate = {r: n for n, r in ricevute_dichiarate().items() if r is not None}
    comuni = set(auto) & set(dichiarate)
    assert comuni, "nessuna sorgente automatica è servita da un job dell'inventario"
    # Il pilota del rilascio: le tre caselle PEC passano da qui.
    assert "pec_fetch" in comuni, "pec_fetch non è più il raccordo fra registry e inventario"
    assert sorted(auto["pec_fetch"]) == [
        "PEC_MAILBOX_INTUR_APPEND",
        "PEC_MAILBOX_ORTI_APPEND",
        "PEC_MAILBOX_VIGNA_APPEND",
    ]
    # Nessuna ambiguità: una pipeline, un job.
    rivendicazioni = [r for n, r in ricevute_dichiarate().items() if r is not None]
    assert len(rivendicazioni) == len(set(rivendicazioni)), (
        "due job dell'inventario dichiarano la stessa ricevuta"
    )
