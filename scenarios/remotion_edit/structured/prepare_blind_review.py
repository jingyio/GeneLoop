"""Prepare deidentified local review materials, without inventing human scores."""
from __future__ import annotations
import hashlib,json,os,random,shutil
from pathlib import Path

BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve();EXP=BASE/'structured-v1'

def main():
    output=EXP/'blind-review'
    if output.exists():raise ValueError('preserve the existing review package and ratings')
    runs=[]
    for result in sorted((EXP/'runs').glob('*/*/*/result.json')):
        run=result.parent;effective=json.loads((run/'effective.json').read_text())
        if effective['trial'] in ('v1','v2') and effective['task']['partition']=='evaluation':
            runs.append((run,effective))
    if len(runs)!=35:raise ValueError('both complete 20+15 matrices are required, including failed delivery')
    rng=random.Random(20261028);rng.shuffle(runs)
    groups={key:'Q%02d'%(i+1) for i,key in enumerate(sorted({(e['trial'],e['task']['id']) for _,e in runs}))}
    (output/'videos').mkdir(parents=True)
    key=[];ratings=[];questions={}
    for i,(run,effective) in enumerate(runs):
        clip='V%03d'%(i+1);task=effective['task'];q=groups[(effective['trial'],task['id'])]
        video=run/task['id']/'out/video.mp4';target=output/'videos'/(clip+'.mp4')
        digest=None
        if video.is_file():
            shutil.copy2(video,target);digest=hashlib.sha256(target.read_bytes()).hexdigest()
        key.append({'clip':clip,'question':q,'trial':effective['trial'],'arm':effective['arm'],'task':task['id'],
                    'run':str(run),'video_sha256':digest})
        ratings.append({'clip':clip,'question':q,'delivered_video':video.is_file(),'content_correct':None,
                        'timing_correct':None,'layout_readable':None,'audio_correct':None,
                        'major_error':None,'overall_acceptable':None,'notes':''})
        questions.setdefault(q,{'task':task,'clips':[]})['clips'].append((clip,target if video.is_file() else None))
    lines=['# 去除臂标签的视频审阅包','',
           '这是待人工审阅材料，尚无人工评分。请先不看成本或映射表，按每题原要求查看完整视频；缺少视频也保留为一条结果。',
           '在ratings.json填写内容、时间、布局、音频和整体是否可接受，并说明重大错误；没有检查的字段保留null。',
           '同一题的不同协议复测分列，不当作新独立客户。此包只去除运行臂标签，不保证所有画面风格线索均被隐藏。',
           '评分后再由实验负责人合并私有映射与成本。已有自动检查及Agent审阅不在此包预填，避免影响评分。','']
    (output/'sources').mkdir()
    lines.extend(['## 共同源素材','', '检查源时点时，请打开对应源文件对照；源文件名不包含运行臂信息。',''])
    sources=[]
    for name in sorted({name for _,e in runs for name in e['task']['assets']}):
        original=BASE/'assets'/name;target=output/'sources'/name
        shutil.copy2(original,target);sha=hashlib.sha256(target.read_bytes()).hexdigest()
        sources.append({'name':name,'sha256':sha});lines.append(f'- [{name}](<{target}>)，SHA256 {sha}')
    (output/'source-manifest.json').write_text(json.dumps(sources,indent=2));lines.append('')
    for q,group in sorted(questions.items()):
        task=group['task'];lines.extend(['## '+q,'',task['instruction'],
            f"输出{task['width']}×{task['height']}，{task['fps']}fps，{task['frames']}帧。",''])
        for clip,target in sorted(group['clips']):
            lines.append('- '+(f'[{clip}](<{target}>)' if target else clip+'：没有交付视频'))
        lines.append('')
    (output/'README.md').write_text('\n'.join(lines))
    (output/'ratings.json').write_text(json.dumps(ratings,ensure_ascii=False,indent=2))
    mapping=EXP/'blind-review-key.json';mapping.write_text(json.dumps({'seed':20261028,'assignments':key},indent=2))
    for file in [output/'README.md',output/'ratings.json',mapping]:file.chmod(0o600)
    print(json.dumps({'review_directory':str(output),'matrix_entries':len(runs),'videos':sum(r['delivered_video'] for r in ratings),
                      'human_ratings_completed':0,'method':'fixed random assignment; arm and cost omitted from review materials'}))

if __name__=='__main__':main()
