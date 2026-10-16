"""Checks for src/polish_check.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from polish_check import check  # noqa: E402


def narration(headline, explanation):
    return {"headline": headline, "explanation": explanation, "numbers_used": ["0.1415"]}


PASS_CASES = [
    narration("Ellis Harwick saves Niko Vane's 10.0-metre shot",  # headlines need no full stop
              "Ellis Harwick saved Niko Vane's shot from 10.0 metres. Kai Renwick made the key pass."),
    narration("h", "Kai Renwick passed into a 0.1607 xT spot!"),
    narration("h", 'Ellis Harwick saved it: "denied."'),  # punctuation inside closing quotes
    narration("h", "Theo Brannick passed the ball to Cass Dunmore."),
]


@pytest.mark.parametrize("output", PASS_CASES)
def test_clean_text_passes(output):
    result = check(output)
    assert result.passed, result.offending


FAIL_CASES = [
    (narration("h", "London Red did it in the the 74th minute."), {"the the"}),
    (narration("h", "Ellis Harwick saved it. Saved saved."), {"Saved saved"}),
    (narration("h", "The move had won the ball back and shot 7 seconds later"),
     {"explanation: ...shot 7 seconds later"}),
    (narration("h", "Kai Renwick passed the key pass with xT 0.1415."), {"passed the key pass"}),
    (narration("h", "Cass Dunmore's near-range attempt was saved."), {"near-range"}),
    (narration("Near range miss", "Cass Dunmore missed."), {"Near range"}),
]


@pytest.mark.parametrize("output,expected", FAIL_CASES)
def test_slips_fail(output, expected):
    result = check(output)
    assert not result.passed
    assert {o["value"] for o in result.offending} == expected
