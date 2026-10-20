"""Il piano di rilascio sulle sue classi di guasto, con un cloud finto.

Nessuna chiamata a Google, nessun job eseguito, nessun digest reale: lo stato
del cloud è iniettato. Qui si verifica la cosa che è facile sbagliare — che
«tornare all'ultimo eseguito» non venga confuso con «tornare alla
configurazione precedente», perché non sono la stessa cosa.
"""

import pytest

from scripts.cloud.rilascio_jobs import carica_inventario, piano, verifica

IMMAGINE = "europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs"
NUOVO = "sha256:" + "a" * 64
VECCHIO = "sha256:" + "b" * 64
TERZO = "sha256:" + "c" * 64
INVENTARIO = carica_inventario()


class CloudFinto:
    """Stato del cloud come dati. Solo letture, come l'originale."""

    def __init__(self, configurata=None, esecuzione=None, digesti=None, righe=None):
        self._configurata = configurata or {}
        self._esecuzione = esecuzione or {}
        self._digesti = digesti or {}
        self._righe = righe if righe is not None else []
        self.ricevute_chieste = []

    def immagine_configurata(self, job):
        if job not in self._configurata:
            raise RuntimeError(f"{job}: non esiste")
        return self._configurata[job]

    def ultima_esecuzione(self, job):
        return self._esecuzione.get(job)

    def digest(self, riferimento):
        return self._digesti.get(riferimento)

    def ricevute(self, pipeline_name, da, a):
        self.ricevute_chieste.append((pipeline_name, da, a))
        return self._righe


def esecuzione(nome, digest, fine="2026-10-20T02:01:00Z", riuscite=1, fallite=0):
    return {
        "nome": nome, "immagine": f"{IMMAGINE}@{digest}",
        "inizio": "2026-10-20T02:00:00Z", "fine": fine,
        "riuscite": riuscite, "fallite": fallite,
    }


def cloud_in_ordine(**extra):
    """Caso sano: il job è configurato su un tag che risolve a VECCHIO, e
    l'ultima esecuzione ha girato proprio quel digest."""
    base = dict(
        configurata={"pec-fetch": f"{IMMAGINE}:v5"},
        esecuzione={"pec-fetch": esecuzione("pec-fetch-k4cpd", VECCHIO)},
        digesti={f"{IMMAGINE}:v5": VECCHIO, f"{IMMAGINE}:nuovo": NUOVO},
    )
    base.update(extra)
    return CloudFinto(**base)


def fai_piano(cloud, scelti=("pec-fetch",), tag="nuovo"):
    return piano(cloud, INVENTARIO, list(scelti), f"{IMMAGINE}:{tag}", "commit-di-prova")


def test_il_piano_del_pilota_tiene_distinti_i_tre_stati():
    p = fai_piano(cloud_in_ordine())
    assert p["rifiuti"] == []
    assert p["digest_destinazione"] == NUOVO
    assert [j["nome"] for j in p["job"]] == ["pec-fetch"]
    j = p["job"][0]
    assert j["immagine_configurata"] == f"{IMMAGINE}:v5"
    assert j["digest_configurato"] == VECCHIO
    assert j["digest_osservato"] == VECCHIO
    # Lo stato che il ritorno ripristina è la configurazione attuale risolta,
    # non «l'ultimo che ha girato»: qui coincidono, ed è per questo che vale.
    # E comprende il repository, non solo il digest.
    assert j["repository_configurato"] == IMMAGINE
    assert j["ripristina_stato"] == f"{IMMAGINE}@{VECCHIO}"
    assert f"--image={IMMAGINE}@{NUOVO}" in j["aggiorna"]
    assert f"--image={IMMAGINE}@{VECCHIO}" in j["torna_indietro"]
    assert j["ricevuta_attesa"] == "pec_fetch"


def test_job_aggiornato_e_mai_eseguito_dopo_l_update_ferma_il_piano():
    """La fixture che conta.

    Il job è stato aggiornato a una configurazione nuova e da allora non è più
    partito: l'ultima esecuzione disponibile ha girato il digest di PRIMA.
    Proporre quel digest come ritorno sarebbe proporre un terzo stato, non un
    ripristino. Il percorso automatico si ferma e dichiara la divergenza.
    """
    cloud = cloud_in_ordine(
        configurata={"pec-fetch": f"{IMMAGINE}:v7"},
        digesti={f"{IMMAGINE}:v7": TERZO, f"{IMMAGINE}:nuovo": NUOVO},
        esecuzione={"pec-fetch": esecuzione("pec-fetch-vecchia", VECCHIO)},
    )
    p = fai_piano(cloud)
    assert p["job"] == [], "ha proposto un ritorno su una divergenza"
    assert len(p["rifiuti"]) == 1
    rifiuto = p["rifiuti"][0]
    assert "DIVERGENZA" in rifiuto
    assert TERZO in rifiuto and VECCHIO in rifiuto, "la divergenza va dichiarata con i due digest"
    assert "pec-fetch-vecchia" in rifiuto
    assert "NON riporterebbe" in rifiuto


