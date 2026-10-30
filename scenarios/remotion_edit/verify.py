"""Independent media checks; never equate successful decoding with creative quality."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(os.environ.get('GENELOOP_CODE_ROOT',str(Path(__file__).resolve().parents[2]))).resolve()
BASE=Path(os.environ.get('REMOTION_EXPERIMENT_ROOT',str(ROOT/'.local/experiments/remotion-motivation-20261027-v1'))).resolve()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tasks',type=Path,default=ROOT/'scenarios/remotion_edit/tasks.json');ap.add_argument('--output-dir',type=Path,default=BASE/'qa');args=ap.parse_args()
    tasks=json.loads(args.tasks.read_text());OUT=args.output_dir;OUT.mkdir(parents=True,exist_ok=True);out=[]
    for task in tasks:
        tid=task['id'];work=BASE/'workspaces'/tid;video=work/'out/video.mp4';qa=OUT/tid;qa.mkdir(parents=True,exist_ok=True)
        if not (BASE/'results'/f'{tid}.json').exists():
            out.append({'task':tid,'technical_pass':None,'reason':'task_still_running_or_not_started'});continue
        if not video.is_file():out.append({'task':tid,'technical_pass':False,'reason':'missing_video'});continue
        cfg=json.loads((BASE/'configs'/f'{tid}-effective.json').read_text());image=cfg['image']
        def run(program,args):
            command=['docker','run','--rm','--user',f'{os.getuid()}:{os.getgid()}','--network','none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=2g','--cpus=2','--tmpfs','/tmp','--entrypoint',('/tools/node_modules/@ffmpeg-installer/linux-x64/ffmpeg' if program=='ffmpeg' else '/runtime/node_modules/@remotion/compositor-linux-x64-gnu/ffprobe'),'-v',f'{BASE}/qa-runtime:/tools:ro','-v',f'{BASE}/runtime:/runtime:ro','-v',f'{work}:/work:ro','-v',f'{qa}:/qa:rw',image,*args]
            return subprocess.run(command,capture_output=True,text=True,timeout=150)
        probe=run('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json','/work/out/video.mp4'])
        if probe.returncode:
            out.append({'task':tid,'technical_pass':False,'reason':'probe_failed','error':probe.stderr[-1000:]});continue
        metadata=json.loads(probe.stdout);vs=next(s for s in metadata['streams'] if s['codec_type']=='video')
        decoded=run('ffmpeg',['-v','error','-xerror','-i','/work/out/video.mp4','-map','0:v:0','-c:v','libx264','-preset','ultrafast','-f','null','-'])
        frames=int(vs.get('nb_read_frames') or vs.get('nb_frames') or 0);num,den=map(int,vs['r_frame_rate'].split('/'))
        checks={'width':vs['width']==task['width'],'height':vs['height']==task['height'],'fps':num/den==task['fps'],'frame_count':frames==task['frames'],'full_video_decode':decoded.returncode==0}
        for i,frame in enumerate([min(15,task['frames']-1),task['frames']//2,task['frames']-min(15,task['frames'])]):
            run('ffmpeg',['-v','error','-y','-i','/work/out/video.mp4','-vf',f'select=eq(n\\,{frame}),scale=480:-1','-frames:v','1',f'/qa/frame-{i}.png'])
        row={'task':tid,'technical_pass':all(checks.values()),'checks':checks,'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'width':vs['width'],'height':vs['height'],'fps':num/den,'decoded_frames':frames,'video_duration_seconds':float(vs['duration']),'audio_streams':sum(s['codec_type']=='audio' for s in metadata['streams']),'bytes':video.stat().st_size,'semantic_quality':'not_blind_reviewed','decode_error':decoded.stderr[-1000:]}
        (qa/'probe.json').write_text(json.dumps(metadata,indent=2));out.append(row)
    (OUT/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
