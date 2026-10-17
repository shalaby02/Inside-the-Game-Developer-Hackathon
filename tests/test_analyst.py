"""Checks the Analyst's validation on hand-written answers: one that must
pass, and broken copies of it that must fail. No model calls."""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import analyst  # noqa: E402
import style_check  # noqa: E402
from analyst import CONNECTOR_RULES, analyst_input, flagged, resolve, run_checks  # noqa: E402

KEY_MOMENTS = json.loads((ROOT / "data" / "key_moments.json").read_text())
SUMMARY = json.loads((ROOT / "data" / "match_summary.json").read_text())
INPUTS = analyst_input(KEY_MOMENTS, SUMMARY)

GOOD = {
    "match_headline": "London Red won 2-1 after trailing from the 61st minute to the 74th.",
    "story_arc": [
        {"moment_id": "m04", "role": "opening"},
        {"moment_id": "m07", "role": "build_up"},
        {"moment_id": "m08", "role": "build_up"},
        {"moment_id": "m09", "role": "build_up"},
        {"moment_id": "m10", "role": "turning_point"},
        {"moment_id": "m11", "role": "decider"},
    ],
    "turning_point": {
        "moment_id": "m10",
        "reason": "Rafael Tovey's goal in the 74th minute levelled the match at 1-1, ending London Blue's lead, "
                  "with a key pass that added 0.1007 xT.",
    },
    "phase_notes": [
        {"text": "London Red made 24 final-third entries in the first half to 11 for London Blue.",
         "cites": ["summary.by_half.first_half.london_red.final_third_entries",
                   "summary.by_half.first_half.london_blue.final_third_entries"]},
        {"text": "In the first half London Red created 1.4019 of threat from 9 shots and London Blue 0.1746 "
                 "from 2 shots, with no goals for either team.",
         "cites": ["summary.first_half_summary"]},
        {"text": "London Blue in the 61st minute and London Red in the 74th minute both scored in transition.",
         "cites": ["m07.minute", "m10.minute"]},
    ],
    "moment_priority": {"essential": ["m07", "m10", "m11"], "supporting": ["m04", "m08", "m09"]},
}


def broken(change):
    a = copy.deepcopy(GOOD)
    change(a)
    return a


def lines(analysis):
    return flagged(run_checks(analysis, INPUTS))


def fails(analysis, *expected):
    """The analysis fails, and some flagged line contains each expected piece of text."""
    checks = run_checks(analysis, INPUTS)
    assert not checks["passed"]
    found = flagged(checks)
    for text in expected:
        assert any(text in line for line in found), (text, found)


def note(i, text, cites=None):
    def change(a):
        a["phase_notes"][i]["text"] = text
        if cites is not None:
            a["phase_notes"][i]["cites"] = cites
    return broken(change)


def turning_point_m09(reason):
    """GOOD with m09 (Red's surge) as the turning point instead of m10."""
    def change(a):
        a["story_arc"][3]["role"], a["story_arc"][4]["role"] = "turning_point", "response"
        a["moment_priority"] = {"essential": ["m07", "m09", "m10", "m11"], "supporting": ["m04", "m08"]}
        a["turning_point"] = {"moment_id": "m09", "reason": reason}
    return broken(change)


# ------------------------------------------------------------ must pass

def test_good_analysis_passes():
    assert lines(GOOD) == []


def test_momentum_shift_can_be_the_turning_point():
    assert lines(turning_point_m09("From the 70th minute London Red created 1.2259 of threat against 0.0448 "
                                   "for London Blue.")) == []


def test_cite_paths_resolve():
    assert resolve("m09.team_threat", INPUTS) == (1.2259, "team_threat")
    assert resolve("m09.facts.team_threat", INPUTS) == (1.2259, "team_threat")
    assert resolve("summary.by_half.first_half.london_red.final_third_entries", INPUTS) == (24, "final_third_entries")
    assert resolve("summary.goals.0.minute", INPUTS) == (61, "minute")
    assert resolve("summary.momentum_runs.1.goals_in_run", INPUTS) == (["m10", "m11"], "goals_in_run")
    assert resolve("m12.team_threat", INPUTS) is None
    assert resolve("summary.by_half.third_half", INPUTS) is None


