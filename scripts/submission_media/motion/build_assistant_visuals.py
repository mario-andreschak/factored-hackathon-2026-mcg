"""Render three silent, editable Pillow/FFmpeg TV-spot support inserts.

Run from the repository root:
  python scripts/submission_media/motion/build_assistant_visuals.py
"""
from __future__ import annotations
import hashlib, json, math, pathlib, subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT=pathlib.Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/submission/media/motion'
WORK=ROOT/'private/submission_media/motion'
W,H,FPS=1920,1080,24
FOREST='#173c35'; CREAM='#f8f9f6'; LIME='#d9edb7'; MUTED='#9cb8a3'; MOSS='#779961'; SOFT='#e8eee7'
REG=pathlib.Path('C:/Windows/Fonts/segoeui.ttf'); MED=pathlib.Path('C:/Windows/Fonts/seguisb.ttf'); BOLD=pathlib.Path('C:/Windows/Fonts/segoeuib.ttf')

def font(n,weight='regular'):
    p={'regular':REG,'medium':MED,'bold':BOLD}[weight]
    return ImageFont.truetype(str(p if p.exists() else REG),n)
def clamp(x): return max(0,min(1,x))
def ease(x): x=clamp(x); return x*x*(3-2*x)
def rgba(c,a=1):
    h=c.lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))+(round(255*clamp(a)),)
def label(d,xy,s,size,color,weight='regular',anchor=None): d.text(xy,s,font=font(size,weight),fill=color,anchor=anchor)
def roundrect(d,box,r,fill,outline=None,w=1): d.rounded_rectangle(box,radius=r,fill=fill,outline=outline,width=w)
def base(bg=CREAM): return Image.new('RGB',(W,H),bg)
def brand(d,color=FOREST,small=42): label(d,(82,57),'savia.',small,color,'bold')

def soft_orb(d,cx,cy,r,t,a=1):
    pulse=1+.045*math.sin(t*2.5)
    r=int(r*pulse)
    for k,op in [(2.35,.055),(1.75,.09),(1.25,.12)]:
        rr=int(r*k); d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill=rgba(LIME,op*a))
    d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=rgba(LIME,a),outline=rgba(FOREST,.88*a),width=3)
    # Three moving bars suggest a calm voice without imitating a progress meter.
    heights=[18,34,22,42,25,35,16]
    for i,h0 in enumerate(heights):
        h=h0*(.68+.32*math.sin(t*3+i*.7))
        x=cx-57+i*19; d.rounded_rectangle((x,cy-h/2,x+7,cy+h/2),radius=4,fill=rgba(FOREST,.86*a))

def scene_intro(t,dur):
    im=base(CREAM); d=ImageDraw.Draw(im,'RGBA')
    brand(d,FOREST)
    # Voice orb answers gently with a living waveform; no on-screen device UI.
    cx,cy=960,366
    for i in range(5):
        r=124+i*47+int(8*math.sin(t*.7+i*.8))
        d.arc((cx-r,cy-r,cx+r,cy+r),194,346,fill=(23,60,53,round(27*ease(t/1.8))),width=2)
    orb=ease((t-.35)/1.45)
    soft_orb(d,cx,cy,77,t,orb)
    title=ease((t-1.0)/1.0)
    label(d,(960,630),'Let’s take it calmly.',62,rgba(FOREST,title),'medium','mm')
    sub=ease((t-4.9)/1.2)
    label(d,(960,736),'Savia, your friendly voice assistant.',32,rgba('#526c60',sub),'regular','mm')
    # Small wavelets echo the recorded assistant voice and leave room for its audio mix.
    wave_a=ease((t-.8)/1.1)
    for i,h0 in enumerate([14,27,18,35,22,41,19,30,13]):
        h=h0*(.55+.45*math.sin(t*2.2+i*.65))
        x=960-4*23+i*23
        d.rounded_rectangle((x,859-h/2,x+7,859+h/2),radius=4,fill=rgba(MOSS,.68*wave_a))
    return im

