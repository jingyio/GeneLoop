"""Render learned source in the existing sandbox and compare its native witness.

Source equivalence is separate from new-task generalization, which is measured
by the frozen paired trials. No random-input variation is passed off as a held-
out task, and no additional model call is made by this checker.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image,ImageChops,ImageStat

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from src.adapters.source_program_compiler import source_library,program_identity
from src.adapters.script_motif_compiler import digest,sha


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)


def materialize(program):
    # Offline candidate instantiation uses exactly the online implementation.
    request={'operation':'candidate_materialize','program':program,'parameters':program['default_parameters']}
    run=subprocess.run(['node','--experimental-strip-types',str(ROOT/'scripts/materialize-source-program.mjs')],
                       input=json.dumps(request),text=True,capture_output=True,cwd=ROOT,timeout=15)
    if run.returncode:raise ValueError(run.stderr[-1500:])
    return json.loads(run.stdout)


def render_source(work,source,effective,base):
    work.mkdir(parents=True,exist_ok=False)
    for name in ('src','out','public'):(work/name).mkdir()
    (work/'node_modules').symlink_to('/runtime/node_modules')
    (work/'package.json').write_text('{"private":true}')
    for name in effective['task']['assets']:
        (work/'public'/name).write_bytes((base/'assets'/name).read_bytes())
    (work/'src/index.tsx').write_text(source)
    os.environ.update(REMOTION_WORK=str(work),REMOTION_RUNTIME=str(base/'runtime'),REMOTION_IMAGE=effective['image'],
                      REMOTION_MEDIA_TOOLS=str(base/'qa-runtime'),REMOTION_TASK_ASSETS=json.dumps(effective['assets']),
                      REMOTION_TASK_NONCE=work.name,REMOTION_FUSED_PROBE='1')
    spec=importlib.util.spec_from_file_location('certification_scene',Path(__file__).with_name('server.py'))
    scene=importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)
    try:return scene.render_composition(scene.current_source_version())
    finally:scene.workspace.close_container()


def compare_videos(reference,actual,task,output,base):
    ffmpeg=base/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg'
    rows=[]
    for i,seconds in enumerate([0.1,task['frames']/task['fps']/2,(task['frames']-2)/task['fps']]):
        images=[]
        for label,path in [('reference',reference),('actual',actual)]:
            target=output/f'{i}-{label}.png'
            run=subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(seconds),'-i',str(path),'-frames:v','1',str(target)],capture_output=True,timeout=60)
            if run.returncode:raise ValueError('source_equivalence_frame_extraction_failed')
            images.append(Image.open(target).convert('RGB'))
        if images[0].size!=images[1].size:raise ValueError('source_equivalence_dimensions_changed')
        mae=sum(ImageStat.Stat(ImageChops.difference(*images)).mean)/3
        rows.append({'seconds':seconds,'pixel_mae':mae})
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    base=Path(os.environ['REMOTION_EXPERIMENT_ROOT']);library=json.loads(args.library.read_text())
    args.output.mkdir(parents=True,exist_ok=False);accepted=[];rejected=[]
    for program in library['programs']:
        folder=args.output/program['id'];folder.mkdir()
        try:
            witness=program['source_witness'];run=Path(witness['run']);effective=json.loads((run/'effective.json').read_text())
            if sha((run/'events.jsonl').read_bytes())!=witness['events_sha256']:raise ValueError('source_events_changed')
            reference=run/effective['task']['id']/'out/video.mp4'
            if sha(reference.read_bytes())!=witness['video_sha256']:raise ValueError('source_video_changed')
            materialized=materialize(program);work=folder/'workspace'
            receipt=render_source(work,materialized['source'],effective,base)
            frames=compare_videos(reference,work/'out/video.mp4',effective['task'],folder,base)
            # Codec/renderer variation may change encoded bytes; frozen pixel
            # equivalence is stricter than the task source-frame MAE threshold.
            passed=all(r['pixel_mae']<=1.0 for r in frames)
            report={'source_equivalent':passed,'frames':frames,'render':receipt,
                    'program_identity':digest(program_identity(program)),
                    'source_witness':witness,'checker_sha256':sha(Path(__file__).read_bytes()),
                    'scope':'source_frame_equivalence_not_new_task_quality_or_complete_video_equivalence'}
            write(folder/'verification.json',report)
            if not passed:raise ValueError('source_parameterization_changed_pixels')
            program={**program,'status':'certified','certification':report};accepted.append(program)
            print(json.dumps({'certified':program['id'],'frame_mae':[r['pixel_mae'] for r in frames]}),flush=True)
        except Exception as error:
            rejected.append({'id':program['id'],'source_task':program['source_witness']['task_id'],'error':str(error)[:1800]})
            print(json.dumps(rejected[-1]),flush=True)
        write(args.output/'rejected.json',rejected)
    write(args.output/'library.json',source_library(accepted))
    print(json.dumps({'accepted':len(accepted),'rejected':len(rejected)}))


if __name__=='__main__':main()
