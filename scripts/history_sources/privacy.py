"""Remove embedded private Slack history from otherwise permitted sources.

Slack tool results can be JSON wrapped inside FLUJO/Codex tool output strings.
Recognition uses channel scope plus Slack message/listing shapes, not a broad
ban on development prose mentioning a channel name. Canonical history record
IDs and timestamps are preserved when their body/metadata payload is omitted.
"""
from __future__ import annotations

import json
import re


OMITTED_SLACK_HISTORY = "[Slack history omitted by privacy policy]"
_DEFAULT_EXCLUDED = {"find-a-team", "challenge-help", "technical-help"}
_DM_TYPES = {"im", "mpim", "dm", "group_dm", "direct_message", "group_direct_message"}
_SLACK_ID = re.compile(r"^[CDGU][A-Z0-9]{8,}$")
_DM_ID = re.compile(r"^[DU][A-Z0-9]{8,}$")
_MESSAGE_SHAPE = re.compile(r"(?m)^\s*Message TS:\s*\d+\.\d+\b|^\s*=== Message from .+? at .+? ===|^\s*From:\s*[^\n]+\nTime:[^\n]+\nMessage TS:\s*\d+\.\d+")
_CHANNEL_HEADING = re.compile(r"(?mi)^\s*(?:#{1,2}\s*)?Channel\s*:\s*([^\n]+)")
_CHANNEL_ID_HEADING = re.compile(r"(?m)^\s*(?i:Channel(?: ID)?|ID)\s*:\s*([CDGU][A-Z0-9]{8,})(?![A-Za-z0-9])")
_TYPE_HEADING = re.compile(r"(?mi)^\s*Type\s*:\s*(im|mpim|dm|group_dm|direct_message|group_direct_message)\s*$")
_SECTION = re.compile(r"(?m)^\s*###\s+([^\n]+)\n")
_CANONICAL_KEYS = {"id", "timestamp", "threadId", "threadIds", "sessionId", "callId", "conversationId", "messageId", "flowId", "nodeId", "machineId", "evidenceEventIds", "evidenceSourceEventIds", "fromEventId", "toEventId"}


def _name(value):
    return str(value or "").strip().strip("`\"'").lstrip("#").strip().lower().replace("_", "-")


def _excluded(config):
    return _DEFAULT_EXCLUDED | {_name(value) for value in (config or {}).get("slack_exclude_channels", [])}


def _true(value):
    return value is True or isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}


def _dm_name(value):
    return bool(re.match(r"^(?:dm(?:\s+with|\s*:|$)|group[ -]+dm\b|group[ -]+direct[ -]+message\b|direct[ -]+message\b|mpdm-)", _name(value), re.I))


def _excluded_name(value, config):
    name = _name(value)
    # The connected connector annotates headings with '(ID: C...)'. Slack
    # channel names contain no spaces; exclude the channel token before this
    # display annotation, without matching technical-help-backend by prefix.
    token = re.match(r"^([a-z0-9][a-z0-9-]*)(?:\s|\(|$)", name)
    return name in _excluded(config) or bool(token and token[1] in _excluded(config))


def _scope(record, config):
    """Interpret only a channel-shaped object, never a message author's user ID."""
    if isinstance(record, str):
        identity = record.strip().strip("\"'")
        return bool(_DM_ID.fullmatch(identity)) or _excluded_name(record, config) or _dm_name(record)
    if not isinstance(record, dict):
        return False
    identity = str(record.get("channelId") or record.get("channel_id") or record.get("id") or "")
    name = record.get("channelName") or record.get("channel_name") or record.get("name") or record.get("channel")
    kind = str(record.get("channelType") or record.get("channel_type") or record.get("conversation_type") or record.get("type") or "").lower().replace("-", "_").replace(" ", "_")
    return (_true(record.get("is_im")) or _true(record.get("is_mpim")) or kind in _DM_TYPES or bool(_DM_ID.fullmatch(identity))
        or _excluded_name(name, config) or _dm_name(name))


def _channel_scope(record, config):
    for key in ("channel_info", "channelInfo", "channel", "conversation", "conversation_info"):
        if key in record and _scope(record[key], config):
            return True
    channel_fields = {key: record[key] for key in ("channel_id", "channelId", "channelName", "channel_name", "channelType", "channel_type", "is_im", "is_mpim") if key in record}
    return bool(channel_fields) and _scope(channel_fields, config)


def _formatted_scope(text, config):
    clean = text.replace("**", "").replace("__", "")
    for match in _CHANNEL_HEADING.finditer(clean):
        if _scope(match[1], config):
            return True
    for match in _CHANNEL_ID_HEADING.finditer(clean):
        if _DM_ID.fullmatch(match[1]):
            return True
    if _TYPE_HEADING.search(clean):
        return True
    return any(_scope(match[1], config) for match in _SECTION.finditer(clean))


