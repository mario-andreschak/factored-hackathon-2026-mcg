"""Build the owner-directed six-slide pitch without changing frozen RC media.

Run with the bundled Python, then export_final_pitch.ps1 for native PDF/previews.
All diagrams and slide text are editable PowerPoint objects.
"""
from pathlib import Path
from html import escape
import hashlib
import json
import shutil
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.util import Inches, Pt
from PIL import Image, ImageOps, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/submission/media/decks/final'
OUT.mkdir(parents=True, exist_ok=True)
NAME = 'savia-final-pitch'
INK, MINT, WHITE, MUTED, PANEL, GOLD = '12332D', 'D9EDB7', 'F8F8F2', 'C6D3CA', '214A3F', 'E9C977'
REPO = 'https://github.com/mario-andreschak/factored-hackathon-2026-mcg'
CAP_PIN = '95e2b9d62685f2669473258b88935a43dbe1bf75'
SOURCES = {
    'capacity': f'{REPO}/blob/{CAP_PIN}/docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md',
    'capacity_receipt': f'{REPO}/blob/{CAP_PIN}/docs/submission/measurements/infrastructure-capacity.json',
    'release': f'{REPO}/blob/843da50698b559dc748bea4505d1d93483ff29b3/docs/submission/RELEASE_CANDIDATE.md',
    'customer': f'{REPO}/blob/{CAP_PIN}/docs/submission/CUSTOMER_JOURNEY.md',
    'connector': f'{REPO}/blob/{CAP_PIN}/docs/submission/assistant/FLEET_CONNECTOR.md',
    'eleven': 'https://elevenlabs.io/blog/eleven-v4-turbo-in-elevenagents',
    'pitch_style': 'https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791068906645819',
    'english': 'https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791153414484629',
    'submission': 'https://factored-hackathon.slack.com/archives/C0BU6V61273/p1791211945034199',
    'voice_clarification': 'https://factored-hackathon.slack.com/archives/C0BU6V61273/p1791228494554899',
    'models_local': str(ROOT.parent / 'FLUJO/docs/features/models/connecting.md'),
    'statistics_local': str(ROOT.parent / 'FLUJO/docs/statistics.md'),
    'landscape_local': str(ROOT / 'docs/architecture/system-landscape.md'),
    'recovery_local': str(ROOT / 'docs/architecture/rc-runtime-reference.md'),
}

