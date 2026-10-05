"""Read persisted FLUJO messages from Docker without changing running services."""
from __future__ import annotations

import json
import subprocess
from urllib.parse import quote
from .common import content_text, stable_id, timestamp

# Only conversation/message fields are exported. Configuration, provider keys,
# frozen system prompts, environment, variables and database keys are not read.
DOCKER_READER = r'''
const fs=require('fs'),path=require('path');
const base=process.argv[1]; let count=0, bad=0;
const workspaces=fs.existsSync(base)?fs.readdirSync(base).filter(n=>!n.startsWith('.')&&fs.statSync(path.join(base,n)).isDirectory()):[];
for(const workspace of workspaces){
 const db=path.join(base,workspace,'db'), dir=path.join(db,'conversations');
 const seen=new Set();
 const emit=(m,c,origin)=>{if(!m||!['user','assistant','tool','function'].includes(m.role)||m.type==='thinking')return;
 const id=m.id||m.messageId||null;const key=c.conversationId+'|'+(id||JSON.stringify([m.role,m.timestamp,m.content]));if(seen.has(key))return;seen.add(key);
 console.log(JSON.stringify({workspace,conversationId:c.conversationId,title:c.title||'FLUJO conversation',createdAt:c.createdAt,flowId:c.flowId,flowName:c.statisticsFlowName,source:c.source,bankingOwned:!!c.bankingOwned,origin,message:{id,role:m.role,content:m.content,timestamp:m.timestamp,toolCalls:m.tool_calls||m.toolCalls,name:m.name}}));count++;};
 const conversations=new Map();
 if(fs.existsSync(dir))for(const name of fs.readdirSync(dir).filter(n=>n.endsWith('.json'))){try{const c=JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));c.conversationId=c.conversationId||name.slice(0,-5);conversations.set(c.conversationId,c);for(const m of c.messages||[])emit(m,c,'conversation-state');}catch(e){bad++;}}
 const logs=path.join(db,'conversation-logs');
 if(fs.existsSync(logs))for(const name of fs.readdirSync(logs).filter(n=>n.endsWith('.jsonl'))){const id=name.slice(0,-6),c=conversations.get(id)||{conversationId:id,title:'Recovered FLUJO log'};try{for(const line of fs.readFileSync(path.join(logs,name),'utf8').split('\n')){if(!line.trim())continue;try{const e=JSON.parse(line);if(e.type==='message'&&e.message)emit({...e.message,timestamp:e.message.timestamp||e.timestamp},c,'conversation-log');}catch(e){bad++;}}}catch(e){bad++;}}
 console.log(JSON.stringify({_workspace:workspace,conversations:conversations.size}));
}
console.log(JSON.stringify({_summary:true,messages:count,malformedRecords:bad,workspaces:workspaces.length}));
'''


def collect(repo, config):
    container = config.get("flujo_container", "flujo-slack-flujo-1")
    base = config.get("flujo_workspace_path", "/data/flujo/workspaces")
    events, notes, stats = [], [], {"conversations": 0, "messages": 0, "missingTimestamps": 0}
    try:
        process = subprocess.Popen(["docker", "exec", container, "node", "-e", DOCKER_READER, base], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        for line in process.stdout:
            row = json.loads(line)
            if row.get("_workspace"):
                stats["conversations"] += row["conversations"]
                continue
            if row.get("_summary"):
                stats.update({key: value for key, value in row.items() if not key.startswith("_")})
                continue
            message = row["message"]
            body = content_text(message.get("content"))
            if message.get("toolCalls"):
                body += "\n" + json.dumps(message["toolCalls"], ensure_ascii=False)
            time = message.get("timestamp")
            if not time:
                stats["missingTimestamps"] += 1
                continue
            conversation = row["conversationId"]
            uid = message.get("id") or stable_id([message["role"], time, body])
            events.append({"id": f"flujo:{row['workspace']}:{conversation}:{uid}", "timestamp": timestamp(time), "source": "flujo", "kind": message["role"] + "_message", "title": row["title"], "body": body, "actor": "FLUJO" if message["role"] == "assistant" else message.get("name") or ("Tool" if message["role"] in ("tool", "function") else "User"), "url": config.get("flujo_url", "http://localhost:43420") + "/chat?conversation=" + quote(conversation) + "&message=" + quote(str(uid)), "threadId": conversation, "tags": [row.get("flowName") or "FLUJO", message["role"]] + (["banking-run"] if row.get("bankingOwned") else []), "metadata": {"workspace": row["workspace"], "flowId": row.get("flowId"), "flowName": row.get("flowName"), "role": message["role"], "origin": row["origin"], "conversationSource": row.get("source"), "bankingOwned": row.get("bankingOwned"), "rawTimestamp": time}})
        errors = process.stderr.read()
        code = process.wait(timeout=600)
        if code:
            raise RuntimeError("Docker history reader failed: " + errors[:180])
        if not stats.get("workspaces"):
            raise RuntimeError("No workspaces found at the configured Docker path")
        notes.append(f"Read-only persisted conversation state and append-only message logs from {container}, all workspaces. Includes banking/test conversations; system prompts and hidden reasoning are excluded. UI instance: {config.get('flujo_url', 'http://localhost:43420')}.")
        if stats["missingTimestamps"]:
            notes.append(f"Skipped {stats['missingTimestamps']} messages with no authoritative message timestamp.")
        if stats.get("malformedRecords"):
            notes.append(f"Skipped {stats['malformedRecords']} malformed/truncated records; rerun after active writes settle.")
        return {"events": events, "status": "partial" if stats["missingTimestamps"] or stats.get("malformedRecords") else "ok", "notes": notes, "stats": stats}
    except Exception as error:
        return {"events": events, "status": "partial" if events else "unavailable", "notes": [f"FLUJO: {type(error).__name__}: {str(error)[:220]}"], "stats": stats}
