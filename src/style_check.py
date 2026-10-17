"""Style check: blocks wording the facts can't support, even when every name
and number in it is grounded (see src/grounding.py for those).

No model calls. The rules themselves live in src/style_rules.py, shared
with the agents' instructions; this file only applies them.

Use:  from style_check import check;  check(narration, facts).passed
"""

import re
from dataclasses import dataclass, field

from style_rules import BLOCKED, DURATION, MAX_NUMBERS, fact_rules

MIN_QUOTE_WORDS = 4  # a copied stretch of a fact phrase this long counts as a quote

# A score ("1-0") and a minute ("61st") count as one number each.
_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?")


def _compile(pattern):
    # Grouped, so the whole-word guards apply to every alternative in the pattern.
    return re.compile(rf"(?<![\w-])(?:{pattern})(?![\w-])", re.I)


_DURATION = _compile(DURATION[0])


@dataclass
class StyleResult:
    passed: bool
    offending: list = field(default_factory=list)  # [{"type": "style", "value": ..., "reason": ...}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "offending": self.offending}


def check(output, facts: dict, moment_rules: bool = True, extra_rules=()) -> StyleResult:
    """moment_rules=False skips fact_rules(), which only make sense for a text
    about one moment (its action_type and category); whole-match text such as
    the Analyst's phase notes leaves them out. extra_rules: more (pattern,
    reason) pairs, such as the Analyst's connectors. They are stricter than
    the other rules: they only skip a fact phrase quoted in full, so "London
    Red won 2-1 after London Blue scored first" is not excused by starting
    like a fact phrase."""
    rules = [(_compile(p), why) for p, why in BLOCKED + (fact_rules(facts) if moment_rules else [])]
    strict = [(_compile(p), why) for p, why in extra_rules]
    phrases = [s.lower() for s in _fact_strings(facts)]

    offending = []

    def flag(value, reason):
        item = {"type": "style", "value": value, "reason": reason}
        if item not in offending:
            offending.append(item)

    for key, text in _texts(output):
        for pattern, why in strict:
            for m in pattern.finditer(_mask_whole(text, phrases)):
                flag(m.group(0), why)
        text = _mask_quotes(text, phrases)
        for pattern, why in rules:
            for m in pattern.finditer(text):
                flag(m.group(0), why)
        for m in _DURATION.finditer(text):
            if not _as_in_facts(text, m, phrases):
                flag(m.group(0), DURATION[1])
        n = len(_NUMBER.findall(text))
        if n > MAX_NUMBERS:
            flag(f"{key}: {n} numbers", f"too many numbers (at most {MAX_NUMBERS})")
    return StyleResult(passed=not offending, offending=offending)


def _mask_whole(text, phrases):
    """Blank out every fact phrase quoted in full (any case), longest first so
    a short phrase ("London Red") can't break up a longer one."""
    for phrase in sorted(phrases, key=len, reverse=True):
        text = re.sub(re.escape(phrase), lambda m: " " * len(m.group(0)), text, flags=re.I)
    return text


def _mask_quotes(text, phrases):
    """Blank out every run of MIN_QUOTE_WORDS or more words copied from a fact
    phrase, so quoting build_up ("after 3 passes and a carry from midfield")
    is never blocked and its numbers don't count towards MAX_NUMBERS."""
    for phrase in phrases:
        words = re.findall(r"[\w'’-]+", phrase)
        for n in range(len(words), MIN_QUOTE_WORDS - 1, -1):
            for i in range(len(words) - n + 1):
                pattern = r"(?<![\w-])" + r"[\s,;:]+".join(map(re.escape, words[i:i + n])) + r"(?![\w-])"
                text = re.sub(pattern, lambda m: " " * len(m.group(0)), text, flags=re.I)
    return text


def _as_in_facts(text, m, phrases):
    """The duration and the word after it appear together in a fact phrase,
    e.g. "10 seconds later" from build_up. "10 seconds" alone does not count."""
    nxt = re.match(r"\s+(\w+)", text[m.end():])
    used = (m.group(0) + (" " + nxt.group(1) if nxt else "")).lower()
    return bool(nxt) and any(used in p for p in phrases)


def _fact_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _fact_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _fact_strings(v)


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
