"""Smoke test: call the deployed Foundry chat model and print its reply.

Reads FOUNDRY_ENDPOINT, FOUNDRY_DEPLOYMENT and FOUNDRY_API_KEY from .env.
Uses the OpenAI SDK against the resource's /openai/v1 endpoint, which is what
Microsoft's Foundry docs recommend for Chat Completions with an API key.
"""

import os
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import NotFoundError, OpenAI

PROMPT = "Say hello in English and Arabic."


def openai_base_url(endpoint: str) -> str:
    """Turn any Foundry endpoint form into https://<host>/openai/v1/.

    Accepts the bare resource URL, a project URL (/api/projects/<name>) or a
    URL that already ends in /openai/v1.
    """
    parts = urlsplit(endpoint.strip())
    if not parts.scheme or not parts.netloc:
        sys.exit("FOUNDRY_ENDPOINT must be a full URL, e.g. https://<resource>.services.ai.azure.com/")
    return f"{parts.scheme}://{parts.netloc}/openai/v1/"


def main() -> None:
    load_dotenv()

    missing = [name for name in ("FOUNDRY_ENDPOINT", "FOUNDRY_DEPLOYMENT", "FOUNDRY_API_KEY") if not os.getenv(name)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    client = OpenAI(
        base_url=openai_base_url(os.environ["FOUNDRY_ENDPOINT"]),
        api_key=os.environ["FOUNDRY_API_KEY"],
    )

    deployment = os.environ["FOUNDRY_DEPLOYMENT"]
    try:
        response = client.chat.completions.create(
            model=deployment,  # the deployment name, not the model family
            messages=[{"role": "user", "content": PROMPT}],
        )
    except NotFoundError:
        sys.exit(
            f"Deployment '{deployment}' not found on this resource. Set FOUNDRY_DEPLOYMENT to the "
            "'Name' shown under Models + endpoints in the Foundry portal."
        )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
