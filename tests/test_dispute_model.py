"""Configured model transport and explicit same-turn batching boundaries."""
import asyncio
import json

import httpx
import pytest

from dispute_workflow.model import FlujoModel
from dispute_workflow.prompts import StageAdapters, StageError


QUESTION = "Não reconheço a compra de ontem."
PREFLIGHT = {
    "rewrite_decompose": {"user_question": QUESTION, "historic_conversation": ""},
    "detect_attack": {"user_question": QUESTION},
    "detect_context": {"user_question": QUESTION, "historic_conversation": ""},
}
OUTPUTS = {
    "rewrite_decompose": {"clean_query": QUESTION, "sub_queries": [{"query_text": QUESTION}]},
    "detect_attack": {"inappropriate": 0, "deceptive": 0},
    "detect_context": {"emotional_context": "Neutro", "language": "pt"},
}


def completion(content="{}", **extra):
    return {"id": "codex_private-response-id", "model": "model-fixture",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 14000, "completion_tokens": 50, "total_tokens": 14050,
                      "prompt_tokens_details": {"cached_tokens": 13000, "cache_write_tokens": 0},
                      "completion_tokens_details": {"reasoning_tokens": 7}}, **extra}


def model_with_response(payload, seen=None, status=200):
    def handle(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, json=payload)
    return FlujoModel("http://127.0.0.1:43420", "model-fixture", transport=httpx.MockTransport(handle))


def test_transport_records_provider_cache_usage_without_invented_cost():
    seen = []
    model = model_with_response(completion(), seen)
    assert asyncio.run(model("detect_attack", "system", "synthetic message")) == "{}"
    row = model.observations[0]
    assert row["prompt_tokens"] == 14000 and row["cached_prompt_tokens"] == 13000
    assert row["completion_tokens"] == 50 and row["reasoning_tokens"] == 7
    assert row["cost_usd"] is None and row["cache_write_tokens"] == 0
    assert row["response_id_kind"] == "codex" and "private-response-id" not in repr(row)
    assert row["request_system_chars"] == 6 and row["status"] == "ok"
    assert set(seen[0]) == {"model", "messages", "stream", "temperature", "max_tokens"}
    assert "synthetic message" not in repr(row)


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": -1}, {"prompt_tokens_details": "secret"}])
def test_unreported_or_invalid_provider_usage_remains_unknown(usage):
    model = model_with_response(completion(usage=usage))
    asyncio.run(model("stage", "system", "user"))
    row = model.observations[0]
    assert row["prompt_tokens"] is None and row["cost_usd"] is None
    assert "secret" not in repr(row)


def test_inconsistent_provider_aggregates_are_unknown_without_discarding_known_counts():
    usage = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 99,
             "prompt_tokens_details": {"cached_tokens": 11, "cache_write_tokens": 12},
             "completion_tokens_details": {"reasoning_tokens": 4}}
    model = model_with_response(completion(usage=usage, id="chatcmpl-private-response-id"))
    asyncio.run(model("stage", "system", "user"))
    row = model.observations[0]
    assert row["prompt_tokens"] == 10 and row["completion_tokens"] == 3
    assert row["response_id_kind"] == "chatcmpl"
    assert "private-response-id" not in repr(row)
    assert set(row["usage_inconsistent_fields"]) == {"total_tokens", "cached_prompt_tokens", "cache_write_tokens", "reasoning_tokens"}
    assert all(row[field] is None for field in row["usage_inconsistent_fields"])


@pytest.mark.parametrize("update", [
    {"choices": [{"message": {"role": "assistant", "content": "{}"}}]},
    {"choices": [{"finish_reason": None, "message": {"role": "assistant", "content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"role": "user", "content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
    {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"finish_reason": "tool_calls", "message": {"content": "{}"}}]},
    {"choices": [{"message": {"content": "{}", "tool_calls": [{"secret": "private-token"}]}}]},
    {"choices": [{"message": {"content": "{}", "refusal": "private-token"}}]},
    {"choices": [{"message": {"content": {"secret": "private-token"}}}]},
])
def test_provider_tool_refusal_partial_and_invalid_content_fail_closed(update):
    model = model_with_response(completion(**update))
    with pytest.raises(ValueError) as caught:
        asyncio.run(model("stage", "system", "user"))
    assert str(caught.value) == "configured model request failed"
    assert "private-token" not in repr(model.observations)
    assert model.observations[0]["status"] == "error"
    assert model.observations[0]["prompt_tokens"] == 14000
    assert model.observations[0]["cached_prompt_tokens"] == 13000


def test_http_error_never_echoes_private_body():
    model = model_with_response({"error": "private-token"}, status=403)
    with pytest.raises(ValueError) as caught:
        asyncio.run(model("stage", "system", "user"))
    assert "private-token" not in str(caught.value) + repr(model.observations)


def test_timeout_is_bounded_and_records_unknown_usage():
    async def handle(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json=completion())
    model = FlujoModel("http://127.0.0.1:43420", "model-fixture", timeout=0.001, transport=httpx.MockTransport(handle))
    with pytest.raises(TimeoutError):
        asyncio.run(model("stage", "system", "user"))
    assert model.observations[0]["status"] == "timeout"
    assert model.observations[0]["prompt_tokens"] is None


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 121, True])
def test_timeout_options_are_finite_and_bounded(timeout):
    with pytest.raises(ValueError):
        FlujoModel("http://127.0.0.1:43420", "model-fixture", timeout=timeout)


