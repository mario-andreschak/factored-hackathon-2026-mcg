"""Deterministic grounding and canonical fallbacks for the Gloria generator.

The caller supplies host-sanitized display facts, never a complete ChatState.
Chat text and history are deliberately not evidence. A success projection must
include a reread receipt, in addition to its flags::

    action.receipt = {"verified": True, "result_id": action.result_id}
    handoff.receipt = {"verified": True, "handoff_id": handoff.handoff_id}
    existing_case.receipt = {"verified": True, "complaint_id": ..., "status": ...}

A native banking receipt can instead be wrapped in ``{"state": "verified",
"receipt": {...}}``. A writer's ``state=created`` is not readback proof. The
host, not this module or an LLM, verifies ownership, snapshot and authorization.
These conservative textual checks do not prove arbitrary natural-language
claims. This module does not perform model repairs or any external operation.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
import re
import unicodedata

import yaml


_ROOT = Path(__file__).resolve().parents[1]
_FIELDS = {"message", "language", "arquetipos", "chunk_ids", "data_sources", "grounding_violation"}
_ARCHETYPES = {"Guía Clara", "Acompañamiento", "Orientación a la solución"}
_ID = re.compile(r"(?:(?:TRX|CMP|HOF)-[A-Za-z0-9_-]+|(?:txn|rev)_[A-Za-z0-9_-]+)\Z")
_ID_HINT = re.compile(r"(?:TRX|CMP|HOF)-|(?:txn|rev)_", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?\b|\b\d{1,2}/\d{1,2}/\d{4}\b")
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+|[ \u00a0\u202f]\d{3}(?!\d))*")
_CURRENCIES = set("COP USD EUR BRL MXN ARS CLP PEN UYU PYG BOB VES GBP CAD AUD CHF JPY CNY INR KRW SEK NOK DKK NZD ZAR HKD SGD AED SAR TRY RUB CRC DOP GTQ HNL NIO PAB BZD CUP".split())
_STATUS_WORDS = {"approved", "declined", "denied", "reversed", "pending", "settled", "failed", "open", "closed", "escalated", "cancelled", "canceled", "received", "in process", "resolved", "aprobado", "rechazado", "abierto", "cerrado", "recibido", "aprovado", "recusado", "rejeitado", "aberto", "fechado", "recebido"}
_PRIVATE = re.compile(r"\b(?:customer_id|session_id|conversation_id|risk_signals|fraud_score|amount_usd|unrecognized_count_24h|idempotency_key|pending_handle|selection_handle|request_id|authorization_expires_at|trusted_confirmation|service_token|stack\s*trace|traceback|umbral(?:es)?|limiar(?:es)?)\b", re.I)
_TOOLS = re.compile(r"\b(?:get_my_transaction|list_my_transactions|search_transactions|get_transaction|get_related_complaints|create_complaint|confirm_simulated_intake|prepare_unrecognized_charge|read_intake_receipt|create_verified_handoff|read_verified_handoff|execute_action|verify_action)\b", re.I)
_PROCESSING = re.compile(r"\b(?:fue procesad[ao]|foi processad[ao]|ya proces[eé]|j[aá] processei)\b")
_ADDITIONAL_SUCCESS = re.compile(r"\b(?:fue cread[ao]|qued[oó] registrad[ao]|he registrado|se ha registrado|ya est[aá] registrad[ao]|j[aá] est[aá] registrad[ao]|se registr[oó]|se cadastrou|foi cadastrada)\b")
_HANDOFF_SUCCESS = re.compile(r"\b(?:deriv[eé]|transfer[ií]|encaminhei|encaminhamos|ha sido derivad[ao]|fue derivad[ao]|foi encaminhad[ao]|derivaci[oó]n creada|encaminhamento criado)\b")
_HANDOFF_NOUN = re.compile(r"\b(?:atenci[oó]n humana|atendimento humano|derivaci[oó]n|encaminhamento|asesor|agente humano)\b")
_COMPLAINT_NOUN = re.compile(r"\b(?:reclamo|reclamaci[oó]n|reclama[cç][aã]o)\b")
_UNSUPPORTED_PROMISE = re.compile(r"\b(?:reembolso garantizado|devoluci[oó]n garantizada|devolu[cç][aã]o garantida|te devolveremos|vamos devolver|bloque[eé] tu tarjeta|bloqueei seu cart[aã]o|un agente (?:ya )?recibi[oó]|um agente (?:j[aá] )?recebeu|un humano (?:ya )?respondi[oó]|um humano (?:j[aá] )?respondeu)\b")
_FACT_KEYS = {"transaction_id", "complaint_id", "transaction_reference", "amount", "claimed_amount", "currency", "transaction_date", "date_from", "date_to", "created_at", "complaint_date", "process_date", "status", "transaction_status", "ref", "match_count"}
_SKIP_KEYS = {"text", "description", "label", "merchant", "merchant_name", "clean_query", "historic_conversation", "customer_stated_claims", "risk_signals", "error", "receipt", "action", "handoff", "existing_case"}
_MONTHS = {"enero": 1, "janeiro": 1, "febrero": 2, "fevereiro": 2, "marzo": 3, "marco": 3, "março": 3, "abril": 4, "mayo": 5, "maio": 5, "junio": 6, "junho": 6, "julio": 7, "julho": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "setembro": 9, "octubre": 10, "outubro": 10, "noviembre": 11, "novembro": 11, "diciembre": 12, "dezembro": 12}
_NAMED_DATE = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS) + r")\s+de\s+(\d{4})\b", re.I)


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _language(inputs: Mapping) -> str:
    return "pt" if inputs.get("language") == "pt" else "es"


def _mode(inputs: Mapping) -> str:
    return str(inputs.get("response_mode") or _mapping(_mapping(inputs.get("workflow_state")).get("policy_decision")).get("response_mode") or "TOOL_ERROR")


@lru_cache(maxsize=1)
def _templates() -> Mapping:
    with (_ROOT / "resources/prompts/fallback_templates.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


@lru_cache(maxsize=1)
def _success_phrases() -> tuple[str, ...]:
    with (_ROOT / "config/policy_rules.yaml").open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    return tuple(_normalized(phrase) for phrases in config["success_phrases"].values() for phrase in phrases)


def _tokens(message: str):
    """Yield maximal Unicode L/M/N, dash and underscore tokens with offsets."""
    start = None
    for index, character in enumerate(message + " "):
        included = character in "-_" or unicodedata.category(character)[0] in "LMN"
        if included and start is None:
            start = index
        elif not included and start is not None:
            yield message[start:index], start, index
            start = None


def _date_key(value: str) -> str | None:
    try:
        if "/" in value:
            day, month, year = map(int, value.split("/"))
            return date(year, month, day).isoformat()
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except (ValueError, TypeError):
        return None


def _decimals(value: str) -> set[Decimal]:
    """Accept common ES/PT display formats, preserving decimal precision."""
    compact = re.sub(r"[ \u00a0\u202f]", "", value)
    alternatives = {compact}
    if "," in compact and "." in compact:
        decimal_mark = "," if compact.rfind(",") > compact.rfind(".") else "."
        alternatives.add(compact.replace("." if decimal_mark == "," else ",", "").replace(decimal_mark, "."))
    elif "," in compact:
        alternatives.add(compact.replace(",", "."))
        if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+", compact):
            alternatives.add(compact.replace(",", ""))
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", compact):
        alternatives.add(compact.replace(".", ""))
    result = set()
    for alternative in alternatives:
        try:
            number = Decimal(alternative)
            if number.is_finite():
                result.add(number)
        except InvalidOperation:
            pass
    return result


def _receipt(projection: Mapping, identifier: str, expected: object, *, kind: str) -> Mapping:
    """Return only an explicitly verified, exact-ID readback receipt."""
    envelope = _mapping(projection.get("receipt"))
    native = _mapping(envelope.get("receipt")) if "receipt" in envelope else envelope
    verified = (native.get("verified") is True or envelope.get("state") == "verified"
                or projection.get("receipt_verified") is True or projection.get("state") == "verified")
    if not verified or not isinstance(expected, str) or not _ID.fullmatch(expected):
        return {}
    actual = native.get(identifier, native.get("id"))
    if actual != expected:
        return {}
    if "id" in native and (kind == "case"):
        if native.get("kind") != "simulated_intake" or native.get("simulated") is not True:
            return {}
    return native


def _action(inputs: Mapping) -> tuple[bool, Mapping]:
    action = _mapping(_mapping(inputs.get("workflow_state")).get("action"))
    receipt = _receipt(action, "result_id", action.get("result_id"), kind="case")
    return (all(action.get(field) is True for field in ("authorized", "executed", "verified")) and bool(receipt), receipt)


def _handoff(inputs: Mapping) -> tuple[bool, Mapping]:
    handoff = _mapping(_mapping(inputs.get("workflow_state")).get("handoff"))
    receipt = _receipt(handoff, "handoff_id", handoff.get("handoff_id"), kind="handoff")
    return (handoff.get("created") is True and bool(receipt), receipt)


def _existing(inputs: Mapping) -> tuple[bool, Mapping]:
    existing = _mapping(_mapping(inputs.get("workflow_state")).get("existing_case"))
    receipt = _receipt(existing, "complaint_id", existing.get("complaint_id"), kind="case")
    return (existing.get("found") is True and bool(receipt) and isinstance(existing.get("status"), str)
            and bool(existing.get("status")) and receipt.get("status") == existing.get("status"), receipt)


def _facts(inputs: Mapping) -> dict[str, set]:
    facts = {key: set() for key in ("ids", "dates", "amounts", "amount_currency", "currencies", "refs", "numbers", "statuses")}

    def collect(value: object):
        if isinstance(value, Mapping):
            for amount_key in ("amount", "claimed_amount"):
                if value.get(amount_key) is not None and isinstance(value.get("currency"), str):
                    try:
                        amount = Decimal(str(value[amount_key]))
                        if amount.is_finite():
                            facts["amount_currency"].add((amount, value["currency"].upper()))
                    except InvalidOperation:
                        pass
            for key, item in value.items():
                if key in _SKIP_KEYS:
                    continue
                if key in _FACT_KEYS and item is not None:
                    if key.endswith("_id") or key == "transaction_reference":
                        if isinstance(item, str) and _ID.fullmatch(item):
                            facts["ids"].add(item)
                    elif key in {"amount", "claimed_amount"}:
                        try:
                            amount = Decimal(str(item))
                            if amount.is_finite():
                                facts["amounts"].add(amount)
                        except InvalidOperation:
                            pass
                    elif key == "currency" and isinstance(item, str):
                        facts["currencies"].add(item.upper())
                    elif "date" in key or key == "created_at":
                        if isinstance(item, str) and (normalized := _date_key(item)):
                            facts["dates"].add(normalized)
                            facts["dates"].add(normalized[:10])
                    elif key == "ref" and isinstance(item, str):
                        facts["refs"].add(item)
                    elif key == "match_count" and type(item) is int:
                        facts["numbers"].add(Decimal(item))
                    elif key in {"status", "transaction_status"} and isinstance(item, str):
                        facts["statuses"].add(item)
                elif isinstance(item, (Mapping, list, tuple)):
                    collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    structured = _mapping(inputs.get("structured_data"))
    if structured.get("status") != "error":
        collect(structured)
    workflow = _mapping(inputs.get("workflow_state"))
    collect({"transaction_id": workflow.get("transaction_id"), "pending": workflow.get("pending", {})})
    for gate, identifier, projection_key in ((_action, "result_id", "action"), (_handoff, "handoff_id", "handoff"), (_existing, "complaint_id", "existing_case")):
        valid, receipt = gate(inputs)
        if valid:
            projection = _mapping(workflow.get(projection_key))
            facts["ids"].add(projection[identifier])
            collect({key: value for key, value in receipt.items() if key != "verified"})
            if projection_key == "existing_case":
                facts["statuses"].add(projection["status"])
    return facts


def _chunks(value: object) -> set[str]:
    result = set()
    if isinstance(value, Mapping):
        if isinstance(value.get("chunk_id"), str):
            result.add(value["chunk_id"])
        for key, item in value.items():
            if key not in {"text", "content", "description"}:
                result.update(_chunks(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            result.update(_chunks(item))
    elif isinstance(value, str):
        # The prompt adapter serializes its bounded chunk objects as JSON.
        import json
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return result
        if isinstance(parsed, (Mapping, list)):
            result.update(_chunks(parsed))
    return result


def validate_response(candidate: Mapping, generator_input: Mapping) -> list[str]:
    """Return stable safe error codes. Empty means all implemented checks pass."""
    if not isinstance(candidate, Mapping):
        return ["response_schema"]
    errors = []
    if set(candidate) != _FIELDS:
        errors.append("response_schema")
    message = candidate.get("message")
    if not isinstance(message, str) or not message.strip():
        errors.append("message_schema")
        message = ""
    if candidate.get("language") != _language(generator_input):
        errors.append("language_mismatch")
    for key in ("arquetipos", "chunk_ids", "data_sources"):
        value = candidate.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(key + "_schema")
    archetypes = candidate.get("arquetipos")
    if isinstance(archetypes, list) and any(not isinstance(item, str) or item not in _ARCHETYPES for item in archetypes):
        errors.append("arquetipos_unsupported")
    if type(candidate.get("grounding_violation")) is not int or candidate.get("grounding_violation") not in (0, 1):
        errors.append("grounding_violation_schema")
    elif candidate["grounding_violation"] == 1:
        errors.append("generator_grounding_violation")
    allowed_sources = _mapping(generator_input.get("structured_data")).get("data_sources", [])
    allowed_sources = {item for item in allowed_sources if isinstance(item, str)} if isinstance(allowed_sources, list) else set()
    for key, allowed in (("data_sources", allowed_sources), ("chunk_ids", _chunks(generator_input.get("policy_context")))):
        value = candidate.get(key)
        if isinstance(value, list) and any(not isinstance(item, str) or item not in allowed for item in value):
            errors.append(key + "_unverified")

    facts = _facts(generator_input)
    ignored_spans = []
    for token, start, end in _tokens(message):
        if _ID_HINT.search(token):
            ignored_spans.append((start, end))
            if not _ID.fullmatch(token) or token not in facts["ids"]:
                errors.append("id_unverified")
    normalized = _normalized(message)
    # Check the original spelling before normalization: Unicode token extensions
    # must never be reduced to a known ASCII identifier.
    if _PRIVATE.search(normalized) or _TOOLS.search(normalized):
        errors.append("private_or_implementation_detail")
    if _UNSUPPORTED_PROMISE.search(normalized):
        errors.append("unsupported_action_or_promise")
    for match in _DATE.finditer(message):
        ignored_spans.append(match.span())
        if _date_key(match.group()) not in facts["dates"]:
            errors.append("date_unverified")
    deaccented = "".join(char for char in unicodedata.normalize("NFD", message) if unicodedata.category(char) != "Mn")
    # NFD mark removal changes offsets, so use this only for date membership;
    # number offsets for ordinary named months are retained by the original RE.
    for match in _NAMED_DATE.finditer(deaccented):
        try:
            named = date(int(match[3]), _MONTHS[match[2].casefold()], int(match[1])).isoformat()
        except ValueError:
            named = None
        if named not in facts["dates"]:
            errors.append("date_unverified")
    for match in _NAMED_DATE.finditer(message):
        ignored_spans.append(match.span())
    for match in _NUMBER.finditer(message):
        if any(start <= match.start() and match.end() <= end for start, end in ignored_spans):
            continue
        line_start = message.rfind("\n", 0, match.start()) + 1
        is_ref = not message[line_start:match.start()].strip() and message[match.end():match.end() + 1] in {".", ")"}
        if is_ref and match.group() in facts["refs"]:
            continue
        numbers = _decimals(match.group())
        following = re.match(r"[*\s]*([A-Z]{3})\b", message[match.end():], re.I)
        preceding = re.search(r"\b([A-Z]{3})[*\s]*$", message[:match.start()], re.I)
        adjacent = next((item for item in (following, preceding) if item and (item[1].isupper() or item[1].upper() in _CURRENCIES)), None)
        if adjacent:
            currency = adjacent[1].upper()
            if currency not in facts["currencies"]:
                errors.append("currency_unverified")
            if not numbers.intersection({amount for amount, code in facts["amount_currency"] if code == currency}):
                errors.append("amount_unverified")
        elif not numbers.intersection(facts["amounts"] | facts["numbers"]):
            errors.append("number_unverified")
    for token in re.findall(r"\b[A-Z]{3}\b", message, re.I):
        currency = token.upper()
        if currency in _CURRENCIES and currency not in facts["currencies"]:
            errors.append("currency_unverified")
    for match in re.finditer(r"\*\*([^*\n]+)\*\*", message):
        value = _normalized(match[1].strip())
        preceding = _normalized(message[max(0, match.start() - 30):match.start()])
        is_status = value in _STATUS_WORDS or re.search(r"\b(?:estado|status)\s*(?:verificado\s*)?[:=]?\s*$", preceding)
        if is_status and value not in {_normalized(status) for status in facts["statuses"]}:
            errors.append("status_unverified")

    mode = _mode(generator_input)
    action_ok, _ = _action(generator_input)
    handoff_ok, _ = _handoff(generator_input)
    existing_ok, _ = _existing(generator_input)
    workflow = _mapping(generator_input.get("workflow_state"))
    action_id = _mapping(workflow.get("action")).get("result_id")
    handoff_id = _mapping(workflow.get("handoff")).get("handoff_id")
    if mode == "ACTION_DONE":
        if not action_ok:
            errors.append("action_receipt_unverified")
        elif f"**{action_id}**" not in message:
            errors.append("action_result_missing")
    if mode == "INFORM_EXISTING_CASE":
        existing = _mapping(workflow.get("existing_case"))
        if not existing_ok:
            errors.append("existing_case_receipt_unverified")
        elif existing["complaint_id"] not in message or existing["status"] not in message:
            errors.append("existing_case_facts_missing")
    for sentence in re.split(r"[.!?;\n]", normalized):
        success = any(phrase in sentence for phrase in _success_phrases()) or bool(_ADDITIONAL_SUCCESS.search(sentence))
        handoff_success = _HANDOFF_SUCCESS.search(sentence) is not None
        if success or handoff_success:
            describes_handoff = bool(_HANDOFF_NOUN.search(sentence)) and not _COMPLAINT_NOUN.search(sentence)
            if describes_handoff or handoff_success:
                if not handoff_ok or mode not in {"HANDOFF", "ACTION_UNVERIFIED"} or _normalized(str(handoff_id)) not in sentence:
                    errors.append("handoff_success_unverified")
            elif not action_ok or mode != "ACTION_DONE" or _normalized(str(action_id)) not in sentence:
                errors.append("action_success_unverified")
    if _PROCESSING.search(normalized) and _mapping(workflow.get("action")).get("executed") is not True:
        errors.append("processing_unverified")
    if mode in {"SMALL_TALK", "OUT_OF_SCOPE", "BLOCKED", "AUTH_REQUIRED"} and (_ID_HINT.search(message) or _DATE.search(message) or _NUMBER.search(message)):
        errors.append("facts_not_allowed_in_mode")
    if generator_input.get("language") == "other" and not ("español" in normalized and "portugués" in normalized):
        errors.append("language_availability_missing")
    return list(dict.fromkeys(errors))


def _display(value: object) -> str:
    return str(value).strip() if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool) else ""


def _summary(candidate: Mapping) -> str:
    fields = []
    for key in ("transaction_id", "transaction_reference", "complaint_id", "transaction_date"):
        if candidate.get(key) is not None and (text := _display(candidate[key])):
            fields.append(f"**{text}**")
    if candidate.get("amount") is not None and candidate.get("currency"):
        fields.append(f"**{_display(candidate['amount'])} {_display(candidate['currency'])}**")
    for keys in (("status", "transaction_status"), ("merchant_name", "merchant"), ("channel",), ("transaction_city",)):
        text = next((_display(candidate[key]) for key in keys if candidate.get(key) is not None), "")
        if text:
            fields.append(text)
    return ", ".join(fields)


def _records(inputs: Mapping) -> list[Mapping]:
    data = _mapping(inputs.get("structured_data"))
    if data.get("status") == "error":
        return []
    for key in ("transaction", "complaint"):
        if isinstance(data.get(key), Mapping):
            return [data[key]]
    for key in ("candidates", "complaints", "transactions"):
        if isinstance(data.get(key), list):
            return [item for item in data[key] if isinstance(item, Mapping)]
    return []


def _clarification(inputs: Mapping, language: str) -> str:
    workflow = _mapping(inputs.get("workflow_state"))
    pending = _mapping(workflow.get("pending"))
    candidates = pending.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    records = _records(inputs)
    if not candidates:
        candidates = records
    lines = []
    for candidate in candidates[:5]:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("ref"), str):
            continue
        identifier = candidate.get("transaction_id") or candidate.get("complaint_id")
        record = next((item for item in records if identifier and identifier in (item.get("transaction_id"), item.get("transaction_reference"), item.get("complaint_id"))), candidate)
        if summary := _summary(record):
            lines.append(f"{candidate['ref']}. {summary}")
    if lines:
        question = "Elige una referencia." if language == "es" else "Escolha uma referência."
        count = _mapping(inputs.get("structured_data")).get("match_count")
        if type(count) is int and count > len(lines):
            question += " Añade otro criterio para acotar los resultados." if language == "es" else " Acrescente outro critério para restringir os resultados."
        return "\n" + "\n".join(lines) + "\n" + question
    translations = {"es": {"amount": "importe", "date": "fecha", "date_from": "fecha inicial", "date_to": "fecha final", "currency": "moneda", "merchant": "comercio", "transaction_id": "referencia de la transacción", "complaint_id": "referencia del reclamo"}, "pt": {"amount": "valor", "date": "data", "date_from": "data inicial", "date_to": "data final", "currency": "moeda", "merchant": "estabelecimento", "transaction_id": "referência da transação", "complaint_id": "referência da reclamação"}}
    missing = workflow.get("missing_fields", [])
    names = [translations[language][key] for key in missing if isinstance(key, str) and key in translations[language]] if isinstance(missing, list) else []
    if names:
        return ("Indica: " if language == "es" else "Informe: ") + ", ".join(names) + "."
    return "Indica el importe y la fecha de la transacción." if language == "es" else "Informe o valor e a data da transação."


def fallback_response(generator_input: Mapping, *, reason: str | None = None) -> dict:
    """Render canonical ES/PT text, downgrading unsupported success to neutral.

    ``reason`` is an opaque caller diagnostic; it is never shown to customers.
    The selected safe mode is used for final checks, because stale ACTION_DONE
    input must be able to return a neutral ACTION_UNVERIFIED fallback.
    """
    language = _language(generator_input)
    original_mode = _mode(generator_input)
    mode = original_mode
    workflow = _mapping(generator_input.get("workflow_state"))
    values = {}
    facts_used = False
    if mode == "ACTION_DONE":
        if _action(generator_input)[0]:
            values["action_result_id"] = _mapping(workflow.get("action"))["result_id"]
            facts_used = True
        else:
            mode = "ACTION_UNVERIFIED"
    if mode == "INFORM_EXISTING_CASE":
        if _existing(generator_input)[0]:
            existing = _mapping(workflow.get("existing_case"))
            values.update(complaint_id=existing["complaint_id"], complaint_status=existing["status"])
            facts_used = True
        else:
            mode = "TOOL_ERROR"
    selected = mode
    if mode in {"HANDOFF", "ACTION_UNVERIFIED"} and _handoff(generator_input)[0]:
        selected = mode + "_HANDOFF_VERIFIED" if mode == "ACTION_UNVERIFIED" else "HANDOFF_VERIFIED"
        values["handoff_id"] = _mapping(workflow.get("handoff"))["handoff_id"]
        facts_used = True
    if mode == "CLARIFY":
        values["clarification_text"] = _clarification(generator_input, language)
        facts_used = bool(_records(generator_input))
    if mode in {"INFORM", "CONFIRM_ACTION"}:
        records = _records(generator_input)
        if len(records) == 1 and (summary := _summary(records[0])):
            values["verified_summary" if mode == "INFORM" else "transaction_summary"] = summary
            facts_used = True
        else:
            mode = selected = "TOOL_ERROR"
    templates = _templates()
    template = _mapping(templates.get(selected)).get(language)
    if not isinstance(template, str):
        mode = selected = "TOOL_ERROR"
        template = templates[mode][language]
    missing = False

    def substitute(match: re.Match) -> str:
        nonlocal missing
        value = _display(values.get(match[1]))
        if not value:
            missing = True
        return value

    message = re.sub(r"{{\s*(\w+)\s*}}", substitute, template)
    if missing:
        mode = selected = "TOOL_ERROR"
        message = templates[mode][language]
        facts_used = False
    context = _mapping(_mapping(generator_input.get("structured_data")).get("search_context"))
    if context.get("used_snapshot_default") is True and mode in {"NO_MATCH", "CLARIFY", "INFORM", "CONFIRM_ACTION"}:
        start, end = context.get("date_from"), context.get("date_to")
        if isinstance(start, str) and isinstance(end, str) and _date_key(start) and _date_key(end):
            message += (f" La consulta corresponde al intervalo **{start}** a **{end}** de un snapshot histórico." if language == "es" else f" A consulta corresponde ao intervalo **{start}** a **{end}** de um snapshot histórico.")
            facts_used = True
        else:
            mode = "TOOL_ERROR"
            message = templates[mode][language]
            facts_used = False
    if generator_input.get("language") == "other":
        message += " El servicio está disponible en español y portugués."
    sources = _mapping(generator_input.get("structured_data")).get("data_sources", [])
    response = {"message": message, "language": language, "arquetipos": ["Guía Clara"], "chunk_ids": [], "data_sources": list(dict.fromkeys(item for item in sources if isinstance(item, str))) if facts_used and isinstance(sources, list) else [], "grounding_violation": 0}
    safe_input = {**generator_input, "response_mode": mode}
    if validate_response(response, safe_input):
        response["message"] = templates["TOOL_ERROR"][language]
        response["data_sources"] = []
        if generator_input.get("language") == "other":
            response["message"] += " El servicio está disponible en español y portugués."
    return response
