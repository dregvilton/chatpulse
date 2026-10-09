"""Offline Ollama privacy gates tested with synthetic local HTTP replies only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chatpulse.ollama_local import (
    LocalModelError, OllamaHTTPError, OllamaLocal, assert_cloud_disabled,
    validate_local_model_name,
)


class FakeResponse:
    def __init__(self, data, *, status=200):
        self.status = status
        self.body = json.dumps(data).encode("utf-8")

    def read(self, max_bytes):
        return self.body[:max_bytes]


class FakeHttpConnection:
    created = []
    responses = []

    def __init__(self, host, port, *, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.requests = []
        FakeHttpConnection.created.append(self)

    def request(self, method, route, *, body, headers):
        self.requests.append((method, route, body, headers))

    def getresponse(self):
        return FakeHttpConnection.responses.pop(0)

    def close(self):
        pass


def tags(model="qwen3:4b", size=3_000_000_000, **extra):
    return {"models": [{"name": model, "size": size, **extra}]}


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "server.json"
        self.config.write_text('{"disable_ollama_cloud": true}', encoding="utf-8")
        FakeHttpConnection.created = []
        FakeHttpConnection.responses = []

    def gateway(self):
        return OllamaLocal(config_path=self.config)

    def test_no_cloud_config_refuses_before_network(self):
        self.config.unlink()
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   side_effect=AssertionError("must not connect")):
            with self.assertRaises(LocalModelError):
                self.gateway().local_models()
        self.config.write_text('{"disable_ollama_cloud": false}', encoding="utf-8")
        with self.assertRaises(LocalModelError):
            assert_cloud_disabled(self.config)

    def test_remote_and_cloud_models_are_excluded(self):
        FakeHttpConnection.responses = [
            FakeResponse({"models": [
                {"name": "qwen3:4b", "size": 3_000_000_000},
                {"name": "remapped", "size": 3_000_000_000,
                 "remote_host": "https://example.com"},
                {"name": "other:cloud", "size": 3_000_000_000},
                {"name": "tiny", "size": 10},
            ]})
        ]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            result = self.gateway().local_models()
        self.assertEqual([model.name for model in result], ["qwen3:4b"])
        self.assertEqual(FakeHttpConnection.created[0].host, "127.0.0.1")

    def test_remote_alias_blocked_by_show_before_private_prompt(self):
        FakeHttpConnection.responses = [
            FakeResponse(tags("qwen3:4b")),
            FakeResponse({"remote_model": "cloud-model", "details": {"format": "gguf"}}),
        ]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            with self.assertRaises(LocalModelError):
                self.gateway().chat(model="qwen3:4b", system="SAFE", user="PRIVATE")
        self.assertEqual(
            [c.requests[0][1] for c in FakeHttpConnection.created],
            ["/api/tags", "/api/show"],
        )
        for request in FakeHttpConnection.created:
            self.assertNotIn("PRIVATE", str(request.requests))

    def test_chat_local_only_with_no_extra_headers(self):
        FakeHttpConnection.responses = [
            FakeResponse(tags()),
            FakeResponse({"details": {"format": "gguf"}}),
            FakeResponse({"model": "qwen3:4b", "done": True,
                          "message": {"content": "Краткая сводка"}}),
        ]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            result = self.gateway().chat(
                model="qwen3:4b", system="Only local", user="Fake redacted text"
            )
        self.assertEqual(result, "Краткая сводка")
        self.assertEqual(len(FakeHttpConnection.created), 3)
        method, route, request_body, headers = FakeHttpConnection.created[-1].requests[0]
        self.assertEqual((method, route), ("POST", "/api/chat"))
        self.assertTrue(json.loads(request_body)["stream"] is False)
        self.assertFalse(json.loads(request_body)["think"])
        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["Connection"], "close")

    def test_http_redirect_never_followed(self):
        FakeHttpConnection.responses = [FakeResponse({}, status=302)]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            with self.assertRaises(LocalModelError):
                self.gateway().local_models()
        self.assertEqual(len(FakeHttpConnection.created), 1)

    def test_http_error_reports_only_status_and_safe_route(self):
        FakeHttpConnection.responses = [
            FakeResponse({"error": "secret private user conversation"}, status=500)
        ]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            with self.assertRaises(OllamaHTTPError) as observed:
                self.gateway().local_models()
        self.assertEqual(observed.exception.status, 500)
        self.assertEqual(observed.exception.route, "/api/tags")
        self.assertNotIn("secret private", str(observed.exception))

    def test_non_local_urls_rejected(self):
        for url in ("https://127.0.0.1:11434", "http://ollama.com:11434",
                    "http://10.0.0.2:11434", "http://127.0.0.1:11434/api/chat"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OllamaLocal(url=url)

    def test_rejects_cloud_model_names(self):
        for name in ("gpt-oss:120b-cloud", "cloud", "MyCloudProxy", "bad name"):
            with self.subTest(name=name), self.assertRaises(LocalModelError):
                validate_local_model_name(name)

    def test_never_displays_raw_http_error(self):
        FakeHttpConnection.responses = [
            FakeResponse({"error": "PRIVATE CHAT CONTENT"}, status=500)
        ]
        with patch("chatpulse.ollama_local.http.client.HTTPConnection",
                   FakeHttpConnection):
            with self.assertRaises(LocalModelError) as exc:
                self.gateway().local_models()
        self.assertNotIn("PRIVATE CHAT CONTENT", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
