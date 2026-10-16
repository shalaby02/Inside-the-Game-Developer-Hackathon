"""Polish check: writing slips that are neither ungrounded nor blocked style,
such as a doubled word or a missing full stop.

No model calls. Edit CLUMSY to add or remove phrases: each entry is a
regular expression (matched case-insensitively, on whole words) and the
reason shown to the model when it retries.

Use:  from polish_check import check;  check(narration).passed
"""

import re
from dataclasses import dataclass, field

CLUMSY = [
    (r"pass(?:es|ed)? the (?:key )?pass", 'say "made the key pass" or "passed"'),
    (r"near[- ]range", 'not a football phrase; give the distance in metres'),
]

# Fields that must read as full sentences: they end with . ! or ?
SENTENCE_FIELDS = ("explanation",)

_REPEATED = re.compile(r"\b(\w+)\s+\1\b", re.I)  # "the the"


@dataclass
class PolishResult:
    passed: bool
    offending: list = field(default_factory=list)  # [{"type": "polish", "value": ..., "reason": ...}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "offending": self.offending}


def check(output, sentence_fields=SENTENCE_FIELDS) -> PolishResult:
    rules = [(re.compile(rf"(?<![\w-])(?:{p})(?![\w-])", re.I), why) for p, why in CLUMSY]
    offending = []
    for key, text in _texts(output):
        for m in _REPEATED.finditer(text):
            offending.append({"type": "polish", "value": m.group(0), "reason": "repeated word"})
        for pattern, why in rules:
            for m in pattern.finditer(text):
                offending.append({"type": "polish", "value": m.group(0), "reason": why})
        if key in sentence_fields and not re.search(r"[.!?][\"”’')]*\s*$", text):
            offending.append({"type": "polish", "value": f"{key}: ...{text.strip()[-20:]}",
                              "reason": "missing final punctuation"})
    return PolishResult(passed=not offending, offending=offending)


def _texts(output, key=None):
    """(field name, string) for every string in output, skipping numbers_used."""
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
