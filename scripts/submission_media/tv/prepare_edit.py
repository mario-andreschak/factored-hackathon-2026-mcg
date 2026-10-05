"""Prepare the assistant-led TV edit. Original evidence remains untouched."""
import json, pathlib, sys
from PIL import Image

ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/submission_media'))
from build_video import run

def main():
    out=ROOT/'docs/submission/media/video'; out.mkdir(parents=True,exist_ok=True)
    work=ROOT/'private/submission_media/tv'; work.mkdir(parents=True,exist_ok=True)
    # An editorial return to breakfast, cropped to the coffee/table. Offscreen
    # dialogue never replaces the generated lips of a visibly speaking presenter.
    im=Image.open(ROOT/'docs/video/pilot/keyframes/home.png').convert('RGB')
    im.crop((40,610,585,916)).resize((1920,1080),Image.Resampling.LANCZOS).save(work/'coffee.png')
    run(['ffmpeg','-y','-v','error','-loop','1','-i',str(work/'coffee.png'),'-t','7','-vf','zoompan=z=min(zoom+0.00012\\,1.021):d=168:s=1920x1080:fps=24','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(work/'coffee.mp4')])
    for scene in ['beach','skydiving']:
        run(['ffmpeg','-y','-v','error','-loop','1','-i',str(ROOT/f'docs/submission/media/tv/keyframes/{scene}.png'),'-t','6.3','-vf','scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z=min(zoom+0.00015\\,1.022):d=152:s=1920x1080:fps=24','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',str(work/f'{scene}-cutaway.mp4')])
    pilot='docs/video/pilot/savia-three-scene-pilot.mp4'
    motion='docs/submission/media/motion/'
    audio='docs/submission/media/audio/'
    def cinema(id,dur,source,start=0,captions=None):
        return {'id':id,'kind':'cinema','duration':dur,'source':source,'start':start,'captions':captions or []}
    def animation(id,dur,source,narration=None,text=None):
        s={'id':id,'kind':'motion','duration':dur,'source':source}
        if narration: s.update(narration=audio+narration,narrator_text=text)
        return s
    def screen(id,dur,source,eyebrow,label,**kw):
        return {'id':id,'kind':'clip','duration':dur,'source':source,'eyebrow':eyebrow,'label':label,**kw}
    sections=[
        cinema('breakfast',5.5,pilot,captions=[{'start':0,'end':5.4,'text':"I don't recognize this charge. What now?"}]),
        animation('meet-savia',12.2,motion+'assistant-intro.mp4','savia-actual-opening.wav',"I understand. Let's take it calmly: tell me what you see on the charge, such as the date or name, and I'll help you understand it."),
        cinema('shop',3.5,pilot,5.5,[{'start':0,'end':3.5,'text':'Savia finds the facts. You stay in control.'}]),
        screen('facts',14.693,'docs/submission/measurements/story-es-v2/actual-browser.webm','Start with what you know','Actual fictional demo · edited conversation',intervals=[{'start':1.2,'end':5.2},{'start':198.3,'end':208.993}]),
        cinema('bowling',8,'docs/submission/media/tv/clips/bowling.mp4',captions=[{'start':.3,'end':4.5,'text':'And if it needs more than one expert?'},{'start':4.5,'end':7.8,'text':'Savia brings a team.'}]),
        animation('team',16,motion+'assistant-team.mp4','team-bridge.wav','So, who is looking at it? Two helpers. One checks the facts. One finds a useful next step. And you? Breakfast.'),
        screen('actual-team',15,'docs/submission/measurements/inquiry-story/actual-browser.webm','One question. Two perspectives.','Actual fictional inquiry · informational helpers',start=0),
        cinema('kayak',4.407,pilot,9,[{'start':0,'end':2.9,'text':'And some things still need a human.'},{'start':2.9,'end':4.407,'text':'Like paddling.'}]),
        screen('savia-speaks',10.4,'docs/submission/measurements/voice-overlap/voice-overlap.webm','Keep talking. Savia keeps working.','Actual AI voice · typed fictional input',start=7.519,native_audio_source='docs/submission/measurements/voice-overlap/foreground-help.wav',captions=[{'start':0,'end':5.6,'text':'You can keep the payment date, amount, and merchant or recipient.'},{'start':5.6,'end':10,'text':'That makes an unfamiliar charge easier to identify.'}]),
        cinema('boardgames',8,'docs/submission/media/tv/clips/boardgames.mp4',captions=[{'start':.2,'end':2.6,'text':'They work on the question.'},{'start':2.6,'end':6.1,'text':"So I don't have to chase everyone?"},{'start':6.1,'end':7.8,'text':'Exactly.'}]),
        screen('followup',15,'docs/submission/measurements/story-es-v2/actual-browser.webm','Your question comes back with a next step','Actual demo · simulated receipt kept after reload',intervals=[{'start':392,'end':397},{'image':'docs/submission/measurements/story-es-v2/10-rechecked-next-step.png','duration':10,'source_event_ms':459062,'reason':'Legibility hold of actual follow-up'}],narration=audio+'followup-bridge.wav',narrator_text='Do you have to start over tomorrow? No. Savia keeps the question, and brings back the next step.'),
        cinema('beach',8,'docs/submission/media/tv/clips/beach.mp4',captions=[{'start':.2,'end':2.3,'text':'And tomorrow?'},{'start':2.3,'end':7.8,'text':"The question doesn't disappear when your day changes."}]),
        animation('continuity',16,motion+'assistant-continuity.mp4'),
        cinema('skydiving',8,'docs/submission/media/tv/clips/skydiving.mp4',captions=[{'start':.2,'end':2.6,'text':'Can you keep up?'},{'start':2.6,'end':4.7,'text':'Savia can.'},{'start':4.7,'end':7.8,'text':"Good. I can't."}]),
        animation('how',12,motion+'architecture.mp4','how-bridge.wav','How does that work? One friendly voice. Two helpers. Permission before a bank action.'),
        animation('coffee',7,'private/submission_media/tv/coffee.mp4','closing-bridge.wav','So, what is next? Coffee first. Savia can keep the question.'),
        animation('end',16.3,motion+'assistant-end.mp4'),
    ]
    by_id={s['id']:s for s in sections}
    by_id['facts'].update(duration=12,source='docs/submission/measurements/team-story-final/actual-browser.webm',intervals=[{'start':11.6,'end':23.6}],crop=[395,118,490,278])
    by_id['facts']['captions']=[{'start':0,'end':6,'text':'A purchase at Nébula Market: 4,280.75 MXN, October 2.'},{'start':6,'end':12,'text':'An existing demo request is kept. No second request is created.'}]
    by_id['team']['duration']=11.4
    by_id['actual-team'].update(source='docs/submission/measurements/team-story-final/actual-browser.webm',start=212.5,label='Actual demo · two helpers · customer found the explanation useful',crop=[395,300,490,380])
    by_id['actual-team']['captions']=[{'start':0,'end':5,'text':'The customer confirmed the explanation helped. Savia kept the suggestions.'},{'start':5,'end':10,'text':'Compare the date and amount with your receipts.'},{'start':10,'end':15,'text':'Keep the reference with your receipts. A saved request is not a bank decision.'}]
    by_id['savia-speaks']={'id':'savia-speaks','kind':'motion','duration':10.4,'source':'docs/submission/media/motion/assistant-spoken-update.mp4','narration':'docs/submission/measurements/team-voice/useful-team-update.wav','captions':[{'start':0,'end':3.6,'text':'The charge is from Nébula Market.'},{'start':3.6,'end':9.4,'text':'Check your receipts and consider whether these suggestions help with your next step.'}]}
    for old_scene in ['breakfast','shop','kayak']: by_id[old_scene]['captions_already_burned']=True
    by_id['bowling'].update(duration=7,captions=[{'start':.78,'end':3.3,'text':'And if it needs more than one expert?'},{'start':5.37,'end':6.8,'text':'Savia brings a team.'}])
    by_id['boardgames'].update(duration=6,captions=[{'start':.62,'end':2.4,'text':'They work on the question.'},{'start':2.6,'end':4.6,'text':"So I don't have to chase everyone?"},{'start':4.6,'end':5.7,'text':'Exactly.'}])
    by_id['followup'].update(duration=12,intervals=[{'start':392,'end':394},{'image':'docs/submission/measurements/story-es-v2/10-rechecked-next-step.png','duration':10,'source_event_ms':459062,'reason':'Legibility hold of actual follow-up'}])
    by_id['beach']=animation('beach',6,'private/submission_media/tv/beach-cutaway.mp4','beach-pickup.wav','And tomorrow? Savia keeps the question.')
    by_id['skydiving']=animation('skydiving',6.3,'private/submission_media/tv/skydiving-cutaway.mp4','skydiving-pickup.wav','Can you keep up? Savia can. Good. I cannot.')
    by_id['continuity'].update(duration=9,start=7)
    by_id['how']['duration']=8.2
    by_id['end'].update(duration=7.593,start=4.4)
    sections=[by_id[s['id']] for s in sections]
    pt=screen('portuguese',7,'docs/submission/measurements/portuguese-final/actual-browser.webm','In your own words','Actual Portuguese clarification · fictional customer',start=15.6,crop=[395,205,490,195],captions=[{'start':0,'end':7,'text':'To find the charge, please tell me its date and amount.'}])
    sections.insert(next(i for i,s in enumerate(sections) if s['id']=='skydiving'),pt)
    # Use exact generated turn intervals for the offscreen editorial dialogue.
    for s in sections:
        if s.get('narration') and s['id']!='meet-savia':
            receipt=ROOT/pathlib.Path(s['narration']).with_suffix('.json')
            if receipt.exists():
                meta=json.loads(receipt.read_text(encoding='utf-8'))
                s['captions']=[{'start':t['start_seconds'],'end':t['start_seconds']+t['duration_seconds'],'text':t.get('transcript',t.get('text'))} for t in meta['turns']]
                s.pop('narrator_text',None)
    data={'schema':'savia-fun-tv-edit/v1','scope':'Illustrative fictional TV cast plus edited actual fictional prototype inserts. Five generated moving dialogue scenes; beach/sky are deliberate photo cutaways with stock-voice editorial dialogue after native rendering failed. Actual provider Savia opening and useful spoken completed-team update. The voice and text customer-helpful closure are separate fictional prototype runs; the completed-update speech has one full playback acknowledgement. Queued/working model progress speech was flagged as overstated and excluded. Two actual informational agents; simulated banking receipts, no real refund, bank decision or live human acceptance. One actual 30-minute repeat check; day/week framing is product direction with controlled-time scheduler tests. No physical microphone qualification.','original_score':True,'burn_captions':True,'sections':sections}
    overrides=out/'integrated-voice-replacements.json'
    if overrides.exists():
        reviewed=json.loads(overrides.read_text(encoding='utf-8-sig'))
        if reviewed.get('semantic_review')!='accepted' or reviewed.get('surface')!='integrated-savia-dialog':
            raise ValueError('Integrated replacements need reviewed evidence from the intended Savia dialog')
        patches=reviewed['sections']
        if set(patches)!={'meet-savia','savia-speaks'}:
            raise ValueError('Replacement scope is exactly the two voice proof slots')
        for s in sections:
            if s['id'] not in patches: continue
            patch=patches[s['id']]
            if set(patch)-{'narration','captions','duration','source','start'}:
                raise ValueError('Unexpected replacement property')
            if not (ROOT/patch['narration']).is_file(): raise ValueError('Missing actual integrated voice WAV')
            s.pop('narrator_text',None)
            s.update(patch)
        data['scope']=reviewed['scope']
        data['integrated_voice_evidence']=reviewed['evidence']
    else:
        assert abs(sum(s['duration'] for s in sections)-150.5)<.001
    (out/'tv-timeline.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(out/'tv-timeline.json')

if __name__=='__main__': main()
