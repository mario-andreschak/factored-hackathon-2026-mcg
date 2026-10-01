"""Local OpenAI wire fixture. It emits routing only, never banking evidence."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import threading
import time
import uuid

from contract import require, require_runtime_release, strict_json


def completion(body: dict) -> dict:
    require(body.get("model") == "synthetic-fixture-model" and type(body.get("stream", False)) is bool,
            "fixture_model_request_invalid")
    tools = body.get("tools")
    require(isinstance(tools, list) and len(tools) == 1, "finish_routing_tool_required")
    tool = tools[0]
    function = tool.get("function", {})
    parameters = function.get("parameters")
    require(tool.get("type") == "function" and function.get("name") == "handoff_to_finish"
            and isinstance(parameters, dict) and parameters.get("type") == "object"
            and parameters.get("properties") == {}
            and ("required" not in parameters or parameters["required"] == []), "finish_routing_only")
    # Use the actual advertised routing name, which FLUJO maps to its Finish node.
    # All scenario-specific decisions and MCP results come from real host actions.
    return {"id": "fixture-" + uuid.uuid4().hex, "object": "chat.completion",
            "created": int(time.time()), "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": "Synthetic inquiry routing.",
                                     "tool_calls": [{"id": "call_" + uuid.uuid4().hex, "type": "function",
                                                     "function": {"name": function["name"], "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def stream_chunks(result: dict) -> bytes:
    message = result["choices"][0]["message"]
    call = message["tool_calls"][0]
    base = {key: result[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    chunks = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": message["content"]},
                                     "finish_reason": None}]},
              {**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, **call}]},
                                     "finish_reason": None}]},
              {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
              {**base, "choices": [], "usage": result["usage"]}]
    return b"".join(b"data: " + json.dumps(chunk, separators=(",", ":")).encode() + b"\n\n"
                    for chunk in chunks) + b"data: [DONE]\n\n"


class FixtureProvider:
    def __init__(self, port: int, token: str):
        self.port, self.token = port, token
        self.calls = 0
        self.rejections = 0
        self.accepted_routing = {}  # private in-memory IDs/hashes, never prompts or credentials
        self.lock = threading.Lock()
        self.server = self.thread = None

    def start(self):
        require_runtime_release(dict(os.environ))
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                with parent.lock:
                    parent.calls += 1  # actual inbound request, including rejects
                try:
                    require(self.path == "/v1/chat/completions"
                            and self.headers.get("Authorization") == "Bearer " + parent.token,
                            "fixture_provider_route_or_auth")
                    length = int(self.headers.get("Content-Length", "0"))
                    require(0 < length <= 1024 * 1024 and not self.headers.get("Transfer-Encoding"),
                            "fixture_provider_request_limit")
                    body = strict_json(self.rfile.read(length))
                    result = completion(body)
                    status = 200
                    streaming = body.get("stream", False)
                except Exception:
                    with parent.lock:
                        parent.rejections += 1
                    result, status = {"error": {"message": "Fixture request rejected."}}, 400
                    streaming = False
                raw = stream_chunks(result) if streaming else json.dumps(result, separators=(",", ":")).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    self.wfile.flush()
                    if status == 200:
                        call = result["choices"][0]["message"]["tool_calls"][0]
                        with parent.lock:
                            parent.accepted_routing[call["id"]] = {
                                "function": call["function"]["name"],
                                "arguments_sha256": hashlib.sha256(call["function"]["arguments"].encode()).hexdigest(),
                                "wire_sha256": hashlib.sha256(raw).hexdigest()}
                except OSError:
                    with parent.lock:
                        parent.rejections += 1

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self.server = self.thread = None
