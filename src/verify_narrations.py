"""Verify data/narrations.json as it is now, with no model calls.

For every moment in data/key_moments.json, runs the same checks the Narrator
runs on the model's output (narrator.run_checks) on the narration saved in
the file, including hand edits: format (at most 2 sentences, the save
headline, the team named in momentum shifts, build_up word for word,
counter_label on counter goals), grounding, style and polish.

Reads only; never writes either file and never imports the model client.

Run:  python src/verify_narrations.py      (exit code 1 if any moment fails)
"""

import json
import sys
from pathlib import Path

from narrator import flagged, moment_input, run_checks

ROOT = Path(__file__).resolve().parent.parent
MOMENTS_PATH = ROOT / "data" / "key_moments.json"
NARRATIONS_PATH = ROOT / "data" / "narrations.json"


def manually_edited(entry: dict) -> bool:
    """The saved text differs from what the model last generated."""
    attempts = entry.get("attempts") or []
    return bool(entry.get("manually_edited")) or bool(attempts and entry.get("narration") != attempts[-1]["narration"])


def verify(moments: list, narrations: dict) -> list:
    """[(moment id, passed, notes, flagged lines)] in match order."""
    results = []
    for moment in moments:
        entry = narrations.get(moment["id"])
        if not entry or not entry.get("narration"):
            results.append((moment["id"], False, [], ["no narration saved"]))
            continue
        checks = run_checks(entry["narration"], moment_input(moment))
        notes = ["manually edited"] if manually_edited(entry) else []
        results.append((moment["id"], checks["passed"], notes, flagged(checks)))
    return results


def main() -> int:
    moments = json.loads(MOMENTS_PATH.read_text(encoding="utf-8"))["moments"]
    narrations = {n["id"]: n for n in json.loads(NARRATIONS_PATH.read_text(encoding="utf-8"))["narrations"]}

    results = verify(moments, narrations)
    for moment_id, passed, notes, lines in results:
        print(f"{moment_id}: {'PASS' if passed else 'FAIL'}" + (f" ({', '.join(notes)})" if notes else ""))
        for line in lines:
            print(f"    {line}")
    extra = sorted(set(narrations) - {m["id"] for m in moments})
    if extra:
        print(f"Narrations with no matching moment (ignored): {', '.join(extra)}")

    failed = [r[0] for r in results if not r[1]]
    edited = [r[0] for r in results if r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} pass."
          + (f" Failed: {', '.join(failed)}." if failed else "")
          + (f" Manually edited: {', '.join(edited)}." if edited else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
