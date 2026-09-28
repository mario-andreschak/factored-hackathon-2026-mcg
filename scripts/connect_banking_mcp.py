"""Register the local MCP in FLUJO using its API. Secrets stay in the private config file."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:43420")
    p.add_argument("--name", default="Banking MCP")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--python", type=Path)
    p.add_argument("--server-url", help="MCP endpoint reachable from FLUJO's runtime (e.g. Docker)")
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    if urlparse(a.base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("local FLUJO only")
    for path in (a.config, a.repo):
        if not path.exists():
            raise ValueError("a required local path is missing")
    def request(method, path, body=None):
        req = Request(a.base.rstrip("/") + path + "?workspace=default-workspace", method=method,
                      headers={"Content-Type": "application/json"},
                      data=json.dumps(body).encode() if body is not None else None)
        with urlopen(req, timeout=90) as r:
            return json.load(r)
    config = {"name": a.name, "disabled": False,
              "rootPath": "", "env": {}, "_buildCommand": "", "_installCommand": "",
              "exposeAsMcpServer": False, "enableMcpApps": False, "enableMcpSkills": False,
              "sampling": {"enabled": False}}
    if a.server_url:
        parsed = urlparse(a.server_url)
        local_hosts = {"127.0.0.1", "localhost", "banking-mcp", "banking-mcp-demo"}
        if parsed.scheme != "http" or parsed.hostname not in local_hosts or parsed.path != "/mcp":
            raise ValueError("use a local or private Docker MCP endpoint")
        private = json.loads(a.config.read_text(encoding="utf-8"))
        config.update(transport="streamable", serverUrl=a.server_url,
                      headers={"Authorization": {"value": "Bearer " + private["service_token"],
                                                  "metadata": {"isSecret": True}}})
    else:
        if not a.python or not a.python.is_file():
            raise ValueError("stdio requires --python")
        config.update(transport="stdio", command=str(a.python.resolve()), cwd=str(a.repo.resolve()),
                      args=["-m", "banking_mcp", "serve", "--config", str(a.config.resolve()), "--transport", "stdio"],
                      rootPath=str(a.repo.resolve()))
    existing = request("GET", "/api/mcp/servers")
    match = next((s for s in existing if s["name"] == a.name), None)
    if match:
        # Only update a registration of this application. The one-time stdio-to-
        # HTTP migration is needed when the FLUJO API runs inside Docker.
        owned_stdio = match.get("args", [])[:3] == ["-m", "banking_mcp", "serve"]
        owned_http = match.get("serverUrl") == config.get("serverUrl") and match.get("transport") == "streamable"
        if not (owned_stdio or owned_http):
            raise ValueError("server name already belongs to another configuration")
        request("PUT", "/api/mcp/servers/" + quote(a.name, safe=""), config)
    else:
        request("POST", "/api/mcp/servers", config)
    tools = request("GET", "/api/mcp/servers/" + quote(a.name, safe="") + "/tools")
    print(json.dumps({"server": a.name, "tools": [t["name"] for t in tools.get("tools", [])]}))


if __name__ == "__main__":
    main()
