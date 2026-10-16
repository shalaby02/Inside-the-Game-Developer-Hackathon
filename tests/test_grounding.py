"""Checks for src/grounding.py, using the real moments in data/key_moments.json
as the facts (through narrator.moment_input, exactly what the model sees)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from grounding import check  # noqa: E402
from narrator import moment_input  # noqa: E402

MOMENTS = {m["id"]: m for m in json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]}


def facts(moment_id):
    return moment_input(MOMENTS[moment_id])


def narration(headline, explanation, numbers_used=()):
    return {"headline": headline, "explanation": explanation, "numbers_used": list(numbers_used)}


# ------------------------------------------------------------- must pass

PASS_CASES = [
    ("m07", narration(
        "Niko Vane punishes London Red on the break",
        "Niko Vane finished in the 61st minute to put London Blue 1-0 up. "
        "London Blue won the ball back in midfield and scored 10 seconds later, and Dario Quill's key pass "
        "added 0.1392 xT. It was the fastest of the match's two counter-attacks.",
        ["61", "1-0", "10", "0.1392", "two"])),
    ("m07", narration(  # minute:second, possessive, sentence-start word, 2 from "two" in counter_label
        "Vane strikes first",
        "With the clock on 61:14, Vane's shot from 12.7 metres went in. "
        "It was the fastest of 2 counters.")),
    ("m01", narration(  # 8 for 8.0; "Hollis" alone mid-sentence
        "Bram Hollis keeps it level early",
        "In the 3rd minute, Cass Dunmore shot from just 8 metres, "
        "a zone worth 0.3, and Hollis stood firm. The score stayed 0-0.")),
    ("m09", narration(  # momentum: start and last minute, block length, negative number
        "London Red take over the closing stages",
        "From the 70th minute to the 93rd minute, London Red won 5 straight 5-minute blocks, "
        "creating 1.2259 xT to London Blue's 0.0448. Before that they had managed -0.0002 "
        "while London Blue were on top for 2 blocks. Theo Brannick led the way with 0.6178.")),
    ("m10", narration(  # number word, team name, score
        "Rafael Tovey levels it",
        "Rafael Tovey made it 1-1 in the 74th minute, two of the match's counters now ending in goals. "
        "Theo Brannick's pass added 0.1007 and London Red scored 12 seconds later.")),
]


@pytest.mark.parametrize("moment_id,output", PASS_CASES)
def test_grounded_narration_passes(moment_id, output):
    result = check(output, facts(moment_id))
    assert result.passed, result.offending


def test_plain_string_output_and_other_facts_shapes():
    # Reusable for other agents: any string or JSON output, any JSON facts.
    assert check("Ada Lovelace scored 3 in the 12th minute.",
                 {"scorer": "Ada Lovelace", "goals": 3, "minute": 12}).passed


# ------------------------------------------------------------- must fail

FAIL_CASES = [
    # invented player, full name
    ("m07", narration("Niko Vane scores", "Marco Silva set up Niko Vane in the 61st minute. It was 1-0."),
     {("name", "Marco Silva")}),
    # invented player, surname only, mid-sentence
    ("m07", narration("Vane scores", "Vane finished after a pass from Smith. It was 1-0."),
     {("name", "Smith")}),
    # invented player at the start of a sentence
    ("m07", narration("Vane scores", "Okafor won the ball for London Blue. Vane made it 1-0."),
     {("name", "Okafor")}),
    # a real player who is not in this moment
    ("m07", narration("Vane scores", "Kai Renwick started it and Niko Vane made it 1-0."),
     {("name", "Kai Renwick")}),
    # first and last names from two different players
    ("m11", narration("Cass Brannick wins it", "Cass Brannick scored in the 89th minute. It was 2-1."),
     {("name", "Cass Brannick")}),
    # wrong minute
    ("m07", narration("Vane scores", "Niko Vane scored in the 62nd minute. It was 1-0."),
     {("minute", "62nd minute"), ("number", "62")}),
    # wrong minute even though the number exists elsewhere (possession_seconds = 10)
    ("m07", narration("Vane scores", "Niko Vane scored in the 10th minute. It was 1-0."),
     {("minute", "10th minute")}),
    # stoppage-time form instead of the minute as given
    ("m09", narration("Red surge", "London Red were on top from the 70th minute to 90+3. They created 1.2259."),
     {("number", "90"), ("number", "3")}),
    # a number not in the facts: rounding
    ("m07", narration("Vane scores", "Dario Quill's pass added 0.14 xT. It was 1-0."),
     {("number", "0.14")}),
    # a number not in the facts: a conversion to a percentage
    ("m01", narration("Hollis saves", "The shot came from a zone worth 30%. Bram Hollis saved it."),
     {("number", "30")}),
    # a number not in the facts: arithmetic (1.2259 - 0.0448)
    ("m09", narration("Red surge", "London Red out-threatened London Blue by 1.1811. They held 5 blocks."),
     {("number", "1.1811")}),
    # a number word not in the facts
    ("m07", narration("Vane scores", "The move took three seconds. Niko Vane made it 1-0."),
     {("number", "three")}),
    # raw positions and the possession clock are hidden from the model, so they are not facts
    ("m07", narration("Vane scores", "The move started at 44.0. Niko Vane made it 1-0."),
     {("number", "44.0")}),
    ("m10", narration("Tovey scores", "Rafael Tovey shot from 90.0. It was 1-1."),
     {("number", "90.0")}),
    # a phrase word is not a name: "midfield" is in build_up, "Midfield" mid-sentence is not a name
    ("m07", narration("Vane scores", "London Blue won it in Midfield. Niko Vane made it 1-0."),
     {("name", "Midfield")}),
    # numbers_used lists a number the facts don't have
    ("m07", narration("Vane scores", "Niko Vane made it 1-0. Dario Quill set it up.", ["1-0", "0.5"]),
     {("number", "0.5")}),
]


@pytest.mark.parametrize("moment_id,output,expected", FAIL_CASES)
def test_ungrounded_narration_fails(moment_id, output, expected):
    result = check(output, facts(moment_id))
    assert not result.passed
    assert {(o["type"], o["value"]) for o in result.offending} == expected




def test_possessive_ends_a_name():
    # "London Blue's Bram Hollis" is a team and a player, not one long name
    out = narration("Bram Hollis saves", "London Blue's Bram Hollis saved Cass Dunmore's shot.")
    assert check(out, facts("m01")).passed