def scene_team(t,dur):
    im=base(FOREST); d=ImageDraw.Draw(im,'RGBA')
    # Fine, slow orbit lines give the scene life while keeping the words quiet.
    for i in range(4):
        r=235+i*38+int(8*math.sin(t*.6+i))
        d.arc((960-r,260-r,960+r,260+r),195,345,fill=rgba(LIME,.12),width=2)
    brand(d,LIME)
    title=ease(t/1.2)
    label(d,(960,112),'One question. Two perspectives.',54,rgba(CREAM,title),'medium','mm')
    orb=ease((t-.7)/1.3)
    soft_orb(d,960,332,78,t,orb)
    # Helpers enter on separate arcs, with a light moving signal dot on each connector.
    node_y=553
    for side,cx,start in [(-1,492,1.75),(1,1428,2.25)]:
        p=ease((t-start)/.9)
        sx,sy=(960+side*36,421); ex,ey=(cx,node_y-6)
        d.line((sx,sy,ex,ey),fill=rgba(LIME,.46*p),width=4)
        q=clamp((t-start-0.25)/2.8)
        dotx=sx+(ex-sx)*q; doty=sy+(ey-sy)*q
        d.ellipse((dotx-7,doty-7,dotx+7,doty+7),fill=rgba(LIME,p))
        cardw,cardh=612,310; x=cx-cardw//2; y=588
        offset=round((1-p)*26)
        roundrect(d,(x,y+offset,x+cardw,y+cardh+offset),28,rgba(CREAM,p),outline=rgba(LIME,.68*p),w=2)
        # A concise role marker makes the two actual helper perspectives legible.
        d.ellipse((x+36,y+33+offset,x+83,y+80+offset),fill=rgba(LIME,p))
        if side<0:
            label(d,(x+59,y+56+offset),'F',26,rgba(FOREST,p),'bold','mm')
            title_text='Facts'; body=('Check whether the merchant name','matches your receipt.')
        else:
            label(d,(x+59,y+56+offset),'→',25,rgba(FOREST,p),'bold','mm')
            title_text='Next step'; body=('Save any reference together','with your receipts.')
        label(d,(x+105,y+43+offset),title_text,36,rgba(FOREST,p),'medium')
        body_a=ease((t-(start+1.8))/1.0)*p
        label(d,(x+42,y+134+offset),body[0],26,rgba(FOREST,body_a),'regular')
        label(d,(x+42,y+180+offset),body[1],26,rgba(FOREST,body_a),'regular')
    return im

