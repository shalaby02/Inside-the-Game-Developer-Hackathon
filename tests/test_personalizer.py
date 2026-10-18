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
from personalizer import (build_moment_input, count_numbers, flagged, recap_skeleton, run_moment_checks,  # noqa: E402
                          run_recap_checks, text_of)
from profiles import Profile  # noqa: E402

DATA = rp.load_data()
MOMENTS = {m["id"]: m for m in DATA["moments"]}
FAN = Profile.parse("fan/studio/en/london_blue", players=DATA["players"])
STADIUM = Profile.parse("fan/stadium/en/none", players=DATA["players"])
ANALYST = Profile.parse("analyst/studio/en/none", players=DATA["players"])
FOCUS = Profile.parse("fan/stadium/en/none/Cass Dunmore", players=DATA["players"])
FOCUS_STUDIO = Profile.parse("fan/studio/en/none/Cass Dunmore", players=DATA["players"])


def moment_checks(moment_id, profile, headline, *lines):
    inputs = build_moment_input(MOMENTS[moment_id], DATA["narrations"][moment_id]["narration"], profile)
    return run_moment_checks({"headline": headline, "lines": list(lines)}, inputs, profile)


def skeleton(profile):
    return rp.plan(profile, DATA)["recap_inputs"]["skeleton"]


def recap_checks(profile, lines):
    p = rp.plan(profile, DATA)
    return run_recap_checks({"lines": lines}, p["recap_inputs"], p["recap_context"], profile)


def flags(checks):
    return " | ".join(flagged(checks))


# ------------------------------------------------------------ passing outputs

def test_good_fan_moment_passes():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored in the 61st minute to put London Blue 1-0 up.")
    assert c["passed"], flags(c)


def test_good_stadium_moment_in_several_lines_passes():
    c = moment_checks("m08", STADIUM, "What a save!", "What a save!", "Ellis Harwick denies Niko Vane from 10.0 metres!")
    assert c["passed"], flags(c)


# ------------------------------------------------------------ lines (no line breaks inside a string)

def test_a_line_break_inside_a_line_fails():
    c = moment_checks("m07", STADIUM, "Goal!", "Goal!\nNiko Vane scores! London Blue lead 1-0.")
    assert "line break inside it" in flags(c)


def test_every_line_ends_with_punctuation():
    c = moment_checks("m07", FAN, "Niko Vane scores", "Niko Vane put London Blue 1-0 up", "In the 61st minute.")
    assert 'lines[0] "' in flags(c) and 'must end with' in flags(c)


def test_old_text_field_is_rejected():
    inputs = build_moment_input(MOMENTS["m07"], DATA["narrations"]["m07"]["narration"], FAN)
    c = run_moment_checks({"headline": "Niko Vane scores", "text": "Niko Vane put London Blue 1-0 up."}, inputs, FAN)
    assert "lines must be a non-empty list" in flags(c)


# ------------------------------------------------------------ moments: must fail

def test_invented_number_in_fan_mode_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up", "Niko Vane scored from 13 metres in the 61st minute.")
    assert '"13": number not in facts' in flags(c)


def test_clock_second_does_not_ground_an_invented_number():
    # 14 is m07's second; the Personalizer never sees it, so it can't excuse "14 metres".
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up", "Niko Vane scored from 14 metres in the 61st minute.")
    assert '"14": number not in facts' in flags(c)


def test_xt_number_in_fan_mode_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts London Blue 1-0 up",
                      "Niko Vane scored from a 0.1607 spot in the 61st minute.")
    assert '"0.1607" is an xT number' in flags(c)


def test_the_word_xt_in_fan_mode_fails_but_not_in_analyst_mode():
    text = "Niko Vane scored in the 61st minute and Dario Quill's pass added 0.1392 xT."
    assert 'fan mode: say "danger"' in flags(moment_checks("m07", FAN, "Niko Vane scores", text))
    c = moment_checks("m07", ANALYST, "Niko Vane scores", text)
    assert c["style"]["passed"] and c["grounding"]["passed"], flags(c)


