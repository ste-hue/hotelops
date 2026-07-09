import pytest

from workspace.miners.dossier_official import order_summary


def test_order_summary_costs():
    orders, total = order_summary(["visura", "soci"])
    assert [o["order_id"] for o in orders] == ["visura", "soci"]
    assert total == pytest.approx(5.90 + 2.30)


def test_order_summary_rejects_unknown():
    with pytest.raises(KeyError):
        order_summary(["visura", "ubo"])
