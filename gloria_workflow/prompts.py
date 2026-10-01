"""Executable adapters for the eight canonical Gloria language stages.

The model is injectable and receives only ``(stage, system, user)``. This module
does not route policy, authorize actions, call bank tools, or retry a model call.
Output schemas below encode the closed schemas declared by resources/prompts;
the YAML remains the single source for actual prompt text and versions.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

Model = Callable[[str, str, str], Awaitable[str]]
PROMPT_DIR = Path(__file__).resolve().parents[1] / "resources" / "prompts"
STAGE_FILES = {
    "detect_attack": "attack_detection_prompt.yml",
    "detect_context": "context_detection_prompt.yml",
    "rewrite_decompose": "rewrite_decompose_prompt.yml",
    "detect_intent": "intent_detection_prompt.yml",
    "extract_slots": "slot_extraction_prompt.yml",
    "resolve_clarification": "clarification_resolution_prompt.yml",
    "generate": "generator_prompt_v3.yml",
    "generate_handoff_summary": "handoff_summary_prompt.yml",
}
DOMAINS = ("TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS",
           "HUMAN_REQUEST", "GREETING", "PERSONALITY", "OOD")
MODES = ("SMALL_TALK", "OUT_OF_SCOPE", "BLOCKED", "AUTH_REQUIRED", "CLARIFY",
         "NO_MATCH", "INFORM", "INFORM_EXISTING_CASE", "CONFIRM_ACTION",
         "ACTION_DONE", "ACTION_UNVERIFIED", "ACTION_CANCELLED", "OUT_OF_POLICY",
         "HANDOFF", "TOOL_ERROR")
ARCHETYPES = ("Guía Clara", "Orientación a la solución", "Acompañamiento")


def _string(*, nullable=False, enum=None, pattern=None, maximum=12000):
    return {"type": ("string", "null") if nullable else "string", "enum": enum,
            "pattern": pattern, "maxLength": maximum}


def _array(items, maximum=20):
    return {"type": "array", "items": items, "maxItems": maximum}


def _object(properties):
    return {"type": "object", "properties": properties}


SLOT_FIELDS = ("currency", "currency_raw", "date_from", "date_to", "date_expression",
               "merchant", "transaction_type", "channel", "city", "country",
               "transaction_id", "complaint_id", "product_hint", "product_last4")
SLOT_SCHEMA = {key: _string(nullable=True, maximum=200) for key in SLOT_FIELDS}
SLOT_SCHEMA.update(amount={"type": ("number", "null")},
                   amount_is_approximate={"type": "boolean"},
                   foreign_customer_reference={"type": "boolean"})
SLOT_SCHEMA["currency"] = _string(nullable=True, pattern=r"[A-Z]{3}")
SLOT_SCHEMA["transaction_type"] = _string(nullable=True, enum=(
    "Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment", None))
SLOT_SCHEMA["channel"] = _string(nullable=True, enum=(
    "POS", "ATM", "Web", "App", "Branch", "Transfer", None))
SLOT_SCHEMA["transaction_id"] = _string(nullable=True, pattern=r"TRX-[A-Z0-9]+")
SLOT_SCHEMA["complaint_id"] = _string(nullable=True, pattern=r"CMP-[A-Za-z0-9_-]+")
SLOT_SCHEMA["product_last4"] = _string(nullable=True, pattern=r"[0-9]{4}")
SCHEMAS = {
    "detect_attack": _object({"inappropriate": {"type": "integer", "enum": (0, 1)},
                              "deceptive": {"type": "integer", "enum": (0, 1)}}),
    "detect_context": _object({
        "emotional_context": _string(enum=("Neutro", "Positivo", "Frustración", "Emergencia")),
        "language": _string(enum=("es", "pt", "other"))}),
    "rewrite_decompose": _object({"clean_query": _string(), "sub_queries": _array(
        _object({"query_text": _string()}), 8)}),
    "detect_intent": _object({"intents": _array(_object({
        "query_text": _string(), "domain": _string(enum=DOMAINS)}), 8)}),
    "extract_slots": _object(SLOT_SCHEMA),
    "resolve_clarification": _object({
        "resolution_type": _string(enum=("SELECTED", "CONFIRMED", "DENIED", "UNCLEAR", "NEW_REQUEST")),
        "selected_ref": _string(nullable=True, maximum=40)}),
    "generate": _object({"message": _string(maximum=12000),
                         "language": _string(enum=("es", "pt")),
                         "arquetipos": _array(_string(enum=ARCHETYPES), 3),
                         "chunk_ids": _array(_string(maximum=160), 30),
                         "data_sources": _array(_string(maximum=160), 30),
                         "grounding_violation": {"type": "integer", "enum": (0, 1)}}),
    "generate_handoff_summary": _object({
        "request_summary": _string(maximum=2000),
        "customer_language": _string(enum=("es", "pt", "other")),
        "customer_stated_claims": _array(_string(maximum=1000), 20),
        "suggested_open_questions": _array(_string(maximum=240), 4)}),
}


class StageError(ValueError):
    """Safe error metadata: never includes model output or sensitive input."""

    def __init__(self, stage: str, code: str, errors=()):
        self.stage, self.code, self.errors = stage, code, tuple(errors)
        super().__init__(f"{stage}: {code}")


@dataclass(frozen=True)
class PromptSpec:
    stage: str
    prompt_id: str
    version: str
    input_variables: tuple[str, ...]
    system: str
    user: str


def _type_matches(value, kind):
    return {"null": value is None, "string": isinstance(value, str),
            "integer": type(value) is int, "number": type(value) is int
            or (type(value) is float and math.isfinite(value)), "boolean": type(value) is bool,
            "array": isinstance(value, list), "object": isinstance(value, dict)}[kind]


def schema_errors(value: Any, schema: Mapping, path="output") -> list[str]:
    """Validate the small JSON-schema subset needed by canonical stage outputs."""
    kinds = schema["type"]
    if isinstance(kinds, str):
        kinds = (kinds,)
    if not any(_type_matches(value, kind) for kind in kinds):
        return [f"{path}.type"]
    errors = []
    if schema.get("enum") is not None and value not in schema["enum"]:
        errors.append(f"{path}.enum")
    if isinstance(value, dict):
        props = schema["properties"]
        if set(value) != set(props):
            errors.append(f"{path}.keys")
        for key in props.keys() & value.keys():
            errors.extend(schema_errors(value[key], props[key], f"{path}.{key}"))
    elif isinstance(value, list):
        if len(value) > schema["maxItems"]:
            errors.append(f"{path}.max_items")
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, schema["items"], f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) > schema["maxLength"]:
            errors.append(f"{path}.max_length")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}.pattern")
    return errors


def _parse_json(stage: str, raw: str, limit: int):
    if not isinstance(raw, str) or len(raw) > limit:
        raise StageError(stage, "invalid_json", ("output.type_or_size",))

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise StageError(stage, "invalid_json", ("output.json",)) from None


def _calendar(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value))


def _semantic_errors(stage, output, inputs):
    errors = []
    if stage == "detect_intent":
        if [item["query_text"] for item in output["intents"]] != inputs["queries"]:
            errors.append("output.intents.input_order")
    elif stage == "rewrite_decompose":
        queries = output["sub_queries"]
        if not output["clean_query"] and queries:
            errors.append("output.sub_queries.empty_query")
        if output["clean_query"] and not queries:
            errors.append("output.sub_queries.required")
        if len(queries) == 1 and queries[0]["query_text"] != output["clean_query"]:
            errors.append("output.sub_queries.single_query")
    elif stage == "resolve_clarification":
        resolution, ref, pending = output["resolution_type"], output["selected_ref"], inputs["pending"]
        if resolution == "SELECTED":
            refs = [item.get("ref") for item in pending.get("candidates", [])]
            if pending.get("type") != "awaiting_selection" or ref is None or refs.count(ref) != 1:
                errors.append("output.selected_ref.not_displayed")
        elif ref is not None:
            errors.append("output.selected_ref.only_selected")
        if resolution == "CONFIRMED" and pending.get("type") != "awaiting_confirmation":
            errors.append("output.resolution_type.no_confirmation_pending")
    elif stage == "extract_slots":
        for field in ("date_from", "date_to"):
            if output[field] is not None:
                try:
                    if not _calendar(output[field]):
                        raise ValueError()
                    date.fromisoformat(output[field])
                except ValueError:
                    errors.append(f"output.{field}.calendar")
        if (output["date_from"] is None) != (output["date_to"] is None):
            errors.append("output.date_range.paired")
        if output["date_from"] and output["date_to"] and output["date_from"] > output["date_to"]:
            errors.append("output.date_range.order")
        if output["amount"] is not None and output["amount"] < 0:
            errors.append("output.amount.nonnegative")
    elif stage == "generate_handoff_summary":
        if output["customer_language"] != inputs["language"]:
            errors.append("output.customer_language.input")
    elif stage == "generate":
        if output["language"] != ("pt" if inputs["language"] == "pt" else "es"):
            errors.append("output.language.input")
    return errors


# Explicit customer display fields. Never recurse through arbitrary state keys.
FACT_FIELDS = ("ref", "transaction_id", "transaction_reference", "transaction_date",
               "amount", "currency", "transaction_type", "channel", "merchant",
               "merchant_name", "merchant_category", "transaction_city", "transaction_country",
               "city", "country", "transaction_status", "status", "product", "product_type",
               "product_last4", "complaint_id", "complaint_status", "created_at", "label")
_PRIVATE_TEXT = re.compile(r"\bCLI-[A-Za-z0-9_-]+\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_DOCUMENT_TEXT = re.compile(r"(\b(?:documento|c[eé]dula|cpf|cuit|tel[eé]fono|telefone|celular|tarjeta|cart[aã]o)\s*(?:(?:n[uú]mero|n[ºo.]|final|terminad[ao])\s*)?[:#=-]?\s*)([0-9][0-9 .()-]{6,}[0-9])", re.IGNORECASE)
_PHONE_TEXT = re.compile(r"(?<!\w)\+[0-9]{1,3}(?:[ .()-]+[0-9]{1,4}){2,6}(?!\w)")
_SOURCE_PATH_TEXT = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>]{1,240}|/(?:Users|home|tmp|var|etc|data|private|sandbox)/[^\s\"'<>]{1,240}")
_SOURCE_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}")


def _text(value):
    text = _PRIVATE_TEXT.sub("[DATO_REDACTADO]", str(value or ""))
    text = _DOCUMENT_TEXT.sub(lambda match: match[1] + "[DOCUMENTO_REDACTADO]", text)
    text = _PHONE_TEXT.sub("[TELÉFONO_REDACTADO]", text)
    return _SOURCE_PATH_TEXT.sub("[RUTA_REDACTADA]", text)[:12000]


def _fields(value, allowed):
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for key in allowed:
        item = value.get(key)
        if key in value and (item is None or isinstance(item, (str, bool, int, float))):
            if key == "product_last4" and item is not None and not re.fullmatch(r"[0-9]{4}", str(item)):
                continue
            result[key] = _text(item) if isinstance(item, str) else item
    return result


def safe_structured_data(value: Mapping) -> dict:
    """Allowlist host-redacted facts, excluding risk, private IDs and capabilities.

    The trusted host must semantically redact full names and addresses in free
    text before using this API. Regex defense here cannot identify arbitrary
    personal names; it additionally removes known identifier/phone/path forms.
    """
    result = _fields(value, ("status", "match_count"))
    for field in ("candidates", "transactions", "complaints"):
        if isinstance(value.get(field), list):
            result[field] = [_fields(item, FACT_FIELDS) for item in value[field][:20]]
    for field in ("transaction", "complaint"):
        if isinstance(value.get(field), Mapping):
            result[field] = _fields(value[field], FACT_FIELDS)
    result["data_sources"] = [item for item in value.get("data_sources", [])
                              if isinstance(item, str) and _SOURCE_LABEL.fullmatch(item)][:30]
    if isinstance(value.get("search_context"), Mapping):
        result["search_context"] = _fields(value["search_context"], (
            "date_from", "date_to", "date_basis", "used_snapshot_default", "coverage_complete"))
    return result


def _receipt(value):
    return _fields(value, ("verified", "result_id", "handoff_id", "complaint_id", "status",
                           "id", "kind", "simulated"))


def safe_workflow_state(value: Mapping) -> dict:
    result = _fields(value, ("transaction_identified", "transaction_unique", "transaction_id"))
    for field, allowed in {
        "pending": ("type", "proposed_action", "candidate_type"),
        "policy_decision": ("response_mode", "requires_confirmation", "requires_human", "reason_code"),
        "existing_case": ("found", "complaint_id", "status", "state", "receipt_verified"),
        "action": ("name", "authorized", "executed", "verified", "result_id", "state", "receipt_verified"),
        "handoff": ("required", "created", "handoff_id", "state", "receipt_verified"),
    }.items():
        source = value.get(field, {})
        result[field] = _fields(source, allowed)
        if isinstance(source, Mapping) and isinstance(source.get("receipt"), Mapping):
            result[field]["receipt"] = _receipt(source["receipt"])
    pending = value.get("pending", {})
    if isinstance(pending, Mapping) and isinstance(pending.get("candidates"), list):
        result["pending"]["candidates"] = [_fields(item, FACT_FIELDS) for item in pending["candidates"][:20]]
    result["missing_fields"] = [item for item in value.get("missing_fields", [])
                                if item in SLOT_FIELDS or item in ("amount", "date", "currency")]
    return result


def safe_policy_context(value):
    # Text-only context cannot prove chunk IDs. Prefer [{chunk_id,text}] from host.
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, Mapping):
        value = value.get("chunks", [])
    if not isinstance(value, list):
        return []
    return [_fields(item, ("chunk_id", "text", "content")) for item in value[:30]]


def _structured_from_state(state):
    if isinstance(state.get("structured_data"), Mapping):
        return state["structured_data"]
    tools = state.get("tool_results", {})
    result = dict(tools.get("search_transactions", {}))
    for tool, field in (("get_transaction", "transaction"), ("get_complaint", "complaint")):
        if isinstance(tools.get(tool, {}).get(field), Mapping):
            result[field] = tools[tool][field]
    if isinstance(tools.get("list_customer_complaints", {}).get("complaints"), list):
        result["complaints"] = tools["list_customer_complaints"]["complaints"]
    return result


def build_stage_inputs(stage: str, state: Mapping, **overrides) -> dict:
    """Construct only declared variables from canonical state; never send ChatState."""
    if stage not in STAGE_FILES:
        raise StageError(stage, "input", ("stage.unknown",))
    variables = {
        "detect_attack": ("user_question",),
        "detect_context": ("user_question", "historic_conversation"),
        "rewrite_decompose": ("user_question", "historic_conversation"),
        "detect_intent": ("queries",),
        "extract_slots": ("clean_query", "current_date", "customer_currencies"),
        "resolve_clarification": ("clean_query", "pending", "historic_conversation"),
        "generate_handoff_summary": ("clean_query", "historic_conversation", "structured_data", "workflow_state", "language"),
        "generate": ("response_mode", "language", "emotional_context", "clean_query", "structured_data", "policy_context", "workflow_state", "historic_conversation", "customer_first_name", "current_date"),
    }[stage]
    if set(overrides) - set(variables):
        raise StageError(stage, "input", ("input.unknown_override",))
    try:
        if not isinstance(state, Mapping):
            raise TypeError()

        def section(key):
            value = state.get(key, {})
            if not isinstance(value, Mapping):
                raise TypeError()
            return value

        def default(key):
            if key in ("user_question", "clean_query", "current_date"):
                return section("turn").get(key, "")
            if key == "language":
                return section("turn").get("language", "es")
            if key == "emotional_context":
                return section("turn").get(key, "Neutro")
            if key == "queries":
                return [item["query_text"] for item in section("turn").get("sub_queries", [])]
            if key == "historic_conversation":
                return section("runtime").get("history", "")
            if key == "customer_currencies":
                return section("runtime").get(key, [])
            if key == "pending":
                return section("workflow_state").get("pending", {})
            if key == "workflow_state":
                return section("workflow_state")
            if key == "response_mode":
                return section("workflow_state").get("policy_decision", {}).get("response_mode", "TOOL_ERROR")
            if key == "structured_data":
                return _structured_from_state(state)
            if key == "policy_context":
                return section("tool_results").get("retrieve_policy", {}).get("chunks", [])
            if key == "customer_first_name":
                return section("tool_results").get("get_customer_profile", {}).get("first_name", "")
            raise ValueError()

        values = {key: overrides[key] if key in overrides else default(key) for key in variables}
        return _safe_inputs(stage, values)
    except StageError:
        raise
    except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
        raise StageError(stage, "input", ("input.projection",)) from None


def _safe_inputs(stage, inputs):
    if any(isinstance(value, str) and len(value) > 12000 for value in inputs.values()):
        raise StageError(stage, "input", ("input.string_bound",))
    result = dict(inputs)
    for field in ("user_question", "historic_conversation", "clean_query", "customer_first_name"):
        if field in result and isinstance(result[field], str):
            result[field] = _text(result[field])
    if "queries" in result and isinstance(result["queries"], list):
        if any(isinstance(item, str) and len(item) > 12000 for item in result["queries"]):
            raise StageError(stage, "input", ("input.string_bound",))
        result["queries"] = [_text(item) if isinstance(item, str) else item for item in result["queries"]]
    for field, projector in (("structured_data", safe_structured_data), ("workflow_state", safe_workflow_state)):
        if field in result and isinstance(result[field], Mapping):
            result[field] = projector(result[field])
    if "pending" in result and isinstance(result["pending"], Mapping):
        result["pending"] = safe_workflow_state({"pending": result["pending"]})["pending"]
    if "policy_context" in result:
        result["policy_context"] = safe_policy_context(result["policy_context"])
    return result


class StageAdapters:
    def __init__(self, model: Model, *, timeout_seconds=15, prompt_dir=None, max_output_chars=50000):
        if not callable(model):
            raise TypeError("model must be an async callable")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be finite and in (0,120]")
        if type(max_output_chars) is not int or not 1 <= max_output_chars <= 200000:
            raise ValueError("max_output_chars must be in [1,200000]")
        self.model, self.timeout_seconds, self.max_output_chars = model, timeout_seconds, max_output_chars
        self.specs = {}
        directory = Path(prompt_dir) if prompt_dir else PROMPT_DIR
        for stage, filename in STAGE_FILES.items():
            try:
                loaded = yaml.safe_load((directory / filename).read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or len(loaded) != 1:
                    raise ValueError()
                entry = next(iter(loaded.values()))
                meta = entry["metadata"]
                if meta["node"] != stage or meta["output_format"] != "json":
                    raise ValueError()
                spec = PromptSpec(stage, meta["prompt_id"], str(meta["version"]),
                                  tuple(meta["input_variables"]), entry["system"], entry["user"])
                placeholders = set(re.findall(r"{{\s*(\w+)\s*}}", spec.user))
                if placeholders != set(spec.input_variables):
                    raise ValueError()
                self.specs[stage] = spec
            except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
                raise StageError(stage, "input", ("prompt.contract",)) from None

    def build_inputs(self, stage: str, state: Mapping, **overrides):
        return build_stage_inputs(stage, state, **overrides)

    async def from_state(self, stage: str, state: Mapping, **overrides):
        return await self.run(stage, self.build_inputs(stage, state, **overrides))

    async def run(self, stage: str, inputs: Mapping, *, correction: str | None = None) -> dict:
        if stage not in self.specs:
            raise StageError(stage, "input", ("stage.unknown",))
        spec = self.specs[stage]
        if not isinstance(inputs, Mapping) or set(inputs) != set(spec.input_variables):
            raise StageError(stage, "input", ("input.keys",))
        if any(isinstance(value, str) and len(value) > 12000 for value in inputs.values()):
            raise StageError(stage, "input", ("input.string_bound",))
        try:
            inputs = _safe_inputs(stage, inputs)
        except StageError:
            raise
        except (TypeError, ValueError, AttributeError, RecursionError):
            raise StageError(stage, "input", ("input.projection",)) from None
        self._check_inputs(stage, inputs)
        # A substitution callback replaces only canonical placeholders once. User
        # braces cannot become new variables or instructions in the system prompt.
        def render(match):
            value = inputs[match.group(1)]
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        try:
            user = re.sub(r"{{\s*(\w+)\s*}}", render, spec.user)
        except (ValueError, TypeError, RecursionError):
            raise StageError(stage, "input", ("input.json",)) from None
        if len(user) > 100000:
            raise StageError(stage, "input", ("input.size",))
        system = spec.system
        if correction is not None:
            if not isinstance(correction, str) or len(correction) > 2000:
                raise StageError(stage, "input", ("correction.size",))
            system += "\n\n[Corrección de validación del host]\n" + correction
        try:
            response = self.model(stage, system, user)
            if not inspect.isawaitable(response):
                raise TypeError("model must return awaitable")
            raw = await asyncio.wait_for(response, timeout=self.timeout_seconds)
        except TimeoutError:
            raise StageError(stage, "timeout") from None
        except Exception:
            raise StageError(stage, "model_error") from None
        output = _parse_json(stage, raw, self.max_output_chars)
        errors = schema_errors(output, SCHEMAS[stage])
        if not errors:
            errors = _semantic_errors(stage, output, inputs)
        if errors:
            raise StageError(stage, "schema", errors)
        return output

    @staticmethod
    def _check_inputs(stage, inputs):
        string_fields = ("user_question", "historic_conversation", "clean_query", "current_date",
                         "language", "emotional_context", "customer_first_name", "response_mode")
        if any(key in inputs and not isinstance(inputs[key], str) for key in string_fields):
            raise StageError(stage, "input", ("input.type",))
        for key in ("pending", "workflow_state", "structured_data"):
            if key in inputs and not isinstance(inputs[key], Mapping):
                raise StageError(stage, "input", ("input.type",))
        for key in ("queries", "customer_currencies"):
            if key in inputs and (not isinstance(inputs[key], list) or not all(isinstance(item, str) for item in inputs[key])):
                raise StageError(stage, "input", ("input.type",))
        if "queries" in inputs and len(inputs["queries"]) > 8:
            raise StageError(stage, "input", ("input.queries.bound",))
        if "language" in inputs and inputs["language"] not in ("es", "pt", "other"):
            raise StageError(stage, "input", ("input.language",))
        if "emotional_context" in inputs and inputs["emotional_context"] not in ("Neutro", "Positivo", "Frustración", "Emergencia"):
            raise StageError(stage, "input", ("input.emotional_context",))
        if "customer_currencies" in inputs and any(not re.fullmatch(r"[A-Z]{3}", item) for item in inputs["customer_currencies"]):
            raise StageError(stage, "input", ("input.customer_currencies",))
        if "response_mode" in inputs and inputs["response_mode"] not in MODES:
            raise StageError(stage, "input", ("input.response_mode",))
        if "current_date" in inputs:
            try:
                if not _calendar(inputs["current_date"]):
                    raise ValueError()
                date.fromisoformat(inputs["current_date"])
            except ValueError:
                raise StageError(stage, "input", ("input.current_date",)) from None

    async def detect_attack(self, user_question):
        return await self.run("detect_attack", {"user_question": user_question})

    async def detect_context(self, user_question, historic_conversation=""):
        return await self.run("detect_context", {"user_question": user_question, "historic_conversation": historic_conversation})

    async def rewrite_decompose(self, user_question, historic_conversation=""):
        return await self.run("rewrite_decompose", {"user_question": user_question, "historic_conversation": historic_conversation})

    async def detect_intent(self, queries):
        return await self.run("detect_intent", {"queries": queries})

    async def extract_slots(self, clean_query, current_date, customer_currencies=None):
        return await self.run("extract_slots", {"clean_query": clean_query, "current_date": current_date, "customer_currencies": customer_currencies or []})

    async def resolve_clarification(self, clean_query, pending, historic_conversation=""):
        return await self.run("resolve_clarification", {"clean_query": clean_query, "pending": pending, "historic_conversation": historic_conversation})

    async def generate(self, inputs, *, correction=None):
        return await self.run("generate", inputs, correction=correction)

    async def generate_handoff_summary(self, inputs):
        return await self.run("generate_handoff_summary", inputs)
