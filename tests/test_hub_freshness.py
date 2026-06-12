"""Hub — semaforo freshness."""

from verticals.hub.freshness import semaforo


def test_semaforo_verde_entro_soglia():
    assert semaforo(0) == "🟢"
    assert semaforo(3) == "🟢"


def test_semaforo_giallo_tra_soglie():
    assert semaforo(4) == "🟡"
    assert semaforo(7) == "🟡"


def test_semaforo_rosso_oltre_o_ignoto():
    assert semaforo(8) == "🔴"
    assert semaforo(None) == "🔴"


def test_semaforo_soglie_custom():
    assert semaforo(10, soglia_attenzione=15, soglia_allarme=30) == "🟢"