def test_tag_spostato_sotto_i_piedi_e_la_stessa_divergenza():
    """Stesso tag configurato, ma nel frattempo il tag punta altrove: ciò che
    ha girato non è ciò che girerebbe adesso."""
    cloud = cloud_in_ordine(digesti={f"{IMMAGINE}:v5": TERZO, f"{IMMAGINE}:nuovo": NUOVO})
    p = fai_piano(cloud)
    assert p["job"] == []
    assert "DIVERGENZA" in p["rifiuti"][0]


def test_immagine_gia_pinnata_per_digest_non_ha_niente_da_risolvere():
    cloud = cloud_in_ordine(
        configurata={"pec-fetch": f"{IMMAGINE}@{VECCHIO}"},
        digesti={f"{IMMAGINE}:nuovo": NUOVO},  # nessun tag da risolvere
    )
    p = fai_piano(cloud)
    assert p["rifiuti"] == []
    assert p["job"][0]["digest_configurato"] == VECCHIO


def test_nessuna_esecuzione_osservata_non_diventa_un_ritorno_inventato():
    cloud = cloud_in_ordine(esecuzione={})
    p = fai_piano(cloud)
    assert p["job"] == []
    assert "nessuna esecuzione osservata" in p["rifiuti"][0]
    assert "decidere a mano" in p["rifiuti"][0]


def test_configurazione_non_risolvibile_ferma_il_piano():
    cloud = cloud_in_ordine(digesti={f"{IMMAGINE}:nuovo": NUOVO})  # :v5 non risolve
    cloud._esecuzione = {}
    p = fai_piano(cloud)
    assert p["job"] == []
    assert "non si risolve in un digest" in p["rifiuti"][0]


def test_la_destinazione_va_risolta_prima_di_comparire_nei_comandi():
    cloud = cloud_in_ordine(digesti={f"{IMMAGINE}:v5": VECCHIO})  # il tag nuovo non esiste
    p = fai_piano(cloud)
    assert p["digest_destinazione"] is None
    assert p["job"] == []
    assert "non esiste in Artifact Registry" in p["rifiuti"][0]


def test_nessun_job_chiesto_non_aggiorna_niente():
    p = fai_piano(cloud_in_ordine(), scelti=())
    assert p["job"] == []
    assert "sceglie i job uno per uno" in p["rifiuti"][0]


def test_un_job_fuori_inventario_non_si_rilascia():
    cloud = cloud_in_ordine(configurata={"job-ignoto": f"{IMMAGINE}:v5"})
    p = fai_piano(cloud, scelti=("job-ignoto",))
    assert p["job"] == []
    assert "non è nell'inventario" in p["rifiuti"][0]


def test_il_piano_dichiara_sempre_il_limite_della_correlazione():
    assert "plausibile e non certa" in fai_piano(cloud_in_ordine())["limite"]


# ── Verifica ────────────────────────────────────────────────────────────────


def stati(esito):
    return [s for s, _ in esito["esiti"]]


def fai_verifica(cloud, nome="pec-fetch", digest=NUOVO):
    return verifica(cloud, INVENTARIO, nome, digest)


def test_verifica_digest_diverso_si_ferma_prima_di_cercare_la_ricevuta():
    cloud = cloud_in_ordine(esecuzione={"pec-fetch": esecuzione("pec-fetch-x", VECCHIO)})
    esito = fai_verifica(cloud)
    assert stati(esito) == ["DIVERSO"]
    assert cloud.ricevute_chieste == [], "ha cercato la ricevuta su un digest sbagliato"


