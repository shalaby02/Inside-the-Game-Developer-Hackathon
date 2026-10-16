"""Grounding check: does an agent's text only use names, numbers and minutes
from its facts?

No model calls. Works for any agent: pass the agent's output (a string, or
any JSON-like dict/list, every string in it is checked) and the facts the
agent was given (any JSON-like object).

What counts as allowed:
- numbers: every number anywhere in the facts, including numbers inside
  fact strings ("scored 10 seconds later", "two counter-attacks"), compared by value, so "8"
  matches 8.0 and "0.30" matches 0.3, but "0.08" does not match 0.0758 and
  "30%" does not match 0.3. Signs are ignored, so "-0.0002" and "0.0002"
  both match -0.0002. Scores like "1-0" and times like "61:14" are read as
  separate numbers.
- minutes: a minute mention ("61st minute", "minute 61", "61'") must match a
  minute field in the facts: a key named "minute" or ending in "_minute".
  A duration ("5 minutes", "5-minute blocks") is checked as a plain number
  instead.
- names: capitalised words are read as names. A run of them ("Cass Dunmore")
  must be a run of capitalised words in a fact string ("Cass Dunmore",
  "put London Blue 1-0 up"), and a single capitalised word ("Dunmore") must
  be one of those words. Common words that start a sentence
  ("The", "After") are skipped.

Run the tests:  python -m pytest tests/test_grounding.py
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}  # "one" is left out: "one of", "no one" are not numbers

# Capitalised words that are not names when they start a sentence (or a run).
COMMON_WORDS = {
    "a", "an", "the", "this", "that", "these", "those", "it", "its", "his", "her", "their",
    "they", "he", "she", "we", "you", "i", "there", "here", "what", "why", "how", "when",
    "where", "who", "which", "while", "after", "before", "with", "without", "in", "on", "at",
    "from", "by", "for", "of", "to", "into", "onto", "over", "under", "inside", "within",
    "between", "across", "through", "during", "until", "since", "as", "but", "and", "or",
    "yet", "so", "then", "now", "just", "only", "even", "still", "again", "once", "every",
    "each", "both", "all", "no", "not", "nothing", "never", "one", "another", "more", "most",
    "less", "much", "many", "few", "first", "second", "third", "last", "late", "early",
    "half", "big", "huge", "great", "good", "real", "pure", "sheer", "clinical", "brilliant",
    "superb", "vital", "crucial", "key", "top", "high", "low", "long", "short", "fast",
    "quick", "deep", "close", "near", "far", "back", "up", "down", "out", "off", "away",
    "home", "goal", "save", "shot", "chance", "miss", "pass", "carry", "counter", "threat",
    "momentum", "pressure", "control", "danger", "denied", "stopped", "level", "lead",
    "winner", "equaliser", "opener", "breakthrough", "turning", "point", "game", "match",
    "minute", "minutes", "seconds", "moment", "move", "run", "spell", "block", "blocks",
    "zone", "box", "area", "value", "expected", "metres", "meters", "if", "because", "although",
    "though", "despite", "against", "behind", "ahead", "beyond", "around", "about", "like",
    "is", "was", "are", "were", "be", "been", "has", "had", "have", "do", "did", "does",
    "can", "could", "would", "should", "will", "must", "may", "might", "make", "makes",
    "made", "take", "takes", "took", "keep", "keeps", "kept", "hold", "holds", "held",
    "win", "wins", "won", "lose", "lost", "score", "scores", "scored", "keeper", "striker",
}

_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])")
_MINUTE_PATTERNS = [
    re.compile(r"(?<![\d.])(\d+)(?:st|nd|rd|th)\s+minute\b", re.I),           # 61st minute
    re.compile(r"\bminute\s+(\d+)\b", re.I),                                  # minute 61
    re.compile(r"(?<![\d.])(\d+)['’](?![a-z])", re.I),                        # 61'
]
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_CAPITAL_RUN = re.compile(r"[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)*")
_SENTENCE_END = re.compile(r"[.!?:;\"“(\[—–]\s*$")


@dataclass
class GroundingResult:
    passed: bool
    offending: list = field(default_factory=list)  # [{"type": ..., "value": ..., "reason": ...}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "offending": self.offending}


def check(output, facts, extra_names=()) -> GroundingResult:
    """Check every string (and number) in output against facts.

    extra_names: names an agent may use that are not strings in facts.
    """
    allowed_numbers, allowed_minutes, name_strings = _collect(facts)
    name_strings += list(extra_names)
    # Only capitalised words in the facts count as names, so a phrase such as
    # "won the ball back in midfield" doesn't make "Midfield" a name.
    names = [[re.sub(r"['’]s?$", "", w) for w in run.split()]
             for n in name_strings for run in _CAPITAL_RUN.findall(n)]
    name_words = {w.lower() for n in names for w in n}

    offending = []

    def flag(kind, value, reason):
        item = {"type": kind, "value": value, "reason": reason}
        if item not in offending:
            offending.append(item)

    for text in _strings(output):
        for value, minute in _minutes(text):
            if minute not in allowed_minutes:
                flag("minute", value, "minute not in facts")
        for value, number in _numbers(text):
            if abs(number) not in allowed_numbers:
                flag("number", value, "number not in facts")
        for run in _name_runs(text):
            if not _name_ok(run, names, name_words):
                flag("name", " ".join(run), "name not in facts")

    return GroundingResult(passed=not offending, offending=offending)


# ---------------------------------------------------------------- facts side

def _collect(facts):
    numbers, minutes, strings = set(), set(), []

    def walk(obj, key=None):
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            numbers.add(abs(_dec(obj)))
            if key is not None and (key == "minute" or key.endswith("_minute")):
                minutes.add(_dec(obj))
        elif isinstance(obj, str):
            strings.append(obj)
            # numbers inside code-derived phrases, e.g. "scored 10 seconds later", "put London Blue 1-0 up"
            for _, n in _numbers(obj):
                numbers.add(abs(n))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, str(k))
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, key)

    walk(facts)
    return numbers, minutes, strings


def _dec(x) -> Decimal:
    return Decimal(str(x)).normalize()


# ---------------------------------------------------------------- output side

def _strings(output):
    if isinstance(output, str):
        yield output
    elif isinstance(output, bool) or output is None:
        return
    elif isinstance(output, (int, float)):
        yield str(output)
    elif isinstance(output, dict):
        for v in output.values():
            yield from _strings(v)
    elif isinstance(output, (list, tuple)):
        for v in output:
            yield from _strings(v)


def _numbers(text):
    for m in _NUMBER.finditer(text):
        try:
            yield m.group(0), _dec(m.group(0))
        except InvalidOperation:
            continue
    for m in _WORD.finditer(text):
        n = NUMBER_WORDS.get(m.group(0).lower())
        if n is not None:
            yield m.group(0), Decimal(n)


def _minutes(text):
    for pattern in _MINUTE_PATTERNS:
        for m in pattern.finditer(text):
            yield m.group(0), _dec(m.group(1))


def _name_runs(text):
    """Runs of capitalised words, minus leading common words at a sentence start."""
    words = list(_WORD.finditer(text))
    run, runs = [], []
    for i, m in enumerate(words):
        word = re.sub(r"['’]s$|['’]$", "", m.group(0))  # Dunmore's -> Dunmore
        # A possessive ends a name: "London Blue's Bram Hollis" is two names.
        joined = (run and text[words[i - 1].end():m.start()] == " "
                  and not re.search(r"['’]s?$", words[i - 1].group(0)))
        if word[0].isupper() and (not run or joined):
            run.append((word, m.start()))
            continue
        if run:
            runs.append(run)
        run = [(word, m.start())] if word[0].isupper() else []
    if run:
        runs.append(run)

    for run in runs:
        sentence_start = _SENTENCE_END.search(text[:run[0][1]]) or not text[:run[0][1]].strip()
        tokens = [w for w, _ in run]
        # Common words are only skipped at the start of a run (or a sentence):
        # "The London Red side" -> ["London", "Red"].
        while tokens and tokens[0].lower() in COMMON_WORDS:
            tokens.pop(0)
            sentence_start = True
        if not tokens:
            continue
        if len(tokens) == 1 and sentence_start and _looks_like_word(tokens[0]):
            continue
        yield tokens


def _looks_like_word(word):
    w = word.lower()
    return w in COMMON_WORDS or (len(w) > 4 and w.endswith(("ing", "ly", "ed")))


def _name_ok(tokens, names, name_words):
    if len(tokens) == 1:
        return tokens[0].lower() in name_words
    low = [t.lower() for t in tokens]
    for name in names:
        n = [w.lower() for w in name]
        for start in range(len(n) - len(low) + 1):
            if n[start:start + len(low)] == low:
                return True
    return False