def test_batch_is_one_provider_call_with_all_canonical_stage_contracts():
    seen = []
    model = model_with_response(completion(json.dumps(OUTPUTS)), seen)
    adapter = StageAdapters(model, batch_preflight=True)
    result = asyncio.run(adapter.run_parallel(PREFLIGHT))
    assert result == OUTPUTS and len(seen) == 1
    payload = seen[0]
    for stage in PREFLIGHT:
        assert adapter.specs[stage].system in payload["messages"][0]["content"]
        assert stage in json.loads(payload["messages"][1]["content"])
    assert len(model.observations) == 1
    assert model.observations[0]["stage"] == "preflight_batch"
    assert set(model.observations[0]["stages"]) == set(PREFLIGHT)


def test_batch_is_opt_in_and_fallback_uses_three_independent_stage_calls():
    calls = []
    async def individual(stage, system, user):
        calls.append(stage)
        return json.dumps(OUTPUTS[stage])
    result = asyncio.run(StageAdapters(individual).run_parallel(PREFLIGHT, use_batch=True))
    assert result == OUTPUTS and set(calls) == set(PREFLIGHT)
    assert len(calls) == 3


def test_disabled_batch_keeps_gather_even_if_model_supports_batch():
    class Model:
        async def __call__(self, stage, system, user):
            return json.dumps(OUTPUTS[stage])
        async def batch(self, requests):
            pytest.fail("default must not enable batching")
    assert asyncio.run(StageAdapters(Model()).run_parallel(PREFLIGHT)) == OUTPUTS


@pytest.mark.parametrize("field", ["question", "history"])
def test_different_turn_or_history_cannot_be_batched(field):
    class Model:
        async def __call__(self, *args):
            pytest.fail("scope mismatch must not call provider")
        async def batch(self, requests):
            pytest.fail("scope mismatch must not call provider")
    inputs = {stage: dict(values) for stage, values in PREFLIGHT.items()}
    inputs["detect_context"]["user_question" if field == "question" else "historic_conversation"] = "different private turn"
    result = asyncio.run(StageAdapters(Model(), batch_preflight=True).run_parallel(inputs))
    assert all(isinstance(value, StageError) and value.code == "input" for value in result.values())


@pytest.mark.parametrize("field", ["question", "history"])
def test_redaction_cannot_collapse_different_private_turns_into_one_batch(field):
    class Model:
        async def __call__(self, *args):
            pytest.fail("distinct original scope must not call provider")
        async def batch(self, requests):
            pytest.fail("distinct original scope must not call provider")
    inputs = {stage: dict(values) for stage, values in PREFLIGHT.items()}
    if field == "question":
        for stage in inputs:
            inputs[stage]["user_question"] = "Hola CLI-A"
        inputs["detect_attack"]["user_question"] = "Hola CLI-B"
    else:
        inputs["rewrite_decompose"]["historic_conversation"] = "Hola CLI-A"
        inputs["detect_context"]["historic_conversation"] = "Hola CLI-B"
    result = asyncio.run(StageAdapters(Model(), batch_preflight=True).run_parallel(inputs))
    assert all(isinstance(value, StageError) and value.errors == ("input.same_turn_scope",) for value in result.values())


@pytest.mark.parametrize("content", ["not JSON", "{}", json.dumps({**OUTPUTS, "extra": {}}), '{"detect_attack":{},"detect_attack":{}}'])
def test_malformed_batch_fails_closed_for_all_barrier_branches(content):
    adapter = StageAdapters(model_with_response(completion(content)), batch_preflight=True)
    result = asyncio.run(adapter.run_parallel(PREFLIGHT))
    assert all(isinstance(value, StageError) and value.code == "model_error" for value in result.values())


def test_one_invalid_batch_child_cannot_masquerade_as_successful_stage():
    outputs = {**OUTPUTS, "detect_attack": {"inappropriate": 0, "deceptive": 0, "authorized": True}}
    adapter = StageAdapters(model_with_response(completion(json.dumps(outputs))), batch_preflight=True)
    result = asyncio.run(adapter.run_parallel(PREFLIGHT))
    assert isinstance(result["detect_attack"], StageError) and result["detect_attack"].code == "schema"
    assert result["detect_context"] == OUTPUTS["detect_context"]


def test_batch_timeout_marks_all_three_logical_stages_without_hidden_retry():
    calls = []
    class Model:
        async def __call__(self, *args):
            pytest.fail("batch failure must not silently retry individually")
        async def batch(self, requests):
            calls.append(requests)
            await asyncio.sleep(0.1)
    result = asyncio.run(StageAdapters(Model(), timeout_seconds=0.001, batch_preflight=True).run_parallel(PREFLIGHT))
    assert len(calls) == 1
    assert all(isinstance(value, StageError) and value.code == "timeout" for value in result.values())
