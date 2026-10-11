import json

import pytest

from core.ai_output import parse_json_batch


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        "{}",
        '[{"category": "A"}]',
        '[{"category": "A"}, {"category": "B"}, {"category": "C"}]',
        '[{"amount": NaN}, {}]',
        '[{"amount": Infinity}, {}]',
    ],
)
def test_invalid_or_unaligned_batch_is_not_assigned_to_sources(raw):
    assert parse_json_batch(raw, 2) == [None, None]


def test_bad_item_preserves_later_item_position():
    assert parse_json_batch('[{}, null, {"category": "C"}]', 3) == [
        {},
        None,
        {"category": "C"},
    ]


def test_fences_and_brackets_inside_strings_are_supported():
    rows = [{"reason": "a [bracket] and a } brace"}, {"reason": "second"}]
    assert parse_json_batch("```json\n" + json.dumps(rows) + "\n```", 2) == rows
