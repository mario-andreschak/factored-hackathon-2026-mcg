"""Evidence-backed agent lifetimes, dispatches, and saved FLUJO flow graphs.

The live reader is deliberately a projection: it never emits node properties,
frozen prompts, environment, variables, messages, reasoning, or tool outputs.
Tool arguments are inspected only for an allowlist of public coordination IDs.
Saved graph definitions are declarations; only timestamped execution logs make
an execution event. Last observed activity is never presented as completion.
"""
from __future__ import annotations

from bisect import bisect_right
import ast
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from .common import sanitize, stable_id
from .codex import _discovery, _utc, _time_key, _epoch


DOCKER_READER = r'''
const fs=require('fs'),path=require('path');
const base=process.argv[1];let bad=0,logs=0;
const emit=(kind,workspace,row)=>console.log(JSON.stringify({kind,workspace,...row}));
const read=p=>{try{return JSON.parse(fs.readFileSync(p,'utf8'));}catch{bad++;return null;}};
const names=p=>fs.existsSync(p)?fs.readdirSync(p).filter(n=>n.endsWith('.json')):[];
const pick=(v,keys)=>Object.fromEntries(keys.filter(k=>v&&v[k]!==undefined).map(k=>[k,v[k]]));
const graph=f=>({id:f.id,name:f.name,createdAt:f.createdAt,updatedAt:f.updatedAt,
 nodes:(f.nodes||[]).map((n,i)=>({id:n.id,label:n.data?.label||n.label||n.id,type:n.type||n.data?.type||'process',
 x:Number(n.position?.x)||0,y:Number(n.position?.y)||i*160,subflowId:n.data?.properties?.subflowId})),
 edges:(f.edges||[]).map(e=>({id:e.id,from:e.source,to:e.target,label:e.label,type:e.type}))});
const kinds=new Set(['run:start','run:done','node:enter','node:exit','handoff','subflow:start','subflow:done','model:dispatch','model:dispatch-result','tool:start','tool:done']);
for(const workspace of fs.existsSync(base)?fs.readdirSync(base).filter(n=>!n.startsWith('.')&&fs.statSync(path.join(base,n)).isDirectory()):[]){
 const db=path.join(base,workspace,'db'),flows=new Map(),conversations=new Map(),selected=new Set(),flowIds=new Set();
 for(const name of names(path.join(db,'flows'))){const f=read(path.join(db,'flows',name));if(f)flows.set(f.id,f);}
 for(const name of names(path.join(db,'conversations'))){const c=read(path.join(db,'conversations',name));if(!c)continue;c.conversationId=c.conversationId||name.slice(0,-5);conversations.set(c.conversationId,c);
  if(/^Hackathon_Release_/i.test(c.statisticsFlowName||c.flowSnapshot?.name||flows.get(c.flowId)?.name||'')||/\bdevthread\b/i.test(c.title||''))selected.add(c.conversationId);}
 const tasks=names(path.join(db,'subflow-tasks')).map(n=>read(path.join(db,'subflow-tasks',n))).filter(Boolean);
 let changed=true;while(changed){changed=false;for(const c of conversations.values()){
  if(selected.has(c.conversationId)){for(const id of [c.parentConversationId,c.rootConversationId])if(id&&conversations.has(id)&&!selected.has(id)){selected.add(id);changed=true;}}
  else if(selected.has(c.parentConversationId)||selected.has(c.rootConversationId)){selected.add(c.conversationId);changed=true;}}
  for(const t of tasks)if(selected.has(t.originConversationId)||selected.has(t.childConversationId))for(const id of [t.originConversationId,t.childConversationId])if(id&&conversations.has(id)&&!selected.has(id)){selected.add(id);changed=true;}}
 for(const id of selected){const c=conversations.get(id);if(!c)continue;if(c.flowId)flowIds.add(c.flowId);
  const row=pick(c,['conversationId','title','flowId','createdAt','updatedAt','status','currentNodeId','source','parentConversationId','rootConversationId','logicalRunId','parentLogicalRunId','plannedExecutionId','statisticsRunStartedAt','statisticsFlowRevisionId']);
  row.flowName=c.statisticsFlowName||c.flowSnapshot?.name||flows.get(c.flowId)?.name;
  row.subflowLane=pick(c.subflowLane,['laneIndex','laneCount','parentNodeId']);
  row.codexSessions=Object.entries(c.codexSessions||{}).map(([nodeId,s])=>({nodeId,...pick(s,['adapter','threadId','updatedAt'])}));
  if(c.flowSnapshot)row.flowSnapshot=graph(c.flowSnapshot);emit('conversation',workspace,row);
  const file=path.join(db,'conversation-logs',id+'.jsonl');if(!fs.existsSync(file))continue;logs++;
  for(const [lineIndex,line] of fs.readFileSync(file,'utf8').split('\n').entries()){if(!line.trim())continue;let e;try{e=JSON.parse(line);}catch{bad++;continue;}if(!kinds.has(e.type))continue;
   const r=pick(e,['type','timestamp','seq','status','action','toNodeId','edgeId','subflowId','depth','laneIndex','laneCount','laneConversationId','dispatchId','outcome']);
   r.conversationId=id;r.line=lineIndex+1;r.node=pick(e.node,['nodeId','nodeName','nodeType']);r.from=pick(e.from,['nodeId']);
   if(e.turn)r.turn={...pick(e.turn,['id','conversationId','runId','modelName','adapter','operation','timestamp','outcome','attempt']),node:pick(e.turn.node,['nodeId','nodeName','nodeType'])};
   emit('log',workspace,r);}}
 for(const t of tasks)if(selected.has(t.originConversationId)||selected.has(t.childConversationId)){if(t.flowId)flowIds.add(t.flowId);emit('task',workspace,pick(t,['taskId','originConversationId','originNodeId','originLogicalRunId','flowId','childConversationId','status','createdAt','updatedAt','completedAt']));}
 for(const id of flowIds){const f=flows.get(id);if(f)emit('flow',workspace,{flow:graph(f),basis:'current-declaration'});
  const dir=path.join(db,'flow-versions',id);for(const name of names(dir)){const v=read(path.join(dir,name));if(v?.flow)emit('flow',workspace,{flow:graph(v.flow),versionId:v.versionId,savedAt:v.savedAt,basis:'saved-version'});}}
 const plans=read(path.join(db,'planned_executions.json'));
 for(const p of plans?.executions||[]){if(!flowIds.has(p.flowId))continue;emit('plan',workspace,{...pick(p,['id','name','flowId','createdAt','updatedAt','enabled']),trigger:pick(p.trigger,['type','cron','timezone'])});
  const file=path.join(db,'planned-execution-runs',p.id+'.json');if(fs.existsSync(file))for(const r of read(file)||[])emit('planned-run',workspace,{planId:p.id,flowId:p.flowId,planName:p.name,...pick(r,['runId','conversationId','firedAt','finishedAt','status','triggerSummary'])});}
}
console.log(JSON.stringify({kind:'summary',malformedRecords:bad,conversationLogs:logs}));
'''


