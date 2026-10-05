"""Make a compact table and attach separately observed call counts by time window.

Only use an exclusive serialized measurement window. This screens observed
behavior; it never supplies independent human adjudication or resolution claims.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('comparison',type=Path)
    p.add_argument('--observations-private',type=Path)
    p.add_argument('--output-prefix',type=Path,required=True)
    a=p.parse_args()
    r=json.loads(a.comparison.read_text(encoding='utf-8'))
    observations=[] if not a.observations_private else [json.loads(x) for x in a.observations_private.read_text().splitlines() if x]
    lines=['# Actual customer comparison','',r['baseline_scope'],'',
      'AI-authored cases and agent screening; independent human adjudication remains pending. HTTP success is separate from useful behavior.','',
      '| Case | Deterministic baseline copy (local CPU ms) | Actual reply (HTTP ms) | Agent usefulness screening | HTTP / exact history | Model attempts / transport completions |',
      '| --- | --- | --- | --- | --- | --- |']
    for c in r['cases']:
        request=next(x for x in c['http_calls'] if x['path']=='/api/chat/messages')
        if a.observations_private and 'started_at' in request:
            lo,hi=map(datetime.fromisoformat,(request['started_at'],request['completed_at']))
            observed=[x for x in observations if lo<=datetime.fromisoformat(x['observed_at'])<=hi]
            models=[x for x in observed if x['kind']=='model']
            bank=[x for x in observed if x['kind'].startswith('bank_')]
            c['actual'].update(model_call_count=len(models),completed_model_transport_count=sum(x['status']=='ok' for x in models),
                tool_call_count=len(bank),observed_operations=[{k:x.get(k) for k in ('kind','stage','operation','status','latency_ms','model','prompt_tokens','completion_tokens','cost_usd') if k in x} for x in observed])
        reply=c['actual']['response'].get('reply','')
        count=c['actual'].get('model_call_count')
        accepted=c['actual'].get('completed_model_transport_count')
        counts='unattributed' if count is None else f'{count} / {accepted}'
        simple=c['baseline']['reply'].replace('|','/').replace(chr(10),' ')
        screening=c.get('agent_screening')
        screened='pending' if screening is None else ('useful' if screening['useful'] else 'not useful') + ': ' + screening['note']
        lines.append(f"| {c['case']} | {simple} ({c['baseline']['latency_ms']:.3f} ms) | {reply.replace('|','/').replace(chr(10),' ')[:420]} ({c['actual']['latency_ms']:.1f} ms) | {screened} | {c['actual']['http_status']} / {c['actual']['exact_reply_in_history']} | {counts} |")
    ms=[c['actual']['latency_ms'] for c in r['cases']]
    r['summary']={'sample_size':len(ms),'http_chat_success':sum(c['actual']['http_status']==200 for c in r['cases']),
        'history_exact':sum(c['actual']['exact_reply_in_history'] for c in r['cases']),
        'latency_ms':{'minimum':min(ms),'median':statistics.median(ms),'maximum':max(ms)},
        'independent_human_adjudication':False,'bank_resolution_observed':False}
    screened=[c for c in r['cases'] if c.get('agent_screening')]
    if screened:r['summary']['agent_screening']={'reviewed':len(screened),'useful':sum(c['agent_screening']['useful'] for c in screened),'language_correct':sum(c['agent_screening']['language_correct'] for c in screened)}
    if a.observations_private:r['limits'].append('Call counts use exclusive serialized chat time windows; transport completion does not establish semantic output acceptance. Bank operation wrappers may include nested read-back operations, not network MCP transports.')
    lines+=['',f"n={len(ms)}; latency range {min(ms)/1000:.2f}–{max(ms)/1000:.2f}s; median {statistics.median(ms)/1000:.2f}s.",
      '', 'Baseline local CPU render times are in the JSON. They do not include authentication, network, bank reads, action, or follow-up; no speedup ratio is justified.',
      '', 'The baseline renders selected facts or asks for missing date/amount. Its usefulness is limited to that copy behavior; it cannot execute a team request, bank action, handoff or durable follow-up. No baseline quality rate is inferred.',
      '', 'Useful answer, correct language and grounding require checking each exact reply against its display facts. No improvement percentage or resolved-dispute rate is inferred.','']
    a.output_prefix.with_suffix('.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    a.output_prefix.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(r['summary']))
if __name__=='__main__':main()
