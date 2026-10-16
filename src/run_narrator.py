"""Narrate every key moment and save the results to data/narrations.json.

Reads data/key_moments.json (never changes it) and FOUNDRY_ENDPOINT,
FOUNDRY_DEPLOYMENT and FOUNDRY_API_KEY from .env. The key is only handed to
the client, never printed or saved.

data/narrations.json is a cache: a moment that already passed with the same
input and instructions is skipped. Failed moments are tried again on the
next run. Use --force to redo everything.

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
from narrator import INSTRUCTIONS, MODEL_PARAMS, OUTPUT_SCHEMA, moment_input, narrate
from style_check import BLOCKED, MAX_NUMBERS

ROOT = Path(__file__).resolve().parent.parent
MOMENTS_PATH = ROOT / "data" / "key_moments.json"
OUT_PATH = ROOT / "data" / "narrations.json"


def input_hash(moment: dict) -> str:
    """Changes when the moment, the instructions, the model settings or the style rules change."""
    blob = json.dumps([moment_input(moment), INSTRUCTIONS, MODEL_PARAMS, OUTPUT_SCHEMA, BLOCKED, MAX_NUMBERS],
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_cache() -> dict:
    if not OUT_PATH.exists():
        return {}
    return {n["id"]: n for n in json.loads(OUT_PATH.read_text(encoding="utf-8"))["narrations"]}


def save(results: list, deployment: str) -> None:
    OUT_PATH.write_text(json.dumps({"model_deployment": deployment, "narrations": results},
                                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    load_dotenv(ROOT / ".env")
    missing = [n for n in ("FOUNDRY_ENDPOINT", "FOUNDRY_DEPLOYMENT", "FOUNDRY_API_KEY") if not os.getenv(n)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    deployment = os.environ["FOUNDRY_DEPLOYMENT"]
    client = OpenAI(base_url=openai_base_url(os.environ["FOUNDRY_ENDPOINT"]),
                    api_key=os.environ["FOUNDRY_API_KEY"])

    moments = json.loads(MOMENTS_PATH.read_text(encoding="utf-8"))["moments"]
    cache = {} if "--force" in sys.argv else load_cache()

    results = []
    for moment in moments:
        h = input_hash(moment)
        cached = cache.get(moment["id"])
        if cached and cached["status"] == "ok" and cached.get("input_hash") == h:
            print(f"{moment['id']}: cached")
            results.append(cached)
            continue
        try:
            result = narrate(client, deployment, moment)
        except OpenAIError as e:  # the message never includes the key
            result = {"id": moment["id"], "status": "failed", "narration": None, "grounding": None,
                      "style": None, "retries": 0, "attempts": [], "error": f"{type(e).__name__}: {e}"}
        result["input_hash"] = h
        results.append(result)
        save(results + [cache[m["id"]] for m in moments[len(results):] if m["id"] in cache], deployment)
        print(f"{moment['id']}: {result['status']}, {result['retries']} retr{'y' if result['retries'] == 1 else 'ies'}")

    save(results, deployment)
    failed = [r["id"] for r in results if r["status"] != "ok"]
    print(f"\n{len(results) - len(failed)}/{len(results)} narrated and grounded."
          + (f" Failed: {', '.join(failed)}" if failed else ""))
    print(f"Saved {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
