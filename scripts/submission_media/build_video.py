"""Build Savia's editable, evidence-scoped submission edit.

Timeline JSON supplies source intervals, captions and optional narration. Original
recordings are never modified. No screen or bank outcome is fabricated.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, re
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/submission/media/video'
WORK = ROOT / 'private/submission_media/video'
W, H, FPS = 1920, 1080, 24
FOREST, CREAM, LIME = '#173c35', '#f8f9f6', '#d9edb7'
FONT = pathlib.Path('C:/Windows/Fonts/segoeui.ttf')
BOLD = pathlib.Path('C:/Windows/Fonts/segoeuib.ttf')

def run(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(p.stderr[-5000:])
    return p.stdout

def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)

def lines(draw, text, xy, size, color, max_width, bold=False, gap=1.35):
    f=font(size,bold); x,y=xy
    for para in text.split('\n'):
        words=para.split(); line=''
        for word in words:
            test=(line+' '+word).strip()
            if draw.textlength(test,font=f)>max_width and line:
                draw.text((x,y),line,font=f,fill=color); y+=size*gap; line=word
            else: line=test
        if line: draw.text((x,y),line,font=f,fill=color); y+=size*gap
    return y

def base(section, transparent=False):
    im=Image.new('RGBA' if transparent else 'RGB',(W,H),(0,0,0,0) if transparent else CREAM)
    d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,104),fill=FOREST)
    d.text((68,20),'savia.',font=font(44,True),fill=LIME)
    d.text((290,30),section['eyebrow'].upper(),font=font(29),fill=CREAM)
    d.rectangle((0,1000,W,H),fill=FOREST)
    d.text((68,1020),section['label'],font=font(24),fill=CREAM)
    d.text((1590,1020),'FACTORED 2026',font=font(23),fill=LIME)
    return im,d

def card(section, path):
    im,d=base(section)
    d.rounded_rectangle((1370,160,1810,910),radius=42,fill=FOREST)
    d.ellipse((1470,225,1750,505),fill=LIME)
    d.text((1540,272),section.get('number','01'),font=font(108,True),fill=FOREST)
    lines(d,section.get('aside','Facts.\nConsent.\nContinuity.'),(1430,570),44,CREAM,320,True)
    y=lines(d,section['title'],(92,182),76,FOREST,1180,True,1.1)
    y+=50
    for item in section.get('points',[]):
        d.ellipse((95,y+17,111,y+33),fill='#779961')
        y=lines(d,item,(145,y),36,FOREST,1090,gap=1.32)+30
    im.save(path)

def architecture(section,path):
    im,d=base(section)
    d.text((80,145),'Language is flexible. Authority is explicit.',font=font(60,True),fill=FOREST)
    boxes=[(85,335,400,540,'Savia UI','Customer + consent'),
           (540,335,930,540,'Trusted host','Selection + receipts'),
           (1080,335,1510,540,'Banking MCP','Ownership + policy'),
           (1080,700,1510,900,'Serving snapshots','Validated pipeline'),
           (540,700,930,900,'Generic FLUJO','Permitted display facts')]
    for x,y,x2,y2,title,detail in boxes:
        d.rounded_rectangle((x,y,x2,y2),radius=28,fill=FOREST)
        lines(d,title,(x+26,y+32),38,LIME,x2-x-50,True)
        lines(d,detail,(x+26,y+115),25,CREAM,x2-x-50)
    for a,b in [((400,435),(540,435)),((930,435),(1080,435)),((1295,540),(1295,700)),((735,540),(735,700))]:
        d.line((a,b),fill='#779961',width=8)
        if a[1]==b[1]: d.polygon([(b[0],b[1]),(b[0]-20,b[1]-14),(b[0]-20,b[1]+14)],fill='#779961')
        else: d.polygon([(b[0],b[1]),(b[0]-14,b[1]-20),(b[0]+14,b[1]-20)],fill='#779961')
    lines(d,'Banking data, credentials and action authority stay in the application and MCP.',(85,770),31,FOREST,390)
    im.save(path)

def proof(section,path):
    im,d=base(section)
    lines(d,section['title'],(90,170),64,FOREST,1720,True)
    for n,metric in enumerate(section['metrics']):
        x=90+n*900
        d.rounded_rectangle((x,335,x+830,890),radius=36,fill=FOREST)
        lines(d,metric['value'],(x+48,380),118,LIME,734,True)
        lines(d,metric['label'],(x+48,560),44,CREAM,734,True)
        lines(d,metric['scope'],(x+48,735),28,CREAM,734)
    im.save(path)

def stamp(seconds, separator=','):
    ms=round(seconds*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02}{separator}{ms:03}'

def subtitles(timeline, name, burn=False):
    cues=[]; elapsed=0
    for section in timeline['sections']:
        if section.get('narration') and section.get('narrator_text'):
            duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(ROOT/section['narration'])]).strip())
            raw_sentences=re.split(r'(?<=[.!?])\s+',section['narrator_text'])
            sentences=[]
            for sentence in raw_sentences:
                words=sentence.split()
                for n in range(0,len(words),14): sentences.append(' '.join(words[n:n+14]))
            weight=sum(len(t.split()) for t in sentences); pos=elapsed
            for sentence in sentences:
                length=duration*len(sentence.split())/max(weight,1)
                cues.append((pos,pos+length,sentence)); pos+=length
        for cue in ([] if burn and section.get('captions_already_burned') else section.get('captions',[])):
            cues.append((elapsed+cue['start'],elapsed+cue['end'],cue['text']))
        elapsed+=section['duration']
    cues.sort()
    directory=WORK if burn else OUT
    (directory/f'{name}.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{t}' for i,(a,b,t) in enumerate(cues))+'\n',encoding='utf-8')
    if not burn: (OUT/f'{name}.vtt').write_text('WEBVTT\n\n'+'\n\n'.join(f'{stamp(a,".")} --> {stamp(b,".")}\n{t}' for a,b,t in cues)+'\n',encoding='utf-8')

def build(timeline_path, name, only=None, assemble_only=False):
    OUT.mkdir(parents=True,exist_ok=True)
    graphics=WORK/'graphics'; graphics.mkdir(parents=True,exist_ok=True)
    parts=WORK/'segments'; parts.mkdir(exist_ok=True)
    timeline=json.loads(timeline_path.read_text(encoding='utf-8-sig'))
    concat=[]; receipts=[]; elapsed=0
    for i,s in enumerate(timeline['sections']):
        if only and s['id'] not in only:
            elapsed+=s['duration']; continue
        dest=parts/f'{i:02d}-{s["id"]}.mp4'
        dur=s['duration']; graphic=graphics/f'{i:02d}-{s["id"]}.png'
        if assemble_only:
            if not dest.exists(): raise ValueError(f'Missing prepared section: {dest}')
            observed=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(dest)]).strip())
            if abs(observed-dur)>.13: raise ValueError(f'{s["id"]}: prepared duration {observed} differs from {dur}')
        if s.get('narration'):
            audio_duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(ROOT/s['narration'])]).strip())
            if audio_duration>dur+0.05: raise ValueError(f'{s["id"]}: narration {audio_duration}s exceeds picture {dur}s; adjust edit rather than truncate speech')
        if s['kind'] in ('pilot','cinema'):
            args=['ffmpeg','-y','-v','error','-ss',str(s.get('start',0)),'-i',str(ROOT/s['source']),'-t',str(dur),'-map','0:v:0','-map','0:a:0','-vf','scale=1920:1080,setsar=1']
        elif s['kind']=='motion':
            source=pathlib.Path(s['source']); source=source if source.is_absolute() else ROOT/source
            args=['ffmpeg','-y','-v','error','-stream_loop','-1','-ss',str(s.get('start',0)),'-i',str(source)]
            if s.get('narration'): args+=['-i',str(ROOT/s['narration'])]
            else: args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            args+=['-map','0:v:0','-map','1:a:0','-t',str(dur),'-vf','scale=1920:1080,setsar=1']
        elif s['kind']=='clip':
            source=pathlib.Path(s['source']); source=source if source.is_absolute() else ROOT/source
            if s.get('intervals'):
                cuts=[]; cut_duration=0
                for j,interval in enumerate(s['intervals']):
                    piece=WORK/f'{i:02d}-{s["id"]}-cut{j}.mp4'
                    if interval.get('image'):
                        length=interval['duration']; input_args=['-loop','1','-i',str(ROOT/interval['image'])]
                    else:
                        length=interval['end']-interval['start']; input_args=['-ss',str(interval['start']),'-i',str(source)]
                    cut_duration+=length
                    run(['ffmpeg','-y','-v','error',*input_args,'-t',str(length),'-an','-c:v','libx264','-preset','veryfast','-crf','18','-r',str(FPS),'-pix_fmt','yuv420p',str(piece)])
                    cuts.append("file '"+piece.as_posix()+"'")
                if abs(cut_duration-dur)>.1: raise ValueError(f'{s["id"]}: source intervals {cut_duration}s do not match edit window {dur}s')
                cutlist=WORK/f'{s["id"]}-cuts.txt'; cutlist.write_text('\n'.join(cuts),encoding='utf-8')
                edited=WORK/f'{s["id"]}-edited.mp4'
                run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(cutlist),'-c','copy',str(edited)])
                source=edited
            im,_=base(s,True); im.save(graphic)
            args=['ffmpeg','-y','-v','error','-ss',str(s.get('start',0)),'-i',str(source),'-loop','1','-i',str(graphic)]
            if s.get('native_audio_source'):
                args+=['-ss',str(s.get('audio_start',0)),'-i',str(ROOT/s['native_audio_source'])]; audio_map='2:a:0'
            elif s.get('native_audio'):
                audio_map='0:a:0'
            elif s.get('narration'):
                args+=['-i',str(ROOT/s['narration'])]; audio_map='2:a:0'
            else:
                args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']; audio_map='2:a:0'
            crop=''
            if s.get('crop'):
                x,y,w,h=s['crop']; crop=f'crop={w}:{h}:{x}:{y},'
            vf='[0:v]'+crop+'scale=1800:880:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xf8f9f6[v];[v][1:v]overlay=0:0,scale=1920:1080,setsar=1[out]'
            args+=['-filter_complex',vf,'-map','[out]','-map',audio_map,'-t',str(dur)]
        else:
            ({'architecture':architecture,'proof':proof}.get(s['kind'],card))(s,graphic)
            args=['ffmpeg','-y','-v','error','-loop','1','-i',str(graphic)]
            if s.get('narration'): args+=['-i',str(ROOT/s['narration'])]
            else: args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            args+=['-map','0:v:0','-map','1:a:0','-t',str(dur)]
        args+=['-af','apad','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-r',str(FPS),'-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(dest)]
        if not assemble_only: run(args)
        concat.append("file '"+dest.as_posix()+"'")
        receipts.append({'id':s['id'],'start':round(elapsed,3),'duration':dur,'source':s.get('source'),'source_intervals':s.get('intervals'),'narration':s.get('narration'),'native_audio_source':s.get('native_audio_source'),'label':s.get('label'),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        elapsed+=dur
        print(f'{s["id"]}: {dur}s',flush=True)
    if only:
        print('Prepared selected sections in '+str(parts)); return
    subtitles(timeline,name)
    listing=parts/'concat.txt'; listing.write_text('\n'.join(concat),encoding='utf-8')
    final=OUT/f'{name}.mp4'
    assembled=WORK/f'{name}-assembled.mp4'
    run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(assembled)])
    score=ROOT/'private/submission_media/video/savia-original-score.wav'
    if timeline.get('original_score') and score.exists():
        run(['ffmpeg','-y','-v','error','-i',str(assembled),'-i',str(score),'-filter_complex','[0:a]loudnorm=I=-17:TP=-2:LRA=10[voice];[1:a]volume=0.42[bed];[voice][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(final)])
    else:
        run(['ffmpeg','-y','-v','error','-i',str(assembled),'-c','copy','-movflags','+faststart',str(final)])
    if timeline.get('burn_captions'):
        subtitles(timeline,name,burn=True)
        subtitled=WORK/f'{name}-captioned.mp4'
        subtitle_path=(WORK/f'{name}.srt').relative_to(ROOT).as_posix()
        style='FontName=Segoe UI,FontSize=14,PrimaryColour=&H00F6F9F8,OutlineColour=&H00353C17,Outline=1,Shadow=0,MarginV=24'
        run(['ffmpeg','-y','-v','error','-i',str(final),'-vf',f"subtitles=filename='{subtitle_path}':force_style='{style}'",'-c:v','libx264','-preset','veryfast','-crf','19','-c:a','copy','-movflags','+faststart',str(subtitled)])
        subtitled.replace(final)
    run(['ffmpeg','-v','error','-i',str(final),'-f','null','-'])
    probe=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(final)]))
    receipt={'artifact':str(final.relative_to(ROOT)),'duration':float(probe['format']['duration']),'full_decode':'passed','sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'timeline':str(timeline_path.relative_to(ROOT)),'sections':receipts,'scope':timeline['scope']}
    (OUT/f'{name}-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    preview_times=[round(elapsed*f,3) for f in [.02,.12,.23,.35,.48,.59,.72,.86,.96]]
    for sec in preview_times:
        run(['ffmpeg','-y','-v','error','-ss',str(sec),'-i',str(final),'-frames:v','1',str(graphics/f'preview-{sec:03}.png')])
    sheet=Image.new('RGB',(1440,810),CREAM)
    for n,sec in enumerate(preview_times):
        tile=Image.open(graphics/f'preview-{sec:03}.png'); tile.thumbnail((480,270)); sheet.paste(tile,((n%3)*480,(n//3)*270))
    sheet.save(OUT/f'{name}-contact-sheet.jpg')
    subtitles(timeline,name)
    print(final)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--timeline',default='docs/submission/media/video/tv-timeline.json'); p.add_argument('--name',default='savia-submission'); p.add_argument('--only',help='Comma-separated section IDs for partial preparation'); p.add_argument('--assemble-only',action='store_true',help='Assemble explicitly prepared parts after validating their duration'); a=p.parse_args()
    build(ROOT/a.timeline,a.name,set(a.only.split(',')) if a.only else None,a.assemble_only)