@pytest.mark.parametrize(
    "caso,righe,atteso",
    [
        ("una riga nella finestra", [{"status": "OK"}], "PLAUSIBILE"),
        ("nessuna riga", [], "MANCA"),
        ("due righe nella finestra", [{"status": "OK"}, {"status": "FAIL"}], "AMBIGUO"),
    ],
)
def test_verifica_della_ricevuta_distingue_i_tre_esiti(caso, righe, atteso):
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-nuova", NUOVO)}, righe=righe
    )
    esito = fai_verifica(cloud)
    # «NOTA» chiude la lista perché pec-fetch ha un entrypoint a due fasi.
    assert stati(esito) == ["OK", atteso, "NOTA"], caso
    assert cloud.ricevute_chieste == [("pec_fetch", "2026-10-20T02:00:00Z", "2026-10-20T02:01:00Z")]
    if atteso == "MANCA":
        # Non deve concludere la causa: writer assente e permesso negato
        # producono lo stesso silenzio.
        messaggio = esito["esiti"][1][1]
        assert "best-effort" in messaggio and "non li distingue" in messaggio


def test_un_job_senza_ricevuta_non_viene_dichiarato_guasto():
    cloud = CloudFinto(
        configurata={"canone-push": f"{IMMAGINE}:v7"},
        esecuzione={"canone-push": esecuzione("canone-push-1", NUOVO)},
        digesti={},
    )
    esito = verifica(cloud, INVENTARIO, "canone-push", NUOVO)
    assert stati(esito) == ["OK", "ATTESO"]
    assert cloud.ricevute_chieste == []


def test_esecuzione_non_conclusa_resta_ignota():
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-in-corso", NUOVO, fine="")}
    )
    esito = fai_verifica(cloud)
    assert stati(esito) == ["OK", "IGNOTO"]
    assert cloud.ricevute_chieste == []


def test_il_ritorno_conserva_il_repository_da_cui_il_job_pescava():
    """Appendere il digest al repository di DESTINAZIONE sarebbe un terzo stato
    anche con il digest giusto: il job tornerebbe a un'altra provenienza."""
    altro = "europe-west1-docker.pkg.dev/hotelops-suite/legacy/jobs"
    cloud = cloud_in_ordine(
        configurata={"pec-fetch": f"{altro}:v5"},
        digesti={f"{altro}:v5": VECCHIO, f"{IMMAGINE}:nuovo": NUOVO},
    )
    p = fai_piano(cloud)
    assert p["rifiuti"] == []
    j = p["job"][0]
    assert j["repository_configurato"] == altro
    assert f"--image={altro}@{VECCHIO}" in j["torna_indietro"]
    # L'aggiornamento va comunque al repository dell'inventario: è lì che la
    # nuova immagine è stata costruita.
    assert f"--image={IMMAGINE}@{NUOVO}" in j["aggiorna"]


def test_l_esecuzione_fallita_non_passa_per_buona():
    """Digest giusto e ricevuta presente non dicono che il lavoro sia andato
    bene: l'esito dell'esecuzione è un'affermazione a parte."""
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-ko", NUOVO, riuscite=0, fallite=1)},
        righe=[{"status": "FAIL"}],
    )
    esito = fai_verifica(cloud)
    assert "ESECUZIONE_FALLITA" in stati(esito)
    assert "CORRELATA_NON_RIUSCITA" in stati(esito)


def test_una_ricevuta_fallita_non_e_un_successo():
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-x", NUOVO)}, righe=[{"status": "FAIL"}]
    )
    esito = fai_verifica(cloud)
    assert stati(esito) == ["OK", "CORRELATA_NON_RIUSCITA", "NOTA"]
    assert "la ricevuta c'è, il lavoro no" in esito["esiti"][1][1]


def test_esecuzione_senza_esito_leggibile_resta_ignota():
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-?", NUOVO, riuscite=0, fallite=0)},
        righe=[{"status": "OK"}],
    )
    assert "ESECUZIONE_IGNOTA" in stati(fai_verifica(cloud))


def test_la_nota_dice_che_la_ricevuta_copre_solo_la_prima_fase():
    """pec-fetch è `fetch && classify`: pec_fetch attesta il fetch, non il
    classify che lo segue."""
    cloud = cloud_in_ordine(
        esecuzione={"pec-fetch": esecuzione("pec-fetch-ok", NUOVO)}, righe=[{"status": "OK"}]
    )
    nota = [m for s, m in fai_verifica(cloud)["esiti"] if s == "NOTA"]
    assert nota and "attesta solo la prima" in nota[0]
    assert "classify" in nota[0] or "pec_fetch" in nota[0]


def test_un_job_a_una_sola_fase_non_porta_la_nota():
    cloud = CloudFinto(
        configurata={"coperti": f"{IMMAGINE}:v5"},
        esecuzione={"coperti": esecuzione("coperti-1", NUOVO)},
        digesti={}, righe=[{"status": "OK"}],
    )
    assert stati(verifica(cloud, INVENTARIO, "coperti", NUOVO)) == ["OK", "PLAUSIBILE"]
