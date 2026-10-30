"""Independent media and frozen source-frame diagnostics for generated trials."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess
from fractions import Fraction
from pathlib import Path
from PIL import Image,ImageChops,ImageStat

BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve();EXP=BASE/'structured-v1'
FFMPEG=BASE/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--trial');parser.add_argument('--output-root',type=Path);args=parser.parse_args()
    experiment=args.output_root.resolve() if args.output_root else EXP
    rows=[]
    for config in sorted((experiment/'runs').glob('*/*/*/effective.json')):
        run=config.parent
        if not (run/'result.json').exists():continue
        effective=json.loads(config.read_text());task=effective['task'];work=run/task['id'];video=work/'out/video.mp4'
        if args.trial and effective['trial']!=args.trial:continue
        out=run/'qa';out.mkdir(exist_ok=True)
        row={'task':task['id'],'arm':effective['arm'],'trial':effective['trial'],'technical_pass':False,
             'semantic_quality':'not_human_blind_reviewed'}
        if not video.is_file():
            row['reason']='missing_video';(out/'verification.json').write_text(json.dumps(row,indent=2));rows.append(row);continue
        def container(program,args):
            return subprocess.run(['docker','run','--rm','--user',f'{os.getuid()}:{os.getgid()}',
                '--network','none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                '--memory=2g','--cpus=2','--tmpfs','/tmp','--entrypoint',
                '/runtime/node_modules/@remotion/compositor-linux-x64-gnu/ffprobe' if program=='ffprobe' else '/tools/node_modules/@ffmpeg-installer/linux-x64/ffmpeg',
                '-v',f'{BASE}/runtime:/runtime:ro','-v',f'{BASE}/qa-runtime:/tools:ro','-v',f'{work}:/work:ro',
                effective['image'],*args],capture_output=True,text=True,timeout=180)
        probe=container('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json','/work/out/video.mp4'])
        if probe.returncode:raise ValueError('independent probe failed: '+probe.stderr[-1000:])
        metadata=json.loads(probe.stdout);stream=next(s for s in metadata['streams'] if s['codec_type']=='video')
        decoded=container('ffmpeg',['-v','error','-xerror','-i','/work/out/video.mp4','-map','0:v:0','-c:v','libx264','-preset','ultrafast','-f','null','-'])
        checks={'width':stream['width']==task['width'],'height':stream['height']==task['height'],
                'fps':float(Fraction(stream['r_frame_rate']))==task['fps'],
                'frames':int(stream.get('nb_read_frames') or 0)==task['frames'],'full_decode':decoded.returncode==0}
        row.update(technical_pass=all(checks.values()),checks=checks,video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                   actual_width=stream['width'],actual_height=stream['height'],actual_fps=stream['r_frame_rate'],
                   actual_frames=stream.get('nb_read_frames'),audio_streams=sum(s['codec_type']=='audio' for s in metadata['streams']))
        if effective['arm']!='legacy':
            receipts=[json.loads(p.read_text()) for p in (work/'out').glob('render-*/receipt.json')]
            matching=[r for r in receipts if r.get('video_sha256')==row['video_sha256']]
            current_sha=hashlib.sha256((work/'src/index.tsx').read_bytes()).hexdigest()
            row['published_video_matches_current_source']=any(r['source_version']==current_sha for r in matching)
            row['source_currency_check_scope']='additional posthoc integrity check; does not alter frozen media or pixel gates'
        def frame(path,seconds,target,fit=None,size=None):
            args=[str(FFMPEG),'-v','error','-y','-ss',str(seconds),'-i',str(path)]
            width,height=size or (task['width'],task['height'])
            if fit=='cover':args+=['-vf',f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"]
            args+=['-frames:v','1',str(target)]
            p=subprocess.run(args,capture_output=True,text=True,timeout=60)
            if p.returncode or not target.is_file():raise ValueError('independent frame extraction failed')
            return Image.open(target).convert('RGB')
        times=[min(.5,(task['frames']-1)/task['fps']),task['frames']/task['fps']/2,(task['frames']-min(15,task['frames']))/task['fps']]
        for i,t in enumerate(times):frame(video,t,out/f'frame-{i}.png')
        source_checks=[]
        for i,sample in enumerate(task['qa']['source_samples']):
            actual=frame(video,sample['output_seconds'],out/f'sample-{i}-actual.png')
            size=(task['width'],task['height'])
            if 'box' in sample:
                region=sample['box']
                if not (0<=region[0]<region[2]<=task['width'] and 0<=region[1]<region[3]<=task['height']):raise ValueError('invalid frozen sample box')
                actual=actual.crop(tuple(region));size=actual.size
            expected=frame(BASE/'assets'/sample['source'],sample['source_seconds'],out/f'sample-{i}-expected.png',sample['fit'],size)
            x0,y0,x1,y1=sample['roi'];box=(round(x0*size[0]),round(y0*size[1]),round(x1*size[0]),round(y1*size[1]))
            if actual.size!=expected.size:
                mae=None
            else:mae=sum(ImageStat.Stat(ImageChops.difference(actual.crop(box),expected.crop(box))).mean)/3
            source_checks.append({**sample,'central_pixel_mae':mae,'within_frozen_mae_threshold':mae is not None and mae<=task['qa']['pixel_mae_max']})
        row['source_frame_checks']=source_checks
        row['selected_source_frames_pass']=all(c['within_frozen_mae_threshold'] for c in source_checks) if source_checks else None
        audio_spec=task['qa'].get('audio_windows')
        if audio_spec is None and task['id']=='t36_music_window':
            audio_spec=[{'start':s,'duration':d,'silent':q} for s,d,q in [(.05,.7,True),(2.5,1,False),(5.2,.6,True)]]
        if audio_spec is not None:
            windows=[]
            for spec in audio_spec:
                start,duration=spec['start'],spec['duration']
                silent=spec['expected_silent'] if 'expected_silent' in spec else spec['silent']
                p=subprocess.run([str(FFMPEG),'-hide_banner','-i',str(video),'-vn','-af',f'aresample=async=1:first_pts=0,atrim=start={start}:duration={duration},volumedetect','-f','null','-'],capture_output=True,text=True,timeout=60)
                match=re.search(r'mean_volume:\s*(-?\d+(?:\.\d+)?|-inf)\s*dB',p.stderr)
                mean=float(match.group(1)) if match and match.group(1)!='-inf' else -120 if match else None
                windows.append({'start':start,'duration':duration,'mean_db':mean,'expected_silent':silent,
                                'pass':row['audio_streams']>0 and mean is not None and (mean<-70 if silent else mean>-70)})
            row['audio_windows']=windows
        (out/'probe.json').write_text(json.dumps(metadata,indent=2));(out/'verification.json').write_text(json.dumps(row,ensure_ascii=False,indent=2));rows.append(row)
    (experiment/('verification-summary-'+args.trial+'.json' if args.trial else 'verification-summary.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps([{'task':r['task'],'arm':r['arm'],'technical_pass':r['technical_pass'],'selected_source_frames_pass':r.get('selected_source_frames_pass')} for r in rows],ensure_ascii=False))

if __name__=='__main__':main()