def _listing_block(block, heading, config):
    clean = block.replace("**", "").replace("__", "")
    ids = list(_CHANNEL_ID_HEADING.finditer(clean))
    # Require real channel metadata so Markdown/source-code section headings
    # named after a help channel do not vanish from project documentation.
    listing_shape = bool(ids) or bool(re.search(r"(?mi)^\s*Type\s*:\s*(?:public_channel|private_channel|im|mpim|dm)\s*$", clean))
    return listing_shape and (_scope(heading, config) or any(_DM_ID.fullmatch(match[1]) for match in ids) or bool(_TYPE_HEADING.search(clean)))


def _text(value, config, payload_context=False):
    if value == OMITTED_SLACK_HISTORY:
        return value
    stripped = value.strip()
    if stripped[:1] in {"{", "[", '"'} and stripped[-1:] in {"}", "]", '"'}:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                cleaned = _walk(parsed, config, payload_context)
                if cleaned == parsed:
                    return value
                if cleaned == OMITTED_SLACK_HISTORY:
                    return OMITTED_SLACK_HISTORY
                return json.dumps(cleaned, ensure_ascii=False, indent=2 if "\n" in value else None)
            if isinstance(parsed, str) and parsed.strip().startswith(("{", "[", '"')) and parsed != value:
                cleaned = _text(parsed, config, payload_context)
                if cleaned != parsed:
                    return json.dumps(cleaned, ensure_ascii=False)
        except (ValueError, TypeError, RecursionError):
            pass
    if _formatted_scope(value, config) and (payload_context or _MESSAGE_SHAPE.search(value)):
        return OMITTED_SLACK_HISTORY
    sections = list(_SECTION.finditer(value))
    if sections:
        pieces = [value[:sections[0].start()]]
        changed = False
        for index, section in enumerate(sections):
            end = sections[index+1].start() if index+1 < len(sections) else len(value)
            block = value[section.start():end]
            if _listing_block(block, section[1], config):
                pieces.append(OMITTED_SLACK_HISTORY + "\n\n")
                changed = True
            else:
                pieces.append(block)
        if changed:
            return "".join(pieces)
    return value


def _history_shape(record):
    messages = record.get("messages")
    if isinstance(messages, list):
        return not messages or any(isinstance(message, dict) and ("ts" in message or "thread_ts" in message) for message in messages)
    return isinstance(messages, str)


def _walk(value, config, payload_context=False):
    if isinstance(value, str):
        return _text(value, config, payload_context)
    if isinstance(value, list):
        return [_walk(item, config, payload_context) for item in value]
    if not isinstance(value, dict):
        return value
    canonical = bool(value.get("source") and "id" in value and "timestamp" in value)
    formatted_messages = isinstance(value.get("messages"), str) and _formatted_scope(value["messages"], config) and any(key in value for key in ("pagination_info", "channel_info", "channelInfo", "response_metadata", "has_more"))
    if not canonical and _history_shape(value) and (_channel_scope(value, config) or formatted_messages):
        return OMITTED_SLACK_HISTORY
    result = {}
    for key, item in value.items():
        if key in _CANONICAL_KEYS and not isinstance(item, dict) and (not isinstance(item, list) or all(not isinstance(child, (dict, list)) for child in item)):
            result[key] = item
            continue
        if key in {"channels", "conversations"} and isinstance(item, list):
            result[key] = [_walk(channel, config) for channel in item if not (isinstance(channel, dict)
                and (_SLACK_ID.fullmatch(str(channel.get("id") or channel.get("channelId") or "")) or any(flag in channel for flag in ("is_im", "is_mpim", "channelType", "channel_type"))) and _scope(channel, config))]
            continue
        # A connector response's messages field is an explicit Slack payload
        # context. This also removes empty excluded-channel history responses.
        is_messages = key == "messages" and (any(name in value for name in ("pagination_info", "channel_info", "channelInfo", "response_metadata", "has_more")) or _channel_scope(value, config))
        result[key] = _walk(item, config, payload_context or is_messages)
    if canonical and _channel_scope(value.get("metadata") or {}, config) and isinstance(result.get("body"), str) and _MESSAGE_SHAPE.search(result["body"]):
        result["body"] = OMITTED_SLACK_HISTORY
    return result


def scrub_embedded_slack(value, config=None):
    """Omit private Slack payloads wherever they occur in source snapshots."""
    return _walk(value, config or {})
