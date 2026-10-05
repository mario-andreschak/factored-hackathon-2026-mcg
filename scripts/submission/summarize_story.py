"""Summarize observed browser events; no provider calls or inferred resolution."""
import argparse
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    r=json.loads(a.capture.read_text(encoding='utf-8'))
    events=r['events']
    http=[e for e in events if e.get('kind')=='http']
    replies=[e for e in http if e.get('public_response',{}).get('reply')]
    confirmations=[e for e in http if e.get('path')=='/api/action/confirm']
    consent=next((e for e in events if str(e.get('step','')).startswith('Confirmo')),None)
    sent=next((e for e in events if e.get('step')=='Enviar mensaje'),None)
    confirmed=next((e for e in confirmations if e.get('public_response',{}).get('state') in {'intake_verified','existing_case_verified'}),None)
    snapshots={s['name']:s for s in r['snapshots']}
    checks=[e for e in http if e.get('path')=='/api/followups/check']
    result={'schema':'savia-recorded-story-summary/v1','runtime':r['runtime'],'generated_only':r['generated_only'],
      'capture':str(a.capture),'mocked_requests':r['mocked_requests'],'sample_size':1,
      'scope':'One actual fictional browser customer journey; observed host behavior, not independent human acceptance or live-bank resolution',
      'first_visible_host_reply_ms':None if not replies or not sent else replies[0]['at_ms']-sent['at_ms'],
      'model_generated_answer_success':None,
      'explicit_confirmation_click_observed':consent is not None,'verified_simulated_receipt_observed':confirmed is not None,
      'confirm_to_http_receipt_ms':confirmed['at_ms']-consent['at_ms'] if confirmed and consent else None,
      'actual_confirm_http_count':len(confirmations),'actual_manual_followup_checks':len(checks),
      'followup_after_reload_visible':any('return' in name and 'Volví a comprobarlo' in s['text'] for name,s in snapshots.items()),
      'followup_next_step_visible':any('Próximo paso' in s['text'] and 'canal oficial' in s['text'] for s in snapshots.values()),
      'actual_reply':replies[0]['public_response']['reply'] if replies else None,
      'markers':[{'name':s['name'],'at_ms':s['at_ms']} for s in r['snapshots']],
      'limits':['Browser event clock has no independently measured video-frame offset; visually verify editorial cut points',
        'Full recorder wall duration includes video save/close overhead; use FFprobe for video duration',
        'A local simulated receipt and continued status are not refund, human acceptance or resolved dispute']}
    if a.capture.parent.name=='story-es-v2':
        result['model_generated_answer_success']=False
        result['frame_notes']={'07-verified-receipt':'Premature snapshot name: frame still shows pending confirmation. Verified receipt is shown in 08-durable-followup and later frames; original raw events and filename retained.'}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    history=next((e['public_response']['messages'] for e in reversed(http) if e.get('public_response',{}).get('messages')),[])
    transcript=['# Recorded fictional customer story','',
        'Exact public conversation restored from the actual browser history. Banking is a generated fictional scenario and the receipt is a simulation. No refund or resolved dispute was observed.','']
    for entry in history:
        transcript += [f"**{entry.get('role','unknown')}**",'',entry.get('text',entry.get('content','')),'']
    transcript += ['| Observed screen | Browser event time |','| --- | ---: |']
    transcript += [f"| {s['name']} | {s['at_ms']/1000:.3f}s |" for s in r['snapshots']]
    transcript += ['', 'The final follow-up card was visible after reload:', '']
    last=r['snapshots'][-1]['text']
    if 'Seguimiento de esta recepción' in last:
        transcript.append(last[last.rfind('Seguimiento de esta recepción'):].split('Las respuestas se basan')[0].strip())
    transcript += ['', 'Timing is the browser observer clock. Operator pauses between steps are included; video saving/closing overhead is not product response latency. Visually verify video cut points.','']
    a.output.with_suffix('.md').write_text('\n'.join(transcript),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('sample_size','explicit_confirmation_click_observed','verified_simulated_receipt_observed','followup_after_reload_visible','first_visible_host_reply_ms')}))
if __name__=='__main__':main()
