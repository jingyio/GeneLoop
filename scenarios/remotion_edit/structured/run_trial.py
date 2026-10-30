"""Experimental batch control using the existing DSH SDK and cumulative gate.

There is no new Agent loop here. All semantic/model decisions and tool dispatch
remain DSH-owned, including certified synthetic calls from the shared plugin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.adapters.harness_runtime import create_harness
from src.adapters.scenario import prepare_scenario
from src.adapters.deepseek_cost_gate import State, create_server
from src.adapters.native_budget import NativeBudgetGuard
from deepseek_harness.api import final_response, finish_reason

HERE = Path(__file__).resolve().parent
BASE = Path(os.environ.get('REMOTION_EXPERIMENT_ROOT', str(ROOT / '.local/experiments/remotion-motivation-20261027-v1'))).resolve()
EXP = BASE / 'structured-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
    path.chmod(0o600)


class TaskTurnEnded(Exception):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['learn', 'evaluate'], required=True)
    parser.add_argument('--tasks', type=Path, default=HERE / 'tasks.json')
    parser.add_argument('--task')
    parser.add_argument('--arm', choices=['legacy', 'typed', 'execute', 'fused', 'program'])
    parser.add_argument('--program-library', type=Path)
    parser.add_argument('--catalog-format', choices=['full','example'], default='example')
    parser.add_argument('--representation', choices=['program_catalog','typed_tools'], default='program_catalog')
    parser.add_argument('--form-store', type=Path)
    parser.add_argument('--form-owner')
    parser.add_argument('--form-file', type=Path)
    parser.add_argument('--tool-naming', choices=['opaque','description'], default='opaque')
    parser.add_argument('--parameter-binding', choices=['full','defaults'], default='full')
    parser.add_argument('--program-evidence', choices=['interface','source'], default='interface')
    parser.add_argument('--form-instruction-scope', choices=['program','both'], default='program')
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--trial', default='v1')
    parser.add_argument('--call-model', action='store_true')
    args = parser.parse_args()
    form_snapshot = None
    selected_form = None
    if args.form_store:
        if args.program_library or not args.form_owner or args.form_file:
            parser.error('form-store needs owner and resolves the program library itself')
        request = {'operation':'resolve_form','store':str(args.form_store.resolve()),'owner':args.form_owner}
        loaded = subprocess.run(['node','--experimental-strip-types',str(ROOT/'scripts/materialize-source-program.mjs')],
            input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=ROOT)
        if loaded.returncode:raise ValueError('published form unavailable: '+loaded.stderr[-1000:])
        form_snapshot=json.loads(loaded.stdout)
        args.program_library=Path(form_snapshot['library_path'])
        args.representation=form_snapshot['policy']['form']['representation']
        args.catalog_format=form_snapshot['policy']['form']['catalog_format']
        selected_form=form_snapshot['policy']['form']
    elif args.form_file:
        if not args.program_library:parser.error('candidate form needs its frozen program library')
        from src.adapters.reuse_form_rsi import validate_form
        form_snapshot=json.loads(args.form_file.read_text())
        selected_form=validate_form(form_snapshot.get('form',form_snapshot))
        args.representation=selected_form['representation'];args.catalog_format=selected_form['catalog_format']
    if selected_form:args.tool_naming=selected_form.get('tool_naming','opaque')
    if selected_form:args.parameter_binding=selected_form.get('parameter_binding','full')
    if selected_form:args.program_evidence=selected_form.get('program_evidence','interface')
    library_scope=selected_form.get('library_scope','all') if selected_form else 'all'
    experiment = args.output_root.resolve() if args.output_root else EXP
    if args.arm == 'program' and not args.program_library:
        parser.error('program arm requires a frozen source-program library')
    if not args.trial.replace('-', '').isalnum():
        parser.error('bounded trial identity required')
    tasks = json.loads(args.tasks.read_text())
    experiment_id = 'remotion-structured-reuse-20261028-' + args.trial
    assets = {r['name']: r for r in json.loads((BASE / 'asset-manifest-v2.json').read_text())}
    for task in tasks:
        for name in task['assets']:
            if hashlib.sha256((BASE / 'assets' / name).read_bytes()).hexdigest() != assets[name]['sha256']:
                raise ValueError('frozen task source changed')
    jobs = [(t, arm) for t in tasks
            if (t['partition'] != 'evaluation') == (args.phase == 'learn')
            and (not args.task or args.task == t['id'])
            for arm in (['typed'] if args.phase == 'learn' else t['arm_order'])
            if not args.arm or arm == args.arm]
    if not jobs:
        parser.error('no selected jobs')
    image = os.environ['REMOTION_IMAGE']
    if args.call_model and not os.environ.get('DEEPSEEK_API_KEY'):
        raise ValueError('private model credential required')
    checkpoint = BASE / 'budget-checkpoint.json'
    if not checkpoint.exists():
        raise ValueError('existing cumulative ledger required; never start a fresh budget')
    attribution_path = experiment / ('request-attribution-' + args.trial + '-' + args.phase + '.json')
    attribution = {int(k): v for k, v in json.loads(attribution_path.read_text()).items()} if attribution_path.exists() else {}
    current_job = None

    class AuditedState(State):
        def log(self, row):
            # Files API transfers have no inference request_id. Keep them in
            # the ledger, with collection context rather than inventing a
            # billed model request or claiming exact late-transfer ownership.
            context = attribution.get(row.get('request_id'), current_job)
            super().log({**row, 'collection_active_job': context,
                         'record_utc_epoch': time.time(),
                         'experiment_id': experiment_id})

        def book(self, body):
            booked = super().book(body)
            if booked:
                save(BASE / 'requests' / f'{booked[0]:06d}.json', json.loads(body))
                attribution[booked[0]] = current_job
                save(attribution_path, attribution)
            return booked

    state = AuditedState(cap_usd=None, output_cap=6000, record=BASE / 'cost-ledger.jsonl',
                         request_limit=None, checkpoint=checkpoint)
    gate = create_server('127.0.0.1', 0, 'https://api.deepseek.com', state)
    worker = threading.Thread(target=gate.serve_forever, daemon=True)
    worker.start()
    try:
        for task, arm in jobs:
            run = experiment / 'runs' / args.trial / arm / task['id']
            if (run / 'result.json').exists():
                continue
            work = run / task['id']
            work.mkdir(parents=True, exist_ok=True)
            for name in ('src', 'out', 'public'):
                (work / name).mkdir(exist_ok=True)
            for name in task['assets']:
                target = work / 'public' / name
                if not target.exists():
                    target.write_bytes((BASE / 'assets' / name).read_bytes())
                if hashlib.sha256(target.read_bytes()).hexdigest() != assets[name]['sha256']:
                    raise ValueError('existing task copy differs from frozen source')
            if not (work / 'node_modules').is_symlink():
                (work / 'node_modules').symlink_to('/runtime/node_modules')
            source = work / 'src/index.tsx'
            if not source.exists():
                save(source, "import React from 'react';import {registerRoot,Composition,AbsoluteFill} from 'remotion';\n"
                     "const Edit=()=> <AbsoluteFill style={{backgroundColor:'#102235',color:'white'}}>EDIT ME</AbsoluteFill>;\n"
                     f"registerRoot(()=> <Composition id='Main' component={{Edit}} durationInFrames={{{task['frames']}}} fps={{{task['fps']}}} width={{{task['width']}}} height={{{task['height']}}}/>);\n")
            save(work / 'package.json', {'private': True, 'name': 'remotion-structured-task'})
            if args.program_library:
                if arm not in ('fused','program'):
                    raise ValueError('source-program comparison uses matched fused/program arms')
                tools = ['list_assets','probe_asset','read_source','write_source','render_composition',
                         'inspect_render','write_notes','list_programs','render_source','render_program']
                if arm=='fused' or args.representation=='typed_tools':
                    tools=[name for name in tools if name not in ('list_programs','render_program')]
                server_path = HERE / 'program_server.py'
                guide = ('使用普通probe_asset读取当前素材属性。render_source(text)可一次写入完整TSX并渲染，'
                         '两臂都有此普通工具。inspect_render返回实际像素，请检查成片。'
                         '优先考虑本任务可用的已学程序或工具，适用时复用并绑定当前任务参数；'
                         '程序不适用时直接编写源码，不要强行复用。write_notes保存简短说明。')
                if selected_form and (arm=='program' or args.form_instruction_scope=='both'):
                    guide+='\n'+selected_form.get('agent_instruction','')
                if args.parameter_binding=='defaults' and arm=='program':
                    guide+='\n已学程序采用参数覆盖：只需传当前任务需要改变的顶层字段，其余沿用冻结接口示例默认值；数组/对象字段整项替换。请自行核对默认值是否符合当前任务。'
                if args.program_evidence=='source' and arm=='program':
                    guide+='\n已学实现源码是实际可执行能力的证据；描述和默认值仅概括历史示例。请按真实实现和schema判断可表达性，尤其数组、循环、可选字段，不把示例数值或描述中的次数当作未声明的限制。'
                if arm=='fused':guide+='\n本次普通工具基线未加载学习程序，使用当前编辑工具完成任务。'
                if arm=='program' and args.representation=='typed_tools':
                    guide+='\n可用学习程序已直接列为具体工具，工具定义包含完整参数schema和默认示例；据此绑定当前参数并直接调用。'
            elif arm == 'legacy':
                tools = ['list_files', 'read_file', 'write_file', 'run_command']
                server_path = HERE.parent / 'server.py'
                guide = ('源在public/，使用现有文件/命令工具实际探测、写src/index.tsx并渲染out/video.mp4。'
                         'CLI: node /runtime/node_modules/@remotion/cli/remotion-cli.js render src/index.tsx Main out/video.mp4 '
                         '--browser-executable=/usr/bin/chromium-headless-shell --concurrency=2 --log=error。'
                         'ffprobe/完整ffmpeg在PATH；命令timeout_seconds为1–240。')
            else:
                tools = ['list_assets', *(['probe_asset'] if arm == 'fused' else ['pin_asset', 'probe_media']),
                         'read_source', 'write_source', 'render_composition', 'inspect_render', 'write_notes']
                server_path = HERE / 'server.py'
                guide = ('使用结构化工具核对实际素材属性，单文件编写src/index.tsx。write_source返回源码摘要，'
                         'render_composition需绑定当前摘要，它只做固定CLI渲染和独立解码检查，不替你选择剪辑或写代码。'
                         'inspect_render按输出秒数返回真实图片附件，请看实际像素而非只看成功回执。'
                         '可修改源码重渲染，保留失败；write_notes保存说明。')
            brief = (f"你是视频剪辑Agent，使用Remotion4.0.539/React19完成真实成片。任务：{task['instruction']}\n"
                     f"输出{task['width']}x{task['height']}、{task['fps']}fps、精确{task['frames']}帧。"
                     '先核对实际素材属性和源时点，再自主完成剪辑、渲染和检查。禁止只写计划或编造成功。'
                     '素材来自公开影片派生夹具，不代表独立客户项目。不要安装依赖或访问网络。'
                     '模型负责镜头/代码/质量决定，不需要重复询问本隔离任务的许可。\n'
                     'OffthreadVideo的trimBefore/startFrom按合成fps换算秒数，Sequence.from是输出时间轴，不能代替源裁剪。'
                     '禁CSS动画/定时器。可用remotion的Freeze做冻结；不要反复诊断无关浏览器内部行为。\n'
                     + guide + '\n准确工具名前缀均为mcp__remotion__。完成后保留out/video.mp4和简短剪辑说明。')
            protocol = task.get('prompt_protocol', 'baseline-v1')
            if protocol == 'semantic-timing-v2':
                brief += ('\n语义交接自检：素材读取或渲染回执不代表剪辑计划已经完成。写源码前，'
                          '先在本次回复中用简短表格核对每段的文件、source_start_seconds、output_start_seconds、'
                          'duration_seconds和Composition fps；随后可在同一回复调用写源码工具，无需额外等待。'
                          '源起点、输出起点和时长必须分开命名，不能用duration_seconds当作源起点。'
                          'trimBefore=source_start_seconds×Composition fps，不乘源fps；OffthreadVideo没有fps属性，'
                          '不要给它传fps，也不要为了对齐编码帧率改变播放速度。最终用实际帧检查源时点。')
            elif protocol != 'baseline-v1':
                raise ValueError('unknown frozen prompt protocol')
            program_digest = None
            learned_tools = []
            visible_program_ids = []
            if args.program_library and arm == 'program':
                library = json.loads(args.program_library.read_text())
                if library.get('digest') != digest({k:v for k,v in library.items() if k!='digest'}):
                    raise ValueError('frozen source-program library changed')
                program_digest = library['digest']
                programs=library['programs']
                if library_scope!='all':
                    request={'operation':'catalog','library':str(args.program_library.resolve()),
                             'library_scope':library_scope,'intent':task['instruction']}
                    selected=subprocess.run(['node','--experimental-strip-types',str(ROOT/'scripts/materialize-source-program.mjs')],
                        input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=ROOT)
                    if selected.returncode:raise ValueError('program retrieval failed: '+selected.stderr[-1500:])
                    ids={p['id'] for p in json.loads(selected.stdout)['programs']}
                    programs=[p for p in programs if p['id'] in ids]
                visible_program_ids=[p['id'] for p in programs]
                fields = ('id','description','parameters_schema','default_parameters') if args.catalog_format=='full' else ('id','description','default_parameters')
                catalog = [{k:p[k] for k in fields} for p in programs]
                if args.program_evidence=='source':
                    for item,program in zip(catalog,programs):item.update(language=program['language'],template=program['template'])
                if args.representation=='program_catalog':
                    brief += '\n本任务冻结的学习程序目录（选择及参数含义由当前任务决定，历史默认值仅是接口示例）：\n'+json.dumps(catalog,ensure_ascii=False)
                else:
                    from src.adapters.source_program_mcp import learned_tool_name
                    learned_tools=[learned_tool_name(p,args.tool_naming) for p in programs]
                    tools.extend(learned_tools)
            save(work / 'brief.md', brief)
            bound_assets = {name: assets[name]['sha256'] for name in task['assets']}
            server_env = {'REMOTION_WORK': str(work), 'REMOTION_RUNTIME': str(BASE / 'runtime'),
                          'REMOTION_IMAGE': image, 'REMOTION_MEDIA_TOOLS': str(BASE / 'qa-runtime'),
                          'REMOTION_TASK_ASSETS': json.dumps(bound_assets), 'REMOTION_TASK_NONCE': uuid4().hex,
                          'REMOTION_FUSED_PROBE': '1' if arm in ('fused','program') else '0'}
            if args.program_library and arm == 'program':
                server_env['REMOTION_SOURCE_LIBRARY'] = str(args.program_library.resolve())
                server_env['REMOTION_LIBRARY_SCOPE'] = library_scope
                server_env['REMOTION_PROGRAM_INTENT'] = task['instruction']
            if args.program_library:
                server_env['REMOTION_PROGRAM_INTERFACE'] = args.representation
                server_env['REMOTION_PROGRAM_TOOL_NAMING'] = args.tool_naming
                server_env['REMOTION_PARAMETER_BINDING'] = args.parameter_binding
                server_env['REMOTION_PROGRAM_EVIDENCE'] = args.program_evidence
            config = {'schema_version': 1, 'name': 'remotion_structured', 'prompt': str(work / 'brief.md'),
                      'servers': [{'server_name': 'remotion', 'transport': 'stdio', 'command': sys.executable,
                                   'args': [str(server_path)], 'cwd': str(ROOT), 'env': server_env,
                                   'tool_call_timeout_ms': 300000}],
                      'allowed_tools': ['mcp__remotion__' + t for t in tools]}
            save(run / 'scenario.json', config)
            prepared = prepare_scenario(run / 'scenario.json')
            session = 'remotion-structured-' + uuid4().hex
            patches = [prepared['patch']]
            env = {'SSS_SCENARIO_TOOLS': json.dumps(prepared['allowed_tools']),
                   'DEEPSEEK_API_KEY': os.environ.get('DEEPSEEK_API_KEY', ''),
                   'DEEPSEEK_BASE_URL': f'http://127.0.0.1:{gate.server_port}/v1',
                   'SSS_BUDGET_GATE_ACTIVE': '1', 'SSS_BUDGET_CAP_USD': '0',
                   'SSS_BUDGET_LEDGER': str(BASE / 'cost-ledger.jsonl')}
            manifest_digest = None
            if arm == 'execute':
                manifest_path = EXP / 'library/online-manifest.json'
                manifest = json.loads(manifest_path.read_text())
                manifest_digest = manifest['manifest_digest']
                structured = {'schema_version': 1, 'task_id': task['id'], 'session_id': session,
                              'intent': task['instruction'], 'input_version': digest([task, bound_assets]),
                              'bindings': {}, 'source_versions': {
                                  'mcp__remotion__pin_asset': list(bound_assets.values()),
                                  'mcp__remotion__probe_media': list(bound_assets.values())}}
                save(run / 'structured-task.json', structured)
                patch = EXP / 'config/closed-read.patch.yml'
                save(patch, '- insert:\n    - id: remotion-certified-source-dereference\n      name: '
                     + json.dumps((HERE / 'plugin.ts').as_uri()) + '\n')
                patches.append(str(patch))
                env.update(SSS_ONLINE_MOTIF_MANIFEST=str(manifest_path),
                           SSS_ONLINE_MOTIF_TASK=str(run / 'structured-task.json'),
                           SSS_ONLINE_MOTIF_MODE='execute',
                           SSS_ONLINE_MOTIF_PROMPT_SHA256=prepared['prompt_sha256'],
                           SSS_REMOTION_IMAGE=image)
            snapshot = {'experiment_id': experiment_id, 'trial': args.trial,
                        'arm': arm, 'task': task, 'session_id': session, 'prompt_sha256': prepared['prompt_sha256'],
                        'model': 'deepseek-flash', 'reasoning_effort': 'off', 'max_output': 6000,
                        'cap_usd': None, 'budget_policy': 'uncapped_user_authorized', 'reset_history': False,
                        'max_requests': None, 'max_task_wall_seconds': 900, 'image': image,
                        'mode': 'execute' if arm == 'execute' else 'baseline', 'manifest_digest': manifest_digest,
                        'embedding_policy': 'disabled_fail_closed_source_dereference_only',
                        'tool_order': prepared['allowed_tools'], 'assets': bound_assets,
                        'tasks_sha256': hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
                        'task_registry': args.tasks.name, 'prompt_protocol': protocol,
                        'source_program_library_digest': program_digest,
                        'same_render_source_tool_in_both_arms': bool(args.program_library),
                        'program_catalog_format': args.catalog_format if args.program_library else None,
                        'source_program_representation': args.representation if args.program_library else None,
                        'learned_program_tools': ['mcp__remotion__'+name for name in learned_tools],
                        'program_interface_tools': ['mcp__remotion__'+name for name in ['list_programs','render_program',*learned_tools]
                            if 'mcp__remotion__'+name in prepared['allowed_tools']] if arm=='program' else [],
                        'source_form_policy_digest': form_snapshot['policy']['digest'] if form_snapshot and 'policy' in form_snapshot else None,
                        'source_form_proposal_digest': (form_snapshot['policy']['proposal_digest'] if 'policy' in form_snapshot else form_snapshot.get('digest')) if form_snapshot else None,
                        'source_program_tool_naming': args.tool_naming,
                        'source_program_parameter_binding': args.parameter_binding,
                        'source_program_evidence': args.program_evidence,
                        'source_program_library_scope':library_scope,
                        'source_program_visible_ids':visible_program_ids,
                        'form_treatment_scope': args.form_instruction_scope,
                        'initial_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'core_baseline': 'ec72908755ea6df1771ec962b40e3b27be381ebb',
                        'experiment_export_base': '782c4b6388f129e72609ca8bc878cf3cc8edf5cd',
                        'experiment_code': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in [Path(__file__), HERE / 'server.py', HERE / 'plugin.ts', HERE.parent / 'server.py']}}
            if args.program_library:
                for path in [HERE/'program_server.py',ROOT/'src/adapters/source_program_runtime.ts',ROOT/'src/adapters/source_program_mcp.py',ROOT/'scripts/materialize-source-program.mjs']:
                    snapshot['experiment_code'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
            save(run / 'effective.json', snapshot)
            if form_snapshot:
                save(run/'form-snapshot.json',form_snapshot)
            if not args.call_model:
                print(json.dumps({'preview': str(run), 'arm': arm, 'task': task['id'], 'paid_api_called': False}), flush=True)
                continue
            current_job = '/'.join([args.trial, arm, task['id']])
            guard = NativeBudgetGuard(max_model_requests=None, max_observed_input_tokens=None)
            started = time.monotonic()

            def observe(notification):
                if notification.method == 'session.event':
                    event = notification.payload.get('event')
                    if isinstance(event, dict):
                        with (run / 'events.jsonl').open('a') as stream:
                            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                guard.on_notification(notification)
                if (notification.method == 'session.event' and notification.payload.get('sessionId') == session
                        and notification.payload.get('event', {}).get('type') == 'turn/end'):
                    raise TaskTurnEnded()
                if time.monotonic() - started > 900:
                    raise TimeoutError('900s experiment checkpoint; failed trial and spend retained')

            metrics = {'status': 'failed', 'job': current_job}
            print(json.dumps({'start': current_job, 'prior_requests': state.request_count}), flush=True)
            try:
                with create_harness(root=ROOT, patches=tuple(patches), env=env, provider='deepseek-official',
                                    model='deepseek-flash', max_tokens=6000, cwd=str(work),
                                    runtime_cwd=str(work), request_timeout_seconds=1800) as harness:
                    result = harness.run(brief, session_id=session, on_notification=observe)
                metrics.update(status='completed' if result.finish_reason == 'completed' else 'incomplete',
                               finish_reason=result.finish_reason)
                save(work / 'answer.md', result.final_response)
            except TaskTurnEnded:
                metrics.update(status='completed' if finish_reason(guard.events) == 'completed' else 'failed',
                               finish_reason=finish_reason(guard.events), completion_collector='original_turn_end_event')
                save(work / 'answer.md', final_response(guard.events))
            except Exception as error:
                metrics['error'] = str(error)[:1500]
            request_ids = [rid for rid, job in attribution.items() if job == current_job]
            audit = work / '.local/online-motif' / (hashlib.sha256(session.encode()).hexdigest() + '.jsonl')
            decisions = [json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []
            metrics.update(request_ids=request_ids, upstream_requests=len(request_ids),
                           elapsed_seconds=round(time.monotonic() - started, 3),
                           video_exists=(work / 'out/video.mp4').is_file(),
                           verified_skips=sum(r.get('kind') == 'model_request_skipped_verified' for r in decisions),
                           quality='not_independently_reviewed', cumulative_requests=state.request_count,
                           cumulative_accounted_usd=state.reserved_usd)
            if metrics['status'] == 'completed' and not metrics['video_exists']:
                metrics['status'] = 'completed_without_delivery'
            containers = subprocess.check_output(['docker', 'ps', '-aq', '--filter',
                'label=geneloop.experiment=remotion-motivation-20261027-v1', '--filter',
                'label=geneloop.task=' + task['id']], text=True).split()
            if containers:
                subprocess.run(['docker', 'rm', '-f', *containers], capture_output=True, timeout=30)
            save(run / 'result.json', metrics)
            save(attribution_path, attribution)
            print(json.dumps(metrics, ensure_ascii=False), flush=True)
    finally:
        gate.shutdown()
        gate.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    main()