def test_fan_needs_fewer_numbers_than_the_narration():
    n = DATA["narrations"]["m11"]["narration"]
    assert count_numbers(n["headline"], n["explanation"]) == 6
    c = moment_checks("m11", FAN, "Cass Dunmore puts London Red 2-1 ahead in the 89th minute",
                      "Cass Dunmore scored from 6.4 metres in the 89th minute to put London Red 2-1 ahead.",
                      "London Red built the move through 2 passes and a carry in the attacking third.")
    assert "fewer numbers than the narration" in flags(c)


def test_analyst_keeps_at_least_the_narrations_numbers():
    c = moment_checks("m07", ANALYST, "Niko Vane scores", "Niko Vane put London Blue 1-0 up in the 61st minute.")
    assert "keep at least as many numbers as the narration" in flags(c)


@pytest.mark.parametrize("moment_id, profile, text", [
    ("m11", FOCUS_STUDIO, "Theo Brannick passed to Cass Dunmore from 6.4 metres in the 89th minute."),
    ("m11", ANALYST, "Theo Brannick passed to Cass Dunmore from 6.4 metres."),
    ("m04", FOCUS_STUDIO, "Luca Merriden found Cass Dunmore 6.4 metres out in the 38th minute."),
    ("m08", FAN, "Kai Renwick's pass reached Niko Vane at 10.0 metres in the 67th minute."),
])
def test_distance_without_a_shot_verb_fails(moment_id, profile, text):
    assert "distance in metres without a shot verb" in flags(moment_checks(moment_id, profile, "A moment", text))


def test_distance_with_a_shot_verb_passes_that_check():
    for text in ("Cass Dunmore scored from 6.4 metres in the 89th minute.",
                 "Bram Hollis denies Cass Dunmore's 8.0-metre shot."):
        c = moment_checks("m11" if "89th" in text else "m01", FOCUS_STUDIO, "A moment", text)
        assert "distance in metres" not in flags(c)
    assert "distance in metres" in flags(moment_checks("m11", FOCUS_STUDIO, "Brannick to Dunmore from 6.4 metres",
                                                       "Cass Dunmore scored in the 89th minute."))


def test_spark_is_blocked_in_every_mode():
    for profile in (FAN, ANALYST):
        c = moment_checks("m09", profile, "London Red take control",
                          "From the 70th minute to the 93rd minute Theo Brannick sparked London Red.")
        assert '"sparked": claims a cause' in flags(c)


def test_movement_and_shot_quality_inventions_are_blocked():
    for text, reason in (("Cass Dunmore bursts into the area.", "describes movement or a location"),
                         ("Theo Brannick darts forward.", "describes movement or a location"),
                         ("London Red surge forward.", "describes movement or a location"),
                         ("Cass Dunmore pounces.", "describes movement or a location"),
                         ("What a strike!", "describes how the shot looked"),
                         ("What a hit!", "describes how the shot looked"),
                         ("A thunderous effort.", "describes how the shot looked")):
        for profile in (FAN, ANALYST):
            assert reason in flags(moment_checks("m11", profile, "Cass Dunmore scores", text)), text
    assert "describes movement" not in flags(moment_checks("m11", FAN, "Cass Dunmore scores",
                                                            "Cass Dunmore scored in the 89th minute."))


def test_connectors_blocked_in_analyst_moments_but_quoted_build_up_is_fine():
    c = moment_checks("m04", ANALYST, "Cass Dunmore misses",
                      "Cass Dunmore missed from 6.4 metres after Luca Merriden's pass added 0.2906 xT.")
    assert '"after" claims an order of events' in flags(c)
    c = moment_checks("m09", ANALYST, "London Red take control",
                      "London Red added 1.2259 xT from the 70th minute to the 93rd minute, London Blue earlier on top.")
    assert '"earlier" claims an order of events' in flags(c)
    build_up = MOMENTS["m03"]["facts"]["build_up"]  # "... 12 seconds later, after 1 earlier pass."
    c = moment_checks("m03", ANALYST, "Femi Oakhurst adds 0.0758 xT", build_up)
    assert "claims an order of events" not in flags(c)