def _result(results, source):
    value = results.get(source, {}) if isinstance(results, dict) else {}
    return value.get('result', value) if isinstance(value, dict) else {}


def _session_id(source, identity, workspace=None):
    return f'{source}:{workspace}:{identity}' if workspace else f'{source}:{identity}'


def _flow_id(workspace, identity, graph):
    return f'flujo:{workspace}:{identity}:{stable_id(json.dumps(graph, sort_keys=True))}'


def _event(identity, time, source, kind, title, body, session, metadata, url=None):
    return {'id': identity, 'timestamp': time, 'source': source, 'kind': kind,
            'title': title, 'body': body, 'actor': 'Codex' if source == 'codex' else 'FLUJO',
            'url': url or session.get('url'), 'threadId': session.get('threadId'),
            'tags': ['agent-topology', kind], 'metadata': {'sessionId': session['id'],
            'flowId': session.get('flowId'), 'flowDefinitionId': session.get('flowDefinitionId'),
            'developmentRelevant': True, **metadata}}


def _compact_text(value, length=180):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:length]


def _role(value):
    text = str(value or '').lower()
    for name, pattern in [('supervisor', 'supervis|coordinat|orchestrat'), ('builder', 'build|implement'),
                          ('review', 'review|security'), ('audit', 'audit'), ('watchdog', 'watchdog'),
                          ('frontend', 'frontend|ui_'), ('backend', 'backend'), ('dataset', 'dataset|data_')]:
        if re.search(pattern, text):
            return name
    return 'agent'


def _safe_json(value):
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(str(value))
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


# These are all structural APIs. Shell commands, arbitrary tool arguments,
# summaries, prompts, and free-form message bodies cannot enter this export.
_ACTIONS = {
    'spawn_agent': 'spawn', 'followup_task': 'steer', 'send_message': 'steer',
    'interrupt_agent': 'interrupt', 'create_thread': 'dispatch', 'fork_thread': 'fork',
    'send_message_to_thread': 'steer', 'handoff_thread': 'handoff',
}
_ARG_FIELDS = {'task_name', 'target', 'threadId', 'hostId', 'destinationHostId',
               'title', 'fork_turns', 'model', 'reasoning_effort', 'thinking'}


def _action_name(name):
    short = re.split(r'__|\.', str(name))[-1]
    return short if short in _ACTIONS else None


def _nested_actions(code):
    """Extract literal structured coordination calls without executing JS.

    JSON literals have exact semantics here. Variable-built argument objects
    are reported as unresolved rather than guessing targets from prose.
    """
    for match in re.finditer(r'\btools\.([A-Za-z0-9_]+)\s*\(\s*(\{)', str(code)):
        action = _action_name(match.group(1))
        if not action:
            continue
        start = match.start(2)
        decoder = json.JSONDecoder()
        try:
            arguments, _ = decoder.raw_decode(str(code)[start:])
        except ValueError:
            arguments = _literal_object(str(code)[start:])
        yield match.group(1), arguments if isinstance(arguments, dict) else {}


def _literal_object(source):
    """Read top-level scalar JS object fields without evaluating expressions.

    Codex scripts often use unquoted property names. A small lexical scanner
    keeps string contents and nested prompt objects out of target matching.
    Dynamic variables and template interpolation remain unresolved.
    """
    result, fields, start, depth, quoted, escaped = {}, [], 1, 0, None, False
    for index, char in enumerate(source[1:], 1):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quoted:
                quoted = None
            continue
        if char in ('"', "'", '`'):
            quoted = char
        elif char in ('{', '[', '('):
            depth += 1
        elif char == '}' and depth == 0:
            fields.append(source[start:index])
            break
        elif char in ('}', ']', ')'):
            depth -= 1
        elif char == ',' and depth == 0:
            fields.append(source[start:index])
            start = index + 1
    for field in fields:
        match = re.match(r'\s*(?:([A-Za-z_][A-Za-z0-9_]*)|["\']([A-Za-z_][A-Za-z0-9_]*)["\'])\s*:\s*([\s\S]+)', field)
        if not match:
            continue
        key, value = match.group(1) or match.group(2), match.group(3).strip()
        if key not in _ARG_FIELDS:
            continue
        try:
            parsed = json.loads(value) if value.startswith('"') or value in ('true', 'false', 'null') else ast.literal_eval(value) if value.startswith("'") or re.fullmatch(r'-?\d+', value) else None
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, (str, int, bool)):
            result[key] = parsed
    return result


