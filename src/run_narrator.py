"""Narrate every key moment and save the results to data/narrations.json.

Reads data/key_moments.json (never changes it) and FOUNDRY_ENDPOINT,
FOUNDRY_DEPLOYMENT and FOUNDRY_API_KEY from .env. The key is only handed to
the client, never printed or saved.

data/narrations.json is a cache: a moment that already passed with the same
input and instructions is skipped. Failed moments are tried again on the
next run.

Hand edits are kept: a moment whose saved text differs from what the model
last generated is marked "manually_edited": true and is never regenerated
by a normal run, even if its inputs change. Its text is re-checked (no model
call) and the results are saved with it, so a failing edit shows up.

--force redoes everything, hand edits included (it lists the edits it
overwrites). To check the file without any model call, use
src/verify_narrations.py.

Run:  python src/run_narrator.py [--force]
"""

import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from hello_foundry import openai_base_url
import polish_check
import style_rules
from narrator import INSTRUCTIONS, MODEL_PARAMS, OUTPUT_SCHEMA, flagged, moment_input, narrate, run_checks
from verify_narrations import manually_edited

ROOT = Path(__file__).resolve().parent.parent
MOMENTS_PATH = ROOT / "data" / "key_moments.json"
OUT_PATH = ROOT / "data" / "narrations.json"


def input_hash(moment: dict) -> str:
    """Changes when the moment, the instructions, the model settings or the check rules change."""
    blob = json.dumps([moment_input(moment), INSTRUCTIONS, MODEL_PARAMS, OUTPUT_SCHEMA, style_rules.BLOCKED,
                       style_rules.DURATION, style_rules.MAX_NUMBERS, polish_check.CLUMSY],
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_cache() -> dict:
    if not OUT_PATH.exists():
        return {}
    return {n["id"]: n for n in json.loads(OUT_PATH.read_text(encoding="utf-8"))["narrations"]}


def save(results: list, deployment: str) -> None:
    OUT_PATH.write_text(json.dumps({"model_deployment": deployment, "narrations": results},
                                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def keep_edit(moment: dict, cached: dict, h: str, log) -> dict:
    """A hand-edited moment: keep its text, re-check it, save the results with it."""
    checks = run_checks(cached["narration"], moment_input(moment))
    entry = {**cached, "manually_edited": True, "status": "ok" if checks["passed"] else "failed",
             **{k: checks[k] for k in ("format_problems", "grounding", "style", "polish")}}
    log(f"{moment['id']}: manually edited, kept; checks {'pass' if checks['passed'] else 'FAIL'}")
    for line in flagged(checks):
        log(f"    {line}")
    if cached.get("input_hash") != h:
        log("    note: its inputs have changed since it was generated; --force would regenerate it")
    return entry


def run(moments: list, cache: dict, narrate_one, force: bool = False, save_fn=lambda results: None,
        log=print) -> list:
    """Narrate what needs it and return every moment's entry. narrate_one(moment)
    is the only thing that calls the model; edited and cached moments never reach it."""
    results = []
    for moment in moments:
        h = input_hash(moment)
        cached = cache.get(moment["id"])
        if cached and not force and manually_edited(cached):
            results.append(keep_edit(moment, cached, h, log))
            continue
        if cached and not force and cached["status"] == "ok" and cached.get("input_hash") == h:
            log(f"{moment['id']}: cached")
            results.append(cached)
            continue
        if cached and force and manually_edited(cached):
            log(f"{moment['id']}: --force is overwriting a manual edit")
        try:
            result = narrate_one(moment)
        except OpenAIError as e:  # the message never includes the key
            result = {"id": moment["id"], "status": "failed", "narration": None, "grounding": None,
                      "style": None, "polish": None, "retries": 0, "attempts": [],
                      "error": f"{type(e).__name__}: {e}"}
        result["input_hash"] = h
        results.append(result)
        save_fn(results + [cache[m["id"]] for m in moments[len(results):] if m["id"] in cache])
        log(f"{moment['id']}: {result['status']}, {result['retries']} retr{'y' if result['retries'] == 1 else 'ies'}")
    save_fn(results)
    return results


def main() -> None:
    load_dotenv(ROOT / ".env")
    missing = [n for n in ("FOUNDRY_ENDPOINT", "FOUNDRY_DEPLOYMENT", "FOUNDRY_API_KEY") if not os.getenv(n)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    deployment = os.environ["FOUNDRY_DEPLOYMENT"]
    client = None

    def narrate_one(moment):
        nonlocal client
        if client is None:  # only connect if something actually needs the model
            client = OpenAI(base_url=openai_base_url(os.environ["FOUNDRY_ENDPOINT"]),
                            api_key=os.environ["FOUNDRY_API_KEY"])
        return narrate(client, deployment, moment)

    moments = json.loads(MOMENTS_PATH.read_text(encoding="utf-8"))["moments"]
    force = "--force" in sys.argv
    # --force still reads the file, but only to name the hand edits it overwrites
    results = run(moments, load_cache(), narrate_one, force=force,
                  save_fn=lambda results: save(results, deployment))
    failed = [r["id"] for r in results if r["status"] != "ok"]
    print(f"\n{len(results) - len(failed)}/{len(results)} narrated and grounded."
          + (f" Failed: {', '.join(failed)}" if failed else ""))
    print(f"Saved {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