def test_fan_moments_keep_their_connectors():
    c = moment_checks("m07", FAN, "Niko Vane scores", "Niko Vane put London Blue 1-0 up after a quick move.")
    assert "claims an order of events" not in flags(c)


def test_taking_a_side_fails():
    c = moment_checks("m07", FAN, "Niko Vane puts us 1-0 up", "We lead!", "Niko Vane put London Blue 1-0 up.")
    assert "first person takes a side" in flags(c)
    c = moment_checks("m11", STADIUM, "Goal!", "Cass Dunmore wins it for London Red!")
    assert "claims what the score did later" in flags(c)


def test_no_gendered_pronouns_and_no_later_claims():
    c = moment_checks("m01", STADIUM, "What a save!", "What a save! Bram Hollis denies her from 8.0 metres.")
    assert "the facts give no gender" in flags(c)
    c = moment_checks("m11", STADIUM, "Dunmore secures late lead", "Goal! Cass Dunmore scores! London Red lead 2-1!")
    assert "claims what the score did later" in flags(c)


def test_studio_voice_has_no_exclamation_marks():
    c = moment_checks("m07", FAN, "Niko Vane scores!", "Niko Vane put London Blue 1-0 up in the 61st minute.")
    assert "exclamation marks" in flags(c)


def test_stadium_voice_needs_short_lines_except_quoted_build_up():
    # score_effect's 5 words don't count, the other 15 do.
    long = "Niko Vane scored in the 61st minute to put London Blue 1-0 up from 12.7 metres out there right now."
    assert "words of its own, the stadium voice allows" in flags(moment_checks("m07", STADIUM, "Goal!", long))
    build_up = MOMENTS["m07"]["facts"]["build_up"]
    c = moment_checks("m07", STADIUM, "Goal!", "Goal!", build_up, "London Blue lead 1-0!")
    assert "stadium voice allows" not in flags(c)


def test_focus_player_must_be_named():
    c = moment_checks("m04", FOCUS, "Missed!", "London Red built the move through 3 passes.", "A miss from 6.4 metres!")
    assert "name the focus player Cass Dunmore" in flags(c)


def test_arabic_is_not_built_yet():
    with pytest.raises(NotImplementedError):
        build_moment_input(MOMENTS["m07"], DATA["narrations"]["m07"]["narration"], Profile.parse("fan/studio/ar/none"))


# ------------------------------------------------------------ recap skeleton

def test_skeleton_is_built_in_code_in_match_order():
    assert skeleton(FAN) == [
        "London Blue and London Red met, and London Red won 2-1 after trailing from the 61st minute to the 74th.",
        "Niko Vane's goal in the 61st minute put London Blue 1-0 up.",
        "Rafael Tovey's goal in the 74th minute levelled the match at 1-1.",
        "Cass Dunmore's goal in the 89th minute put London Red 2-1 ahead.",
        "The turning point was Rafael Tovey's goal in the 74th minute.",
    ]
    assert skeleton(STADIUM)[0] == "London Red won 2-1 after trailing from the 61st minute to the 74th."
    assert skeleton(ANALYST)[-1] == ("The turning point was Rafael Tovey's goal in the 74th minute: its key pass "
                                     "added 0.1007 xT and the shot came from a spot with xT 0.1607.")


