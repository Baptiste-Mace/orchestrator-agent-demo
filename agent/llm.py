"""Abstraction du LLM : une interface, plusieurs implémentations.

Aucune dépendance externe : on parle aux APIs via urllib (stdlib).
Chaque provider renvoie un LLMResponse contenant le texte + l'usage en tokens,
ce qui permet à l'orchestrateur de suivre le budget.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Message:
    role: str      # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 300) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Erreur LLM {e.code}: {detail}") from e


class LLMProvider(ABC):
    """Interface commune. `complete` prend des messages et renvoie une réponse."""

    @abstractmethod
    def complete(self, messages: List[Message]) -> LLMResponse: ...


class OpenAIProvider(LLMProvider):
    """Compatible OpenAI et Azure OpenAI (endpoint chat/completions)."""

    def __init__(self, cfg):
        self.cfg = cfg

    def _url(self) -> str:
        base = self.cfg.base_url or "https://api.openai.com/v1"
        if self.cfg.provider == "azure":
            # base_url = https://<resource>.openai.azure.com
            return (f"{base}/openai/deployments/{self.cfg.model}"
                    f"/chat/completions?api-version={self.cfg.api_version}")
        return f"{base}/chat/completions"

    def _headers(self) -> dict:
        if self.cfg.provider == "azure":
            return {"Content-Type": "application/json", "api-key": self.cfg.api_key}
        return {"Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.api_key}"}

    def complete(self, messages: List[Message]) -> LLMResponse:
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_output_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        body = _post_json(self._url(), self._headers(), payload, self.cfg.request_timeout)
        usage = body.get("usage", {})
        return LLMResponse(
            text=body["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )


class AnthropicProvider(LLMProvider):
    """Compatible Anthropic (endpoint messages)."""

    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, messages: List[Message]) -> LLMResponse:
        base = self.cfg.base_url or "https://api.anthropic.com/v1"
        system = "\n".join(m.content for m in messages if m.role == "system")
        turns = [{"role": m.role, "content": m.content}
                 for m in messages if m.role != "system"]
        payload = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_output_tokens,
            "temperature": self.cfg.temperature,
            "system": system,
            "messages": turns,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.cfg.api_key,
            "anthropic-version": "2023-06-01",
        }
        body = _post_json(f"{base}/messages", headers, payload, self.cfg.request_timeout)
        usage = body.get("usage", {})
        return LLMResponse(
            text=body["content"][0]["text"],
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
        )


class OllamaProvider(LLMProvider):
    """LLM local via Ollama (endpoint /api/chat), sans bibliothèque tierce.

    Ollama expose une API REST : on lui envoie les messages et on force
    stream=False pour recevoir une réponse unique. Le champ "format": "json"
    aide le modèle à renvoyer du JSON valide (ce que nos prompts attendent).
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, messages: List[Message]) -> LLMResponse:
        base = self.cfg.base_url or "http://localhost:11434"
        payload = {
            "model": self.cfg.model,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_output_tokens,
            },
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        body = _post_json(f"{base}/api/chat", {"Content-Type": "application/json"},
                          payload, self.cfg.request_timeout)
        return LLMResponse(
            text=body["message"]["content"],
            # Ollama renvoie le décompte réel de tokens évalués/générés.
            prompt_tokens=body.get("prompt_eval_count", 0),
            completion_tokens=body.get("eval_count", 0),
        )


class MockProvider(LLMProvider):
    """Provider hors-ligne, pour lancer la démo sans clé API.

    Il renvoie du JSON plausible selon le meta-prompt système détecté,
    afin que toute la boucle (plan -> sélection -> exécution) fonctionne.
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, messages: List[Message]) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in messages if m.role == "user"), "")
        prompt_tokens = sum(len(m.content) // 4 for m in messages)

        if "PLANIFICATION" in system:
            text = json.dumps({"plan": [
                "Collecter les informations nécessaires à l'objectif",
                "Produire le livrable principal dans un fichier",
                "Relire et résumer le résultat",
            ]}, ensure_ascii=False)
        elif "SÉLECTION D'OUTIL" in system:
            text = json.dumps({"use": "none", "name": None,
                               "arguments": {}, "reason": "Mock: aucun outil requis."},
                              ensure_ascii=False)
        else:  # EXÉCUTION
            text = json.dumps({
                "result": f"(mock) Étape traitée : {user[:80]}",
                "files": [],
                "notes": "",
            }, ensure_ascii=False)

        return LLMResponse(text=text,
                           prompt_tokens=prompt_tokens,
                           completion_tokens=len(text) // 4)


def make_provider(cfg) -> LLMProvider:
    """Factory : choisit l'implémentation selon la config."""
    providers = {
        "openai": OpenAIProvider,
        "azure": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
        "mock": MockProvider,
    }
    if cfg.provider not in providers:
        raise ValueError(f"Provider inconnu : {cfg.provider}")
    return providers[cfg.provider](cfg)