def scene_continuity(t,dur):
    im=base(CREAM); d=ImageDraw.Draw(im,'RGBA')
    # Light botanical rings drift in from the edges, not behind the text.
    for i in range(6):
        r=330+i*46+int(7*math.sin(t*.45+i*.6))
        d.arc((1590-r,440-r,1590+r,440+r),95,260,fill=(23,60,53,18),width=2)
    brand(d,FOREST)
    label(d,(960,128),'Your question stays with you.',52,FOREST,'medium','mm')
    label(d,(960,198),'Pick up the next step when you’re ready.',26,'#61766c','regular','mm')
    xs=[324,960,1596]; y=488
    progress=ease(t/12.6)
    d.line((xs[0],y,xs[-1],y),fill=(23,60,53,36),width=6)
    d.line((xs[0],y,xs[0]+(xs[-1]-xs[0])*progress,y),fill=rgba(MOSS,.9),width=6)
    nodes=[('Morning','Question saved',.8),('Afternoon','Two perspectives ready',5.2),('Tomorrow','Next step returns',9.5)]
    for i,(when,event,start) in enumerate(nodes):
        p=ease((t-start)/1.0); cx=xs[i]
        rad=27+int(4*math.sin(t*2+i)*p)
        d.ellipse((cx-rad-8,y-rad-8,cx+rad+8,y+rad+8),fill=(217,237,183,round(55*p)))
        d.ellipse((cx-rad,y-rad,cx+rad,y+rad),fill=rgba(FOREST,p))
        if p>.0:
            d.ellipse((cx-7,y-7,cx+7,y+7),fill=rgba(LIME,p))
        # Cards lift softly from the timeline in sequence.
        cardw,cardh=410,196; x=cx-cardw//2; cy=584
        lift=round((1-p)*22)
        roundrect(d,(x,cy+lift,x+cardw,cy+cardh+lift),22,rgba(SOFT,p),outline=rgba('#b6cbb8',.88*p),w=2)
        label(d,(cx,cy+47+lift),when,32,rgba(FOREST,p),'medium','mm')
        label(d,(cx,cy+111+lift),event,23,rgba('#526c60',p),'regular','mm')
        if i<2:
            ax=xs[i]+47; bx=xs[i+1]-50
            midx=ax+(bx-ax)*clamp((t-start-1.1)/2.3)
            if t>start+1.1:
                d.ellipse((midx-5,y-5,midx+5,y+5),fill=rgba(MOSS,p))
    # Required qualifier stays present and readable as a small footer.
    d.line((88,957,1832,957),fill=(23,60,53,27),width=2)
    label(d,(92,1000),'Prototype · scheduled tracking tested with controlled time',17,'#60746a','regular')
    return im

def draw_leaf(d,cx,cy,s,rot=0,color=LIME):
    # Stylized native leaf, with a visible midrib.
    box=(cx-s,cy-s*.48,cx+s,cy+s*.48)
    d.ellipse(box,fill=rgba(color,.96),outline=rgba(FOREST,.52),width=2)
    d.line((cx-s*.68,cy+s*.3,cx+s*.65,cy-s*.3),fill=rgba(FOREST,.48),width=2)

def scene_end(t,dur):
    im=base(FOREST); d=ImageDraw.Draw(im,'RGBA')
    # Quiet coffee cup becomes the Savia orb: rising steam, a leaf and a soft voice pulse.
    cx,cy=960,375; p=ease(t/2.2)
    for i in range(3):
        r=178+i*49+int(9*math.sin(t*.55+i*.5))
        d.arc((cx-r,cy-r,cx+r,cy+r),205,335,fill=rgba(LIME,.10*p),width=2)
    # Cup body + handle, drawn from simple native shapes.
    cw,ch=186,128; x=cx-cw//2; y=cy+38
    roundrect(d,(x,y,x+cw,y+ch),18,rgba(CREAM,p),outline=rgba(LIME,p),w=3)
    d.ellipse((x+12,y-15,x+cw-12,y+21),fill=rgba(LIME,p),outline=rgba(FOREST,.68*p),width=2)
    d.ellipse((x+25,y-8,x+cw-25,y+12),fill=rgba(FOREST,.92*p))
    d.arc((x+cw-3,y+26,x+cw+72,y+103),265,95,fill=rgba(LIME,p),width=12)
    d.arc((x+cw+15,y+43,x+cw+58,y+85),260,100,fill=rgba(FOREST,p),width=8)
    # Leaf / orb above the cup, moving gently in the coffee steam.
    rise=ease((t-.7)/2.1); oy=cy-74-int(24*math.sin(t*.9)*rise)
    d.ellipse((cx-41,oy-41,cx+41,oy+41),fill=rgba(LIME,rise),outline=rgba(CREAM,.8*rise),width=2)
    for i,h in enumerate([12,21,15]):
        xx=cx-19+i*19; d.rounded_rectangle((xx,oy-h/2,xx+6,oy+h/2),radius=3,fill=rgba(FOREST,rise))
    draw_leaf(d,cx+81,oy-22,31,0,LIME)
    # Brand and tagline reveal after the visual settles.
    word=ease((t-2.8)/1.0)
    label(d,(960,646),'savia.',94,rgba(LIME,word),'bold','mm')
    label(d,(960,764),'Ask once. Carry on.',39,rgba(CREAM,ease((t-4.1)/1.0)),'regular','mm')
    label(d,(94,62),'PROTOTYPE',16,rgba(MUTED,.9),'medium')
    credits='Gloria Yanta Salc  ·  Carlos Diaz  ·  Moe + team'
    label(d,(960,977),credits,24,rgba(CREAM,ease((t-7.4)/1.2)),'regular','mm')
    return im