def test_focus_skeleton_stats_come_from_player_summaries():
    p = DATA["players"]["Cass Dunmore"]
    assert skeleton(FOCUS)[-1] == (f"Cass Dunmore completed {p['passes_completed']} of {p['passes_attempted']} "
                                   f"passes and took {p['shots']} shots.") == \
        "Cass Dunmore completed 28 of 34 passes and took 7 shots."
    analyst = Profile.parse("analyst/studio/en/none/Cass Dunmore", players=DATA["players"])
    assert skeleton(analyst)[-1] == ("Cass Dunmore completed 28 of 34 passes, made 1 final-third entry, took 7 shots "
                                     "and added 0.075 xT.")
    keeper = Profile.parse("fan/studio/en/none/Bram Hollis", players=DATA["players"])
    assert skeleton(keeper)[-1] == "Bram Hollis completed 3 of 5 passes, took 0 shots and made 4 saves."


@pytest.mark.parametrize("profile", [FAN, STADIUM, ANALYST, FOCUS,
                                     Profile.parse("fan/stadium/en/london_red/Ellis Harwick")])
def test_the_skeleton_itself_passes_every_recap_check(profile):
    c = recap_checks(profile, skeleton(profile))
    assert c["passed"], flags(c)


def test_good_stadium_rewording_passes():
    lines = ["London Blue and London Red met, and London Red won 2-1 after trailing from the 61st minute to the 74th.",
             "Goal!", "Niko Vane, 61st minute, put London Blue 1-0 up!",
             "Rafael Tovey in the 74th minute levelled the match at 1-1.",
             "Cass Dunmore in the 89th minute put London Red 2-1 ahead!",
             "The turning point: Rafael Tovey's goal in the 74th minute."]
    c = recap_checks(Profile.parse("fan/stadium/en/london_blue"), lines)
    assert c["passed"], flags(c)


def test_recap_dropping_a_goal_fails():
    lines = [s for s in skeleton(FAN) if "Niko Vane" not in s]
    assert 'skeleton sentence 2 is missing: keep "put London Blue 1-0 up"' in flags(recap_checks(FAN, lines))


def test_recap_reordering_fails():
    s = skeleton(FAN)
    c = recap_checks(FAN, [s[0], s[2], s[1], s[3], s[4]])
    assert "out of order" in flags(c)


def test_recap_adding_a_fact_fails():
    c = recap_checks(FAN, skeleton(FAN) + ["Ellis Harwick denied Niko Vane in the 67th minute."])
    assert '"Ellis Harwick": name not in facts' in flags(c)
    assert '"67th minute": minute not in facts' in flags(c)


def test_recap_moving_a_scorer_away_from_the_goal_fails():
    lines = skeleton(FAN)
    lines[2] = "The match was levelled at 1-1 in the 74th minute; levelled the match at 1-1."
    assert '"Rafael Tovey\'s goal"' not in flags(recap_checks(FAN, lines))
    assert 'skeleton sentence 3: "Rafael Tovey" must be in the same sentence' in flags(recap_checks(FAN, lines))


def test_recap_wrong_focus_stats_fail():
    lines = skeleton(FOCUS)
    lines[-1] = "Cass Dunmore completed 27 of 34 passes and took 7 shots."
    c = recap_checks(FOCUS, lines)
    assert 'keep "completed 28 of 34 passes" word for word' in flags(c)
    lines[-1] = "Cass Dunmore completed 28 of 34 passes and took 8 shots."
    assert '"took 7 shots" must be in the same sentence' in flags(recap_checks(FOCUS, lines))


def test_wrong_team_named_first_in_recap_fails():
    lines = skeleton(FAN)
    lines[0] = "London Red won 2-1 after trailing from the 61st minute to the 74th, against London Blue."
    c = recap_checks(FAN, lines)
    assert "first team named must be the favourite team London Blue" in flags(c)


def test_xt_number_in_fan_recap_fails():
    lines = skeleton(FAN)
    lines[-1] = "The turning point was Rafael Tovey's goal in the 74th minute, from a 0.1607 spot."
    c = recap_checks(FAN, lines)
    assert '"0.1607": number not in facts' in flags(c)
    assert '"0.1607" is an xT number' in flags(c)