SLIDES = [
    dict(title='Ask once.\nSavia follows through.', kicker='SAVIA / FACTORED AI & DATA HACKATHON 2026',
         speak="I don't recognize this transaction. For a customer, that is the start of a problem, not just a chat. Meet Savia: one voice assistant that keeps your case moving while you get on with your day. Behind that familiar voice is a network designed for up to one hundred agents.",
         evidence='Product vision: up to 100 team conversations. Working prototype: integrated voice, grounded explanation, durable inquiries and two completed reviewers. Transaction disputes are the first use case. Do not describe all 100 as proven simultaneous customer execution.', sources=['customer','connector']),
    dict(title='Your problem keeps moving.\nYou get on with your day.', kicker='01 / THE CUSTOMER EXPERIENCE',
         speak='Savia checks the selected transaction, explains what is known and takes permitted steps with your consent. If the answer needs investigation, the case keeps its context while specialists explore different approaches. Savia returns with a useful result or prepares the next human handoff. Our prototype already shows a grounded answer, two saved perspectives and a customer returning without starting over.',
         evidence='Actual fictional Spanish UI is shown with an English summary. Demonstrated: selected grounded answer 9.338 s; separate browser team interaction 4.278 s; two suggestions survive new chat/reload; customer marks an informational inquiry helpful. Integrated voice closure has complete playback receipts. A separate simulated receipt check repeats after 30 real minutes. Real human assignment, bank resolution/refund, push/email delivery and multi-day completion remain unverified. The story rail describes the intended full lifecycle, not a recorded four-stage production run.', sources=['customer','release']),
    dict(title='Voice is the beginning.\nFollow-through is the product.', kicker='02 / THE COMMERCIAL REFERENCE',
         speak='ElevenLabs shows how compelling a natural transaction-dispute conversation can be. That is a commercial reference for voice quality. Savia makes the case itself the product: a persistent goal, multiple perspectives, reviewed findings and a deployment the bank can control. We are selling the service that keeps working after the conversation.',
         evidence='Comparison reframes the supplied analysis as product positioning, not a winner table. ElevenLabs official September 28 article, updated October 5, reports expressive voice, about 100 ms median inference, 90+ languages, a financial-services dispute demo and a combined transcription/turn-taking/TTS stack. No head-to-head performance, stronger compliance or missing competitor features are asserted. Savia focus and proposed deployment options differ in scope from a commercial platform showcase.', sources=['eleven','connector']),
    dict(title='One conversation.\nUp to 100 agents behind it.', kicker='03 / THE AI SWARM',
         speak='One assistant stays with the customer. The swarm design spreads the investigation across ten teams: one lead and nine specialists per team, one hundred agent conversations in total. They exchange messages, share evidence, challenge findings and return a reviewed synthesis. FLUJO provides the orchestration foundation; Savia owns the case. Existing sandbox collaboration and capacity tests support this design. The exact hundred-agent customer run still needs qualification.',
         evidence='Counting contract: 10 team Machines × (1 lead + 9 child specialists) = 100 team conversations; Savia root is separate. Configured child concurrency is nine; stock recovered flow used ten. Native subflow messaging/waiting; fleet delegation/message/wait; shared board and independent claim review. Real infrastructure evidence includes 18 simultaneous Fly leaf sandboxes, 17 completed leaf team runs, six matching output hashes; six of 24 leaf slots failed provisioning and operator steering was required. Larger recovered run enrolled 96 child Workers over time, not all simultaneously. Integrated customer attempt failed on first background root model call with disabled provider workspace before delegation. No 100-completion claim.', sources=['capacity','connector']),
    dict(title='The bank controls the stack.\nThe work leaves a trace.', kicker='04 / DEPLOYMENT, DATA & PROOF',
         speak='The system is modular: customer voice, durable case state, FLUJO orchestration and scoped banking tools. Data ownership and consent stay in the host and Banking MCP. Choose local open-weight inference or a hosted provider. FLUJO exposes run, model, tool and subflow statistics. The foundation returned three hundred correct reference codes from three hundred queued requests. The frozen release also records one hundred twenty-nine frontend and three hundred sixty-seven backend tests.',
         evidence='Deployment design supports self-hosted services and model selection; FLUJO local Ollama path is source-documented, not a measured all-local Savia deployment. Capacity benchmark used Qwen3.8-27B FP8 with vLLM 0.30.0 on rented Modal H100: repeat neutral reference-code workload, 1k context, 300 client submissions, p50 273.40 s, p95 441.60 s including queueing. First wording returned 217/300 correct; direct inference returned 399/400 correct; both retained. Counts 129 frontend / 367 backend refer to frozen rc.1 checks, not a fresh whole-release CI claim (current CI has failures). Statistics are metadata-only and best-effort; not every payload is retained and not an audit completeness guarantee. Current public app calls OpenRouter directly; target connects the FLUJO worker fleet. Cases/chat persist on disk; active audio state does not survive restart. Interrupted/unknown work is held rather than blindly replayed. TLS ingress, signed consent-scoped boundaries and separated data/state are source-backed controls, not a compliance certification.', sources=['capacity','capacity_receipt','release','models_local','statistics_local','recovery_local']),
    dict(title='Make “I’ll look into it”\na service customers can feel.', kicker='05 / THE BANK PILOT',
         speak='For customers, the ambition is less chasing and less repeating. For the bank, it is clearer evidence and a better prepared handoff. Start with transaction disputes, then reuse the same modular service for other customer problems. We are seeking a bank partner for a bounded pilot: measure repeat contacts, helpful answers, handoff quality and cost per case. Ask once. Savia follows through.',
         evidence='Pilot invitation, not measured ROI. Live fictional demo link is a review entry point, not a freshly verified end-to-end customer acceptance. Entry code SAVIA-2026. Production bank actions and live human assignment are not claimed. Founder/team credits preserve Gloria Yanta Salc (prompt flow / decision design), Carlos Diaz (data pipeline / lookup), Mario Andreschak (integration / orchestration).', sources=['customer','release']),
]

def color(c): return RGBColor.from_string(c)

def box(s, x,y,w,h, fill=PANEL, line=None, rounded=True):
    sh=s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb=color(fill)
    sh.line.fill.background() if not line else None
    if line: sh.line.color.rgb=color(line)
    if rounded: sh.adjustments[0]=.12
    return sh

