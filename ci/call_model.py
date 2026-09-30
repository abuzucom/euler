"""Send one review to the active model provider and return the report text.

The provider profile comes from ci/model_providers.json. Endpoints must
appear in ALLOWED_ENDPOINTS. The API key comes from MODEL_API_KEY and never
reaches logs or error messages.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

ALLOWED_ENDPOINTS = frozenset({"https://ollama.com/api", "https://api.openai.com/v1", "https://api.anthropic.com/v1"})
DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "model_providers.json"
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 600
ERROR_BODY_LIMIT = 500

Transport = Callable[[str, dict, dict], dict]


class ModelCallError(RuntimeError):
    """The provider call failed or returned an unusable response."""


def post_json(url: str, headers: dict, body: dict) -> dict:
    """POST a JSON body and return the decoded JSON response."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={**headers, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:ERROR_BODY_LIMIT]
        raise ModelCallError(f"provider returned HTTP {error.code}: {detail}. Check the model and quota.") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ModelCallError(f"provider request failed: {error}. Retry the review run.") from error


def load_profile(profile_path: Path) -> dict:
    """Return the active provider profile after the allowlist check."""
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    profile = data["providers"][data["active_provider"]]
    if profile["endpoint"] not in ALLOWED_ENDPOINTS:
        raise ModelCallError(f"endpoint {profile['endpoint']} is not allowlisted. Use an endpoint in ALLOWED_ENDPOINTS.")
    return profile


def ollama_request(profile: dict, system_prompt: str, case_text: str, api_key: str) -> tuple[str, dict, dict]:
    """Return the URL, headers, and body for the Ollama chat API."""
    body = {
        "model": profile["model"],
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": case_text}],
        "options": {"temperature": 0, "num_predict": profile["max_output_tokens"]},
    }
    return f"{profile['endpoint']}/chat", {"Authorization": f"Bearer {api_key}"}, body


def openai_request(profile: dict, system_prompt: str, case_text: str, api_key: str) -> tuple[str, dict, dict]:
    """Return the URL, headers, and body for an OpenAI-compatible chat API."""
    body = {
        "model": profile["model"],
        "temperature": 0,
        "max_completion_tokens": profile["max_output_tokens"],
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": case_text}],
    }
    return f"{profile['endpoint']}/chat/completions", {"Authorization": f"Bearer {api_key}"}, body


def anthropic_request(profile: dict, system_prompt: str, case_text: str, api_key: str) -> tuple[str, dict, dict]:
    """Return the URL, headers, and body for the Anthropic Messages API."""
    body = {
        "model": profile["model"],
        "temperature": 0,
        "max_tokens": profile["max_output_tokens"],
        "system": system_prompt,
        "messages": [{"role": "user", "content": case_text}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    return f"{profile['endpoint']}/messages", headers, body


def extract_text(protocol: str, response: dict) -> str:
    """Return the text content of a provider response."""
    try:
        if protocol == "ollama":
            return response["message"]["content"]
        if protocol == "openai-compatible":
            return response["choices"][0]["message"]["content"]
        return "".join(block["text"] for block in response["content"] if block.get("type") == "text")
    except (KeyError, IndexError, TypeError) as error:
        raise ModelCallError(f"unexpected {protocol} response shape: missing {error}. Check the provider API.") from error


REQUEST_BUILDERS = {"ollama": ollama_request, "openai-compatible": openai_request, "anthropic": anthropic_request}


def call_model(
    system_prompt: str,
    mode: str,
    case_text: str,
    transport: Transport | None = None,
    profile_path: Path | None = None,
    api_key: str | None = None,
) -> str:
    """Return the model report for one review envelope."""
    profile = load_profile(profile_path or DEFAULT_PROFILE_PATH)
    key = os.environ.get("MODEL_API_KEY", "") if api_key is None else api_key
    if not key:
        raise ModelCallError("MODEL_API_KEY is empty. Map the provider secret to MODEL_API_KEY.")
    builder = REQUEST_BUILDERS.get(profile["protocol"])
    if builder is None:
        raise ModelCallError(f"unsupported protocol {profile['protocol']}. Use one of {sorted(REQUEST_BUILDERS)}.")
    url, headers, body = builder(profile, system_prompt, case_text, key)
    response = (transport or post_json)(url, headers, body)
    return extract_text(profile["protocol"], response)