def test_connectors_blocked_in_recap():
    lines = skeleton(FAN)
    lines[2] = "Rafael Tovey's goal in the 74th minute levelled the match at 1-1, after Niko Vane's goal."
    assert '"after" claims an order of events' in flags(recap_checks(FAN, lines))


# ------------------------------------------------------------ runner, fake model

def fake_moment(i):
    out = {"headline": "Niko Vane puts London Blue 1-0 up",
           "lines": ["Niko Vane scored in the 61st minute to put London Blue 1-0 up."]}
    return {"status": "ok", "output": out, "checks": None, "retries": 0, "attempts": [{"attempt": 1, "output": out}]}


def fake_recap():
    out = {"lines": ["x."]}
    return {"status": "ok", "output": out, "checks": None, "retries": 0, "attempts": [{"attempt": 1, "output": out}]}


def test_runner_caches_and_keeps_hand_edits():
    profile = Profile.parse("fan/studio/en/none", players=DATA["players"])  # m07, m10, m11
    calls = []

    def moment_one(i):
        calls.append(i)
        return fake_moment(i)

    def recap_one():
        calls.append("recap")
        return fake_recap()

    doc = rp.run(profile, DATA, None, moment_one, recap_one, log=lambda *a: None)
    assert calls == ["m07", "m10", "m11", "recap"] and doc["selection"] == ["m07", "m10", "m11"]
    calls.clear()
    doc["moments"][0]["output"] = {"headline": "Niko Vane scores", "lines": ["Niko Vane put London Blue 1-0 up."]}
    again = rp.run(profile, DATA, doc, moment_one, recap_one, log=lambda *a: None)
    assert calls == []  # everything was cached or hand-edited
    assert again["moments"][0]["manually_edited"] and again["moments"][0]["status"] == "ok"


def test_runner_flags_moments_involving_the_favourite_and_verify_checks_the_flag(tmp_path):
    profile = Profile.parse("fan/stadium/en/london_blue", players=DATA["players"])
    doc = rp.run(profile, DATA, None, fake_moment, fake_recap, log=lambda *a: None)
    assert [(e["id"], e["involves_favourite"]) for e in doc["moments"]] == [
        ("m01", True), ("m07", True), ("m08", True), ("m10", False), ("m11", False)]
    doc["moments"][3]["involves_favourite"] = True
    path = tmp_path / f"{profile.key()}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    passed, notes = rp.verify(path, DATA)
    assert not passed and "m10: involves_favourite should be False" in notes


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


@pytest.mark.parametrize("key", sorted(DEMO))
def test_demo_files_store_lines_not_line_breaks(key):
    doc = _doc(key)
    for entry in doc["moments"] + [doc["recap"]]:
        assert isinstance(entry["output"]["lines"], list)
        assert not any("\n" in line for line in entry["output"]["lines"])
        assert "text" not in entry["output"]


def test_analyst_and_fan_versions_differ_and_fan_has_fewer_numbers():
    analyst = {e["id"]: e["output"] for e in _doc("analyst-studio-en-none-none")["moments"]}
    fan = {e["id"]: e["output"] for e in _doc("fan-studio-en-london_red-none")["moments"]}
    shared = sorted(set(analyst) & set(fan))
    assert shared
    for i in shared:
        a, f = analyst[i], fan[i]
        assert a != f and text_of(a) != text_of(f), i
        assert count_numbers(f["headline"], text_of(f)) < count_numbers(a["headline"], text_of(a)), i


def test_recap_skeleton_function_matches_plan():
    p = rp.plan(FAN, DATA)
    direct = recap_skeleton(FAN, DATA["analysis"], DATA["summary"], DATA["moments"], DATA["players"])
    assert [s["text"] for s in direct] == p["recap_inputs"]["skeleton"]
