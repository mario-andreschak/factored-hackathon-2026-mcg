"""Bounded real HTTP customer calls and a transparent deterministic baseline.

Private config contains base_url, code, profile, generated_only:true and runtime.
No credentials, cookies, capabilities, or raw exception text enter public output.
This does not infer provider counts or turn HTTP success into bank resolution.
"""
from __future__ import annotations
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from frontend.server.language import MinimizedFacts, render_guidance

CASES = [
    ("es-selected", "es", "No reconozco esta compra. Explícame los datos y qué puedo hacer ahora.", True, "grounded_explanation"),
    ("pt-selected", "pt", "Não reconheço esta compra. Explique os dados e o que posso fazer agora.", True, "grounded_explanation"),
    ("es-ambiguous", "es", "Hay un cobro que no reconozco, pero no sé cuál es.", False, "clarification"),
    ("pt-ambiguous", "pt", "Tem uma cobrança que não reconheço, mas não sei qual é.", False, "clarification"),
    ("es-human", "es", "Necesito ayuda de una persona para revisar un cobro.", False, "honest_handoff"),
    ("pt-human", "pt", "Preciso de ajuda de uma pessoa para verificar uma cobrança.", False, "honest_handoff"),
]

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.calls = []

    def call(self, path, body=None, *, method=None):
        req = urllib.request.Request(self.cfg["base_url"].rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": self.cfg["base_url"].rstrip("/")},
            method=method or ("POST" if body is not None else "GET"))
        start = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            with self.opener.open(req, timeout=600) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, TimeoutError):
            status, raw = 0, b'{}'
        elapsed = round((time.perf_counter() - start)*1000, 1)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            result = {}
        self.calls.append({"path": path.split("?")[0], "method": req.method, "http_status": status, "latency_ms": elapsed,
                           "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat()})
        return result, status

    def login(self):
        _, status = self.call("/api/auth/login", {"profile": self.cfg["profile"], "code": self.cfg["code"]})
        if status != 200:
            raise ValueError("fictional_login_failed")

def baseline(message, language, facts):
    # Frozen rule before outcome inspection: selection explains existing facts;
    # explicit human request suggests human; otherwise ask date/amount.
    folded = message.casefold()
    guidance = "explain_selected" if facts else "suggest_human" if any(x in folded for x in ("persona", "pessoa")) else "ask_date_or_amount"
    return render_guidance(guidance, language, facts)

def run(cfg, selected=None, cases=CASES):
    rows = []
    for name, lang, message, selection, expected in cases:
        client = Client(cfg)
        client.login()
        transactions, status = client.call("/api/transactions?limit=500")
        items = transactions.get("transactions", transactions.get("items", []))
        if not isinstance(items, list):
            raise ValueError("transaction_schema_unknown")
        item = next((x for x in items if x.get("reference") == selected), None) if selected else next((x for x in items if str(x.get("type", "")).lower() == "purchase"), None)
        if item is None:
            raise ValueError("owned_fictional_purchase_required")
        facts = MinimizedFacts(str(item["occurred_at"])[:10], f'{float(item["amount"]):.2f}', item["currency"], item.get("merchant") or None,
            str(item.get("status", "unknown")).lower() if str(item.get("status", "unknown")).lower() in {"approved","pending","reversed"} else "unknown") if selection else None
        t = time.perf_counter()
        simple = baseline(message, lang, facts)
        baseline_ms = round((time.perf_counter()-t)*1000, 3)
        request = {"message": message, "language": lang}
        if selection:
            request["transaction_reference"] = item["reference"]
        result, status = client.call("/api/chat/messages", request)
        chat_call = client.calls[-1]
        history, history_status = client.call("/api/chat/history")
        public = {k: result[k] for k in ("reply", "mode", "status") if k in result}
        reply = public.get("reply", "")
        # Screening only, independently adjudicate usefulness/language/grounding.
        rows.append({"case":name,"language":lang,"message":message,"expected_behavior":expected,
            "display_facts":facts.public() if facts else None,"selection_sha256":digest(item["reference"]) if selection else None,
            "baseline":{"kind":"repository deterministic display copy + frozen selection/human rule","reply":simple,"latency_ms":baseline_ms,"model_calls":0,"tool_calls":0},
            "actual":{"response":public,"http_status":status,"latency_ms":chat_call["latency_ms"],"history_status":history_status,
                "history_message_count":len(history.get("messages",[])),"exact_reply_in_history":any(x.get("text",x.get("content"))==reply for x in history.get("messages",[])) if reply else False,
                "model_call_count":None,"tool_call_count":None},"http_calls":client.calls,
            "human_adjudication":"pending","useful_outcome":None,"grounding":None,"language_correct":None})
        client.call("/api/auth/logout", {}, method="POST")
        print(json.dumps({"case":name,"http_status":status,"latency_ms":chat_call["latency_ms"]}),flush=True)
    return {"schema":"savia-customer-comparison/v1","recorded_at":datetime.now(timezone.utc).isoformat(),
        "runtime":cfg["runtime"],"generated_only":True,"sample_size":len(rows),"real_portions":["actual authenticated HTTP calls","actual configured customer runtime replies"],
        "simulated_portions":["fictional generated banking data","sandbox intake if explicitly confirmed separately"],
        "baseline_scope":"Local deterministic copy on same facts; no task execution, provider, handoff or follow-up. Not a prior production runtime.",
        "limits":["AI-authored cases; not representative traffic", "No independent human adjudication yet", "Provider and tool counts require separately observed runtime evidence", "HTTP 200 does not prove resolved dispute"],"cases":rows}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config-private",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--selected-reference")
    p.add_argument("--cases",help="Optional comma-separated fixed case IDs; does not rewrite prompts or labels")
    a=p.parse_args()
    cfg=json.loads(a.config_private.read_text(encoding="utf-8"))
    if cfg.get("generated_only") is not True or not cfg.get("runtime"):
        p.error("confirmed generated-only runtime and provenance required")
    if a.output.exists():
        p.error("new output path required")
    selected_cases=CASES if not a.cases else [c for c in CASES if c[0] in a.cases.split(',')]
    if not selected_cases or a.cases and set(a.cases.split(',')) != {c[0] for c in selected_cases}:
        p.error('unknown fixed case ID')
    report=run(cfg,a.selected_reference,selected_cases)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"sample_size":report["sample_size"],"output":str(a.output),"http_chat_success":sum(x["actual"]["http_status"]==200 for x in report["cases"])}))
if __name__=="__main__":
    main()
