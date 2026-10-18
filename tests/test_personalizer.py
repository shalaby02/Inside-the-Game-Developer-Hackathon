"""Checks the Personalizer's checks and runner (src/personalizer.py,
src/run_personalizer.py) on hand-written outputs, and the pre-generated demo
files in data/personalized. No model calls: the model is a fake."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import run_personalizer as rp  # noqa: E402
from personalizer import (build_moment_input, count_numbers, flagged, run_moment_checks,  # noqa: E402
                          run_recap_checks)
from profiles import Profile  # noqa: E402

DATA = rp.load_data()
MOMENTS = {m["id"]: m for m in DATA["moments"]}
FAN = Profile.parse("fan/studio/en/london_blue", players=DATA["players"])
STADIUM = Profile.parse("fan/stadium/en/none", players=DATA["players"])
ANALYST = Profile.parse("analyst/studio/en/none", players=DATA["players"])
FOCUS = Profile.parse("fan/stadium/en/none/Cass Dunmore", players=DATA["players"])
RESULT = "London Red won 2-1 after trailing from the 61st minute to the 74th."


def moment_checks(moment_id, profile, headline, text):
    inputs = build_moment_input(MOMENTS[moment_id], DATA["narrations"][moment_id]["narration"], profile)
    return run_moment_checks({"headline": headline, "text": text}, inputs, profile)


def recap_checks(profile, text):
    p = rp.plan(profile, DATA)
    return run_recap_checks({"text": text}, p["recap_inputs"], p["recap_context"], profile)


def lines(checks):
    return " | ".join(flagged(checks))


# ------------------------------------------------------------ passing outputs

def test_good_fan_moment_passes():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored in the 61st minute to put London Blue 1-0 up.")
    assert c["passed"], lines(c)


def test_good_stadium_moment_passes():
    c = moment_checks("m08", STADIUM, "What a save!", "What a save! Ellis Harwick denies Niko Vane from 10.0 metres!")
    assert c["passed"], lines(c)


def test_good_fan_recap_with_favourite_named_first_passes():
    text = ("London Blue went 1-0 up through Niko Vane in the 61st minute. Rafael Tovey levelled the match at 1-1. "
            "Cass Dunmore put London Red 2-1 ahead. " + RESULT)
    c = recap_checks(FAN, text)
    assert c["passed"], lines(c)


# ------------------------------------------------------------ must fail

def test_invented_number_in_fan_mode_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored from 13 metres in the 61st minute.")
    assert not c["passed"]
    assert '"13": number not in facts' in lines(c)


def test_clock_second_does_not_ground_an_invented_number():
    # 14 is m07's second; the Personalizer never sees it, so it can't excuse "14 metres".
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored from 14 metres in the 61st minute.")
    assert '"14": number not in facts' in lines(c)


def test_xt_number_in_fan_mode_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored from a 0.1607 spot in the 61st minute.")
    assert not c["passed"]
    assert '"0.1607" is an xT number' in lines(c)


def test_the_word_xt_in_fan_mode_fails_but_not_in_analyst_mode():
    text = "Niko Vane scored in the 61st minute after Dario Quill's pass added 0.1392 xT."
    assert 'fan mode: say "danger"' in lines(moment_checks("m07", FAN, "Niko Vane scores", text))
    c = moment_checks("m07", ANALYST, "Niko Vane scores", text)
    assert c["style"]["passed"] and c["grounding"]["passed"], lines(c)


def test_fan_needs_fewer_numbers_than_the_narration():
    n = DATA["narrations"]["m11"]["narration"]
    assert count_numbers(n["headline"], n["explanation"]) == 6
    # No xT number and every number grounded, but as many numbers as the narration.
    c = moment_checks("m11", FAN, "Cass Dunmore puts London Red 2-1 ahead in the 89th minute",
                      "Cass Dunmore scored from 6.4 metres in the 89th minute to put London Red 2-1 ahead. "
                      "London Red built the move through 2 passes and a carry in the attacking third.")
    assert "fewer numbers than the narration" in lines(c)


def test_wrong_team_named_first_in_recap_fails():
    text = ("London Red won 2-1 after trailing from the 61st minute to the 74th. London Blue went 1-0 up through "
            "Niko Vane in the 61st minute. Rafael Tovey levelled the match at 1-1.")
    c = recap_checks(FAN, text)
    assert not c["passed"]
    assert "first team named must be the favourite team London Blue" in lines(c)


def test_recap_must_give_the_final_score_winner_first():
    c = recap_checks(FAN, "London Blue lost 1-2 to London Red. Niko Vane scored in the 61st minute. "
                          "Rafael Tovey levelled the match at 1-1.")
    assert "final score 2-1, winner's goals first" in lines(c)


def test_taking_a_side_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts us 1-0 up", "We lead! Niko Vane put London Blue 1-0 up.")
    assert "first person takes a side" in lines(c)
    c = moment_checks("m11", STADIUM, "Goal!", "Cass Dunmore wins it for London Red!")
    assert "claims what the score did later" in lines(c)


def test_studio_voice_has_no_exclamation_marks():
    c = moment_checks("m07", FAN, "Niko Vane scores!", "Niko Vane put London Blue 1-0 up in the 61st minute.")
    assert "exclamation marks" in lines(c)


def test_stadium_voice_needs_short_lines_except_quoted_build_up():
    # score_effect's 5 words don't count, the other 15 do.
    long = "Niko Vane scored in the 61st minute to put London Blue 1-0 up from 12.7 metres out there right now."
    assert "words of its own, the stadium voice allows" in lines(moment_checks("m07", STADIUM, "Goal!", long))
    build_up = DATA["moments"][6]["facts"]["build_up"]
    c = moment_checks("m07", STADIUM, "Goal!", f"Goal! {build_up} London Blue lead 1-0!")
    assert "stadium voice allows" not in lines(c)


def test_focus_player_must_be_named():
    c = moment_checks("m04", FOCUS, "Missed!", "London Red built the move through 3 passes. A miss from 6.4 metres!")
    assert "name the focus player Cass Dunmore" in lines(c)


def test_arabic_is_not_built_yet():
    with pytest.raises(NotImplementedError):
        build_moment_input(MOMENTS["m07"], DATA["narrations"]["m07"]["narration"],
                           Profile.parse("fan/studio/ar/none"))


# ------------------------------------------------------------ runner, fake model

def fake_moment(i):
    out = {"headline": "Niko Vane puts London Blue 1-0 up",
           "text": "Niko Vane scored in the 61st minute to put London Blue 1-0 up."}
    return {"status": "ok", "output": out, "checks": None, "retries": 0, "attempts": [{"attempt": 1, "output": out}]}


def test_runner_caches_and_keeps_hand_edits():
    profile = Profile.parse("fan/studio/en/none", players=DATA["players"])  # m07, m10, m11
    calls = []

    def moment_one(i):
        calls.append(i)
        return fake_moment(i)

    def recap_one():
        calls.append("recap")
        out = {"text": "x"}
        return {"status": "ok", "output": out, "checks": None, "retries": 0, "attempts": [{"attempt": 1, "output": out}]}

    doc = rp.run(profile, DATA, None, moment_one, recap_one, log=lambda *a: None)
    assert calls == ["m07", "m10", "m11", "recap"] and doc["selection"] == ["m07", "m10", "m11"]
    calls.clear()
    doc["moments"][0]["output"] = {"headline": "Niko Vane scores", "text": "Niko Vane put London Blue 1-0 up."}
    again = rp.run(profile, DATA, doc, moment_one, recap_one, log=lambda *a: None)
    assert calls == []  # everything was cached or hand-edited
    assert again["moments"][0]["manually_edited"] and again["moments"][0]["status"] == "ok"


# ------------------------------------------------------------ the pre-generated demo files

DEMO = {Profile.from_dict(p).key(): p for p in rp.DEMO_PROFILES}


def _doc(key):
    path = rp.OUT_DIR / f"{key}.json"
    if not path.exists():
        pytest.fail(f"{path.name} is missing: run python src/run_personalizer.py")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", sorted(DEMO))
def test_demo_file_verifies(key):
    _doc(key)
    passed, notes = rp.verify(rp.OUT_DIR / f"{key}.json", DATA)
    assert passed, notes


def test_analyst_and_fan_versions_differ_and_fan_has_fewer_numbers():
    analyst = {e["id"]: e["output"] for e in _doc("analyst-studio-en-none-none")["moments"]}
    fan = {e["id"]: e["output"] for e in _doc("fan-studio-en-london_red-none")["moments"]}
    shared = sorted(set(analyst) & set(fan))
    assert shared
    for i in shared:
        a, f = analyst[i], fan[i]
        assert a != f and a["text"] != f["text"], i
        assert count_numbers(f["headline"], f["text"]) < count_numbers(a["headline"], a["text"]), i


def test_no_gendered_pronouns_and_no_later_claims():
    c = moment_checks("m01", STADIUM, "What a save!", "What a save! Bram Hollis denies her from 8.0 metres.")
    assert "the facts give no gender" in lines(c)
    c = moment_checks("m11", STADIUM, "Dunmore secures late lead", "Goal! Cass Dunmore scores! London Red lead 2-1!")
    assert "claims what the score did later" in lines(c)


def test_analyst_keeps_at_least_the_narrations_numbers():
    c = moment_checks("m07", ANALYST, "Niko Vane scores", "Niko Vane put London Blue 1-0 up in the 61st minute.")
    assert "keep at least as many numbers as the narration" in lines(c)
