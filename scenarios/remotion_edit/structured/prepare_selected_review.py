"""Export arm/cost-free original frames, then bind explicit reviews to exact bytes.

The key stays outside the review package. A Codex pixel review is AI review of
selected frames, not independent human review or a full-video quality claim.
"""
import argparse,hashlib,json,os,random,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from src.adapters.rsi_protocol import envelope
from src.adapters.script_motif_compiler import digest
from src.adapters.rsi_quality import quality_status,verify_quality_files
from scenarios.remotion_edit.structured.review_program_runs import VISUAL_CHECKS,failed_artifact_review
from src.motif_core.offline.experience_registry import durable,read,sha


def prepare(output,trials,destination,protocol,seed):
    if destination.exists():raise ValueError('preserve_existing_review_package')
    destination.mkdir(parents=True);key=[];index=[]
    runs=[p.parent for trial in trials for p in (output/'runs'/trial).glob('*/*/result.json')]
    random.Random(seed).shuffle(runs)
    ffmpeg=Path(os.environ['REMOTION_EXPERIMENT_ROOT'])/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg'
    for i,run in enumerate(runs):
        label='Q%03d'%(i+1);effective=read(run/'effective.json');task=effective['task'];qa=read(run/'qa/verification.json')
        video=run/task['id']/'out/video.mp4';folder=destination/label;folder.mkdir();frames=[]
        if video.exists():
            if sha(video)!=qa['video_sha256']:raise ValueError('review_final_video_changed')
            seconds=task['qa'].get('review_seconds',[0.1,task['frames']/task['fps']/2,(task['frames']-1)/task['fps']])
            target=run/'qa/review-frames';target.mkdir(exist_ok=True)
            for n in sorted({min(task['frames']-1,max(0,int(s*task['fps']))) for s in seconds}):
                file=target/('frame-%06d.png'%n)
                if not file.exists():
                    subprocess.run([str(ffmpeg),'-v','error','-i',str(video),'-vf',f'select=eq(n\\,{n})',
                        '-vsync','0','-frames:v','1',str(file)],check=True,capture_output=True)
                copy=folder/file.name;shutil.copyfile(file,copy)
                frames.append({'path':str(copy.relative_to(destination)),'run_ref':str(file.relative_to(run)),
                    'sha256':sha(file),'frame_index':n,'seconds':n/task['fps']})
            shutil.copyfile(video,folder/'video.mp4')
        entry={'id':label,'task':task,'frames':frames,'technical_checks':qa.get('checks'),
            'source_checks':qa.get('source_checks'),'source_pass':qa.get('selected_source_frames_pass'),
            'audio_windows':qa.get('audio_windows',[]),'scope':'AI selected original frames and independent media checks'}
        durable(folder/'task.json',entry);index.append(entry)
        key.append({'id':label,'run':str(run),'task_sha256':digest(task),'artifact_sha256':qa.get('video_sha256'),
            'rubric_sha256':sha(protocol),'frames':frames,'automatic_failure':failed_artifact_review(read(run/'result.json'),qa)})
    durable(destination/'index.json',index)
    durable(destination.with_suffix('.key.json'),key,exclusive=True)
    print(json.dumps({'reviews':len(index),'package':str(destination),'costs_and_arms_exposed':False}))


def apply(destination,decisions):
    key=read(destination.with_suffix('.key.json'));answers=read(decisions)
    if set(answers)!={k['id'] for k in key}:raise ValueError('review_inventory_incomplete')
    for entry in key:
        run=Path(entry['run']);answer=answers[entry['id']]
        if entry['automatic_failure']:
            target=run/'qa/semantic-review.json'
            if target.exists() and read(target)!=entry['automatic_failure']:raise ValueError('preserve_existing_quality_review')
            if not target.exists():durable(target,entry['automatic_failure'],exclusive=True)
            continue
        if set(answer)!=set(VISUAL_CHECKS):raise ValueError('review_criteria_changed')
        evidence=[{'ref':f['run_ref'],'sha256':f['sha256']} for f in entry['frames']]
        record=envelope('quality_evaluation',{'id':'selected-frames-'+entry['artifact_sha256'][:24],
            'task_id':read(run/'effective.json')['task']['id'],
            **{k:entry[k] for k in ('task_sha256','artifact_sha256','rubric_sha256')},
            'evaluator':'codex_actual_selected_frames','scope':'selected_original_frames_with_frozen_task_requirements',
            'checks':[{'id':name,'status':answer[name]['status'],'observation':answer[name]['observation'],'evidence':evidence}
                      for name in VISUAL_CHECKS],
            'limitations':['AI review, not human blind review or complete video/audio assessment',
                'Reviewer knows research background; arm and cost absent from review package',
                'Codex host review cost unknown and separate from DeepSeek ledger']})
        quality_status(record,**{k:entry[k] for k in ('task_sha256','artifact_sha256','rubric_sha256')},required_checks=VISUAL_CHECKS)
        verify_quality_files(record,run)
        target=run/'qa/semantic-review.json'
        if target.exists():
            if read(target)!=record:raise ValueError('preserve_existing_quality_review')
        else:durable(target,record,exclusive=True)
    print(json.dumps({'bound_reviews':len(key),'model_requests':0}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path);p.add_argument('--trial',action='append',default=[])
    p.add_argument('--destination',type=Path,required=True);p.add_argument('--protocol',type=Path)
    p.add_argument('--seed',type=int,default=20261030);p.add_argument('--apply',type=Path);a=p.parse_args()
    if a.apply:apply(a.destination,a.apply)
    else:prepare(a.output_root,a.trial,a.destination,a.protocol,a.seed)