def txt(s,x,y,w,h,value,size=20,c=WHITE,bold=False,link=None):
    sh=s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf=sh.text_frame; tf.clear(); tf.word_wrap=True
    tf.margin_left=tf.margin_right=Inches(.01); tf.margin_top=tf.margin_bottom=0
    tf.vertical_anchor=MSO_ANCHOR.TOP
    for i,line in enumerate(value.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph(); p.space_after=Pt(2)
        r=p.add_run(); r.text=line; r.font.name='Aptos'; r.font.size=Pt(size); r.font.bold=bold; r.font.color.rgb=color(c)
    if link: sh.click_action.hyperlink.address=link
    return sh

def circle(s,x,y,d,c):
    sh=s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d)); sh.fill.solid(); sh.fill.fore_color.rgb=color(c); sh.line.fill.background(); return sh

def line(s,x1,y1,x2,y2,c=MINT,width=1.5):
    sh=s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)); sh.line.color.rgb=color(c); sh.line.width=Pt(width)

def eyes(s,x,y,d=1.2):
    for dx,dy in [(0,.07),(d*.98,0)]:
        circle(s,x+dx,y+dy,d,WHITE); circle(s,x+dx+d*.43,y+dy+d*.39,d*.43,INK)

def base(prs,i):
    s=prs.slides.add_slide(prs.slide_layouts[6]); s.background.fill.solid(); s.background.fill.fore_color.rgb=color(INK)
    box(s,.64,.56,.50,.07,MINT,rounded=False)
    txt(s,1.32,.41,13,.35,SLIDES[i]['kicker'],11,MINT,True)
    txt(s,.72,8.50,12,.25,'SAVIA  /  ONE VOICE. A NETWORK BEHIND IT.',9,MUTED)
    txt(s,14.22,8.48,1,.28,f'{i+1:02} / 06',10,MINT,True)
    if i>0: txt(s,.72,1.07,14.8,1.58,SLIDES[i]['title'],38,WHITE,True)
    s.notes_slide.notes_text_frame.text='NARRATION (participant voice)\n'+SLIDES[i]['speak']+'\n\nEVIDENCE / Q&A\n'+SLIDES[i]['evidence']+'\n\nSOURCES\n'+'\n'.join(SOURCES[k] for k in SLIDES[i]['sources'])
    return s

def card(s,x,y,w,h,kicker,title,body,accent=MINT):
    box(s,x,y,w,h)
    txt(s,x+.22,y+.18,w-.44,.32,kicker,10,accent,True)
    txt(s,x+.22,y+.64,w-.44,.69,title,23,WHITE,True)
    txt(s,x+.22,y+1.42,w-.44,h-1.56,body,16,MUTED)