def _output_ids(raw):
    """Only IDs/status survive outputs; no output body is ever exported."""
    output = _safe_json(raw)
    selected = {}
    safe_keys = {'agent_id', 'agentId', 'threadId', 'childThreadId', 'clientThreadId',
                 'task_name', 'canonical_task_name', 'taskName', 'status', 'operationId'}
    def visit(value, depth=0):
        if depth > 5:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in safe_keys and isinstance(item, (str, bool)):
                    selected.setdefault(key, item)
                elif key == 'text' and isinstance(item, str):
                    visit(_safe_json(item), depth + 1)
                elif isinstance(item, (dict, list)):
                    visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:30]:
                visit(item, depth + 1)
    visit(output)
    # Native collaboration tools sometimes return an ID in a plain text line.
    for key in ('agent_id', 'agentId', 'threadId', 'childThreadId', 'clientThreadId', 'canonical_task_name'):
        match = re.search(r'["\']?' + key + r'["\']?\s*[:=]\s*["\']?([A-Za-z0-9_./-]{4,})', str(raw))
        if match:
            selected.setdefault(key, match.group(1))
    return selected


def _read_actions(repo, config, stats, notes):
    options = config.get('codex', {}) or {}
    home = Path(options.get('home') or config.get('codex_home') or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    if not home.is_dir():
        notes.append('Codex coordination details unavailable: no readable local rollout store.')
        return [], []
    files, _ = _discovery(home, Path(repo).resolve(), options, notes)
    actions, discovered, seen = [], [], set()
    for path, meta in files:
        thread_id = str(meta['id'])
        source = _safe_json(meta.get('source'))
        spawn = source.get('subagent', {}).get('thread_spawn', {})
        parent = meta.get('parent_thread_id') or spawn.get('parent_thread_id')
        created = _utc(meta.get('timestamp') or meta.get('created_at_ms') or meta.get('created_at'))
        discovered.append({'id': thread_id, 'title': meta.get('display_name') or meta.get('agent_path') or meta.get('agent_nickname') or 'Codex chat ' + thread_id[:8],
                           'createdAt': created, 'parentThreadId': parent, 'forkedFromId': meta.get('forked_from_id'),
                           'agentPath': meta.get('agent_path') or spawn.get('agent_path'),
                           'agentRole': meta.get('agent_role') or spawn.get('agent_role'), 'archived': bool(meta.get('archived'))})
        calls = {}
        try:
            with path.open(encoding='utf-8-sig') as handle:
                for line_no, line in enumerate(handle, 1):
                    try:
                        record = json.loads(line)
                    except ValueError:
                        stats['malformedCodexRecords'] += 1
                        continue
                    if record.get('type') != 'response_item':
                        continue
                    p = record.get('payload', {})
                    time = _utc(record.get('timestamp'))
                    if not time or created and _epoch(time) < _epoch(created):
                        continue  # Copied parent history is not a child action.
                    typ, call_id = p.get('type'), p.get('call_id')
                    if typ in ('function_call_output', 'custom_tool_call_output'):
                        paired = calls.get(call_id, [])
                        # A batched JS exec can print several unordered tool
                        # outputs. Assigning its first ID to every create/spawn
                        # action would invent an association. Explicit input
                        # target IDs still resolve steer calls independently.
                        if len(paired) == 1:
                            paired[0]['resultIds'] = _output_ids(p.get('output'))
                        elif paired:
                            stats['ambiguousBatchedResults'] += 1
                        continue
                    if typ not in ('function_call', 'custom_tool_call'):
                        continue
                    name = p.get('name', '')
                    entries = [(name, _safe_json(p.get('arguments', p.get('input'))))] if _action_name(name) else list(_nested_actions(p.get('input', ''))) if name in ('functions.exec', 'functions.run', 'exec', 'run') else []
                    for index, (tool, arguments) in enumerate(entries):
                        key = f'{call_id or stable_id([thread_id,line_no])}:{index}'
                        if key in seen:
                            continue
                        seen.add(key)
                        short = _action_name(tool)
                        safe = {k: v for k, v in arguments.items() if k in _ARG_FIELDS and isinstance(v, (str, int, bool))}
                        # create_thread.target is a structural destination object;
                        # expose project id and environment type only.
                        if short == 'create_thread' and isinstance(arguments.get('target'), dict):
                            target = arguments['target']
                            safe['projectId'] = target.get('projectId')
                            safe['targetType'] = target.get('type')
                        action = {'key': key, 'threadId': thread_id, 'timestamp': time, 'action': short,
                                  'kind': _ACTIONS[short], 'tool': tool, 'arguments': safe,
                                  'resultIds': {}, 'originPath': str(path), 'line': line_no}
                        actions.append(action)
                        calls.setdefault(call_id, []).append(action)
        except OSError:
            stats['unreadableCodexRollouts'] += 1
    stats['codexCoordinationCalls'] = len(actions)
    return actions, discovered


def _read_flujo(config, stats, notes):
    container = config.get('flujo_container', 'flujo-slack-flujo-1')
    base = config.get('flujo_workspace_path', '/data/flujo/workspaces')
    try:
        process = subprocess.run(['docker', 'exec', container, 'node', '-e', DOCKER_READER, base],
                                 capture_output=True, encoding='utf-8', errors='replace', timeout=180)
        if process.returncode:
            notes.append(f'FLUJO topology reader unavailable in {container}; persisted message evidence remains visible.')
            stats['flujoReaderUnavailable'] = 1
            return []
        rows = []
        for line in process.stdout.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                stats['malformedTopologyProjection'] += 1
                continue
            if row.get('kind') == 'summary':
                stats['malformedFlujoRecords'] = row.get('malformedRecords', 0)
                stats['flujoConversationLogs'] = row.get('conversationLogs', 0)
            else:
                rows.append(row)
        return rows
    except (OSError, subprocess.TimeoutExpired):
        stats['flujoReaderUnavailable'] = 1
        notes.append('FLUJO topology Docker reader unavailable or timed out; no execution timestamps were guessed.')
        return []


def _new_session(identity, source, thread, label, events, **extra):
    ordered = sorted(events, key=lambda e: (_time_key(e['timestamp']), e['id']))
    return {'id': identity, 'source': source, 'threadId': thread,
            'label': _compact_text(label), 'role': _role(label), 'parentId': None,
            'startedAt': ordered[0]['timestamp'] if ordered else None,
            'lastActivityAt': ordered[-1]['timestamp'] if ordered else None,
            'endedAt': None, 'endBasis': 'No authoritative completion recorded',
            'eventIds': [e['id'] for e in ordered], 'eventCount': len(ordered), **extra}


def derive(repo, source_results, config):
    """Refresh a compact graph from immutable source references and live stores.

    Offline callers should use the cached topology result. Calling derive in
    offline mode performs no live reads, yielding only message-derived sessions
    with an explicit coverage note; this makes its read boundary independently
    safe when embedded in another rebuilding command.
    """
    stats, notes = Counter(), []
    events, agent_edges, sessions, flows = [], [], {}, {}
    codex_result, flujo_result = _result(source_results, 'codex'), _result(source_results, 'flujo')
    source_events = codex_result.get('events', []) + flujo_result.get('events', [])
    by_thread = defaultdict(list)
    for e in source_events:
        if e.get('threadId') and _utc(e.get('timestamp')):
            workspace = e.get('metadata', {}).get('workspace') if e['source'] == 'flujo' else None
            by_thread[_session_id(e['source'], e['threadId'], workspace)].append(e)
    if config.get('offline'):
        actions, discovered, rows = [], [], []
        notes.append('Offline topology fallback uses captured message metadata only; live agent calls and Docker execution logs were not read.')
    else:
        actions, discovered = _read_actions(repo, config, stats, notes)
        rows = _read_flujo(config, stats, notes)
    for thread in [*codex_result.get('threads', []), *discovered]:
        identity = _session_id('codex', thread['id'])
        captured = by_thread.get(identity, [])
        parent = thread.get('parentThreadId') or thread.get('forkedFromId')
        existing = sessions.get(identity)
        data = _new_session(identity, 'codex', thread['id'], thread.get('title') or thread.get('agentPath') or 'Codex chat', captured,
                            parentId=_session_id('codex', parent) if parent else None,
                            agentPath=thread.get('agentPath'), role=thread.get('agentRole') or _role(thread.get('title') or thread.get('agentPath')),
                            startedAt=_utc(thread.get('createdAt')) or (captured[0]['timestamp'] if captured else None),
                            startBasis='Codex session metadata timestamp', archived=thread.get('archived', False),
                            url=f"codex://threads/{thread['id']}")
        if existing:
            data['endedAt'] = existing.get('endedAt')
        sessions[identity] = data
    # Older caches can lack a thread index but still contain parent metadata.
    for identity, captured in by_thread.items():
        if identity in sessions or captured[0]['source'] != 'codex':
            continue
        metadata = captured[0].get('metadata', {})
        parent = metadata.get('parentThreadId') or metadata.get('forkedFromId')
        sessions[identity] = _new_session(identity, 'codex', captured[0]['threadId'], metadata.get('threadTitle') or captured[0].get('title'), captured,
                                          parentId=_session_id('codex', parent) if parent else None, agentPath=metadata.get('agentPath'),
                                          startBasis='First captured visible message', url=captured[0].get('url'))
    aliases = defaultdict(list)
    for session in sessions.values():
        if session.get('agentPath'):
            aliases[(session.get('parentId'), session['agentPath'])].append(session['id'])
            aliases[(session.get('parentId'), session['agentPath'].split('/')[-1])].append(session['id'])

    def resolve_alias(origin, alias, time, spawning=False):
        if alias == '/root':
            current, seen = origin, set()
            while current.get('parentId') in sessions and current['id'] not in seen:
                seen.add(current['id'])
                current = sessions[current['parentId']]
            return current['id'] if current['id'] != origin['id'] else None
        scope, visited = origin['id'], set()
        while scope and scope not in visited:
            visited.add(scope)
            candidates = list(dict.fromkeys(aliases.get((scope, alias), []) + aliases.get((scope, str(alias).split('/')[-1]), [])))
            dated = [sessions[key] for key in candidates if key in sessions and sessions[key].get('startedAt')]
            if dated:
                if spawning:
                    return min(dated, key=lambda s: abs(_epoch(s['startedAt']) - _epoch(time)))['id']
                available = [s for s in dated if _epoch(s['startedAt']) <= _epoch(time)]
                if available:
                    return max(available, key=lambda s: _epoch(s['startedAt']))['id']
            scope = sessions.get(scope, {}).get('parentId')
        return None

    def add_edge(from_id, to_id, kind, time, ids, basis, **extra):
        if not from_id or not to_id or not time:
            return
        identity = 'agent-edge:' + stable_id([from_id, to_id, kind, time, ids])
        agent_edges.append({'id': identity, 'from': from_id, 'to': to_id, 'kind': kind,
                            'timestamp': time, 'eventIds': ids, 'basis': basis, **extra})

    for action in sorted(actions, key=lambda a: (_time_key(a['timestamp']), a['key'])):
        origin = sessions.get(_session_id('codex', action['threadId']))
        if not origin:
            continue
        args, result = action['arguments'], action['resultIds']
        target = result.get('threadId') or result.get('childThreadId') or result.get('agent_id') or result.get('agentId')
        if action['action'] not in ('create_thread', 'spawn_agent', 'fork_thread'):
            target = args.get('threadId') or args.get('target')
        target_id = _session_id('codex', target) if target else None
        if target_id not in sessions:
            alias = args.get('task_name') or target or result.get('canonical_task_name') or result.get('task_name')
            target_id = resolve_alias(origin, alias, action['timestamp'], action['kind'] in ('spawn', 'dispatch', 'fork'))
        if target_id and target:
            aliases[(origin['id'], target)].append(target_id)
        if not target_id and target and re.fullmatch(r'[a-f0-9-]{30,40}', str(target)):
            target_id = _session_id('codex', target)
            sessions[target_id] = _new_session(target_id, 'codex', target, args.get('title') or args.get('task_name') or 'Referenced Codex chat', [],
                                               startedAt=action['timestamp'], startBasis='Coordination tool reference; local messages unavailable',
                                               coverage='referenced-only', url=f'codex://threads/{target}')
        metadata = {'tool': action['tool'], 'coordinationKind': action['kind'], 'targetSessionId': target_id,
                    'targetThreadId': sessions[target_id]['threadId'] if target_id in sessions else None,
                    'taskName': args.get('task_name'), 'resultStatus': result.get('status'),
                    'originPath': action['originPath'], 'line': action['line'],
                    'basis': 'Timestamped Codex coordination tool call and allowlisted result IDs',
                    'targetResolved': bool(target_id)}
        target_label = sessions[target_id]['label'] if target_id in sessions else _compact_text(args.get('task_name') or args.get('target') or args.get('threadId') or 'unresolved target')
        event = _event('codex:coordination:' + stable_id(action['key']), action['timestamp'], 'codex', 'agent_' + action['kind'],
                       f"{origin['label']} · {action['kind']} → {target_label}",
                       f"Recorded {action['tool']} coordination call. Target: {target_label}. " + ('Linked by an explicit tool result or thread/agent identifier.' if target_id else 'Target identity is unavailable; no relationship was invented.'),
                       origin, metadata)
        events.append(event)
        add_edge(origin['id'], target_id, action['kind'], action['timestamp'], [event['id']], metadata['basis'])
        if target_id and action['kind'] in ('spawn', 'dispatch', 'fork'):
            target_session = sessions[target_id]
            target_session['parentId'] = target_session.get('parentId') or origin['id']
            if args.get('task_name'):
                aliases[(origin['id'], args['task_name'])].append(target_id)
        if not target_id:
            stats['unresolvedCoordinationTargets'] += 1

    for session in list(sessions.values()):
        parent = session.get('parentId')
        if not parent or not session.get('startedAt'):
            continue
        if not any(edge['to'] == session['id'] and edge['kind'] in ('spawn', 'dispatch', 'fork') for edge in agent_edges):
            event_id = 'codex:session:' + session['threadId'] + ':started'
            event = _event(event_id, session['startedAt'], 'codex', 'agent_spawn', f"Codex agent starts · {session['label']}",
                           'Parent-child relationship is recorded in Codex session metadata. The precise dispatch call may be unavailable.',
                           session, {'parentSessionId': parent, 'basis': 'Codex session parent/fork metadata', 'agentPath': session.get('agentPath')})
            events.append(event)
            add_edge(parent, session['id'], 'spawn', session['startedAt'], [event_id], 'Codex session parent/fork metadata')

    flow_versions = defaultdict(list)
    for row in rows:
        if row['kind'] != 'flow':
            continue
        f, workspace = row['flow'], row['workspace']
        graph = {'nodes': f.get('nodes', []), 'edges': f.get('edges', [])}
        identity = _flow_id(workspace, f['id'], graph)
        time = _utc(row.get('savedAt') if row.get('basis') == 'saved-version' else f.get('updatedAt'))
        declared = row.get('basis') == 'current-declaration'
        if identity not in flows:
            flows[identity] = {'id': identity, 'source': 'flujo', 'workspace': workspace,
                              'flowDefinitionId': f['id'], 'label': _compact_text(f.get('name')),
                              'nodes': [{**n, 'role': _role(n.get('label'))} for n in graph['nodes']],
                              'edges': [{**e, 'label': e.get('label') or ('Tool access' if e.get('type') == 'mcpEdge' else 'Handoff')} for e in graph['edges']],
                              'availableFrom': time, 'declaredOnly': True, 'currentSnapshot': declared,
                              'revisionIds': [], 'basis': 'Current saved declaration; execution is established separately' if declared else 'Persisted historical flow-version timestamp; declaration only',
                              'eventIds': []}
        flow = flows[identity]
        flow['currentSnapshot'] = flow['currentSnapshot'] or declared
        if row.get('versionId'):
            flow['revisionIds'].append(str(row['versionId']))
        if time and (not flow.get('availableFrom') or _epoch(time) < _epoch(flow['availableFrom'])):
            flow['availableFrom'] = time
            flow['basis'] = 'Persisted historical flow-version timestamp; declaration only'
        if time:
            flow_versions[(workspace, f['id'])].append((_epoch(time), identity, declared))
    for versions in flow_versions.values():
        versions.sort()

    def graph_at(workspace, definition, time, snapshot=None):
        if snapshot:
            graph = {'nodes': snapshot.get('nodes', []), 'edges': snapshot.get('edges', [])}
            identity = _flow_id(workspace, definition, graph)
            if identity not in flows:
                flows[identity] = {'id': identity, 'source': 'flujo', 'workspace': workspace,
                                  'flowDefinitionId': definition, 'label': _compact_text(snapshot.get('name')),
                                  'nodes': [{**n, 'role': _role(n.get('label'))} for n in graph['nodes']],
                                  'edges': graph['edges'], 'availableFrom': time, 'declaredOnly': True,
                                  'currentSnapshot': False, 'revisionIds': [], 'basis': 'Conversation-persisted execution flow snapshot', 'eventIds': []}
            return identity, 'Conversation-persisted execution flow snapshot'
        versions = flow_versions.get((workspace, definition), [])
        historic = [v for v in versions if not v[2] and time and v[0] <= _epoch(time)]
        if historic:
            return historic[-1][1], 'Most recent saved graph version at conversation start; exact executed revision may differ'
        if versions:
            return versions[-1][1], 'Available declared graph; historic executed graph unavailable'
        return None, 'No saved graph available'

    convo_rows = {}
    for row in rows:
        if row['kind'] != 'conversation':
            continue
        workspace, thread = row['workspace'], row['conversationId']
        identity = _session_id('flujo', thread, workspace)
        captured = by_thread.get(identity, [])
        start = _utc(row.get('statisticsRunStartedAt') or row.get('createdAt'))
        graph_id, graph_basis = graph_at(workspace, row.get('flowId'), start, row.get('flowSnapshot'))
        parent = row.get('parentConversationId')
        lane = row.get('subflowLane', {})
        session = _new_session(identity, 'flujo', thread, row.get('title') or row.get('flowName') or 'FLUJO conversation', captured,
                               workspace=workspace, parentId=_session_id('flujo', parent, workspace) if parent else None,
                               rootId=_session_id('flujo', row['rootConversationId'], workspace) if row.get('rootConversationId') else identity,
                               parentNodeId=lane.get('parentNodeId'), laneIndex=lane.get('laneIndex'), laneCount=lane.get('laneCount'),
                               flowId=graph_id, flowDefinitionId=row.get('flowId'), flowLabel=row.get('flowName'),
                               graphBasis=graph_basis, recordedNodeId=row.get('currentNodeId'),
                               role=_role(row.get('flowName')), startedAt=start or (captured[0]['timestamp'] if captured else None),
                               startBasis='Persisted conversation run-start / creation timestamp', status=row.get('status'),
                               statusBasis='Current persisted conversation state; completion time requires a log',
                               plannedExecutionId=row.get('plannedExecutionId'), logicalRunId=row.get('logicalRunId'),
                               url=config.get('flujo_url', 'http://localhost:43420') + '/chat?conversation=' + quote(thread))
        sessions[identity] = session
        convo_rows[identity] = row

    # Provider thread IDs are useful cross-system correlations, but this field
    # is a persisted *current binding*. It does not prove that every earlier
    # model turn used the same provider thread, so it produces no replay event.
    for identity, row in convo_rows.items():
        session = sessions[identity]
        session['runtimeBindings'] = []
        for binding in row.get('codexSessions', []):
            provider_thread = binding.get('threadId')
            if not provider_thread:
                continue
            time = _utc(binding.get('updatedAt'))
            target_id = _session_id('codex', provider_thread)
            linked = target_id in sessions
            session['runtimeBindings'].append({'nodeId': binding.get('nodeId'), 'adapter': binding.get('adapter'),
                                               'threadId': provider_thread, 'sessionId': target_id if linked else None,
                                               'updatedAt': time, 'localRolloutAvailable': linked,
                                               'basis': 'Current persisted provider-thread binding; historical reconnections are not recoverable from this field'})
            if linked and time:
                add_edge(identity, target_id, 'runtime_binding', time, [],
                         'Current persisted provider-thread binding; declaration only',
                         sessionId=identity, flowId=session.get('flowId'), fromNodeId=binding.get('nodeId'),
                         currentSnapshot=True, executed=False)
            stats['providerThreadBindings'] += 1
            stats['linkedLocalProviderThreads' if linked else 'providerThreadsOutsideLocalProject'] += 1

    # Preserve a useful message-only topology when Docker is unavailable. These
    # lifetimes and parents come only from captured metadata, with no node graph
    # or authoritative terminal event invented as a substitute for missing logs.
    for identity, captured in by_thread.items():
        if identity in sessions or captured[0]['source'] != 'flujo':
            continue
        first = captured[0]
        metadata = first.get('metadata', {})
        if not (str(metadata.get('flowName') or '').startswith('Hackathon_Release_') or re.search(r'\bdevthread\b', first.get('title', ''), re.I)):
            continue
        sessions[identity] = _new_session(identity, 'flujo', first['threadId'], first.get('title'), captured,
                                          workspace=metadata.get('workspace'), flowDefinitionId=metadata.get('flowId'),
                                          flowLabel=metadata.get('flowName'), role=_role(metadata.get('flowName')),
                                          graphBasis='Execution graph unavailable; retained captured messages',
                                          startBasis='First captured message timestamp; run-start unavailable',
                                          url=first.get('url'))

    node_timeline = defaultdict(list)
    dispatch_nodes = {}

    def node_graph(session, node_id, time):
        preferred = flows.get(session.get('flowId'), {})
        if any(node.get('id') == node_id for node in preferred.get('nodes', [])):
            return session.get('flowId'), session.get('flowDefinitionId')
        matches = [f for f in flows.values() if f.get('workspace') == session.get('workspace') and any(node.get('id') == node_id for node in f['nodes'])]
        dated = [f for f in matches if f.get('availableFrom') and _epoch(f['availableFrom']) <= _epoch(time)]
        if dated:
            flow = max(dated, key=lambda f: _epoch(f['availableFrom']))
            return flow['id'], flow['flowDefinitionId']
        if matches:
            return matches[0]['id'], matches[0]['flowDefinitionId']
        return session.get('flowId'), session.get('flowDefinitionId')

    for row in rows:
        if row['kind'] != 'log':
            continue
        identity = _session_id('flujo', row['conversationId'], row['workspace'])
        session = sessions.get(identity)
        time = _utc(row.get('timestamp'))
        if not session or not time:
            stats['missingExecutionTimestamps'] += 1
            continue
        typ, node = row['type'], row.get('node', {})
        if typ == 'model:dispatch':
            node = row.get('turn', {}).get('node', {})
        node_id = node.get('nodeId') or row.get('from', {}).get('nodeId')
        dispatch_id = row.get('dispatchId') or row.get('turn', {}).get('id')
        if typ == 'model:dispatch' and dispatch_id:
            dispatch_nodes[(row['workspace'], dispatch_id)] = (node_id, node)
        elif typ == 'model:dispatch-result' and dispatch_id and (row['workspace'], dispatch_id) in dispatch_nodes:
            node_id, node = dispatch_nodes[(row['workspace'], dispatch_id)]
        graph_id, definition_id = node_graph(session, node_id, time) if node_id else (session.get('flowId'), session.get('flowDefinitionId'))
        execution_session = None
        turn_conversation = row.get('turn', {}).get('conversationId')
        if turn_conversation:
            execution_session = sessions.get(_session_id('flujo', turn_conversation, row['workspace']))
        if not execution_session and row.get('depth') and node_id:
            candidates = [s for s in sessions.values() if s.get('parentId') == identity and s.get('flowDefinitionId') == definition_id
                          and (row.get('laneIndex') is None or s.get('laneIndex') in (None, row.get('laneIndex')))
                          and s.get('startedAt') and _epoch(s['startedAt']) <= _epoch(time)]
            if candidates:
                execution_session = max(candidates, key=lambda s: _epoch(s['startedAt']))
        node_name = node.get('nodeName') or node_id or session['flowLabel'] or 'Run'
        metadata = {'nodeId': node_id, 'nodeType': node.get('nodeType'),
                    'flowId': graph_id, 'flowDefinitionId': definition_id,
                    'executingSessionId': execution_session['id'] if execution_session else identity,
                    'observedInSessionId': identity,
                    'fromNodeId': row.get('from', {}).get('nodeId'), 'toNodeId': row.get('toNodeId'), 'edgeId': row.get('edgeId'),
                    'subflowId': row.get('subflowId'), 'childConversationId': row.get('laneConversationId'),
                    'depth': row.get('depth', 0), 'laneIndex': row.get('laneIndex'), 'laneCount': row.get('laneCount'),
                    'sequence': row.get('seq'), 'line': row.get('line'), 'status': row.get('status'),
                    'dispatchId': dispatch_id, 'outcome': row.get('outcome'),
                    'modelName': row.get('turn', {}).get('modelName'), 'adapter': row.get('turn', {}).get('adapter'),
                    'originPath': f"{config.get('flujo_workspace_path', '/data/flujo/workspaces')}/{row['workspace']}/db/conversation-logs/{row['conversationId']}.jsonl",
                    'basis': 'Timestamped persisted FLUJO execution log', 'eventType': typ}
        child = row.get('laneConversationId')
        target = _session_id('flujo', child, row['workspace']) if child else None
        metadata['targetSessionId'] = target
        event_id = f"flujo:execution:{row['workspace']}:{row['conversationId']}:{row.get('seq') or stable_id([row.get('line'),typ,time])}"
        event = _event(event_id, time, 'flujo', typ.replace(':', '_').replace('-', '_'),
                       f'{node_name} · {typ}',
                       f"Recorded {typ} in conversation {row['conversationId']}." + (f" Node: {node_name}." if node_id else '') + (f" Child conversation: {child}." if child else '') + (f" Outcome: {row.get('outcome') or row.get('status')}." if row.get('outcome') or row.get('status') else ''),
                       session, metadata)
        events.append(event)
        if graph_id in flows:
            flows[graph_id]['declaredOnly'] = False
        if typ == 'run:done':
            session['endedAt'] = time
            session['endBasis'] = 'Authoritative run:done execution log'
            session['status'] = row.get('status') or session.get('status')
        elif typ == 'node:enter' and not row.get('depth') and node_id:
            node_timeline[identity].append((time, node_id, event_id))
        elif typ in ('subflow:start', 'subflow:done') and target:
            if target in sessions:
                sessions[target]['parentId'] = sessions[target].get('parentId') or identity
                sessions[target]['parentNodeId'] = sessions[target].get('parentNodeId') or node_id
                if typ == 'subflow:done':
                    sessions[target]['endedAt'] = time
                    sessions[target]['endBasis'] = 'Authoritative parent subflow:done execution log'
            add_edge(identity if typ == 'subflow:start' else target,
                     target if typ == 'subflow:start' else identity,
                     'dispatch' if typ == 'subflow:start' else 'task_completed', time, [event_id], metadata['basis'],
                     sessionId=identity, fromNodeId=node_id, flowId=graph_id)
        elif typ == 'handoff' and metadata['fromNodeId'] and metadata['toNodeId']:
            add_edge(identity, identity, 'node_transition', time, [event_id], metadata['basis'],
                     sessionId=identity, flowId=graph_id, fromNodeId=metadata['fromNodeId'], toNodeId=metadata['toNodeId'], edgeId=metadata['edgeId'])

    for row in rows:
        if row['kind'] != 'task':
            continue
        origin_id = _session_id('flujo', row.get('originConversationId'), row['workspace'])
        child_id = _session_id('flujo', row.get('childConversationId'), row['workspace'])
        origin = sessions.get(origin_id)
        if not origin:
            continue
        for field, kind, direction in [('createdAt', 'task_dispatched', (origin_id, child_id)), ('completedAt', 'task_completed', (child_id, origin_id))]:
            time = _utc(row.get(field))
            if not time:
                continue
            event_id = f"flujo:task:{row['workspace']}:{row['taskId']}:{field}"
            event = _event(event_id, time, 'flujo', kind, f"{origin['flowLabel']} · {kind.replace('_', ' ')}",
                           f"Persisted detached subflow task {row['taskId']}; child {row.get('childConversationId')}; status {row.get('status')}.", origin,
                           {'taskId': row['taskId'], 'targetSessionId': child_id, 'nodeId': row.get('originNodeId'),
                            'childConversationId': row.get('childConversationId'), 'status': row.get('status'), 'timestampField': field,
                            'basis': 'Persisted detached subflow task lifecycle timestamp', 'statusIsCurrentSnapshot': True})
            events.append(event)
            add_edge(*direction, 'dispatch' if field == 'createdAt' else 'task_completed', time, [event_id], event['metadata']['basis'],
                     sessionId=origin_id, fromNodeId=row.get('originNodeId'), flowId=origin.get('flowId'), taskId=row['taskId'])
            if child_id in sessions:
                child = sessions[child_id]
                child['parentId'] = child.get('parentId') or origin_id
                child['parentNodeId'] = child.get('parentNodeId') or row.get('originNodeId')
                if field == 'completedAt' and not child.get('endedAt'):
                    child['endedAt'], child['endBasis'] = time, event['metadata']['basis']

    for row in rows:
        if row['kind'] != 'planned-run':
            continue
        time = _utc(row.get('firedAt'))
        if not time:
            continue
        identity = _session_id('flujo', row.get('conversationId'), row['workspace'])
        session = sessions.get(identity)
        if not session:
            # A skipped trigger has no conversation; keep it as a scheduler
            # lane instead of fabricating an agent run.
            identity = f"flujo:{row['workspace']}:schedule:{row['planId']}"
            session = sessions.setdefault(identity, _new_session(identity, 'flujo', None, row.get('planName'), [],
                                                                  workspace=row['workspace'], role='scheduler', flowDefinitionId=row.get('flowId'),
                                                                  startedAt=time, startBasis='First recorded planned trigger', plannedExecutionId=row['planId'],
                                                                  url=config.get('flujo_url', 'http://localhost:43420') + '/planned-executions'))
        event_id = f"flujo:planned-run:{row['workspace']}:{row['planId']}:{row['runId']}"
        event = _event(event_id, time, 'flujo', 'schedule_trigger', f"{row.get('planName')} · schedule {row.get('status')}",
                       f"Recorded scheduled execution {row['runId']} with status {row.get('status')}; conversation {row.get('conversationId') or 'none (no run started)' }.",
                       session, {'plannedExecutionId': row['planId'], 'runId': row['runId'], 'status': row.get('status'),
                                 'finishedAt': _utc(row.get('finishedAt')), 'basis': 'Persisted planned-execution run ledger'})
        events.append(event)

    # Bind message events to the last actually entered node in that conversation.
    # Forwarded child node events (depth > 0) cannot move the parent's active node.
    for identity, session in sessions.items():
        timeline = sorted(node_timeline.get(identity, []), key=lambda value: _time_key(value[0]))
        times = [_epoch(value[0]) for value in timeline]
        session['nodeActivity'] = [{'timestamp': value[0], 'nodeId': value[1], 'eventId': value[2]} for value in timeline]
        for e in by_thread.get(identity, []):
            metadata = e.setdefault('metadata', {})
            metadata.update({'sessionId': identity, 'flowId': session.get('flowId'), 'flowDefinitionId': session.get('flowDefinitionId')})
            index = bisect_right(times, _epoch(e['timestamp'])) - 1
            if index >= 0:
                metadata['nodeId'] = timeline[index][1]
                metadata['nodeAttributionBasis'] = 'Most recent depth-zero node:enter execution log in the same conversation'
        if session.get('flowId') in flows:
            flows[session['flowId']]['eventIds'].extend(session['eventIds'][:4])
    for event in events:
        session = sessions.get(event['metadata']['sessionId'])
        if session:
            session['eventIds'].append(event['id'])
            time = event['timestamp']
            if not session.get('lastActivityAt') or _epoch(time) > _epoch(session['lastActivityAt']):
                session['lastActivityAt'] = time
    for session in sessions.values():
        session['eventIds'] = list(dict.fromkeys(session['eventIds']))
        session['eventCount'] = len(session['eventIds'])
        if session.get('parentId') and session['parentId'] not in sessions:
            stats['unavailableParentSessions'] += 1
    stats.update({'sessions': len(sessions), 'codexSessions': sum(s['source'] == 'codex' for s in sessions.values()),
                  'flujoSessions': sum(s['source'] == 'flujo' for s in sessions.values()),
                  'agentEdges': len(agent_edges), 'flowGraphs': len(flows), 'executionEvents': len(events),
                  'authoritativeCompletions': sum(bool(s.get('endedAt')) for s in sessions.values())})
    notes.extend([
        'Parallel session bars show creation through last observed activity. They establish overlapping conversation activity, not continuous CPU use; completion appears only with an authoritative lifecycle record.',
        'Saved FLUJO graphs are declarations. Animated node handoffs, subflow dispatches and model turns are individual timestamped execution logs, never inferred from the existence of an edge.',
        'Codex coordination exports only allowlisted identifiers, task labels, tool names and evidence locations. Hidden reasoning, full task prompts, provider credentials and arbitrary tool payloads are excluded.',
        'FLUJO scope is Hackathon_Release_* and explicitly named devthread conversations plus their recorded parent/child tasks. Banking runtime conversations are excluded from this development topology.',
    ])
    if stats['unresolvedCoordinationTargets']:
        notes.append(f"{stats['unresolvedCoordinationTargets']} recorded Codex coordination calls have an unavailable/dynamic target; the event is retained without inventing a relationship.")
    if stats['malformedFlujoRecords'] or stats['malformedCodexRecords']:
        notes.append('An active or malformed record was skipped; rebuild after writes settle to recover complete records.')
    result = {'sessions': sorted(sessions.values(), key=lambda s: (_time_key(s['startedAt']) if s.get('startedAt') else ('', 0), s['id'])),
              'agentEdges': sorted(agent_edges, key=lambda e: (_time_key(e['timestamp']), e['id'])),
              'flows': sorted(flows.values(), key=lambda f: (f.get('availableFrom') or '', f['id'])),
              'events': sorted(events, key=lambda e: (_time_key(e['timestamp']), e['id'])),
              'notes': notes, 'stats': dict(stats)}
    return sanitize(result)
