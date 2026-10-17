"""Checks the Analyst runner's cache, hand-edit handling and verify mode.
No model calls: analyse_one is a fake."""

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import run_analyst as ra  # noqa: E402
from test_analyst import GOOD, INPUTS  # noqa: E402

EDITED = {**GOOD, "match_headline": "London Red won 2-1 after trailing from the 61st minute to the 74th, against London Blue."}


def entry(analysis, input_hash=None, status="ok"):
    return {"status": status, "analysis": analysis, "checks": None, "retries": 0,
            "input_hash": input_hash or ra.input_hash(INPUTS),
            "attempts": [{"attempt": 1, "analysis": GOOD}]}


class FakeAnalyst:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"status": "ok", "analysis": GOOD, "checks": None, "retries": 0,
                "attempts": [{"attempt": 1, "analysis": GOOD}]}


def test_cached_analysis_is_not_redone():
    fake, log = FakeAnalyst(), []
    result = ra.run(INPUTS, entry(GOOD), fake, log=log.append)
    assert fake.calls == 0 and result["analysis"] == GOOD and log == ["cached"]


def test_changed_inputs_redo_it():
    fake = FakeAnalyst()
    result = ra.run(INPUTS, entry(GOOD, input_hash="stale"), fake, log=lambda _: None)
    assert fake.calls == 1 and result["input_hash"] == ra.input_hash(INPUTS)


def test_failed_analysis_is_tried_again():
    fake = FakeAnalyst()
    ra.run(INPUTS, entry(GOOD, status="failed"), fake, log=lambda _: None)
    assert fake.calls == 1


def test_hand_edit_is_kept_and_rechecked():
    fake, log = FakeAnalyst(), []
    result = ra.run(INPUTS, entry(EDITED), fake, log=log.append)
    assert fake.calls == 0 and result["analysis"] == EDITED and result["manually_edited"] is True
    assert result["status"] == "ok" and log[0] == "manually edited, kept; checks pass"


def test_force_overwrites_a_hand_edit():
    fake, log = FakeAnalyst(), []
    result = ra.run(INPUTS, entry(EDITED), fake, force=True, log=log.append)
    assert fake.calls == 1 and result["analysis"] == GOOD
    assert "--force is overwriting a manual edit" in log


def test_verify_passes_and_fails_without_model_calls():
    assert ra.verify(INPUTS, entry(GOOD)) == (True, [])
    bad = copy.deepcopy(GOOD)
    bad["story_arc"].append({"moment_id": "m12", "role": "other"})
    passed, lines = ra.verify(INPUTS, entry(bad, status="ok"))
    assert not passed and any('"m12" is not a moment id' in line for line in lines)
    assert ra.verify(INPUTS, None) == (False, ["no analysis saved"])
