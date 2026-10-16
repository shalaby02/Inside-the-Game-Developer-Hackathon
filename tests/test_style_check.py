"""Checks for src/style_check.py, using the real moments in data/key_moments.json
as the facts (through narrator.moment_input, exactly what the model sees)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from narrator import moment_input  # noqa: E402
from style_check import check  # noqa: E402

MOMENTS = {m["id"]: m for m in json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]}


def facts(moment_id):
    return moment_input(MOMENTS[moment_id])


def narration(headline, explanation, numbers_used=()):
    return {"headline": headline, "explanation": explanation, "numbers_used": list(numbers_used)}


# ------------------------------------------------------------- must pass

PASS_CASES = [
    ("m07", narration(  # goal; "fastest" is backed by counter_rank; numbers_used may repeat anything
        "Niko Vane scores on the fastest counter",
        "Niko Vane scored in the 61st minute to put London Blue 1-0 up at the end of a 10-second counter. "
        "Dario Quill passed into a spot worth 0.1607 xT, and his pass added 0.1392 xT.",
        ["61st", "1-0", "10 seconds", "0.1607", "0.1392"])),
    ("m08", narration(  # save; "goalkeeper" must not trip the "keep" rule
        "Ellis Harwick saves from Niko Vane",
        "Ellis Harwick saved Niko Vane's shot from 10.0 metres in the 67th minute, with the goalkeeper's side 0-1 down. "
        "Kai Renwick had passed into a 0.1607 xT spot after a 13-second move.")),
    ("m04", narration(
        "Cass Dunmore misses from 6.4 metres",
        "Cass Dunmore missed from 6.4 metres in the 38th minute with the game 0-0. "
        "Luca Merriden's pass added 0.2906 xT to set up the chance.")),
    ("m09", narration(  # momentum shift: "5-minute blocks" is the allowed duration form
        "London Red take over from the 70th minute",
        "From the 70th minute London Red were on top for 5 straight 5-minute blocks, adding 1.2259 xT "
        "to London Blue's 0.0448.")),
    ("m05", narration(  # swing whose action_type is pass
        "Idris Stanbury's pass lifts London Red",
        "Idris Stanbury passed from a 0.0046 xT spot into a 0.0801 xT spot, adding 0.0755 xT in the 40th minute.")),
]


@pytest.mark.parametrize("moment_id,output", PASS_CASES)
def test_clean_narration_passes(moment_id, output):
    result = check(output, facts(moment_id))
    assert result.passed, result.offending


def test_carry_words_pass_when_action_type_is_carry():
    f = facts("m05")
    f["facts"]["action_type"] = "carry"
    assert check(narration("Stanbury carries it forward", "Idris Stanbury carried the ball, adding 0.0755 xT."), f).passed


# ------------------------------------------------------------- must fail

FAIL_CASES = [
    # how a save looked
    ("m08", narration("Harwick saves", "Ellis Harwick pushed away Niko Vane's shot."), {"pushed away"}),
    ("m01", narration("Hollis saves", "Bram Hollis turned away Cass Dunmore's shot with a diving stop."),
     {"turned away", "diving"}),
    ("m08", narration("Harwick smothers it", "Ellis Harwick smothered the low attempt."),
     {"smothers", "smothered", "low attempt"}),
    # how a shot looked
    ("m04", narration("Dunmore misses", "Cass Dunmore volleyed wide from 6.4 metres."), {"volleyed", "wide"}),
    # outcome verbs outside the allowed five
    ("m11", narration("Dunmore fires home", "Cass Dunmore netted from 6.4 metres."), {"fires", "netted"}),
    # unsupported claims about the score and the rest of the match
    ("m08", narration("Harwick saves", "Ellis Harwick saved it to keep the score at 0-1."), {"keep"}),
    ("m09", narration("Red surge", "London Red were on top, overturning the match from 0-1."), {"overturning"}),
    ("m11", narration("Dunmore's late winner", "Cass Dunmore scored the decisive goal."), {"winner", "decisive"}),
    ("m05", narration("Stanbury pass", "It was the clearest threat at that point."), {"clearest", "at that point"}),
    # position worked out from coordinates
    ("m11", narration("Dunmore scores", "Cass Dunmore scored from a dangerously central spot."), {"central"}),
    # "carry" when action_type is pass (m06 is a pass)
    ("m06", narration("Brannick's carry", "Theo Brannick carried the ball into a 0.0801 xT spot."),
     {"carry", "carried"}),
    # a pass or momentum shift called a chance
    ("m06", narration("Brannick passes", "Theo Brannick passed and gave London Red a clear chance."), {"chance"}),
    ("m02", narration("Red on top", "London Red created opportunities for 6 blocks."), {"opportunities"}),
    # durations not hyphenated
    ("m07", narration("Vane scores", "Niko Vane scored after a 10 seconds move."), {"10 seconds"}),
    ("m09", narration("Red surge", "London Red led for 5 blocks of 5 minutes each."), {"5 minutes"}),
    # field names
    ("m08", narration("Harwick saves", "The shot_zone_value was 0.1607."), {"shot_zone_value"}),
]


@pytest.mark.parametrize("moment_id,output,expected", FAIL_CASES)
def test_blocked_wording_fails(moment_id, output, expected):
    result = check(output, facts(moment_id))
    assert not result.passed
    assert {o["value"].lower() for o in result.offending} == expected


def test_too_many_numbers_fails():
    text = ("From the 70th to the 93rd minute London Red added 1.2259 xT to 0.0448, "
            "with Theo Brannick adding 0.6178 after 2 blocks behind at 0.4126.")
    result = check(narration("Red surge", text), facts("m09"))
    assert [o["value"] for o in result.offending] == ["explanation: 7 numbers"]


def test_score_counts_as_one_number():
    text = "Niko Vane scored in the 61st minute to make it 1-0 after a 10-second move, from 12.7 metres and 0.1607 xT."
    assert check(narration("Vane scores", text), facts("m07")).passed  # 61, 1-0, 10, 12.7, 0.1607 = 5
