"""Checks src/term_check.py: analysis terms need their facts. No model calls."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from term_check import check, subject  # noqa: E402

COUNTER = {"tags": ["counter"], "facts": {
    "build_up": "London Red won the ball back in the defensive third and scored 12 seconds later, "
                "after 3 passes and a carry from midfield into the attacking third.",
    "shot_zone_value": 0.1607}}
SHIFT = {"tags": [], "facts": {"team_threat": 1.2259}}


def ok(text, subj):
    return check([("t", text, subj)]).passed


def test_transition_needs_the_counter_tag():
    assert ok("London Red scored in transition.", subject([COUNTER]))
    assert not ok("London Red scored in transition.", subject([SHIFT]))
    assert not ok("A counter-attack from London Red.", subject([SHIFT]))


def test_final_third_needs_a_final_third_fact():
    assert ok("London Red made 24 final-third entries.", subject(summary_keys={"final_third_entries"}))
    assert not ok("London Red made 24 final-third entries.", subject(summary_keys={"shots"}))
    assert ok("London Red reached the final third.", subject(summary_keys={"possessions_lost_in_final_third"}))
    assert ok("London Red reached the final third.", subject([COUNTER]))  # build_up: "into the attacking third"
    assert not ok("London Red reached the final third.", subject([SHIFT]))
    # an entry count needs final_third_entries itself, not just any final-third fact
    assert not ok("24 final-third entries.", subject(summary_keys={"possessions_lost_in_final_third"}))


def test_other_terms():
    assert not ok("12 progressive passes.", subject(summary_keys={"final_third_entries"}))
    assert ok("12 progressive passes.", subject(summary_keys={"progressive_actions"}))
    assert not ok("16 penalty-area entries.", subject(summary_keys={"shots"}))
    assert ok("14 possessions lost in the final third.", subject(summary_keys={"possessions_lost_in_final_third"}))
    assert not ok("14 possessions lost in the final third.", subject(summary_keys={"final_third_entries"}))
    assert ok("The build-up phase ran through midfield.", subject([COUNTER]))
    assert not ok("The build-up phase.", subject([SHIFT]))
    assert ok("A shot-location value of 0.1607.", subject([COUNTER]))
    assert not ok("A shot-location value.", subject([SHIFT]))
    assert ok("Threat created rose.", subject([SHIFT]))
    assert not ok("Threat created rose.", subject(summary_keys={"shots"}))


def test_banned_terms_never_pass():
    everything = subject([COUNTER, SHIFT], {"final_third_entries", "progressive_actions", "threat_created"})
    for text in ("London Red had an xG of 1.2.", "Expected goals favoured London Red.",
                 "London Red's pressing won the ball.", "A low PPDA.", "London Red's 4-3-3 formation.",
                 "London Blue stayed compact.", "London Red used the width.", "London Red had 60% possession.",
                 "London Red dominated possession.", "London Red had 14 turnovers."):
        assert not ok(text, everything), text


def test_plain_text_passes():
    assert ok("London Red scored in the 74th minute.", subject())
