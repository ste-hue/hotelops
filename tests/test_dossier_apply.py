from workspace.miners.dossier_apply import plan_apply


def test_plan_apply_filters_ledger_and_applies_threshold():
    items = [
        {"key": "drive:a", "category": "01_Societario", "confidence": 0.9},
        {"key": "drive:b", "category": "02_Fiscale", "confidence": 0.3},
        {"key": "drive:c", "category": "03_Bilanci", "confidence": 0.8},
    ]
    plan = plan_apply(items, ledger_keys={"drive:c"}, threshold=0.6)
    assert [p["key"] for p in plan] == ["drive:a", "drive:b"]
    assert plan[0]["target_category"] == "01_Societario"
    assert plan[1]["target_category"] == "_DaRivedere"
