"""Term-backing check: an analysis term is accepted only if the fact behind it
exists for what the text describes.

No model calls. The terms live in src/style_rules.py (TERMS, BANNED_TERMS),
shared with the Analyst's instructions; this file only applies them.

A text's subject is what it describes:
- moments: the key moments it is about (moment_input() dicts with "tags"
  and "facts"), e.g. the turning point's moment, or the moments a phase
  note cites.
- summary_keys: the match-summary fields it cites, e.g.
  {"final_third_entries"}.

So "transition" passes only if one of the subject's moments has the counter
tag, and "final-third entries" only if final_third_entries is cited. Banned
terms (xG, pressing, formations, ...) never pass.

Use:  from term_check import check;  check([(field, text, subject)]).passed
"""

import re
from dataclasses import dataclass, field

from style_rules import BANNED_TERMS, TERMS

THREAT_FACTS = {"xt_added", "key_pass_xt_added", "team_threat"}


def _compile(pattern):
    return re.compile(rf"(?<![\w-])(?:{pattern})(?![\w-])", re.I)


_BANNED = [(_compile(p), why) for p, why in BANNED_TERMS]
_TERMS = [(label, _compile(p), backing, need) for label, p, backing, need in TERMS]


@dataclass
class TermResult:
    passed: bool
    offending: list = field(default_factory=list)  # [{"type": "term", "value": ..., "reason": ...}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "offending": self.offending}


def subject(moments=(), summary_keys=()):
    return {"moments": list(moments), "summary_keys": set(summary_keys)}


def backed(backing: str, subj: dict) -> bool:
    """Does the subject have the fact this term needs?"""
    moments, keys = subj["moments"], subj["summary_keys"]
    build_ups = [m.get("facts", {}).get("build_up", "") for m in moments]
    facts = [m.get("facts", {}) for m in moments]
    if backing in ("final_third_entries", "progressive_actions"):
        return backing in keys
    if backing in ("penalty_area_entries", "penalty_area"):
        return "penalty_area_entries" in keys
    if backing == "final_third":
        return bool(keys & {"final_third_entries", "possessions_lost_in_final_third"}) or any(
            "attacking third" in b for b in build_ups)
    if backing == "middle_third":
        return any("midfield" in b for b in build_ups)
    if backing == "defensive_third":
        return any("defensive third" in b for b in build_ups)
    if backing == "possessions_lost":
        return "possessions_lost_in_final_third" in keys
    if backing == "counter":
        return any("counter" in m.get("tags", []) for m in moments)
    if backing == "build_up":
        return any(build_ups)
    if backing == "threat":
        return "threat_created" in keys or any(THREAT_FACTS & set(f) for f in facts)
    if backing == "shot_location":
        return any("shot_zone_value" in f for f in facts)
    raise ValueError(f"unknown backing {backing!r}")


def check(items) -> TermResult:
    """items: [(field name, text, subject)]."""
    offending = []

    def flag(where, value, reason):
        item = {"type": "term", "value": f"{where}: {value}", "reason": reason}
        if item not in offending:
            offending.append(item)

    for where, text, subj in items:
        for pattern, why in _BANNED:
            for m in pattern.finditer(text):
                flag(where, m.group(0), why)
        for label, pattern, backing, need in _TERMS:
            if not backed(backing, subj):
                for m in pattern.finditer(text):
                    flag(where, m.group(0), f'"{label}" needs {need} for what this text describes')
    return TermResult(passed=not offending, offending=offending)
