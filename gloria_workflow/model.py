"""Bounded direct calls to an existing configured FLUJO language model.

No flow, MCP server, tools or persisted bank conversation is exposed to the LLM.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Mapping
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
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("bounded model timeout required")
        self.base_url, self.model_id, self._token = base_url.rstrip("/"), model_id, token
        self.transport, self.timeout = transport, timeout
        self.observations = []

    async def __call__(self, stage, system, user):
        return await self._request(stage, system, user)

    async def batch(self, requests):
        """One explicit same-turn preflight call; never coalesce customer calls.

        The caller scopes these three canonical stages to the same original
        question and history. Each stage's input block is separate, and its
        result is subsequently validated by StageAdapters against that block.
        No bank facts, conversation capability, or model configuration changes
        enter this call. The configured provider may still add its own prompt.
        """
        expected = {"detect_attack", "detect_context", "rewrite_decompose"}
        if (not isinstance(requests, list) or len(requests) != 3
                or any(not isinstance(item, tuple) or len(item) != 3 for item in requests)
                or {item[0] for item in requests} != expected
                or any(not isinstance(value, str) for item in requests for value in item)):
            raise ValueError("same-turn preflight batch required")
        system = (
            "Ejecuta tres contratos independientes sobre el mismo turno. "
            "Cada etapa usa exclusivamente su propio bloque de entrada; "
            "el detector de ataques clasifica solo user_question, sin heredar el histórico de otras etapas. "
            "No mezcles salidas ni agregues decisiones, hechos, permisos o acciones. "
            "Devuelve un único objeto JSON con exactamente las claves detect_attack, detect_context "
            "y rewrite_decompose; cada valor es el objeto JSON exigido por su contrato.\n\n"
            + "\n\n".join(f"[contrato: {stage}]\n{instruction}" for stage, instruction, _ in requests)
        )
        user = json.dumps({stage: prompt for stage, _, prompt in requests}, ensure_ascii=False)
        content = await self._request("preflight_batch", system, user, stages=[item[0] for item in requests])
        result = _object_json(content)
        if set(result) != expected or any(not isinstance(item, dict) for item in result.values()):
            raise ValueError("invalid preflight batch result")
        return {stage: json.dumps(result[stage], ensure_ascii=False, allow_nan=False) for stage in expected}

    async def _request(self, stage, system, user, *, stages=None):
        if not all(isinstance(value, str) for value in (stage, system, user)) or len(system) + len(user) > 150000:
            raise ValueError("invalid model input")
        started = time.monotonic()
        observation = {"stage": stage, "model": self.model_id, "status": "error",
                       "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                       "cached_prompt_tokens": None, "cache_write_tokens": None,
                       "reasoning_tokens": None, "cost_usd": None,
                       "request_system_chars": len(system), "request_user_chars": len(user)}
        if stages is not None:
            observation["stages"] = list(stages)
        try:
            async with asyncio.timeout(self.timeout), httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=self.timeout) as client:
                headers = {"Authorization": "Bearer " + self._token} if self._token else {}
                async with client.stream("POST", self.base_url + "/v1/chat/completions", headers=headers, json={"model": self.model_id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "stream": False, "temperature": 0, "max_tokens": 1800}) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 256 * 1024:
                            raise ValueError("oversized model result")
            result = _object_json(data)
            # Rejected completions still consumed provider usage when it is
            # reported. Keep that accounting without retaining output content.
            usage = result.get("usage")
            usage = usage if isinstance(usage, Mapping) else {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                observation[field] = _token_count(usage.get(field))
            details = usage.get("prompt_tokens_details")
            details = details if isinstance(details, Mapping) else {}
            observation["cached_prompt_tokens"] = _token_count(details.get("cached_tokens"))
            observation["cache_write_tokens"] = _token_count(details.get("cache_write_tokens"))
            details = usage.get("completion_tokens_details")
            observation["reasoning_tokens"] = _token_count(details.get("reasoning_tokens")) if isinstance(details, Mapping) else None
            inconsistent = []
            prompt, completion = observation["prompt_tokens"], observation["completion_tokens"]
            total = observation["total_tokens"]
            if prompt is not None and completion is not None and total is not None and total != prompt + completion:
                observation["total_tokens"] = None
                inconsistent.append("total_tokens")
            for field, bound in (("cached_prompt_tokens", prompt), ("cache_write_tokens", prompt), ("reasoning_tokens", completion)):
                if bound is not None and observation[field] is not None and observation[field] > bound:
                    observation[field] = None
                    inconsistent.append(field)
            if inconsistent:
                observation["usage_inconsistent_fields"] = inconsistent
            returned_model = result.get("model")
            observation["response_model"] = returned_model if isinstance(returned_model, str) and re.fullmatch(r"[A-Za-z0-9._ -]{1,256}", returned_model) else None
            response_id = result.get("id")
            observation["response_id_kind"] = next((kind for kind in ("codex", "chatcmpl", "claude") if isinstance(response_id, str) and response_id.startswith((kind + "_", kind + "-"))), "unknown")
            choices = result["choices"]
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping) or choices[0].get("finish_reason") != "stop":
                raise ValueError("invalid model completion")
            message = choices[0]["message"]
            if not isinstance(message, Mapping) or message.get("role") != "assistant" or message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
                raise ValueError("unexpected model tool call")
            content = message.get("content")
            if not isinstance(content, str) or len(content) > 32000:
                raise ValueError("invalid model result")
            observation["status"] = "ok"
            return content
        except (TimeoutError, httpx.TimeoutException):
            observation["status"] = "timeout"
            raise TimeoutError("configured model timeout") from None
        except asyncio.CancelledError:
            observation["status"] = "cancelled"
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise ValueError("configured model request failed") from None
        finally:
            observation["latency_ms"] = round((time.monotonic() - started) * 1000)
            self.observations.append(observation)


def _token_count(value):
    return value if type(value) is int and value >= 0 else None


def _object_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON number")
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise ValueError("object JSON required")
    return result
