"""Tests for ci/call_model.py with the HTTP transport replaced by a stub."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ci import call_model  # resolved through the path set above


class RecordingTransport:
    """Capture one request and return a canned response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.requests: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, headers: dict, body: dict) -> dict:
        self.requests.append((url, headers, body))
        return self.response


class CallModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def write_profile(self, provider: str, endpoint: str, protocol: str | None = None) -> Path:
        """Write a provider profile file and return its path."""
        path = Path(self.temp_dir.name) / "providers.json"
        profile = {"protocol": protocol or provider, "endpoint": endpoint, "model": "m", "max_output_tokens": 64}
        path.write_text(json.dumps({"active_provider": provider, "providers": {provider: profile}}), encoding="utf-8")
        return path

    def test_ollama_request_shape(self) -> None:
        transport = RecordingTransport({"message": {"content": "VERDICT: APPROVE - ok"}})
        profile = self.write_profile("ollama", "https://ollama.com/api")
        text = call_model.call_model("policy", "PR", "{}", transport=transport, profile_path=profile, api_key="k")
        url, headers, body = transport.requests[0]
        self.assertEqual(text, "VERDICT: APPROVE - ok")
        self.assertEqual(url, "https://ollama.com/api/chat")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "policy"})
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertFalse(body["stream"])

    def test_anthropic_request_shape(self) -> None:
        transport = RecordingTransport({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]})
        profile = self.write_profile("anthropic", "https://api.anthropic.com/v1")
        text = call_model.call_model("policy", "PR", "{}", transport=transport, profile_path=profile, api_key="k")
        url, headers, body = transport.requests[0]
        self.assertEqual(text, "ab")
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "k")
        self.assertEqual(body["system"], "policy")
        self.assertEqual(body["temperature"], 0)

    def test_openai_compatible_request_shape(self) -> None:
        transport = RecordingTransport({"choices": [{"message": {"content": "done"}}]})
        profile = self.write_profile("openai-compatible", "https://api.openai.com/v1")
        text = call_model.call_model("policy", "PR", "{}", transport=transport, profile_path=profile, api_key="k")
        self.assertEqual(text, "done")
        self.assertEqual(transport.requests[0][0], "https://api.openai.com/v1/chat/completions")

    def test_endpoint_outside_allowlist_rejected(self) -> None:
        profile = self.write_profile("ollama", "https://attacker.example/api")
        transport = RecordingTransport({})
        with self.assertRaises(call_model.ModelCallError):
            call_model.call_model("p", "PR", "{}", transport=transport, profile_path=profile, api_key="k")
        self.assertEqual(transport.requests, [])

    def test_missing_key_rejected(self) -> None:
        profile = self.write_profile("ollama", "https://ollama.com/api")
        with self.assertRaises(call_model.ModelCallError):
            call_model.call_model("p", "PR", "{}", transport=RecordingTransport({}), profile_path=profile, api_key="")

    def test_unexpected_response_rejected(self) -> None:
        profile = self.write_profile("ollama", "https://ollama.com/api")
        with self.assertRaises(call_model.ModelCallError):
            call_model.call_model("p", "PR", "{}", transport=RecordingTransport({"x": 1}), profile_path=profile, api_key="k")

    def test_repository_profile_is_allowlisted(self) -> None:
        data = json.loads((REPO_ROOT / "ci" / "model_providers.json").read_text(encoding="utf-8"))
        self.assertEqual(data["active_provider"], "ollama")
        for profile in data["providers"].values():
            self.assertIn(profile["endpoint"], call_model.ALLOWED_ENDPOINTS)


class CallOptionsTest(unittest.TestCase):
    """The options object and the deprecation shim for the old parameters."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.profile = Path(self.temp_dir.name) / "providers.json"
        profile = {"protocol": "ollama", "endpoint": "https://ollama.com/api", "model": "m", "max_output_tokens": 64}
        self.profile.write_text(json.dumps({"active_provider": "ollama", "providers": {"ollama": profile}}), encoding="utf-8")
        self.response = {"message": {"content": "ok"}}

    def test_options_object(self) -> None:
        transport = RecordingTransport(self.response)
        options = call_model.CallOptions(transport=transport, profile_path=self.profile, api_key="k")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertEqual(call_model.call_model("p", "PR", "{}", options=options), "ok")
        self.assertEqual(transport.requests[0][1]["Authorization"], "Bearer k")

    def test_legacy_keywords_warn_and_work(self) -> None:
        transport = RecordingTransport(self.response)
        with self.assertWarns(DeprecationWarning):
            text = call_model.call_model("p", "PR", "{}", transport=transport, profile_path=self.profile, api_key="k")
        self.assertEqual(text, "ok")

    def test_legacy_positional_warn_and_work(self) -> None:
        transport = RecordingTransport(self.response)
        with self.assertWarns(DeprecationWarning):
            text = call_model.call_model("p", "PR", "{}", transport, self.profile, "k")
        self.assertEqual(text, "ok")

    def test_unknown_keyword_rejected(self) -> None:
        with self.assertRaises(TypeError):
            call_model.call_model("p", "PR", "{}", retries=3)

    def test_too_many_positional_rejected(self) -> None:
        with self.assertRaises(TypeError):
            call_model.call_model("p", "PR", "{}", None, None, "k", "extra")

    def test_options_with_legacy_rejected(self) -> None:
        options = call_model.CallOptions(api_key="k")
        with self.assertRaises(TypeError):
            call_model.call_model("p", "PR", "{}", options=options, api_key="k")


if __name__ == "__main__":
    unittest.main()
