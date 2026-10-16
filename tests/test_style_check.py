"""Checks for src/style_check.py (and the shared rules in src/style_rules.py),
using the real moments in data/key_moments.json as the facts (through
narrator.moment_input, exactly what the model sees)."""

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
    ("m07", narration(  # goal; build_up duration word for word; counter_label; numbers_used may repeat anything
        "Niko Vane scores on the fastest counter",
        "Niko Vane's goal put London Blue 1-0 up in the 61st minute: London Blue won the ball back in midfield "
        "and scored 10 seconds later. It was the fastest of the match's two counter-attacks.",
        ["61st", "1-0", "10 seconds"])),
    ("m08", narration(  # save; "denied" allowed; "goalkeeper" must not trip the "keep" rule
        "Ellis Harwick saves Niko Vane's 10.0-metre shot",
        "Ellis Harwick denied Niko Vane from 10.0 metres in the 67th minute, with the goalkeeper's side 0-1 down. "
        "Kai Renwick had passed into a 0.1607 xT spot.")),
    ("m01", narration(  # "stopped" allowed; duration as in build_up
        "Bram Hollis saves Cass Dunmore's 8.0-metre shot",
        "London Red won the ball back in the attacking third and shot 7 seconds later, but Bram Hollis "
        "stopped Cass Dunmore from 8.0 metres.")),
    ("m04", narration(
        "Cass Dunmore misses from 6.4 metres",
        "Cass Dunmore missed from 6.4 metres in the 38th minute with the game 0-0. "
        "Luca Merriden's pass added 0.2906 xT to set up the chance.")),
    ("m09", narration(  # momentum shift: team named, minutes as ordinals, no duration
        "London Red take over from the 70th minute",
        "London Red were on top from the 70th minute to the 93rd minute, adding 1.2259 xT to London Blue's 0.0448.")),
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
    # outcome verbs outside the allowed list
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
    # durations outside build_up: "N-second move", "N-second possession", plain, number words, minutes
    ("m07", narration("Vane scores", "Niko Vane scored after a 10-second move."), {"10-second"}),
    ("m01", narration("Hollis saves", "Bram Hollis saved after a 7-second possession."), {"7-second"}),
    ("m10", narration("Tovey scores", "Rafael Tovey scored after 12 seconds."), {"12 seconds"}),
    ("m07", narration("Vane scores", "Niko Vane scored ten seconds after the ball was won."), {"ten seconds"}),
    ("m07", narration("Vane scores", "London Blue scored 10 seconds after winning it."), {"10 seconds"}),
    ("m09", narration("Red surge", "London Red led for 5 blocks of 5 minutes each."), {"5 minutes"}),
    ("m09", narration("Red surge", "London Red led across 5-minute blocks."), {"5-minute"}),
    # always name the team
    ("m09", narration("Red surge", "London Red took over. They added 1.2259 xT while the opponent managed 0.0448."),
     {"they", "the opponent"}),
    ("m02", narration("Red on top", "London Red added 1.0557 xT after their slow start."), {"their"}),
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
    text = "Niko Vane scored in the 61st minute to make it 1-0, from 12.7 metres, 0.1607 xT and a 0.1392 xT pass."
    assert check(narration("Vane scores", text), facts("m07")).passed  # 61, 1-0, 12.7, 0.1607, 0.1392 = 5


def test_quoting_build_up_is_allowed_even_with_carry_and_numbers():
    # m10's key action is a pass, but its build_up mentions a carry; quoting the phrase is fine,
    # and its numbers don't count towards the limit
    text = ("Rafael Tovey's goal levelled the match at 1-1 in the 74th minute: London Red won the ball back in the "
            "defensive third and scored 12 seconds later, after 3 passes and a carry from midfield into the "
            "attacking third, with Theo Brannick's pass adding 0.1007 xT from 10.7 metres at 0.1607 xT.")
    assert check(narration("Rafael Tovey levels it", text), facts("m10")).passed


def test_carry_outside_the_quote_still_fails():
    text = "Theo Brannick carried it forward before Rafael Tovey scored."
    assert {o["value"] for o in check(narration("Tovey scores", text), facts("m10")).offending} == {"carried"}


def test_converting_is_blocked():
    text = "Cass Dunmore scored, converting from 6.4 metres."
    assert {o["value"] for o in check(narration("Dunmore scores", text), facts("m11")).offending} == {"converting"}


def test_blocked_words_only_match_whole_words():
    # every alternative in a pattern is matched as a whole word, not just the first and last
    text = "London Red's widely upheld threat came from a 0.0801 xT spot."
    assert check(narration("Brannick passes", text), facts("m06")).passed
