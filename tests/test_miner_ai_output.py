import json
from types import SimpleNamespace

import pytest

from workspace.miners.classify_attachments import stage2_batch
from workspace.miners.triage_capex import parse_response


def attachment_result(**fields):
    return {
        "category": "PREVENTIVO",
        "fornitore": "Synthetic supplier",
        "importo_eur": 123.45,
        "confidence": "HIGH",
        "reasoning": "Synthetic quote",
        **fields,
    }


def fake_client(raw):
    return SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                content=[SimpleNamespace(text=raw)]
            ),
        )
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"category": "INVENTED"},
        {"category": []},
        {"confidence": "APPROVED"},
        {"fornitore": {}},
        {"reasoning": []},
        {"importo_eur": True},
        {"importo_eur": "123.45"},
        {"importo_eur": float("nan")},
        {"importo_eur": float("inf")},
        {"importo_eur": 10**400},
    ],
)
def test_attachment_contract_rejects_invalid_fields(fields):
    output = stage2_batch(
        fake_client(json.dumps([attachment_result(**fields)])), [("test.pdf", "text")]
    )
    assert output[0]["category"] == "ALTRO"
    assert output[0]["importo_eur"] is None
    assert output[0]["confidence"] == "LOW"


def test_attachment_preserves_valid_amount_as_a_proposal():
    output = stage2_batch(
        fake_client(json.dumps([attachment_result()])), [("test.pdf", "text")]
    )
    assert output == [attachment_result()]


def test_attachment_missing_result_does_not_shift_amount_to_another_document():
    output = stage2_batch(
        fake_client(json.dumps([attachment_result()])),
        [("first.pdf", "one"), ("second.pdf", "two")],
    )
    assert all(r["importo_eur"] is None and r["confidence"] == "LOW" for r in output)
    output[0]["category"] = "FATTURA"
    assert output[1]["category"] == "ALTRO"


def triage_result(**fields):
    return {
        "f_code": "GENERIC_PROJECT",
        "subfolder": "04_comunicazioni",
        "confidence": "HIGH",
        "reasoning": "Synthetic project",
        **fields,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"f_code": "UNKNOWN"},
        {"f_code": []},
        {"subfolder": "../../outside"},
        {"confidence": "APPROVED"},
        {"reasoning": []},
    ],
)
def test_invalid_triage_cannot_produce_a_high_confidence_route(fields):
    result = parse_response(json.dumps([triage_result(**fields)]), 1)
    assert result[0]["f_code"] == "NOISE"
    assert result[0]["confidence"] == "LOW"


def test_triage_extra_or_missing_results_are_unaligned():
    for items in [[triage_result()], [triage_result()] * 3]:
        result = parse_response(json.dumps(items), 2)
        assert all(r["f_code"] == "NOISE" and r["confidence"] == "LOW" for r in result)


def test_invalid_triage_item_keeps_later_result_in_its_slot():
    result = parse_response(json.dumps([None, triage_result()]), 2)
    assert result[0]["f_code"] == "NOISE"
    assert result[1] == triage_result()