def test_analysis_never_sees_narrations_or_coordinates():
    blob = json.dumps(INPUTS)
    assert "narration" not in blob and "explanation" not in blob
    assert "shot_x" not in blob and "possession_seconds" not in blob


def test_result_line_quote_may_contain_after():
    # "after" is a blocked connector, but not inside result_line quoted word for word.
    assert not any("after" in line for line in lines(GOOD))


# ------------------------------------------------------------ must fail: structure

def test_invented_id():
    fails(broken(lambda a: a["story_arc"].insert(0, {"moment_id": "m12", "role": "opening"})
                 or a["story_arc"].__setitem__(1, {"moment_id": "m04", "role": "other"})),
          '"m12" is not a moment id')
    fails(broken(lambda a: a["moment_priority"]["supporting"].append("m99")), '"m99" is not a moment id')


def test_out_of_order_arc():
    def swap(a):
        a["story_arc"][4], a["story_arc"][5] = a["story_arc"][5], a["story_arc"][4]
    fails(broken(swap), "not in match-time order: m11 comes before m10")


def test_moment_twice_in_arc():
    fails(broken(lambda a: a["story_arc"].append({"moment_id": "m11", "role": "other"})),
          '"m11" appears more than once')


def test_missing_goal():
    fails(broken(lambda a: a["moment_priority"]["essential"].remove("m11")), "goal m11 must be essential")


def test_turning_point_must_be_exactly_one_and_match():
    fails(broken(lambda a: a["story_arc"][2].update(role="turning_point")),
          "exactly one turning_point role, has 2")
    fails(broken(lambda a: a["story_arc"][4].update(role="response")), "exactly one turning_point role, has 0")
    fails(broken(lambda a: a["turning_point"].update(moment_id="m11")),
          "turning_point is m11 but story_arc marks m10")


def test_turning_point_must_change_score_state_or_threat_balance():
    def save_tp(a):
        a["story_arc"][2]["role"], a["story_arc"][4]["role"] = "turning_point", "response"
        a["moment_priority"] = {"essential": ["m07", "m08", "m10", "m11"], "supporting": ["m04", "m09"]}
        a["turning_point"] = {"moment_id": "m08", "reason": "Ellis Harwick saved from a spot with xT 0.1607."}
    fails(broken(save_tp), "turning_point m08 is a save")


def test_goal_that_keeps_the_score_state_is_not_a_turning_point():
    summary = copy.deepcopy(SUMMARY)
    summary["goals"][1]["score_after"] = {"london_red": 0, "london_blue": 2}  # pretend m10 made it 0-2
    problems = analyst.turning_point_problems(next(m for m in INPUTS["moments"] if m["id"] == "m10"), summary)
    assert problems == ["turning_point m10 did not change the score state"]


def test_reason_needs_an_xt_number_from_its_moment():
    fails(broken(lambda a: a["turning_point"].update(
        reason="Rafael Tovey's goal in the 74th minute levelled the match at 1-1.")),
        "must quote an xT number from m10")


def test_decider_must_be_a_goal_and_opening_first():
    fails(broken(lambda a: a["story_arc"][5].update(role="other") or a["story_arc"][2].update(role="decider")),
          "decider m08 is not a goal")
    fails(broken(lambda a: a["story_arc"][1].update(role="opening")), "opening must be used at most once")


def test_phase_note_count_and_cites():
    fails(broken(lambda a: a["phase_notes"].pop()), "3 to 5 notes, has 2")
    fails(broken(lambda a: a["phase_notes"][0]["cites"].append("summary.by_half.first_half.london_red.xg")),
          'cites "summary.by_half.first_half.london_red.xg"')


