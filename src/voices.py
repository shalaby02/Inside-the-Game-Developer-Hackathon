"""The Personalizer's two voices, as short trait descriptions.

A voice changes how the facts are said, never which facts are said. Each one
has the traits given to the model (TRAITS) and the limits checked in code
(LIMITS). No voice is based on a real commentator, and none uses a
commentator's signature phrase.

- max_sentences: per moment text (the recap has its own 3-5).
- max_sentence_words: words in one sentence, not counting the words of a fact
  phrase quoted in full (build_up, counter_label, score_effect, result_line),
  which must be word for word.
- max_exclamations: exclamation marks per text field.
"""

VOICES = {
    "studio": {
        "traits": """\
Studio voice: a calm presenter at the desk after the match.
- Pace: unhurried, explains one point at a time.
- Sentences: complete, medium length (about 12 to 25 words), joined smoothly.
- Emotional temperature: cool and measured; interest comes from the facts, not from excitement.
- Goals: announced plainly with what they did to the score, e.g. "Niko Vane scored to put London Blue 1-0 up."
- Saves: stated as who denied whom, e.g. "Ellis Harwick denied Niko Vane."
- No exclamation marks.""",
        "max_sentences": 2,
        "max_sentence_words": 40,
        "max_exclamations": 0,
    },
    "stadium": {
        "traits": """\
Stadium voice: live from the gantry, as the moment happens.
- Pace: quick, present tense is fine.
- Sentences: short and punchy, 3 to 12 words; a one- or two-word line is fine.
- Emotional temperature: high, excited, but the excitement is in the rhythm, never in new facts.
- Goals: a short burst first, then the fact, e.g. "Goal! Niko Vane scores! London Blue lead 1-0."
- Saves: a short burst, then who denied whom, e.g. "What a save! Ellis Harwick denies Niko Vane."
- Exclamation marks are welcome, up to 3 per text. Short words such as "What a save!" or "Goal!" are fine; never add a fact to sound exciting.""",
        "max_sentences": 4,
        "max_sentence_words": 14,
        "max_exclamations": 3,
    },
}

# Interjections the Stadium voice may start a line with. Grounding reads a
# capitalised word as a name, so these are passed to it as allowed words.
INTERJECTIONS = ["Goal", "Save", "What", "Wow", "Oh"]
