"""Gestor de modelos LLM - conecta a Ollama, OpenAI, o cualquier API compatible."""

import json
import time
from pathlib import Path
from typing import AsyncGenerator

import httpx


class ModelManager:
    def __init__(self):
        self.endpoints: list[dict] = []
        self._cache: dict[str, str] = {}
        self._dead_hosts: dict[str, float] = {}
        self._cooldown = 20.0
        self._max_fails = 2
        self._fail_counts: dict[str, int] = {}
        self._settings_path = Path(__file__).parent.parent.parent / "data" / "settings.json"

    # ── Descubrimiento ──────────────────────────────────────────

    async def discover(self):
        from geoia.models_manager.discovery import discover_endpoints
        self.endpoints = await discover_endpoints()
        self._load_settings_endpoints()

    def _load_settings_endpoints(self):
        try:
            if self._settings_path.exists():
                data = json.loads(self._settings_path.read_text("utf-8"))
                for ep in data.get("llm_endpoints", []):
                    if not any(e["base_url"] == ep["base_url"] for e in self.endpoints):
                        self.endpoints.append({
                            "name": ep.get("name", "Custom"),
                            "base_url": ep["base_url"],
                            "api_key": ep.get("api_key", ""),
                            "provider": "custom",
                            "models": ep.get("models", []),
                        })
        except Exception:
            pass

    # ── Listado de modelos ──────────────────────────────────────

    def list_models(self) -> list[dict]:
        result = []
        for ep in self.endpoints:
            if ep.get("models"):
                for m in ep["models"]:
                    result.append({"id": m, "provider": ep["provider"], "endpoint": ep["base_url"]})
            else:
                result.append({"id": f"{ep['name']} (*)", "provider": ep["provider"], "endpoint": ep["base_url"]})
        return result

    def get_endpoint(self, model_id: str) -> dict | None:
        for ep in self.endpoints:
            if model_id in ep.get("models", []) or model_id == ep.get("name"):
                return ep
        return self.endpoints[0] if self.endpoints else None

    # ── Llamadas LLM ────────────────────────────────────────────

    async def chat(self, messages: list[dict], model: str = "", **kwargs) -> str:
        endpoint = self.get_endpoint(model) or (self.endpoints[0] if self.endpoints else None)
        if not endpoint:
            return self._fallback_response(messages)

        if self._is_dead(endpoint["base_url"]):
            return self._fallback_response(messages)

        provider = endpoint["provider"]
        base = endpoint["base_url"].rstrip("/")
        key = endpoint.get("api_key", "")

        first_model = (endpoint.get("models") or [None])[0]
        if provider == "ollama":
            return await self._call_ollama(base, messages, model or first_model or "qwen2.5:0.5b", **kwargs)
        elif provider == "openai":
            return await self._call_openai(base, key, messages, model or first_model or "gpt-4o-mini", **kwargs)
        else:
            return await self._call_openai_compat(base, key, messages, model or first_model or "default", **kwargs)

    async def chat_stream(self, messages: list[dict], model: str = "") -> AsyncGenerator[str, None]:
        endpoint = self.get_endpoint(model) or (self.endpoints[0] if self.endpoints else None)
        if not endpoint:
            yield self._fallback_response(messages)
            return

        provider = endpoint["provider"]
        base = endpoint["base_url"].rstrip("/")
        key = endpoint.get("api_key", "")
        first_model = (endpoint.get("models") or [None])[0]

        if provider == "ollama":
            async for chunk in self._stream_ollama(base, messages, model or first_model or "qwen2.5:0.5b"):
                yield chunk
        elif provider == "openai":
            async for chunk in self._stream_openai(base, key, messages, model or first_model or "gpt-4o-mini"):
                yield chunk
        else:
            async for chunk in self._stream_openai_compat(base, key, messages, model or first_model or "default"):
                yield chunk

    # ── Ollama ──────────────────────────────────────────────────

    async def _call_ollama(self, base: str, messages: list[dict], model: str, **kwargs) -> str:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{base}/api/chat", json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    **kwargs,
                })
                if r.status_code == 200:
                    data = r.json()
                    return data.get("message", {}).get("content", "")
                self._record_failure(base, r.status_code)
        except Exception as e:
            self._record_failure(base, str(e))
        return self._fallback_response(messages)

    async def _stream_ollama(self, base: str, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{base}/api/chat", json={
                    "model": model, "messages": messages, "stream": True,
                }) as r:
                    async for line in r.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "message" in data:
                                    yield data["message"].get("content", "")
                            except json.JSONDecodeError:
                                pass
        except Exception:
            yield self._fallback_response(messages)

    # ── OpenAI ──────────────────────────────────────────────────

    async def _call_openai(self, base: str, key: str, messages: list[dict], model: str, **kwargs) -> str:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{base}/chat/completions", json={
                    "model": model, "messages": messages, **kwargs,
                }, headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                self._record_failure(base, r.status_code)
        except Exception as e:
            self._record_failure(base, str(e))
        return self._fallback_response(messages)

    async def _stream_openai(self, base: str, key: str, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{base}/chat/completions", json={
                    "model": model, "messages": messages, "stream": True,
                }, headers={"Authorization": f"Bearer {key}"}) as r:
                    async for line in r.aiter_lines():
                        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                            except json.JSONDecodeError:
                                pass
        except Exception:
            yield self._fallback_response(messages)

    # ── Compatible OpenAI (vLLM, llama.cpp, etc.) ──────────────

    async def _call_openai_compat(self, base: str, key: str, messages: list[dict], model: str, **kwargs) -> str:
        return await self._call_openai(base, key, messages, model or "default", **kwargs)

    async def _stream_openai_compat(self, base: str, key: str, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
        async for chunk in self._stream_openai(base, key, messages, model or "default"):
            yield chunk

    # ── Fallback local ──────────────────────────────────────────

    def _fallback_response(self, messages: list[dict]) -> str:
        try:
            from geoia.core.llm import get_llm
            llm = get_llm()
            resp = llm.chat(messages)
            if resp:
                return resp
        except Exception:
            pass
        last = messages[-1]["content"] if messages else ""
        from geoia.core.llm import _responder
        rapida = _responder(last)
        if rapida:
            return rapida
        return (
            "[Modo local] No hay modelo LLM disponible. "
            "Instala Ollama (ollama.com) y ejecuta: ollama pull llama3.2, "
            "o configura OPENAI_API_KEY en .env"
        )

    # ── Health / dead-host ──────────────────────────────────────

    def _is_dead(self, host: str) -> bool:
        if host in self._dead_hosts:
            if time.time() - self._dead_hosts[host] > self._cooldown:
                del self._dead_hosts[host]
                return False
            return True
        return False

    def _record_failure(self, host: str, reason):
        self._fail_counts[host] = self._fail_counts.get(host, 0) + 1
        if self._fail_counts[host] >= self._max_fails:
            self._dead_hosts[host] = time.time()

    def health(self) -> dict:
        return {
            "endpoints": len(self.endpoints),
            "total_models": len(self.list_models()),
            "dead_hosts": list(self._dead_hosts.keys()),
            "models": self.list_models(),
        }
