"""Illustrate accepted informational closure without implying a bank decision."""
import pathlib,sys
from PIL import Image,ImageDraw
ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/submission_media/motion'))
import build_assistant_visuals as motion

def frame(t,dur):
    im=Image.new('RGB',(1920,1080),motion.FOREST)
    d=ImageDraw.Draw(im,'RGBA'); motion.brand(d,motion.LIME)
    motion.soft_orb(d,960,345,95,t)
    motion.label(d,(960,600),'Your answer is saved.',62,motion.CREAM,'medium','mm')
    motion.label(d,(960,730),'Nébula Market',44,motion.LIME,'medium','mm')
    motion.label(d,(960,816),'You marked the explanation helpful.',30,motion.CREAM,'regular','mm')
    motion.label(d,(960,1020),'Actual integrated Savia voice · informational closure',20,motion.MUTED,'regular','mm')
    return im

if __name__=='__main__':
    print(motion.render('assistant-spoken-update',4.95,frame))