SCENES=[('assistant-intro',7.6,scene_intro),('assistant-team',16.0,scene_team),('assistant-continuity',16.0,scene_continuity),('assistant-end',12.0,scene_end)]

def call(args):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors='replace')[-4000:])
    return p.stdout

def render(name,duration,fn):
    dest=OUT/f'{name}.mp4'; frames=round(duration*FPS)
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(dest)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            proc.stdin.write(fn(i/FPS,duration).tobytes())
            if i%120==0: print(f'{name}: {i}/{frames}',flush=True)
        proc.stdin.close(); err=proc.stderr.read(); code=proc.wait()
        if code: raise RuntimeError(err.decode(errors='replace')[-4000:])
    except Exception:
        proc.kill(); raise
    return {'id':name,'duration':duration,'frames':frames,'path':str(dest.relative_to(ROOT)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh-preview',action='store_true',help='Rebuild the contact sheet and receipt from existing section MP4s without rerendering them.')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True); WORK.mkdir(parents=True,exist_ok=True)
    if args.refresh_preview:
        sections=[{'id':name,'duration':duration,'frames':round(duration*FPS),'path':str((OUT/(name+'.mp4')).relative_to(ROOT)),'sha256':hashlib.sha256((OUT/(name+'.mp4')).read_bytes()).hexdigest()} for name,duration,_ in SCENES]
    else:
        sections=[render(*s) for s in SCENES]
    # Silent all-three preview lives in the ignored workspace for the parent edit.
    listing=WORK/'assistant-visuals-concat.txt'
    listing.write_text(''.join(f"file '{(OUT/(s['id']+'.mp4')).as_posix()}'\n" for s in sections),encoding='utf-8')
    preview=WORK/'assistant-visuals-preview.mp4'
    if not args.refresh_preview:
        call(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(preview)])
    call(['ffmpeg','-v','error','-i',str(preview),'-f','null','-'])
    tiles=[]; elapsed=0
    from io import BytesIO
    for s in sections:
        sec=elapsed+s['duration']*.8; elapsed+=s['duration']
        raw=call(['ffmpeg','-v','error','-ss',str(sec),'-i',str(preview),'-frames:v','1','-f','image2pipe','-vcodec','mjpeg','-'])
        tile=Image.open(BytesIO(raw)).convert('RGB'); tile.thumbnail((640,360)); tiles.append(tile.copy())
    sheet=Image.new('RGB',(1280,720),CREAM)
    for i,tile in enumerate(tiles): sheet.paste(tile,((i%2)*640,(i//2)*360))
    sheet.save(OUT/'assistant-visuals-contact-sheet.jpg',quality=92)
    duration=float(call(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(preview)]).decode().strip())
    receipt={'format':'1920x1080 H.264 MP4, 24 fps, silent','duration':duration,'decode':'passed','preview':str(preview.relative_to(ROOT)),'sections':sections,'contact_sheet_sample':'80% into each section to show the full end state','source_evidence':'docs/submission/assistant/mcp-smoke.json','voice_asset_for_intro':'avatar/.local/rc-voice-pilot/opening.wav','voice_duration_seconds':12.2,'claims_scope':'Suggestions follow the completed fictional informational inquiry roles. Continuity scene is explicitly labeled as prototype tracking tested with controlled time. Opener video is silent; the parent edit supplies its actual assistant voice.'}
    (OUT/'assistant-visuals-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(preview)

if __name__=='__main__': main()
