"""Independent, narrow content diagnostics. No blind or full-quality verdict."""
from __future__ import annotations
import argparse,json,math,os,re,subprocess
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
ROOT=Path(__file__).resolve().parents[2]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--experiment-root',type=Path,required=True);ap.add_argument('--tasks',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args()
 b=args.experiment_root;out=args.output_dir;out.mkdir(parents=True,exist_ok=True);ffmpeg=b/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg';rows=[]
 def extract(tid,frame,name):
  dst=out/(tid+'-'+name+'.png')
  p=subprocess.run([str(ffmpeg),'-v','error','-y','-i',str(b/'workspaces'/tid/'out/video.mp4'),'-vf',f'select=eq(n\\,{frame}),scale=480:-1','-frames:v','1',str(dst)],capture_output=True,text=True,timeout=60)
  return dst if p.returncode==0 and dst.is_file() else None
 def rms(tid,start,duration):
  p=subprocess.run([str(ffmpeg),'-hide_banner','-i',str(b/'workspaces'/tid/'out/video.mp4'),'-vn','-af',f'aresample=async=1:first_pts=0,atrim=start={start}:duration={duration},volumedetect','-f','null','-'],capture_output=True,text=True,timeout=60)
  hit=re.search(r'mean_volume:\s*(-?\d+(?:\.\d+)?|-inf)\s*dB',p.stderr)
  return float(hit.group(1)) if hit and hit.group(1)!='-inf' else -120.0 if hit else None
 for task in json.loads(args.tasks.read_text()):
  tid=task['id'];result=b/'results'/(tid+'.json');video=b/'workspaces'/tid/'out/video.mp4'
  if not result.exists() or not video.is_file():continue
  row={'task':tid,'review_kind':'narrow_read_only_diagnostic','full_quality_pass':None}
  first=extract(tid,0,'first');last=extract(tid,task['frames']-1,'last')
  if first:
   im=Image.open(first).convert('RGB');stat=ImageStat.Stat(im)
   row['first_frame_mean_rgb']=stat.mean
   row['near_black_first_frame']=max(stat.mean)<2
   if tid=='t30_four_panel_clock':
    w,h=im.size;row['first_frame_quadrant_means']=[ImageStat.Stat(im.crop((x*w//2,y*h//2,(x+1)*w//2,(y+1)*h//2))).mean for y in range(2) for x in range(2)]
  if tid=='t19_long_crossfade':
   refs=[]
   for name,path,seconds in [('source-a',b/'assets/bunny_a_24.mp4',3),('source-c',b/'assets/bunny_c_60.mp4',4.5),('output',video,3)]:
    target=out/('t19-overlap-'+name+'.png')
    result=subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(seconds),'-i',str(path),'-frames:v','1',str(target)],capture_output=True,text=True,timeout=60)
    if result.returncode==0 and target.exists():refs.append(target)
   if len(refs)==3:
    a,c,o=[Image.open(p).convert('RGB').crop((64,60,576,260)) for p in refs]
    mean=lambda im:sum(ImageStat.Stat(im).mean)/3
    row['overlap_midpoint']={'output_seconds':3,'expected_overlap':[2.5,3.5],'reference_linear_mix_fraction':.5,'central_mae_vs_source_c':mean(ImageChops.difference(o,c)),'central_mae_vs_half_mix':mean(ImageChops.difference(o,Image.blend(a,c,.5))),'interpretation':'narrow pixel comparison; intended one-second transition reviewed separately'}
  if tid in ('t20_freeze_detail','t22_repeat_then_move'):
   times=[2.125,2.75] if tid=='t20_freeze_detail' else [.5,1.5,2.5]
   paths=[extract(tid,round(t*task['fps']),f'compare-{i}') for i,t in enumerate(times)]
   if all(paths):
    imgs=[Image.open(p).convert('RGB') for p in paths];w,h=imgs[0].size
    # Exclude headline and output clock; this is a diagnostic, not a complete mask proof.
    crops=[im.crop((w//10,h//3,9*w//10,4*h//5)) for im in imgs]
    row['selected_output_times']=times;row['central_pixel_mae']=[sum(ImageStat.Stat(ImageChops.difference(crops[0],x)).mean)/3 for x in crops[1:]]
    row['central_frames_repeat_approximately']=max(row['central_pixel_mae'])<2
  if tid in ('t25_audio_bridge','t26_silent_open_music'):
   windows=[(.25,1),(3.25,2)] if tid=='t25_audio_bridge' else [(.05,1.3),(2.25,2)]
   row['audio_windows']=[dict(start=s,duration=d,mean_db=rms(tid,s,d)) for s,d in windows]
   silent_index=1 if tid=='t25_audio_bridge' else 0;loud_index=1-silent_index
   sd=row['audio_windows'][silent_index]['mean_db'];ld=row['audio_windows'][loud_index]['mean_db']
   row['expected_silent_window_below_minus70db']=sd is not None and sd<-70
   row['expected_music_or_source_window_nonzero']=ld is not None and ld>-70
  rows.append(row)
 (out/'content-checks.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
if __name__=='__main__':main()
