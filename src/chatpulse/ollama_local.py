"""Ollama transport that refuses cloud models before private content crosses it.

A loopback server is still a trusted local process: ChatPulse cannot remotely
attest Ollama's effective environment or defend against a compromised daemon.
Ollama cloud-disabled config and a locally stored model are mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import http.client
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from chatpulse.privacy import validate_ollama_url


class LocalModelError(RuntimeError):
    """Errors are deliberately non-sensitive; never echo response bodies."""


class OllamaHTTPError(LocalModelError):
    """HTTP status and local API route are safe diagnostics, not response text."""

    def __init__(self, *, status: int, route: str):
        super().__init__("Ollama request failed (HTTP error)")
        self.status = status
        self.route = route


class OllamaConnectionError(LocalModelError):
    """A socket/transport failure, without sensitive exception text."""


class OllamaCompletionError(LocalModelError):
    """Ollama responded but the expected result was not usable."""


MAX_JSON_RESPONSE = 2 * 1024 * 1024
_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")


def assert_cloud_disabled(config_path: Path | None = None) -> None:
    """Fail closed unless the user's Ollama server.json disables cloud.

    This is a local configuration assertion, NOT remote process attestation.
    Users must restart the Ollama daemon after changing its configuration.
    """
    location = config_path or Path.home() / ".ollama" / "server.json"
    try:
        data = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise LocalModelError(
            "Enable Ollama's disable_ollama_cloud=true in ~/.ollama/server.json "
            "and restart Ollama before generating a digest."
        ) from None
    if not isinstance(data, dict) or data.get("disable_ollama_cloud") is not True:
        raise LocalModelError(
            "Ollama cloud must be disabled in ~/.ollama/server.json "
            "(disable_ollama_cloud: true)."
        )


def validate_local_model_name(name: str) -> str:
    if not isinstance(name, str) or not _MODEL_PATTERN.fullmatch(name):
        raise LocalModelError("Invalid Ollama model name")
    if "cloud" in name.casefold():
        raise LocalModelError("Cloud-tagged models are prohibited")
    return name


@dataclass(frozen=True, slots=True)
class LocalModelSummary:
    name: str
    disk_bytes: int


class OllamaLocal:
    """No requests proxy, no DNS hostname, no redirects, no raw HTTP error text."""

    def __init__(
        self, *, url: str = "http://127.0.0.1:11434",
        config_path: Path | None = None, timeout: int = 240,
    ) -> None:
        validate_ollama_url(url)
        parsed = urlsplit(url)
        self.host = parsed.hostname
        self.port = parsed.port
        self.config_path = config_path
        if not 5 <= timeout <= 600:
            raise ValueError("Invalid Ollama timeout")
        self.timeout = timeout

    def _json(self, method: str, route: str, data: dict[str, Any] | None = None) -> dict:
        if method not in ("GET", "POST") or route not in (
            "/api/tags", "/api/show", "/api/chat",
        ):
            raise LocalModelError("Ollama route not permitted")
        if self.host is None or self.port is None:
            raise LocalModelError("Ollama endpoint not configured")

        # stdlib HTTPConnection connects to the numeric loopback IP directly;
        # environment proxies are never consulted, redirects never followed.
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            body = None if data is None else json.dumps(
                data, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            headers = {"Accept": "application/json", "Connection": "close"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise OllamaHTTPError(status=response.status, route=route)
            payload = response.read(MAX_JSON_RESPONSE + 1)
            if len(payload) > MAX_JSON_RESPONSE:
                raise OllamaCompletionError("Ollama response too large")
            try:
                result = json.loads(payload)
            except (UnicodeError, ValueError):
                raise OllamaCompletionError("Ollama returned invalid JSON") from None
            if not isinstance(result, dict):
                raise OllamaCompletionError("Ollama returned an unexpected response")
            return result
        except (OSError, http.client.HTTPException, TimeoutError):
            raise OllamaConnectionError(
                "Cannot reach local Ollama. Start Ollama and verify 127.0.0.1:11434."
            ) from None
        finally:
            connection.close()

    def local_models(self) -> list[LocalModelSummary]:
        assert_cloud_disabled(self.config_path)
        response = self._json("GET", "/api/tags")
        models = response.get("models")
        if not isinstance(models, list):
            raise LocalModelError("Ollama model list is invalid")
        accepted = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name")
            try:
                validate_local_model_name(name)
            except LocalModelError:
                continue
            # No cloud aliases, virtual entries, or model-only remote metadata.
            if model.get("remote_host") or model.get("remote_model"):
                continue
            size = model.get("size")
            if type(size) is not int or size < 10_000_000:
                continue
            accepted.append(LocalModelSummary(name, size))
        return accepted

    def ensure_local(self, name: str) -> str:
        name = validate_local_model_name(name)
        if name not in {item.name for item in self.local_models()}:
            raise LocalModelError("Requested model is not a downloaded local model")
        show = self._json("POST", "/api/show", {"model": name})
        if show.get("remote_host") or show.get("remote_model"):
            raise LocalModelError("The selected Ollama model is remote")
        details = show.get("details")
        if not isinstance(details, dict) or not isinstance(details.get("format"), str):
            raise LocalModelError("Model has no verified local details")
        return name

    def describe_image(self, *, model: str, jpeg: bytes) -> str:
        """One in-memory JPEG, local-only; never print image or reply bodies."""
        self.ensure_local(model)
        if not isinstance(jpeg, bytes) or not 100 <= len(jpeg) <= 900_000:
            raise LocalModelError("Invalid or oversized visual input")
        response = self._json("POST", "/api/chat", {
            "model": model,
            "messages": [{
                "role": "user",
                "content": (
                    "Опиши картинку по-русски в одном коротком предложении: "
                    "что конкретно изображено, какой текст виден и в чём "
                    "может быть визуальная шутка. Не фантазируй, "
                    "не угадывай личности людей или приватные данные. "
                    "Если не понял — ответь 'изображение не распознано'."
                ),
                "images": [base64.b64encode(jpeg).decode("ascii")],
            }],
            "stream": False,
            "think": False,
            # Free the 4B vision model before the larger digest model loads.
            "keep_alive": 0,
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": 125,
            },
        })
        if response.get("model") != model or response.get("done") is not True:
            raise OllamaCompletionError("Visual model or completion mismatch")
        answer = response.get("message")
        result = answer.get("content") if isinstance(answer, dict) else None
        if not isinstance(result, str) or not result.strip() or len(result) > 700:
            raise OllamaCompletionError("Invalid local image description")
        return result.strip()

    def chat(
        self, *, model: str, system: str, user: str,
        num_predict: int = 640, num_ctx: int = 8192,
    ) -> str:
        # Called again on every inference request, not just at startup.
        self.ensure_local(model)
        if not isinstance(system, str) or not isinstance(user, str):
            raise ValueError("Model prompts must be strings")
        if len(user) > 24000 or len(system) > 5000:
            raise LocalModelError("Model prompt too large")
        if not 64 <= num_predict <= 2048 or not 4096 <= num_ctx <= 16384:
            raise ValueError("Invalid inference limits")
        response = self._json("POST", "/api/chat", {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False, "think": False,
            "options": {
                "temperature": 0.35, "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        })
        if response.get("model") != model or response.get("done") is not True:
            raise OllamaCompletionError("Ollama model or completion mismatch")
        message = response.get("message")
        result = message.get("content") if isinstance(message, dict) else None
        if not isinstance(result, str) or not result.strip() or len(result) > 8000:
            raise OllamaCompletionError("Ollama returned empty or oversized output")
        return result.strip()