def build():
    prs=Presentation(); prs.slide_width=Inches(16); prs.slide_height=Inches(9)
    prs.core_properties.title='Savia — one voice, up to 100 agents'; prs.core_properties.author='Savia team'; prs.core_properties.subject='Final six-slide bank-investor pitch / October 5, 2026'
    s=base(prs,0)
    txt(s,.75,1.48,9.3,2.15,SLIDES[0]['title'],55,WHITE,True)
    txt(s,.79,4.04,8.5,1.35,'One voice for you.\nA network designed for up to 100 agents on your case.',27,MINT)
    eyes(s,11.07,1.74,1.59)
    for j in range(16): box(s,10.25+j*.27,4.40-((j%5)*.14),.08,.42+(j%5)*.28,MINT,rounded=False)
    box(s,.79,6.07,14.40,1.53)
    txt(s,1.06,6.31,9.5,.60,'“I don’t recognize this transaction.”',28,WHITE,True)
    txt(s,1.08,7.02,9.8,.28,'OUR FIRST USE CASE: TRANSACTION DISPUTES',11,MINT,True)
    txt(s,11.05,6.41,3.85,.68,'Product vision.\nWorking prototype.',16,MUTED)

    s=base(prs,1)
    stages=[('Ask','One assistant hears your story.'),('Act','Permitted steps, with consent.'),('Investigate','Specialists compare evidence.'),('Return','A result or a human handoff.')]
    for j,(title,body) in enumerate(stages):
        x=.78+j*2.64
        circle(s,x,3.04,.36,MINT); txt(s,x+.49,3.02,1.9,.36,f'{j+1:02}',13,MINT,True)
        if j<3: line(s,x+.39,3.22,x+2.54,3.22)
        txt(s,x,3.75,2.48,.46,title,27,WHITE,True)
        txt(s,x,4.35,2.42,1.15,body,18,MUTED)
    box(s,.78,6.07,10.35,1.57)
    txt(s,1.02,6.28,9.8,.28,'DEMONSTRATED IN THE PROTOTYPE',10,MINT,True)
    txt(s,1.02,6.81,9.75,.62,'Grounded answer · two saved perspectives\nReturn after a new chat without starting over',18,WHITE)
    shot=OUT/'savia-integrated-closure-crop.png'
    shutil.copyfile(ROOT/'docs/submission/media/decks/savia-integrated-closure-crop.png',shot)
    s.shapes.add_picture(str(shot), Inches(11.78), Inches(2.95), width=Inches(3.34), height=Inches(3.78))
    txt(s,11.77,6.91,3.38,.93,'English summary: “The explanation helped.” Saved suggestions remain available.',15,MINT)
    txt(s,.79,7.96,14.45,.31,'Product journey shown above; human pickup and bank resolution are pilot integrations. Fictional UI capture.',11,MUTED)

    s=base(prs,2)
    card(s,.79,3.03,6.93,3.90,'ELEVENAGENTS / COMMERCIAL VOICE REFERENCE','A compelling conversation','Expressive, responsive voice\nFinancial-services dispute showcase\nIntegrated speech and turn-taking',GOLD)
    card(s,8.01,3.03,7.18,3.90,'SAVIA / CASE ORCHESTRATION','A case that keeps moving','Persistent goal and saved context\nUp to 100 agents in the swarm design\nBank-controlled data and model choices')
    txt(s,.82,7.29,14.2,.54,'A familiar voice. A persistent case. A network you control.',25,MINT,True)
    txt(s,.82,7.96,14.2,.27,'Comparison of product emphasis; no head-to-head benchmark or claim of exclusive capabilities.',10,MUTED)
    txt(s,.82,8.22,13,.23,'Reference: ElevenLabs — Eleven v4 Turbo in ElevenAgents',9,MUTED,link=SOURCES['eleven'])

    s=base(prs,3)
    txt(s,.81,2.98,4.1,1.90,'100',102,MINT,True)
    txt(s,.87,5.04,4.0,.73,'team conversations',24,WHITE,True)
    txt(s,.87,5.93,4.1,.95,'10 teams × (1 lead + 9 specialists)\nSavia’s coordinator is separate.',16,MUTED)
    for j in range(10):
        col,row=j%5,j//5; x=5.57+col*1.93; y=3.01+row*1.59
        box(s,x,y,1.73,1.38)
        txt(s,x+.14,y+.13,1.45,.23,f'TEAM {j+1:02}',9,MUTED,True)
        for n in range(10): circle(s,x+.20+(n%5)*.27,y+.54+(n//5)*.33,.17,GOLD if n==0 else MINT)
    txt(s,5.59,6.25,9.55,.29,'LEAD + SPECIALISTS  /  SHARED EVIDENCE  /  INDEPENDENT REVIEW',10,MINT,True)
    for j,(title,body) in enumerate([('Communicate','Native messages + fleet relay'),('Challenge','Shared board + peer review'),('Recover','Saved context; hold uncertain retries')]):
        x=.80+j*4.84; box(s,x,7.02,4.60,.95)
        txt(s,x+.18,7.14,4.2,.32,title,17,WHITE,True); txt(s,x+.18,7.58,4.2,.24,body,11,MUTED)
    txt(s,.82,8.13,14.2,.25,'Swarm design and deployed connector. Exact 100-agent customer completion remains to be qualified.',11,GOLD)

    s=base(prs,4)
    nodes=[('CUSTOMER','Voice + text'),('SAVIA HOST','Case + consent'),('FLUJO','Agents + statistics'),('BANKING MCP','Scoped data + tools')]
    for j,(k,title) in enumerate(nodes):
        x=.80+j*3.65; box(s,x,2.94,3.38,1.35)
        txt(s,x+.19,3.14,2.98,.29,k,10,MINT,True); txt(s,x+.19,3.68,3.0,.43,title,20,WHITE,True)
        if j<3: txt(s,x+3.39,3.44,.25,.5,'→',16,MINT,True)
    txt(s,.85,4.52,14.4,.31,'TLS ingress · separated data and state · authority stays in Savia + Banking MCP',16,MUTED)
    txt(s,.85,5.10,14.4,.36,'Self-hostable foundation · local open-weight model option · interchangeable MCP / model modules',16,MINT,True)
    for j,(stat,label,detail) in enumerate([
        ('300/300','correct FLUJO reference returns','300 queued 1k requests; repeat run\np50 273 s / p95 442 s'),
        ('129 / 367','frontend / backend tests','Recorded frozen rc.1 checks\nBuild + ownership + recovery coverage'),
        ('Run → tool → agent','execution visibility','FLUJO metadata statistics\nDurations, tokens, failures, revisions')]):
        x=.80+j*4.84; box(s,x,5.87,4.60,1.88)
        txt(s,x+.19,6.06,4.21,.62,stat,30 if j<2 else 23,MINT,True)
        txt(s,x+.19,6.76,4.21,.30,label,13,WHITE,True)
        txt(s,x+.19,7.20,4.21,.48,detail,11,MUTED)
    txt(s,.82,7.99,14.4,.37,'Benchmark: Qwen3.8-27B FP8 + vLLM on rented H100. Current demo: direct provider; FLUJO fleet is the integration target.',10,MUTED)
    txt(s,.82,8.24,14.4,.23,'Case state persists; active audio resets after restart. Capacity is a workload result, not 300 simultaneous GPU generations.',9,MUTED)

    s=base(prs,5)
    for j,(k,title,body) in enumerate([
        ('FOR THE CUSTOMER','Less chasing.','One guide keeps the context\nand brings the next step back.'),
        ('FOR THE BANK','Better prepared support.','Reviewed evidence and a clear\npacket for the next handoff.'),
        ('THE NEXT STEP','A bounded bank pilot.','Start with transaction disputes.\nMeasure value before scaling.')]):
        card(s,.80+j*4.84,3.03,4.60,2.94,k,title,body)
    box(s,.80,6.24,14.28,1.57,MINT)
    txt(s,1.05,6.44,13.74,.47,'Ask once. Savia follows through.',29,INK,True)
    txt(s,1.07,7.09,13.66,.33,'Pilot measures: repeat contacts · helpful answers · handoff quality · cost per case',14,INK)
    txt(s,.84,8.00,7.10,.24,'Try the fictional demo: savia-rc-2026.fly.dev  /  SAVIA-2026',10,MINT,link='https://savia-rc-2026.fly.dev')
    txt(s,8.15,8.00,7,.23,'Gloria Yanta Salc · Carlos Diaz · Mario Andreschak',9,MUTED)
    prs.save(OUT/f'{NAME}.pptx')
    (OUT/f'{NAME}-speaker-notes.json').write_text(json.dumps([{'slide':i+1,**s} for i,s in enumerate(SLIDES)],ensure_ascii=False,indent=2),encoding='utf-8')
    notes=['# Savia final pitch — narration and evidence', '', 'Six slides. Narration is approximately three minutes at a comfortable pace; record in a participant’s actual voice.', '']
    for i,spec in enumerate(SLIDES,1):
        notes += [f"## {i}. {spec['title'].replace(chr(10),' ')}",'',spec['speak'],'','Evidence / Q&A: '+spec['evidence'],'','Sources: '+ ' · '.join(f'[{k}]({SOURCES[k]})' for k in spec['sources']),'']
    (OUT/f'{NAME}-speaker-notes.md').write_text('\n'.join(notes),encoding='utf-8')
    provenance={'version':'savia-final-pitch/v1','date':'2026-10-05','slide_count':6,'status':'owner-review-successor-to-frozen-RC-decks','sources':SOURCES,'claims':SLIDES,'organizer_style':'60% product / 40% technical; English; 4–6 slides','audio_guidance':'AI audio allowed with lower presentation score; actual participant voice recommended. Captured assistant speech has no confirmed exemption.','design':'Slides 1–3 and 6 product; slides 4–5 technical; swarm concept also bridges product slides. One message per slide; editable vector diagram; English summary of actual Spanish evidence.','preserved_frozen_artifacts':{}}
    for rel in ['docs/submission/media/decks/savia-pitch-deck.pptx','docs/submission/media/decks/savia-pitch-deck.pdf','docs/submission/media/decks/savia-submission-deck.pptx','docs/submission/media/decks/savia-submission-deck.pdf','docs/submission/media/video/savia-submission.mp4','docs/submission/media/media-freeze-receipt.json']:
        provenance['preserved_frozen_artifacts'][rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    (OUT/f'{NAME}-sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Built {len(prs.slides)} editable slides at {OUT}; narration {sum(len(s["speak"].split()) for s in SLIDES)} words.')

def finish():
    previews=sorted((OUT/'slides').glob('slide-*.png'))
    if len(previews)!=6: raise RuntimeError('Export six slide PNGs first.')
    canvas=Image.new('RGB',(1640,1450),'#EAECE5'); draw=ImageDraw.Draw(canvas)
    for i,p in enumerate(previews):
        with Image.open(p) as im: thumb=ImageOps.contain(im.convert('RGB'),(790,445))
        x=20+(i%2)*820; y=25+(i//2)*480; canvas.paste(thumb,(x,y)); draw.text((x,y+450),f'{i+1:02}  '+SLIDES[i]['title'].replace('\n',' '),fill='#12332D')
    canvas.save(OUT/f'{NAME}-contact-sheet.png')
    sections=[]
    for i,s in enumerate(SLIDES,1):
        sections.append(f'<section id="slide-{i}" aria-label="Slide {i}"><img src="slides/slide-{i:02}.png" alt="{escape(s["title"])}"><details><summary>Narration and evidence for slide {i}</summary><h2>{escape(s["title"])}</h2><p>{escape(s["speak"])}</p><p class="evidence">{escape(s["evidence"])}</p>'+''.join(f'<a href="{escape(SOURCES[k])}">{escape(k)}</a> ' for k in s['sources'] if not k.endswith('_local'))+'</details></section>')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Savia — final pitch</title><style>*{box-sizing:border-box}body{margin:0;background:#0c211d;color:#f8f8f2;font:17px/1.5 Arial,sans-serif}nav{position:sticky;top:0;background:#12332df2;padding:12px 5%;display:flex;gap:16px;align-items:center;z-index:2}a{color:#d9edb7}nav b{margin-right:auto}section{max-width:1280px;margin:24px auto;scroll-margin-top:80px}section img{display:block;width:100%;height:auto}details{padding:16px 24px;background:#214a3f}.evidence{font-size:14px;color:#c6d3ca}summary{cursor:pointer}h2{font-size:24px}.hint{max-width:1280px;margin:16px auto;color:#c6d3ca;font-size:14px}@media print{nav,details,.hint{display:none}section{margin:0;break-after:page}}@media(max-width:700px){nav{font-size:13px;gap:10px}section{margin:12px auto}.hint{padding:12px}}</style><nav><b>SAVIA / FINAL PITCH</b><a href="savia-final-pitch.pptx">Editable PPTX</a><a href="savia-final-pitch.pdf">PDF</a><a href="https://savia-rc-2026.fly.dev">Demo</a></nav><p class="hint">Six slides · English pitch · arrow keys move between slides · evidence and narration beneath each slide.</p>'''+''.join(sections)+'''<script>document.addEventListener('keydown',e=>{if(!['ArrowRight','ArrowLeft'].includes(e.key))return;e.preventDefault();const a=[...document.querySelectorAll('section')];let i=a.reduce((best,s,j)=>Math.abs(s.getBoundingClientRect().top-80)<Math.abs(a[best].getBoundingClientRect().top-80)?j:best,0);i=Math.max(0,Math.min(a.length-1,i+(e.key==='ArrowRight'?1:-1)));a[i].scrollIntoView({behavior:'smooth'});});</script></html>'''
    (OUT/f'{NAME}.html').write_text(html,encoding='utf-8')
    manifest={'schema':'savia-pitch-export/v1','slide_count':6,'files':{p.relative_to(OUT).as_posix():{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='savia-final-pitch-manifest.json'}}
    (OUT/f'{NAME}-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Preview, HTML and SHA-256 export manifest complete.')

if __name__=='__main__':
    import sys
    finish() if '--finish' in sys.argv else build()
