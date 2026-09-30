"""Send one review to the active model provider and return the report text.

The provider profile comes from ci/model_providers.json. Endpoints must
appear in ALLOWED_ENDPOINTS. The API key comes from MODEL_API_KEY and never
reaches logs or error messages.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.parse
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ALLOWED_ENDPOINTS = frozenset({"https://ollama.com/api", "https://api.openai.com/v1", "https://api.anthropic.com/v1"})
DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "model_providers.json"
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 600
ERROR_BODY_LIMIT = 500
HTTPS_PORT = 443
HTTP_ERROR_MIN_STATUS = 400

Transport = Callable[[str, dict, dict], dict]
ConnectionFactory = Callable[[str, int, float], http.client.HTTPSConnection]


class ModelCallError(RuntimeError):
    """The provider call failed or returned an unusable response."""


def open_https_connection(host: str, port: int, timeout: float) -> http.client.HTTPSConnection:
    """Return an HTTPS connection with default certificate verification."""
    return http.client.HTTPSConnection(host, port, timeout=timeout)


def post_json(
    url: str, headers: dict, body: dict, connection_factory: ConnectionFactory = open_https_connection
) -> dict:
    """POST a JSON body over HTTPS and return the decoded JSON response."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ModelCallError(f"provider URL must use https: {url}. Fix the endpoint in model_providers.json.")
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    payload = json.dumps(body).encode("utf-8")
    connection = connection_factory(parts.hostname, parts.port or HTTPS_PORT, REQUEST_TIMEOUT_SECONDS)
    try:
        connection.request("POST", path, body=payload, headers={**headers, "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read()
    except (OSError, http.client.HTTPException) as error:
        raise ModelCallError(f"provider request failed: {error}. Retry the review run.") from error
    finally:
        connection.close()
    if response.status >= HTTP_ERROR_MIN_STATUS:
        detail = raw.decode("utf-8", errors="replace")[:ERROR_BODY_LIMIT]
        raise ModelCallError(f"provider returned HTTP {response.status}: {detail}. Check the model and quota.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelCallError(f"provider response is not JSON: {error}. Retry the review run.") from error


def load_profile(profile_path: Path) -> dict:
    """Return the active provider profile after the allowlist check."""
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    profile = data["providers"][data["active_provider"]]
    if profile["endpoint"] not in ALLOWED_ENDPOINTS:
        raise ModelCallError(
            f"endpoint {profile['endpoint']} is not allowlisted. Use an endpoint in ALLOWED_ENDPOINTS."
        )
    return profile


def ollama_request(profile: dict, system_prompt: str, case_text: str, api_key: str) -> tuple[str, dict, dict]:
    """Return the URL, headers, and body for the Ollama chat API."""
    body = {
        "model": profile["model"],
        "stream": False,
        # Reasoning models otherwise spend num_predict on thinking and return empty content.
        "think": False,
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


def read_text_field(protocol: str, response: dict) -> str:
    """Return the raw text field of a provider response."""
    try:
        if protocol == "ollama":
            return response["message"]["content"]
        if protocol == "openai-compatible":
            return response["choices"][0]["message"]["content"]
        return "".join(block["text"] for block in response["content"] if block.get("type") == "text")
    except (KeyError, IndexError, TypeError) as error:
        raise ModelCallError(
            f"unexpected {protocol} response shape: missing {error}. Check the provider API."
        ) from error


def extract_text(protocol: str, response: dict) -> str:
    """Return the non-empty text content of a provider response."""
    text = read_text_field(protocol, response)
    if not isinstance(text, str) or not text.strip():
        raise ModelCallError(f"{protocol} response has no text content. Check the output token budget and model.")
    return text


REQUEST_BUILDERS = {"ollama": ollama_request, "openai-compatible": openai_request, "anthropic": anthropic_request}


@dataclass(frozen=True)
class CallOptions:
    """Optional overrides for one model call."""

    transport: Transport | None = None
    profile_path: Path | None = None
    api_key: str | None = None


LEGACY_OPTION_NAMES = ("transport", "profile_path", "api_key")


def resolve_options(options: CallOptions | None, legacy_positional: tuple, legacy_keywords: dict) -> CallOptions:
    """Return call options. Accept the pre-0.3.0 parameters with a DeprecationWarning."""
    if len(legacy_positional) > len(LEGACY_OPTION_NAMES):
        raise TypeError(f"call_model takes at most {len(LEGACY_OPTION_NAMES) + 3} positional arguments")
    unknown = sorted(set(legacy_keywords) - set(LEGACY_OPTION_NAMES))
    if unknown:
        raise TypeError(f"call_model got unexpected keyword arguments: {', '.join(unknown)}")
    legacy = dict(zip(LEGACY_OPTION_NAMES, legacy_positional, strict=False))
    duplicated = sorted(set(legacy) & set(legacy_keywords))
    if duplicated:
        raise TypeError(f"call_model got multiple values for: {', '.join(duplicated)}")
    legacy.update(legacy_keywords)
    if not legacy:
        return options or CallOptions()
    if options is not None:
        raise TypeError("pass options or the deprecated transport, profile_path, and api_key arguments, not both")
    warnings.warn(
        "call_model transport, profile_path, and api_key arguments are deprecated. Pass options=CallOptions(...).",
        DeprecationWarning,
        stacklevel=3,
    )
    return CallOptions(**legacy)


def call_model(
    system_prompt: str,
    mode: str,
    case_text: str,
    *legacy_positional: object,
    options: CallOptions | None = None,
    **legacy_keywords: object,
) -> str:
    """Return the model report for one review envelope.

    The transport, profile_path, and api_key parameters from 0.2.0 still work
    by position or keyword and emit a DeprecationWarning.
    """
    resolved = resolve_options(options, legacy_positional, legacy_keywords)
    profile = load_profile(resolved.profile_path or DEFAULT_PROFILE_PATH)
    key = os.environ.get("MODEL_API_KEY", "") if resolved.api_key is None else resolved.api_key
    if not key:
        raise ModelCallError("MODEL_API_KEY is empty. Map the provider secret to MODEL_API_KEY.")
    builder = REQUEST_BUILDERS.get(profile["protocol"])
    if builder is None:
        raise ModelCallError(f"unsupported protocol {profile['protocol']}. Use one of {sorted(REQUEST_BUILDERS)}.")
    url, headers, body = builder(profile, system_prompt, case_text, key)
    response = (resolved.transport or post_json)(url, headers, body)
    return extract_text(profile["protocol"], response)
