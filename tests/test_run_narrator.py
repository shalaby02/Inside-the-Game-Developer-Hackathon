"""Checks that a normal run keeps hand edits, and that verify_narrations
reports what the checks flag. No model calls: narrate_one is a fake."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import run_narrator as rn  # noqa: E402
from verify_narrations import manually_edited, verify  # noqa: E402

MOMENTS = json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]
M11 = next(m for m in MOMENTS if m["id"] == "m11")

MODEL_TEXT = {"headline": "Cass Dunmore's goal put London Red 2-1 ahead",
              "explanation": "Cass Dunmore's goal put London Red 2-1 ahead in the 89th minute. "
                             "London Red built the move through 2 passes and a carry in the attacking third.",
              "numbers_used": ["2-1", "89th", "2"]}
EDITED_TEXT = {**MODEL_TEXT, "headline": "Cass Dunmore puts London Red 2-1 ahead"}


def entry(narration, input_hash=None):
    return {"id": "m11", "status": "ok", "narration": narration, "retries": 0,
            "input_hash": input_hash or rn.input_hash(M11),
            "attempts": [{"attempt": 1, "narration": MODEL_TEXT}]}


class FakeNarrator:
    def __init__(self):
        self.calls = []

    def __call__(self, moment):
        self.calls.append(moment["id"])
        return {"id": moment["id"], "status": "ok", "narration": MODEL_TEXT, "retries": 0,
                "attempts": [{"attempt": 1, "narration": MODEL_TEXT}]}


def test_manual_edit_detected():
    assert not manually_edited(entry(MODEL_TEXT))
    assert manually_edited(entry(EDITED_TEXT))


def test_normal_run_keeps_a_manual_edit_and_marks_it():
    fake, log = FakeNarrator(), []
    [result] = rn.run([M11], {"m11": entry(EDITED_TEXT)}, fake, log=log.append)
    assert fake.calls == []
    assert result["narration"] == EDITED_TEXT
    assert result["manually_edited"] is True
    assert result["status"] == "ok" and result["grounding"]["passed"]  # re-checked on the edited text
    assert log[0] == "m11: manually edited, kept; checks pass"


def test_manual_edit_kept_even_when_inputs_changed():
    fake, log = FakeNarrator(), []
    [result] = rn.run([M11], {"m11": entry(EDITED_TEXT, input_hash="stale")}, fake, log=log.append)
    assert fake.calls == [] and result["narration"] == EDITED_TEXT
    assert any("inputs have changed" in line for line in log)


def test_failing_manual_edit_is_kept_and_reported():
    bad = {**EDITED_TEXT, "explanation": "Cass Dunmore struck in the 88th minute."}
    fake, log = FakeNarrator(), []
    [result] = rn.run([M11], {"m11": entry(bad)}, fake, log=log.append)
    assert fake.calls == [] and result["narration"] == bad
    assert result["status"] == "failed" and result["manually_edited"] is True
    assert any('"88th minute"' in line for line in log)
    # and the next normal run still keeps it
    [again] = rn.run([M11], {"m11": result}, fake, log=[].append)
    assert fake.calls == [] and again["narration"] == bad


def test_unedited_moments_follow_the_cache():
    fake = FakeNarrator()
    rn.run([M11], {"m11": entry(MODEL_TEXT)}, fake, log=[].append)
    assert fake.calls == []                                   # same inputs: cached
    rn.run([M11], {"m11": entry(MODEL_TEXT, input_hash="stale")}, fake, log=[].append)
    assert fake.calls == ["m11"]                              # changed inputs: regenerated


def test_force_overwrites_edits_and_says_so():
    fake, log = FakeNarrator(), []
    [result] = rn.run([M11], {"m11": entry(EDITED_TEXT)}, fake, force=True, log=log.append)
    assert fake.calls == ["m11"] and result["narration"] == MODEL_TEXT
    assert "m11: --force is overwriting a manual edit" in log


def test_verify_reports_flagged_text():
    bad = {**EDITED_TEXT, "explanation": "Cass Dunmore struck in the 88th minute."}
    [(moment_id, passed, notes, lines)] = verify([M11], {"m11": entry(bad)})
    assert (moment_id, passed, notes) == ("m11", False, ["manually edited"])
    assert 'grounding: minute "88th minute": minute not in facts' in lines
    assert 'style: style "struck": outcome verb outside scored, saved, missed, passed, carried, denied, stopped' in lines

    [(_, passed, _, lines)] = verify([M11], {"m11": entry(MODEL_TEXT)})
    assert passed and lines == []
    assert verify([M11], {})[0][1:] == (False, [], ["no narration saved"])
