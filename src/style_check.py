"""Style check: blocks wording the facts can't support, even when every name
and number in it is grounded (see src/grounding.py for those).

No model calls. Edit BLOCKED to add or remove phrases: each entry is a
regular expression (matched case-insensitively, on whole words) and the
reason shown to the model when it retries. A few rules depend on the facts
and live in fact_rules().

Use:  from style_check import check;  check(narration, facts).passed
"""

import re
from dataclasses import dataclass, field

MAX_NUMBERS = 5  # per text field; the Narrator is asked for about four

BLOCKED = [
    # How a save looked: the facts only say it was saved.
    (r"pushe[sd] away|turn(?:s|ed)? away|tip(?:s|ped)?|parr(?:y|ies|ied)|smother(?:s|ed)?|"
     r"palm(?:s|ed)?|claw(?:s|ed)?|div(?:e|es|ed|ing)|fingertips?|full stretch|"
     r"beat(?:s)? away|reflex(?:es)?|acrobatic", "describes how the save was made"),
    # How a shot looked: the facts only say scored or missed.
    (r"volley(?:s|ed)?|header|headed|low (?:shot|attempt|drive|effort)|curl(?:s|ed|ing)?|"
     r"chip(?:s|ped)?|drill(?:s|ed)|lash(?:es|ed)|blast(?:s|ed)|smash(?:es|ed)|"
     r"rifle[sd]|thump(?:s|ed)|slot(?:s|ted)|tap(?:s|ped)? in|tap-in|powered|"
     r"wide|over the bar|(?:top|bottom|far|near) (?:corner|post)|first-time|"
     r"left foot|right foot|left-footed|right-footed", "describes how the shot was taken"),
    # Outcome verbs outside the allowed five (scored, saved, missed, passed, carried).
    (r"fire[sd]?|denie[sd]|deny|nets|netted|finish(?:es|ed)?|strikes|struck|"
     r"squander(?:s|ed)|wast(?:es|ed)|convert(?:s|ed)|buried|teed up|tees up",
     "outcome verb outside scored, saved, missed, passed, carried"),
    # The score is only known at the moment itself.
    (r"keep(?:s|ing)?|kept|remain(?:s|ed)?|stay(?:s|ed)?|held|"
     r"winner|winning goal|decider|decisive|clincher",
     "claims what the score did later"),
    (r"overturn\w*|turn(?:s|ed)? the (?:game|match|tide)|comeback",
     "claims what happened later in the match"),
    # Position wording worked out from coordinates.
    (r"central(?:ly)?|tight angle|angled", "position wording not in the facts"),
    # Comparisons with the rest of the match (counter_rank is phrased by the model as "fastest").
    (r"best|biggest|clearest|greatest|most dangerous|so far|at that point",
     "compares with the rest of the match"),
    # Durations must be written as "7-second" / "5-minute".
    (r"\d+(?:\.\d+)? seconds?", 'write durations as "7-second"'),
    (r"\d+ minutes?", 'write durations as "5-minute"'),
    # Field names leaking into the text.
    (r"[a-z]+(?:_[a-z]+)+", "field name in the text"),
]

SHOT_CATEGORIES = {"goal", "save", "big_chance_missed"}


def fact_rules(facts: dict) -> list:
    """Blocked phrases that depend on this moment's facts."""
    rules = []
    action = (facts.get("facts") or {}).get("action_type", facts.get("action_type"))
    if action != "carry":
        rules.append((r"carr(?:y|ies|ied|ying)", "the action was not a carry (see action_type)"))
    if action == "carry":
        rules.append((r"pass(?:es|ed|ing)?", "the action was a carry, not a pass (see action_type)"))
    if facts.get("category") not in SHOT_CATEGORIES:
        rules.append((r"chances?|opportunit(?:y|ies)", "only a shot is a chance"))
    return rules


# A score ("1-0") and a minute ("61st") count as one number each.
_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?")


@dataclass
class StyleResult:
    passed: bool
    offending: list = field(default_factory=list)  # [{"type": "style", "value": ..., "reason": ...}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "offending": self.offending}


def check(output, facts: dict) -> StyleResult:
    rules = [(re.compile(rf"(?<![\w-]){p}(?![\w-])", re.I), why) for p, why in BLOCKED + fact_rules(facts)]
    offending = []
    for key, text in _texts(output):
        for pattern, why in rules:
            for m in pattern.finditer(text):
                item = {"type": "style", "value": m.group(0), "reason": why}
                if item not in offending:
                    offending.append(item)
        n = len(_NUMBER.findall(text))
        if n > MAX_NUMBERS:
            offending.append({"type": "style", "value": f"{key}: {n} numbers",
                              "reason": f"too many numbers (at most {MAX_NUMBERS})"})
    return StyleResult(passed=not offending, offending=offending)


def _texts(output, key=None):
    """(field name, string) for every string in output; numbers_used is skipped
    because it just repeats numbers from the text."""
    if key == "numbers_used":
        return
    if isinstance(output, str):
        yield key, output
    elif isinstance(output, dict):
        for k, v in output.items():
            yield from _texts(v, k)
    elif isinstance(output, (list, tuple)):
        for v in output:
            yield from _texts(v, key)
