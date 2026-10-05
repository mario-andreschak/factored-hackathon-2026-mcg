"""Isolated fictional actual MCP tick -> two model agents -> status receipt.

No bank service, session, ledger or shared measurement file is accessed.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def run(args):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from savia_assistant import InquiryService
    from frontend.server.language import MinimizedFacts
    state = Path(tempfile.mkdtemp(prefix="savia-inquiry-fictional-"))
    owner = "a" * 64
    service = InquiryService(state)
    service.create(owner, "No reconozco este cargo. ¿Cómo puedo revisar los datos y qué hago después?", "es",
                   MinimizedFacts("2026-10-04", "25.00", "USD", "Café ficticio", "approved"))
    env = dict(os.environ)
    if args.provider == "openrouter":
        values = {}
        for line in args.provider_env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key,value = line.split("=",1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        env["SAVIA_INQUIRY_MODEL_TOKEN"] = os.environ.get("OPENROUTER_API_KEY") or values["OPENROUTER_API_KEY"]
    env.update(SAVIA_INQUIRY_STATE_DIR=str(state), SAVIA_INQUIRY_OWNER=owner,
               SAVIA_INQUIRY_PROVIDER=args.provider, SAVIA_INQUIRY_MODEL_ID=args.model,
               PYTHONPATH=str(ROOT))
    started = time.monotonic()
    params = StdioServerParameters(command=sys.executable, args=["-m","savia_assistant.mcp"], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("savia_inquiry_tick", {})
            receipt = json.loads(result.content[0].text)
            status = await session.call_tool("savia_inquiry_status", {"language":"es"})
            assert json.loads(status.content[0].text)["items"] == receipt["items"]
    item = receipt["items"][0]
    output = {"schema":"savia-inquiry-mcp-smoke/v1", "observed_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
              "fictional":True, "provider":args.provider, "native_flujo_execution":False,
              "mcp_transport":"actual stdio SDK client/server", "tools":[t.name for t in tools.tools],
              "latency_ms":round((time.monotonic()-started)*1000), "worker_count":2,
              "completed_workers":sum(w["state"]=="completed" for w in item["workers"]),
              "bank_authority":False, "item":item}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2), encoding="utf-8")
    print(json.dumps({"state":item["state"],"completed_workers":output["completed_workers"],"latency_ms":output["latency_ms"],"output":str(args.output)}))
    if item["state"] != "team_completed":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider",choices=("flujo","openrouter"),default="openrouter")
    parser.add_argument("--model",default="google/gemini-3.1-flash-lite")
    parser.add_argument("--provider-env",type=Path,default=ROOT/"avatar/openrouter.env")
    parser.add_argument("--output",type=Path,default=ROOT/"docs/submission/assistant/mcp-smoke.json")
    asyncio.run(run(parser.parse_args()))