def test_first_half_summary_must_be_cited():
    fails(note(1, "London Red created 1.4019 of threat in the first half.",
               ["summary.by_half.first_half.london_red.threat_created"]),
          "must cite summary.first_half_summary")


def test_essential_moment_must_be_in_arc():
    fails(broken(lambda a: a["moment_priority"]["supporting"].remove("m08") or
                 a["moment_priority"]["essential"].append("m08") or a["story_arc"].pop(2)),
          "essential moment m08 is missing from story_arc")


# ------------------------------------------------------------ must fail: headline

def test_headline_needs_final_score_and_winner():
    fails(broken(lambda a: a.update(match_headline="London Red came from behind against London Blue.")),
          "must give the final score 2-1", "quote result_line")
    fails(broken(lambda a: a.update(match_headline="London Blue lost 2-1 in the 89th minute.")),
          "must name the winning team: London Red")
    fails(broken(lambda a: a.update(match_headline="London Red won 1-2.")), "must give the final score 2-1")


def test_headline_terms_need_specific_backing():
    # "transition" in the headline is backed only if the headline names a counter moment.
    fails(broken(lambda a: a.update(match_headline="London Red won 2-1 against London Blue in transition.")),
          '"transition" needs')
    assert lines(broken(lambda a: a.update(
        match_headline="London Red won 2-1 after trailing from the 61st minute to the 74th, both goals "
                       "in that spell scored in transition."))) == []
    # A stat term in the headline needs the stat's number in it.
    fails(broken(lambda a: a.update(match_headline="London Red won 2-1 with more final-third entries.")),
          '"final-third entry" needs')


# ------------------------------------------------------------ must fail: text

def test_wrong_minute():
    fails(broken(lambda a: a.update(match_headline="London Red won 2-1 after trailing from the 62nd minute "
                                                   "to the 74th.")),
          'match_headline: 62nd minute')
    # A note may only use minutes it cites: m10's 74th is real, but not cited here.
    fails(broken(lambda a: a["phase_notes"][2].update(cites=["m07.minute"])), "74th minute")


def test_number_not_in_cited_facts():
    # 23 is London Red's second-half count, a real number but not one this note cites.
    fails(note(0, "London Red made 24 final-third entries in the first half and 23 in the second half."),
          'phase_notes[0]: 23')


def test_transition_on_a_non_counter_moment():
    fails(turning_point_m09("From the 70th minute London Red created 1.2259 of threat in transition."),
          '"transition" needs a moment with the counter tag')
    fails(note(2, "London Blue in the 67th minute and London Red in the 89th minute both attacked in transition.",
               ["m08.minute", "m11.minute"]),
          '"transition" needs')


def test_transition_about_a_non_counter_moment_in_a_note_that_also_cites_m07():
    # m07 is a counter, but the sentence with "transition" is about m09 (the 70th minute), which is not.
    fails(note(2, "London Blue scored in the 61st minute. From the 70th minute London Red created 1.2259 of "
                  "threat in transition.", ["m07.minute", "m09.start_minute", "m09.team_threat"]),
          '"transition" needs a moment with the counter tag')
    # The same cites pass when "transition" sits in the sentence about m07.
    assert lines(note(2, "London Blue scored in the 61st minute in transition. From the 70th minute London Red "
                         "created 1.2259 of threat.", ["m07.minute", "m09.start_minute", "m09.team_threat"])) == []


def test_xg_used():
    fails(note(1, "In the first half London Red created 1.4019 of threat, a high xG."), 'xG')


def test_final_third_term_without_its_fact():
    fails(note(1, "London Red made more final-third entries, with 1.4019 of threat created in the first half."),
          '"final-third entry" needs')


def test_turnover_is_banned():
    fails(note(0, "London Red made 24 final-third entries in the first half to 11 for London Blue, with "
                  "19 turnovers."), "turnovers")


