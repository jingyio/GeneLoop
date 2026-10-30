"""Frozen motivation suite, using the existing GeneLoop DSH SDK and cost gate."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.adapters.harness_runtime import create_harness
from src.adapters.scenario import prepare_scenario
from src.adapters.deepseek_cost_gate import State, create_server
from src.adapters.native_budget import NativeBudgetGuard
from deepseek_harness.api import final_response,finish_reason

class TaskTurnEnded(Exception): pass

HERE=Path(__file__).resolve().parent
BASE=Path(os.environ.get('REMOTION_EXPERIMENT_ROOT',str(ROOT/'.local/experiments/remotion-motivation-20261027-v1'))).resolve()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2) if not isinstance(value,str) else value)
    path.chmod(0o600)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--task'); ap.add_argument('--call-model',action='store_true'); ap.add_argument('--parallel',type=int,default=2); ap.add_argument('--tasks',type=Path,default=HERE/'tasks.json'); ap.add_argument('--batch-id',default='v1'); ap.add_argument('--media-tools',type=Path); ap.add_argument('--asset-manifest',type=Path); args=ap.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]{1,40}',args.batch_id) or not 1<=args.parallel<=4: ap.error('invalid batch or parallel limit')
    tasks=json.loads(args.tasks.read_text())
    if len({t['id'] for t in tasks})!=len(tasks): raise ValueError('duplicate task identity')
    manifests=json.loads(args.asset_manifest.read_text()) if args.asset_manifest else []
    source_rows={r['name']:r for r in manifests}
    for task in tasks:
        if not re.fullmatch(r't[0-9]{2}_[a-z0-9_]+',task['id']): raise ValueError('invalid task identity')
        for name in task.get('assets',[]):
            if Path(name).name!=name or name not in source_rows: raise ValueError('missing asset provenance')
            if hashlib.sha256((BASE/'assets'/name).read_bytes()).hexdigest()!=source_rows[name]['sha256']: raise ValueError('changed source asset')
    image=os.environ['REMOTION_IMAGE']
    # Credentials are inherited from private server configuration, never serialized.
    if args.call_model and not os.environ.get('DEEPSEEK_API_KEY'): raise RuntimeError('missing private credential')
    checkpoint=BASE/'budget-checkpoint.json'
    if not checkpoint.exists(): save(checkpoint,{'request_count':0,'reserved_usd':0})
    attribution={}
    class AuditedState(State):
        def book(self,body):
            booked=super().book(body)
            if booked:
                save(BASE/'requests'/f'{booked[0]:06d}.json',json.loads(body))
                payload=body.decode()
                attribution[booked[0]]=next((t['id'] for t in tasks if t['instruction'] in payload), 'unknown')
            return booked
    state=AuditedState(cap_usd=None,output_cap=6000,record=BASE/'cost-ledger.jsonl',request_limit=None,checkpoint=checkpoint)
    gate=create_server('127.0.0.1',0,'https://api.deepseek.com',state)
    worker=threading.Thread(target=gate.serve_forever,daemon=True); worker.start()
    def run_task(task):
        if args.task and task['id']!=args.task: return
        result_path=BASE/'results'/f"{task['id']}.json"
        if result_path.exists(): return # preserve both failed and successful attempts
        work=BASE/'workspaces'/task['id']; work.mkdir(parents=True,exist_ok=True)
        (work/'src').mkdir(exist_ok=True); (work/'out').mkdir(exist_ok=True)
        if task.get('assets'):
            (work/'public').mkdir(exist_ok=True)
            for name in task['assets']:
                target=work/'public'/name
                if not target.exists(): shutil.copyfile(BASE/'assets'/name,target)
            save(work/'public/ASSET-MANIFEST.json',[source_rows[name] for name in task['assets']])
        elif not (work/'public').exists(): shutil.copytree(BASE/'assets',work/'public')
        if not (work/'node_modules').is_symlink(): (work/'node_modules').symlink_to('/runtime/node_modules')
        seed="import React from 'react';\nimport {registerRoot,Composition,AbsoluteFill} from 'remotion';\nconst Edit=()=> <AbsoluteFill style={{backgroundColor:'#102235',color:'white',alignItems:'center',justifyContent:'center',fontSize:36}}>EDIT ME</AbsoluteFill>;\nconst Root=()=> <Composition id='Main' component={Edit} durationInFrames={FRAMES} fps={FPS} width={WIDTH} height={HEIGHT}/>;\nregisterRoot(Root);\n"
        for k in ('frames','fps','width','height'): seed=seed.replace(k.upper(),str(task[k]))
        save(work/'src/index.tsx',seed)
        save(work/'package.json',{'name':'remotion-task','private':True})
        brief=f"你是视频剪辑Agent。使用Remotion 4.0.539和React19完成真实视频，不要只写计划。任务：{task['instruction']}\n输出为{task['width']}x{task['height']}，{task['fps']}fps，精确{task['frames']}帧。源素材在public/，来源、片段父文件及帧率见public/ASSET-MANIFEST.json（若存在），同一影片的派生素材不代表独立拍摄项目。\n请自主检查素材元数据、编写src/index.tsx、实际渲染out/video.mp4并检查输出。当前种子仅为占位卡。不要安装依赖或访问网络。不要编造检查成功。命令工具的准确名字是mcp__remotion__run_command，其他准确名字是mcp__remotion__list_files/read_file/write_file；不得省略remotion前缀。timeout_seconds范围1–240，单位秒。允许在当前隔离工作区编辑和运行，不需要再征询许可。保留简短剪辑说明out/edit-notes.md。\n工具在/work中运行；node_modules链接到/runtime/node_modules。Node路径/usr/local/bin/node（若不存在可用/home/frappe/.nvm/current/bin/node）。Remotion CLI: node /runtime/node_modules/@remotion/cli/remotion-cli.js 。渲染使用 render src/index.tsx Main out/video.mp4 --browser-executable=/usr/bin/chromium-headless-shell --concurrency=2 --log=error。ffprobe和ffmpeg在PATH中；本批次若启用media-tools则ffmpeg为完整版本，ffprobe仍来自固定Remotion运行时。Video使用remotion的OffthreadVideo，staticFile引用public素材；Sequence的from只控制输出时间轴，不能用它代替源裁剪。按本轮安装版Remotion4.0.539，trimBefore/startFrom以合成fps的帧为单位（秒偏移×合成fps），即使源素材fps不同也不要改用源fps去乘；请用实际帧内容检查换算。可用startFrom兼容别名。音频Audio支持volume，帧动画使用useCurrentFrame/interpolate。禁止CSS动画和定时器。同一任务内的容器、后台进程和/tmp持续存在，直到任务结束；推荐先前台渲染等待退出，避免无必要轮询。务必等待实际渲染成功才报告完成。"
        save(work/'brief.md',brief)
        config={'schema_version':1,'name':'remotion_edit','prompt':str(work/'brief.md'),'servers':[{'server_name':'remotion','transport':'stdio','command':sys.executable,'args':[str(HERE/'server.py')],'cwd':str(ROOT),'env':{'REMOTION_WORK':str(work),'REMOTION_RUNTIME':str(BASE/'runtime'),'REMOTION_IMAGE':image,**({'REMOTION_MEDIA_TOOLS':str(args.media_tools.resolve())} if args.media_tools else {})},'tool_call_timeout_ms':300000}],'allowed_tools':['mcp__remotion__list_files','mcp__remotion__read_file','mcp__remotion__write_file','mcp__remotion__run_command']}
        save(BASE/'configs'/f"{task['id']}-scenario.json",config)
        prepared=prepare_scenario(BASE/'configs'/f"{task['id']}-scenario.json")
        session='remotion-'+uuid4().hex
        preview={**task,'session_id':session,'model':'deepseek-flash','reasoning_effort':'off','cap_usd':None,'budget_policy':'uncapped_user_authorized','reset_history':False,'max_requests':None,'max_output':6000,'code_sha':'ec72908755ea6df1771ec962b40e3b27be381ebb','image':image,'prompt_sha256':prepared['prompt_sha256'],'tools':prepared['allowed_tools'],'mode':'baseline','compression':'disabled','manifest':None}
        preview['environment_protocol']='persistent-container-v4-complete-media-tools' if args.media_tools else 'persistent-container-v3-turn-end'
        preview['batch_id']=args.batch_id
        preview['task_manifest_sha256']=hashlib.sha256(args.tasks.read_bytes()).hexdigest()
        preview['task_fingerprint']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        preview['media_tools']=str(args.media_tools.resolve()) if args.media_tools else None
        preview['assets']=[source_rows[n] for n in task.get('assets',[])]
        preview['max_task_wall_seconds']=900
        preview['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
        save(BASE/'configs'/f"{task['id']}-effective.json",preview)
        if not args.call_model:
            print(json.dumps(preview,ensure_ascii=False),flush=True); return
        guard=NativeBudgetGuard(max_model_requests=None,max_observed_input_tokens=None)
        def observe(n):
            if n.method=='session.event':
                event=n.payload.get('event')
                if isinstance(event,dict):
                    event_path=BASE/'events'/task['id']/'agent-events.jsonl'
                    event_path.parent.mkdir(parents=True,exist_ok=True)
                    with event_path.open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
                    event_path.chmod(0o600)
            guard.on_notification(n)
            if n.method=='session.event' and n.payload.get('sessionId')==session and n.payload.get('event',{}).get('type')=='turn/end':
                raise TaskTurnEnded()
            if time.monotonic()-started>900:
                raise TimeoutError('experiment task exceeded 900s wall-time checkpoint; spend history retained')
        env={'SSS_SCENARIO_TOOLS':json.dumps(prepared['allowed_tools']),'DEEPSEEK_API_KEY':os.environ['DEEPSEEK_API_KEY'],'DEEPSEEK_BASE_URL':f'http://127.0.0.1:{gate.server_port}/v1','SSS_BUDGET_GATE_ACTIVE':'1','SSS_BUDGET_CAP_USD':'0','SSS_BUDGET_LEDGER':str(BASE/'cost-ledger.jsonl')}
        started=time.monotonic(); before=state.request_count
        print(json.dumps({'start':task['id'],'prior_requests':before}),flush=True)
        metrics={'task':task['id'],'batch_id':args.batch_id,'status':'failed'}
        try:
            with create_harness(root=ROOT,patches=(prepared['patch'],),env=env,provider='deepseek-official',model='deepseek-flash',max_tokens=6000,cwd=str(work),runtime_cwd=str(work),request_timeout_seconds=1800) as h:
                result=h.run(brief,session_id=session,on_notification=observe)
            save(work/'answer.md',result.final_response)
            metrics.update(status='completed' if result.finish_reason=='completed' else 'incomplete',finish_reason=result.finish_reason)
        except TaskTurnEnded:
            answer=final_response(guard.events);save(work/'answer.md',answer)
            reason=finish_reason(guard.events)
            metrics.update(status='completed' if reason=='completed' and answer.strip() else 'incomplete',finish_reason=reason,completion_collector='original_turn_end_event')
        except Exception as e: metrics['error']=str(e)[:1200]
        metrics.update(elapsed_seconds=round(time.monotonic()-started,3),upstream_requests=sum(t==task['id'] for t in attribution.values()),cumulative_requests=state.request_count,cumulative_accounted_usd=state.reserved_usd,video_exists=(work/'out/video.mp4').is_file(),quality='not_independently_reviewed',verified_skips=0)
        metrics['request_ids']=[i for i,t in attribution.items() if t==task['id']]
        metrics['delivery_state']='video_present' if metrics['video_exists'] else 'missing_video'
        if metrics['status']=='completed' and not metrics['video_exists']: metrics['status']='completed_without_delivery'
        ids=subprocess.check_output(['docker','ps','-aq','--filter','label=geneloop.experiment=remotion-motivation-20261027-v1','--filter',f"label=geneloop.task={task['id']}"],text=True).split()
        if ids: subprocess.run(['docker','rm','-f',*ids],capture_output=True,timeout=30)
        save(result_path,metrics);print(json.dumps(metrics,ensure_ascii=False),flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            list(pool.map(run_task,tasks))
        save(BASE/f'request-attribution-{args.batch_id}.json',attribution)
    finally: gate.shutdown();gate.server_close();worker.join(timeout=5)

if __name__=='__main__':main()
