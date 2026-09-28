"""Register the local MCP in FLUJO using its API. Secrets stay in the private config file."""
import argparse
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:43420")
    p.add_argument("--name", default="Banking MCP")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--python", type=Path)
    p.add_argument("--runtime-stdio", action="store_true", help="Launch inside the existing Linux FLUJO container")
    p.add_argument("--runtime-config", default="/run/banking/bank-config.json")
    p.add_argument("--runtime-repo", default="/opt/banking-mcp")
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
              "sampling": {"enabled": False}, "elicitation": {"enabled": False},
              "headers": {}, "serverUrl": "", "command": "", "args": [], "source": {"type": "local"}}
    if a.runtime_stdio:
        command = str(a.python) if a.python else "/opt/banking-mcp/.venv/bin/python"
        if not all(PurePosixPath(v).is_absolute() for v in [command, a.runtime_config, a.runtime_repo]):
            raise ValueError("runtime paths must be absolute Linux paths")
        config.update(transport="stdio", command=command, cwd=a.runtime_repo,
                      args=["-m", "banking_mcp", "serve", "--config", a.runtime_config, "--transport", "stdio"],
                      rootPath=a.runtime_repo)
    else:
        if not a.python or not a.python.is_file():
            raise ValueError("stdio requires --python")
        config.update(transport="stdio", command=str(a.python.resolve()), cwd=str(a.repo.resolve()),
                      args=["-m", "banking_mcp", "serve", "--config", str(a.config.resolve()), "--transport", "stdio"],
                      rootPath=str(a.repo.resolve()))
    existing = request("GET", "/api/mcp/servers")
    match = next((s for s in existing if s["name"] == a.name), None)
    if match:
        # Migrate only registrations known to belong to this Banking MCP.
        owned_stdio = match.get("args", [])[:3] == ["-m", "banking_mcp", "serve"]
        owned_http = match.get("serverUrl") in {"http://banking-mcp:8000/mcp", "http://banking-mcp-demo:8000/mcp"} and match.get("transport") == "streamable"
        if not (owned_stdio or owned_http):
            raise ValueError("server name already belongs to another configuration")
        request("PUT", "/api/mcp/servers/" + quote(a.name, safe=""), config)
    else:
        request("POST", "/api/mcp/servers", config)
    tools = request("GET", "/api/mcp/servers/" + quote(a.name, safe="") + "/tools")
    names = [t["name"] for t in tools.get("tools", [])]
    if tools.get("error") or set(names) != {"banking_status", "list_my_transactions", "get_my_transaction"}:
        raise ValueError("Banking stdio process is not ready; check its in-runtime installation and mounts")
    print(json.dumps({"server": a.name, "transport": "stdio", "tools": names}))


if __name__ == "__main__":
    main()