def test_existing_blocked_phrases_still_apply():
    fails(broken(lambda a: a.update(match_headline="Cass Dunmore's winner gave London Red a 2-1 comeback.")),
          "claims what the score did later")
    fails(note(0, "London Red made 24 final-third entries in the first half to 11 for their opponents."),
          "name the team instead")


def test_id_in_text():
    fails(broken(lambda a: a["turning_point"].update(
        reason="m10 was where London Red levelled the match at 1-1 with a key pass that added 0.1007 xT.")), "m10")


def test_not_json_object():
    checks = run_checks(None, INPUTS)
    assert not checks["passed"] and checks["format_problems"] == ["response is not a JSON object"]


# ------------------------------------------------------------ connectors

def connector_flags(text):
    return [o["value"] for o in style_check.check({"t": text}, {}, moment_rules=False,
                                                  extra_rules=CONNECTOR_RULES).offending]


def test_connectors_blocked():
    for text, word in [("London Red's surge preceded the goal.", "preceded"),
                       ("The pressure led to a goal.", "led to"), ("The save sparked London Red.", "sparked"),
                       ("London Red scored because of the surge.", "because of"),
                       ("London Red attacked before the goal.", "before"),
                       ("London Red scored after the save.", "after"),
                       ("London Red surged ahead of the equaliser.", "ahead of"),
                       ("The miss caused problems.", "caused")]:
        assert connector_flags(text) == [word], text


def test_connectors_allowed_where_not_connectors():
    assert connector_flags("London Blue led from the 61st minute to the 74th minute.") == []
    assert connector_flags("Cass Dunmore's goal put London Red 2-1 ahead.") == []


def test_connectors_in_headline_and_notes_but_not_reason():
    fails(broken(lambda a: a.update(match_headline="London Red won 2-1 after London Blue scored first.")),
          '"after" claims an order of events')
    fails(note(1, "In the first half London Red created 1.4019 of threat from 9 shots, which preceded "
                  "London Blue's 0.1746 from 2 shots."), '"preceded" claims an order of events')
    # The reason explains why the turning point mattered, so connectors are allowed there.
    assert lines(broken(lambda a: a["turning_point"].update(
        reason="Rafael Tovey's goal in the 74th minute levelled the match at 1-1 after a key pass that added "
               "0.1007 xT."))) == []


def test_connector_list_is_editable():
    import style_rules
    words = [w for w, _, _ in style_rules.CONNECTORS]
    assert words == ["preceded", "led to", "sparked", "because", "before", "after", "ahead of", "caused"]


# ------------------------------------------------------------ the retry loop, with a fake client

class FakeClient:
    """Returns the queued replies in order and records every request."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content = self.replies.pop(0)

        class Message:
            pass
        message = Message()
        message.content = content if isinstance(content, str) else json.dumps(content)
        choice = Message()
        choice.message, choice.finish_reason = message, "stop"
        response = Message()
        response.choices = [choice]
        return response


def test_retry_then_pass():
    bad = broken(lambda a: a["moment_priority"]["essential"].remove("m11"))
    client = FakeClient([bad, GOOD])
    result = analyst.analyse(client, "fake", INPUTS)
    assert result["status"] == "ok" and result["retries"] == 1 and result["analysis"] == GOOD
    feedback = client.requests[1]["messages"][-1]["content"]
    assert "goal m11 must be essential" in feedback
    assert client.requests[0]["reasoning_effort"] == "low" and "temperature" not in client.requests[0]


def test_failed_after_two_retries():
    bad = broken(lambda a: a.update(match_headline="London Red had more xG."))
    client = FakeClient([bad, bad, bad])
    result = analyst.analyse(client, "fake", INPUTS)
    assert result["status"] == "failed" and result["retries"] == analyst.MAX_RETRIES == 2
    assert len(client.requests) == 3 and not client.replies
