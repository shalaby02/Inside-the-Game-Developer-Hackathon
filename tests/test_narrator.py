"""Checks for src/narrator.py that need no model call: what the model sees,
and the format rules (sentences, save headline, team named)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import style_rules  # noqa: E402
from narrator import HIDDEN_FACTS, INSTRUCTIONS, format_problems, moment_input  # noqa: E402

MOMENTS = {m["id"]: m for m in json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]}


def narration(headline, explanation):
    return {"headline": headline, "explanation": explanation, "numbers_used": []}


def test_model_input_hides_positions_and_possession_clock():
    for m in MOMENTS.values():
        assert not HIDDEN_FACTS & moment_input(m)["facts"].keys(), m["id"]
    f = moment_input(MOMENTS["m07"])["facts"]
    assert f["build_up"].startswith("London Blue won the ball back in midfield")
    assert f["score_effect"] == "put London Blue 1-0 up"


def test_instructions_use_the_shared_rules():
    assert style_rules.PROMPT_RULES in INSTRUCTIONS


def test_format_allows_at_most_two_sentences():
    f = moment_input(MOMENTS["m11"])  # a goal with no counter_label to require
    assert format_problems(narration("h", "One at 0.3 xT. Two."), f) == []
    assert format_problems(narration("h", "One. Two. Three."), f) == ["explanation has 3 sentences, at most 2 allowed"]
    assert format_problems("not a dict", f) == ["response is not a JSON object"]


def test_save_headline_pattern():
    f = moment_input(MOMENTS["m08"])
    assert format_problems(narration("Ellis Harwick saves Niko Vane's 10.0-metre shot", "Saved."), f) == []
    assert format_problems(narration("Ellis Harwick saves Niko Vane’s 10.0-metre shot.", "Saved."), f) == []
    assert format_problems(narration("Harwick denies Niko Vane", "Saved."), f) == [
        "save headline must be exactly \"Ellis Harwick saves Niko Vane's 10.0-metre shot\""]


def test_momentum_shift_names_the_team_in_every_sentence():
    f = moment_input(MOMENTS["m09"])
    assert format_problems(narration("h", "London Red took over. London Blue added 0.0448 xT."), f) == []
    assert format_problems(narration("h", "London Red took over. Theo Brannick added 0.6178 xT."), f) == [
        'name the team in every sentence: "Theo Brannick added 0.6178 xT."']


def test_build_up_must_be_used_word_for_word():
    f = moment_input(MOMENTS["m07"])
    build_up = f["facts"]["build_up"]
    label = f["facts"]["counter_label"]
    verbatim = f"Niko Vane's goal put London Blue 1-0 up, {label}. {build_up}"
    assert format_problems(narration("h", verbatim), f) == []
    rebuilt = f"Niko Vane's goal put London Blue 1-0 up, {label}. The move won the ball back in midfield and scored."
    assert format_problems(narration("h", rebuilt), f) == [f'use the build_up sentence word for word: "{build_up}"']


def test_counter_goal_needs_counter_label():
    f = moment_input(MOMENTS["m10"])
    assert format_problems(narration("h", "Rafael Tovey's goal levelled the match at 1-1."), f) == [
        "say the counter_label word for word: \"the second-fastest of the match's two counter-attacks\""]
    # a goal without the counter tag has no label to require
    assert format_problems(narration("h", "Cass Dunmore's goal put London Red 2-1 ahead."),
                           moment_input(MOMENTS["m11"])) == []


def test_first_half_stoppage_run_ends_at_end_of_first_half():
    f = moment_input(MOMENTS["m02"])["facts"]  # last_minute 46 in period 1
    assert "last_minute" not in f and f["run_end"] == "the end of the first half"
    f = moment_input(MOMENTS["m09"])["facts"]  # second half: unchanged
    assert f["last_minute"] == 93 and "run_end" not in f


def test_46th_minute_is_no_longer_grounded():
    import grounding
    f = moment_input(MOMENTS["m02"])
    ok = "London Red took control from the 20th minute until the end of the first half."
    bad = "London Red took control from the 20th minute to the 46th minute."
    assert grounding.check(ok, f).passed
    assert not grounding.check(bad, f).passed
