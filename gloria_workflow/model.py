"""Bounded direct calls to an existing configured FLUJO language model.

No flow, MCP server, tools or persisted bank conversation is exposed to the LLM.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import httpx


class FlujoModel:
    def __init__(self, base_url, model_id, token=None, *, transport=None, timeout=20):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("invalid private FLUJO endpoint")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1", "flujo", "host.docker.internal"}:
            raise ValueError("private TLS or loopback endpoint required")
        if not isinstance(model_id, str) or not model_id.startswith("model-") or len(model_id) > 256:
            raise ValueError("configured direct model identifier required")
        local_operator = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if token is None and not local_operator:
            raise ValueError("private execution credential required")
        if token is not None and (not isinstance(token, str) or len(token) < 16 or any(c.isspace() for c in token)):
            raise ValueError("private execution credential required")
        self.base_url, self.model_id, self._token = base_url.rstrip("/"), model_id, token
        self.transport, self.timeout = transport, timeout
        self.observations = []

    async def __call__(self, stage, system, user):
        async with asyncio.timeout(self.timeout), httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=self.timeout) as client:
            headers = {"Authorization": "Bearer " + self._token} if self._token else {}
            async with client.stream("POST", self.base_url + "/v1/chat/completions", headers=headers, json={"model": self.model_id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "stream": False, "temperature": 0, "max_tokens": 1800}) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 256 * 1024:
                        raise ValueError("oversized model result")
        result = json.loads(data)
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str) or len(content) > 32000:
            raise ValueError("invalid model result")
        usage = result.get("usage", {})
        self.observations.append({"stage": stage, "model": self.model_id, "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")})
        return content
