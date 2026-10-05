"""Small Streamable HTTP MCP client, restricted to history read operations."""
from __future__ import annotations

import json
import os
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

READ_TOOLS = {"slack_list_user_channels", "slack_read_channel", "slack_read_thread", "slack_search_channels", "slack_read_file", "slack_get_reactions"}


def configured_endpoint(config):
    if config.get("slack_mcp_url") or os.environ.get("HISTORY_SLACK_MCP_URL"):
        return config.get("slack_mcp_url") or os.environ["HISTORY_SLACK_MCP_URL"], {}
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    values = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    server = values.get("mcp_servers", {}).get(config.get("slack_mcp_server", "slack-flujo"), {})
    if not server.get("url"):
        raise RuntimeError("No HTTP slack-flujo MCP configured; set HISTORY_SLACK_MCP_URL")
    headers = dict(server.get("http_headers", {}))
    for key, variable in server.get("env_http_headers", {}).items():
        if os.environ.get(variable):
            headers[key] = os.environ[variable]
    if server.get("bearer_token_env_var") and os.environ.get(server["bearer_token_env_var"]):
        headers["Authorization"] = "Bearer " + os.environ[server["bearer_token_env_var"]]
    return server["url"], headers


class Client:
    def __init__(self, url, headers=None):
        self.url = url
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
        self.counter = 0
        self.lock = threading.Lock()
        result = self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "development-history-reader", "version": "1.0"}})
        self.headers["MCP-Protocol-Version"] = result.get("protocolVersion", "2024-11-05")
        self.request("notifications/initialized", {}, notification=True)

    def request(self, method, params, notification=False):
        with self.lock:
            self.counter += 1
            request_id = self.counter
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            payload["id"] = request_id
        for attempt in range(5):
            request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=self.headers)
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    session = response.headers.get("Mcp-Session-Id")
                    if session:
                        self.headers["Mcp-Session-Id"] = session
                    if notification:
                        return {}
                    if "text/event-stream" in response.headers.get("Content-Type", ""):
                        for line in response:
                            if line.startswith(b"data:"):
                                data = json.loads(line[5:])
                                if data.get("id") == request_id:
                                    break
                        else:
                            raise RuntimeError("MCP response ended without a result")
                    else:
                        data = json.load(response)
                if "error" in data:
                    raise RuntimeError("MCP error: " + str(data["error"].get("message", "unknown")))
                return data.get("result", {})
            except urllib.error.HTTPError as error:
                if error.code in (429, 502, 503, 504) and attempt < 4:
                    time.sleep(min(float(error.headers.get("Retry-After", 2 ** attempt)), 30))
                    continue
                raise RuntimeError(f"MCP HTTP {error.code}") from error
        raise RuntimeError("MCP retry limit reached")

    def call(self, name, arguments):
        if name not in READ_TOOLS:
            raise ValueError("The collector only permits read-only Slack tools")
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError("Slack tool failed: " + str(result.get("content", []))[:300])
        if name == "slack_read_file":
            # Slack's read-only MCP download supplies image/base64 content
            # blocks. Preserve them for the local, privacy-screened asset pass.
            return result
        if result.get("structuredContent"):
            return result["structuredContent"]
        blocks = [part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"]
        text = "\n".join(blocks)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"result": text}
