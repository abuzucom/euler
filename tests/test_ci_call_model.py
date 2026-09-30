"""Tests for ci/call_model.py with the HTTP transport replaced by a stub."""

from __future__ import annotations

import contextlib
import io
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
            call_model.call_model(
                "p", "PR", "{}", transport=RecordingTransport({"x": 1}), profile_path=profile, api_key="k"
            )

    def test_repository_profile_is_allowlisted(self) -> None:
        data = json.loads((REPO_ROOT / "ci" / "model_providers.json").read_text(encoding="utf-8"))
        self.assertEqual(data["active_provider"], "ollama")
        for profile in data["providers"].values():
            self.assertIn(profile["endpoint"], call_model.ALLOWED_ENDPOINTS)


class EmptyOutputTest(unittest.TestCase):
    """Reasoning models must not exhaust the budget. Empty text must fail loudly."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def write_profile(self, provider: str, endpoint: str) -> Path:
        """Write a provider profile file and return its path."""
        path = Path(self.temp_dir.name) / "providers.json"
        profile = {"protocol": provider, "endpoint": endpoint, "model": "m", "max_output_tokens": 64}
        path.write_text(json.dumps({"active_provider": provider, "providers": {provider: profile}}), encoding="utf-8")
        return path

    def call(self, provider: str, endpoint: str, response: dict) -> tuple[str, RecordingTransport]:
        """Call the model through a recording transport."""
        transport = RecordingTransport(response)
        profile_path = self.write_profile(provider, endpoint)
        options = call_model.CallOptions(transport=transport, profile_path=profile_path, api_key="k")
        return call_model.call_model("p", "PR", "{}", options=options), transport

    def test_ollama_disables_thinking(self) -> None:
        _, transport = self.call("ollama", "https://ollama.com/api", {"message": {"content": "ok"}})
        self.assertIs(transport.requests[0][2]["think"], False)

    def test_empty_ollama_content_rejected(self) -> None:
        with self.assertRaises(call_model.ModelCallError):
            self.call("ollama", "https://ollama.com/api", {"message": {"content": "", "thinking": "long reasoning"}})

    def test_whitespace_anthropic_text_rejected(self) -> None:
        with self.assertRaises(call_model.ModelCallError):
            self.call("anthropic", "https://api.anthropic.com/v1", {"content": [{"type": "text", "text": "  \n"}]})


class FakeResponse:
    """Minimal http.client response stand-in."""

    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeConnection:
    """Record one HTTPS request and return a canned response."""

    instances: list[FakeConnection] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.requests: list[tuple[str, str, bytes, dict]] = []
        self.closed = False
        self.response = FakeResponse(200, b'{"message": {"content": "ok"}}')
        self.error: Exception | None = None
        FakeConnection.instances.append(self)

    def request(self, method: str, path: str, body: bytes, headers: dict) -> None:
        if self.error is not None:
            raise self.error
        self.requests.append((method, path, body, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class PostJsonTest(unittest.TestCase):
    """post_json sends HTTPS requests through http.client."""

    def setUp(self) -> None:
        FakeConnection.instances = []

    def test_posts_json_to_https_host_and_path(self) -> None:
        result = call_model.post_json(
            "https://ollama.com/api/chat", {"Authorization": "Bearer k"}, {"a": 1}, connection_factory=FakeConnection
        )
        connection = FakeConnection.instances[0]
        method, path, body, headers = connection.requests[0]
        self.assertEqual(result, {"message": {"content": "ok"}})
        self.assertEqual((connection.host, connection.port), ("ollama.com", 443))
        self.assertEqual((method, path), ("POST", "/api/chat"))
        self.assertEqual(json.loads(body), {"a": 1})
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertTrue(connection.closed)

    def test_non_https_url_rejected_before_connecting(self) -> None:
        with self.assertRaises(call_model.ModelCallError):
            call_model.post_json("http://ollama.com/api/chat", {}, {}, connection_factory=FakeConnection)
        self.assertEqual(FakeConnection.instances, [])

    def test_http_error_status_raises(self) -> None:
        def failing_factory(host: str, port: int, timeout: float) -> FakeConnection:
            connection = FakeConnection(host, port, timeout)
            connection.response = FakeResponse(503, b"overloaded")
            return connection

        with self.assertRaises(call_model.ModelCallError) as context:
            call_model.post_json("https://ollama.com/api/chat", {}, {}, connection_factory=failing_factory)
        self.assertIn("503", str(context.exception))
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_http_error_body_kept_out_of_message(self) -> None:
        def failing_factory(host: str, port: int, timeout: float) -> FakeConnection:
            connection = FakeConnection(host, port, timeout)
            connection.response = FakeResponse(402, b"org acme-corp quota exhausted\n::set-output name=x::y")
            return connection

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(call_model.ModelCallError) as context:
            call_model.post_json("https://ollama.com/api/chat", {}, {}, connection_factory=failing_factory)
        self.assertIn("402", str(context.exception))
        self.assertNotIn("acme-corp", str(context.exception))
        self.assertIn("acme-corp", stderr.getvalue())
        self.assertFalse([line for line in stderr.getvalue().splitlines() if line.startswith("::")])

    def test_network_error_raises(self) -> None:
        def broken_factory(host: str, port: int, timeout: float) -> FakeConnection:
            connection = FakeConnection(host, port, timeout)
            connection.error = OSError("connection reset")
            return connection

        with self.assertRaises(call_model.ModelCallError):
            call_model.post_json("https://ollama.com/api/chat", {}, {}, connection_factory=broken_factory)
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_invalid_json_raises(self) -> None:
        def garbage_factory(host: str, port: int, timeout: float) -> FakeConnection:
            connection = FakeConnection(host, port, timeout)
            connection.response = FakeResponse(200, b"not json")
            return connection

        with self.assertRaises(call_model.ModelCallError):
            call_model.post_json("https://ollama.com/api/chat", {}, {}, connection_factory=garbage_factory)


class CallOptionsTest(unittest.TestCase):
    """The options object and the deprecation shim for the old parameters."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.profile = Path(self.temp_dir.name) / "providers.json"
        profile = {"protocol": "ollama", "endpoint": "https://ollama.com/api", "model": "m", "max_output_tokens": 64}
        self.profile.write_text(
            json.dumps({"active_provider": "ollama", "providers": {"ollama": profile}}), encoding="utf-8"
        )
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
