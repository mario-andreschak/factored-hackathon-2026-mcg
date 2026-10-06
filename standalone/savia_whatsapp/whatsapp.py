"""Restricted client for the pinned mcp-whatsapp-web tool interface.

This bridge reads one explicitly configured chat. The MCP currently does not
expose the linked account's identity, so ``self_jid`` is an operator declaration,
not a verified server identity. Voice notes are files, not WhatsApp calls.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections import OrderedDict
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit


class WhatsAppMcpError(RuntimeError):
    """A tool failed or returned an unusable projection."""


class ChatPolicyError(WhatsAppMcpError):
    """An operation would leave the explicitly configured direct chat."""


class UncertainSendError(WhatsAppMcpError):
    """Delivery is unconfirmed. Check the chat; never automatically retry."""


def _jid_key(jid: str) -> str:
    if not isinstance(jid, str):
        raise ChatPolicyError("A direct chat JID must be explicitly configured.")
    match = re.fullmatch(r"([1-9][0-9]{6,14})@(c\.us|s\.whatsapp\.net)", jid)
    if match:
        return "phone:" + match.group(1)
    # LIDs cannot be inferred from phone numbers; only exact configured IDs work.
    if re.fullmatch(r"[0-9]{5,20}@lid", jid):
        return "lid:" + jid
    raise ChatPolicyError("Only explicit direct phone or LID chat JIDs are allowed; groups are blocked.")


@dataclass(frozen=True)
class WhatsAppConfig:
    chat_jid: str
    self_jid: str
    url: str = "http://127.0.0.1:43981/mcp"
    allowlisted_test_jids: tuple[str, ...] = ()
    transport: str = "http"
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    cwd: str | None = None
    tool_timeout_seconds: float = 70.0
    max_media_bytes: int = 6 * 1024 * 1024

    def __post_init__(self) -> None:
        configured = _jid_key(self.chat_jid)
        allowed = {_jid_key(self.self_jid), *(_jid_key(jid) for jid in self.allowlisted_test_jids)}
        if configured not in allowed:
            raise ChatPolicyError("The configured chat must be self or an explicitly allowlisted test chat.")
        if self.transport not in {"http", "stdio"}:
            raise ValueError("MCP transport must be http or stdio.")
        if self.transport == "http":
            parsed = urlsplit(self.url)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path != "/mcp"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("The standalone MCP URL must be a loopback /mcp endpoint.")
        elif not self.command or not self.cwd or not Path(self.cwd).is_absolute():
            raise ValueError("Stdio requires a command and an explicit absolute isolated working directory.")
        if not math.isfinite(self.tool_timeout_seconds) or self.tool_timeout_seconds <= 0:
            raise ValueError("Tool timeout must be positive and finite.")
        if not isinstance(self.max_media_bytes, int) or not 0 < self.max_media_bytes <= 6 * 1024 * 1024:
            raise ValueError("Media limit must fit the MCP server's 10 MB JSON request limit.")


@dataclass(frozen=True)
class BackendStatus:
    backend: str
    authenticated: bool
    history_state: str
    message_count: int | None = None
    chat_count: int | None = None
    contact_count: int | None = None
    history_note: str = ""


@dataclass(frozen=True)
class Message:
    id: str
    chat_id: str
    body: str
    type: str
    timestamp: float
    from_me: bool
    has_media: bool


@dataclass(frozen=True)
class Media:
    data: bytes = field(repr=False)
    mime_type: str


@dataclass(frozen=True)
class SentReceipt:
    id: str
    timestamp: float | None = None


class ToolSession(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any], **kwargs: Any) -> Any: ...


def _value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise WhatsAppMcpError(f"Invalid {label} in MCP response.")
    return float(value)


def _string(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise WhatsAppMcpError(f"Invalid {label} in MCP response.")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise WhatsAppMcpError(f"Invalid {label} in MCP response.")
    return value


class WhatsAppMcpAdapter:
    """Async MCP client with no unrestricted public tool-call entry point.

    Enter and exit this adapter in the same task (for example a FastAPI lifespan).
    Methods are callable by request handlers while the connection is open. A
    supplied session is for offline testing and is not owned by this adapter.
    """

    def __init__(self, config: WhatsAppConfig, *, session: ToolSession | None = None) -> None:
        self.config = config
        self._session = session
        self._supplied_session = session is not None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._observed_messages: OrderedDict[str, str] = OrderedDict()
        self._sent_ids: set[str] = set()

    async def __aenter__(self) -> WhatsAppMcpAdapter:
        if self._supplied_session:
            return self
        if self._stack is not None:
            raise WhatsAppMcpError("The MCP adapter is already connected.")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            if self.config.transport == "http":
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(self.config.url, timeout=self.config.tool_timeout_seconds)
                )
            else:
                read, write = await stack.enter_async_context(
                    stdio_client(StdioServerParameters(
                        command=self.config.command or "",
                        args=list(self.config.args), env=dict(self.config.env), cwd=self.config.cwd,
                    ))
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._session = session
        self._stack = stack
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._stack is not None:
            try:
                await self._stack.__aexit__(exc_type, exc, traceback)
            finally:
                self._stack = None
                self._session = None

    def _authorize_chat(self, chat_id: str) -> None:
        if _jid_key(chat_id) != _jid_key(self.config.chat_jid):
            raise ChatPolicyError("Only the configured test chat can be accessed.")

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise WhatsAppMcpError("Enter the MCP adapter before calling tools.")
        async with self._lock:
            try:
                result = await self._session.call_tool(
                    tool, arguments,
                    read_timeout_seconds=timedelta(seconds=self.config.tool_timeout_seconds),
                )
            except Exception as error:
                raise WhatsAppMcpError(f"MCP {tool} request failed; consult the isolated server log.") from error
        if _value(result, "isError", False):
            # Keep personal message bodies and server internals out of exception text.
            raise WhatsAppMcpError(f"MCP {tool} reported an error; consult the isolated server log.")
        content = _value(result, "content")
        if not isinstance(content, (list, tuple)):
            raise WhatsAppMcpError(f"MCP {tool} returned no content.")
        return result

    @staticmethod
    def _json(result: Any) -> Any:
        texts = [_value(block, "text") for block in _value(result, "content", []) if _value(block, "type") == "text"]
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise WhatsAppMcpError("Expected exactly one JSON text response from MCP.")
        try:
            return json.loads(texts[0])
        except (ValueError, TypeError) as error:
            raise WhatsAppMcpError("MCP returned invalid JSON.") from error

    async def status(self) -> BackendStatus:
        data = self._json(await self._call("get_backend_status", {}))
        if not isinstance(data, dict) or not isinstance(data.get("history"), dict):
            raise WhatsAppMcpError("MCP returned invalid backend status.")
        backend, history = data.get("backend"), data["history"]
        if backend not in {"webjs", "baileys"} or history.get("state") not in {"unavailable", "syncing", "available"}:
            raise WhatsAppMcpError("MCP returned an unknown backend or history state.")
        counts = []
        for key in ("messageCount", "chatCount", "contactCount"):
            count = history.get(key)
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                raise WhatsAppMcpError("MCP returned an invalid history count.")
            counts.append(count)
        return BackendStatus(
            backend, _boolean(data.get("authenticated"), "authentication status"), history["state"],
            *counts, _string(history.get("note", ""), "history note", empty=True),
        )

    async def pairing_qr(self) -> bytes | None:
        result = await self._call("get_qr_code", {})
        images = [block for block in _value(result, "content", []) if _value(block, "type") == "image"]
        if not images:
            return None
        if len(images) != 1 or _value(images[0], "mimeType") != "image/png":
            raise WhatsAppMcpError("MCP returned an invalid pairing QR image.")
        return self._decode_media(_value(images[0], "data"), max_bytes=1024 * 1024)

    def _project_message(self, data: Any) -> Message:
        if not isinstance(data, dict):
            raise WhatsAppMcpError("MCP returned an invalid message.")
        chat = _string(data.get("chatId"), "message chat")
        self._authorize_chat(chat)
        return Message(
            _string(data.get("id"), "message ID"), chat,
            _string(data.get("body"), "message body", empty=True),
            _string(data.get("type"), "message type"), _number(data.get("timestamp"), "message timestamp"),
            _boolean(data.get("fromMe"), "message direction"), _boolean(data.get("hasMedia"), "media flag"),
        )

    async def list_messages(
        self, after_timestamp: float, seen_ids: Sequence[str] = (), limit: int = 50,
    ) -> list[Message]:
        """Poll recent messages at or after a seconds cursor, excluding known IDs.

        Timestamp comparison is inclusive because WhatsApp timestamps have second
        precision. Persist IDs alongside the cursor to handle same-second arrivals.
        This is a bounded recent window, not a guarantee of a complete archive.
        Self-chat inputs can have ``from_me=True`` and must not be discarded.
        """
        cursor = _number(after_timestamp, "cursor")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("Message polling limit must be between 1 and 200.")
        self._authorize_chat(self.config.chat_jid)
        data = self._json(await self._call("list_messages", {"chat_id": self.config.chat_jid, "limit": limit}))
        if not isinstance(data, list):
            raise WhatsAppMcpError("MCP returned an invalid message list.")
        if len(data) > limit:
            raise WhatsAppMcpError("MCP returned more messages than the requested local polling window.")
        messages = [self._project_message(item) for item in data]
        excluded = set(seen_ids) | self._sent_ids
        unique: dict[str, Message] = {}
        for message in messages:
            if message.timestamp >= cursor and message.id not in excluded:
                if message.id in unique and unique[message.id] != message:
                    raise WhatsAppMcpError("MCP returned inconsistent duplicate message IDs.")
                unique[message.id] = message
        for message in unique.values():
            self._observed_messages[message.id] = message.chat_id
            self._observed_messages.move_to_end(message.id)
        while len(self._observed_messages) > 10_000:
            self._observed_messages.popitem(last=False)
        return sorted(unique.values(), key=lambda message: (message.timestamp, message.id))

    def _decode_media(self, data: Any, *, max_bytes: int | None = None) -> bytes:
        limit = max_bytes or self.config.max_media_bytes
        if not isinstance(data, str) or len(data) > 4 * ((limit + 2) // 3):
            raise WhatsAppMcpError("MCP media is missing or exceeds the local size limit.")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise WhatsAppMcpError("MCP returned invalid base64 media.") from error
        if not decoded or len(decoded) > limit:
            raise WhatsAppMcpError("MCP media is empty or exceeds the local size limit.")
        return decoded

    async def download_media(self, message_id: str, chat_id: str) -> Media:
        self._authorize_chat(chat_id)
        observed_chat = self._observed_messages.get(message_id)
        if observed_chat is None:
            raise ChatPolicyError("Media can only be downloaded for a message observed in the current test chat.")
        self._authorize_chat(observed_chat)
        message = self._project_message(self._json(await self._call("get_message_by_id", {"message_id": message_id})))
        if message.id != message_id or not message.has_media:
            raise WhatsAppMcpError("The observed message no longer has matching media.")
        result = await self._call("download_media", {"message_id": message_id, "include_full_data": True})
        audio = [block for block in _value(result, "content", []) if _value(block, "type") == "audio"]
        if len(audio) != 1:
            raise WhatsAppMcpError("This voice bridge only accepts one audio media block.")
        mime = _string(_value(audio[0], "mimeType"), "audio MIME type")
        if not mime.lower().startswith("audio/"):
            raise WhatsAppMcpError("MCP returned non-audio media.")
        return Media(self._decode_media(_value(audio[0], "data")), mime)

    async def _send(self, tool: str, arguments: dict[str, Any]) -> SentReceipt:
        self._authorize_chat(self.config.chat_jid)
        try:
            data = self._json(await self._call(tool, arguments))
            if not isinstance(data, dict) or data.get("success") is not True:
                raise WhatsAppMcpError("MCP returned no successful send receipt.")
            receipt_id = _string(data.get("messageId"), "send receipt ID")
            timestamp = _number(data["timestamp"], "send timestamp") if "timestamp" in data else None
        except Exception as error:
            raise UncertainSendError("WhatsApp delivery is unconfirmed. Check the test chat before retrying.") from error
        self._sent_ids.add(receipt_id)
        return SentReceipt(receipt_id, timestamp)

    async def send_text(self, text: str) -> SentReceipt:
        if not isinstance(text, str) or not text.strip() or len(text) > 16_000:
            raise ValueError("Text must be nonempty and at most 16000 characters.")
        return await self._send("send_message", {"recipient_jid": self.config.chat_jid, "message": text})

    async def send_voice_note(self, audio_bytes: bytes, mime_type: str = "audio/wav") -> SentReceipt:
        if not isinstance(audio_bytes, bytes) or not audio_bytes or len(audio_bytes) > self.config.max_media_bytes:
            raise ValueError("Audio must be nonempty bytes within the configured media size limit.")
        if not isinstance(mime_type, str) or not re.fullmatch(r"audio/[A-Za-z0-9.+-]+(?:;[ A-Za-z0-9=.+-]+)?", mime_type):
            raise ValueError("Voice note input must have an audio MIME type.")
        return await self._send("send_media", {
            "recipient_jid": self.config.chat_jid,
            "media_content": base64.b64encode(audio_bytes).decode("ascii"),
            "mime_type": mime_type,
            "as_audio_message": True,
            "include_full_data": False,
        })
