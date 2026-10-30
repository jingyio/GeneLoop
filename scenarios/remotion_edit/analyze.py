"""Audit real request boundaries and run GeneLoop's existing offline compiler.

No shell-looking string is promoted to a safe Motif contract. Categories below
are descriptive only and are never reported as verified request savings.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(os.environ.get('GENELOOP_CODE_ROOT',str(Path(__file__).resolve().parents[2]))).resolve();sys.path.insert(0,str(ROOT))
from src.adapters.dsh_trajectory import ToolContract,extract_dsh_trace,mine_dsh_traces
from src.motif_core.offline.library_builder import build_read_motif_library
BASE=Path(os.environ.get('REMOTION_EXPERIMENT_ROOT',str(ROOT/'.local/experiments/remotion-motivation-20261027-v1'))).resolve()
def readlines(path):return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def classify(call):
    name=call.get('name','')
    try:args=json.loads(call.get('arguments','{}')) if isinstance(call.get('arguments'),str) else call.get('arguments',{})
    except ValueError:args={}
    if name.endswith('write_file'):return 'source_or_notes_write'
    if name.endswith(('read_file','list_files')):return 'file_inspection'
    cmd=args.get('command','')
    if 'remotion-cli' in cmd and re.search(r'\b(render|still|compositions)\b',cmd):return 'remotion_render_or_preview'
    if re.search(r'\bsleep\b|render\.log|render\.exit',cmd):return 'polling_or_runtime_diagnosis'
    if re.search(r'\b(ffprobe|ffmpeg)\b',cmd):return 'media_probe_or_validation'
    return 'other_shell'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tasks',type=Path,default=ROOT/'scenarios/remotion_edit/tasks.json');ap.add_argument('--split-file',type=Path);ap.add_argument('--output-dir',type=Path,default=BASE/'analysis');args=ap.parse_args()
    tasks=json.loads(args.tasks.read_text());OUT=args.output_dir;OUT.mkdir(parents=True,exist_ok=True)
    ledgers=readlines(BASE/'cost-ledger.jsonl'); rows_by_id={r['request_id']:r for r in ledgers}
    requests={int(p.stem):json.loads(p.read_text()) for p in (BASE/'requests').glob('*.json')}
    per_task={t['id']:[] for t in tasks};attribution={}
    for rid,v in requests.items():
        body=json.dumps(v,ensure_ascii=False)
        matches=[t['id'] for t in tasks if t['instruction'] in body]
        attribution[rid]=matches[0] if len(matches)==1 else 'unknown'
        if matches:per_task[matches[0]].append(rid)
    # Probe attempt has the same t01 brief but is a separate aborted trial.
    diagnostic_checkpoint=BASE/'diagnostics/attempt-0001/budget-checkpoint.json'
    diagnostic_ids=set(range(1,json.loads(diagnostic_checkpoint.read_text())['request_count']+1)) if diagnostic_checkpoint.exists() else set()
    contracts={
      'mcp__remotion__list_files':ToolContract((),True,('files',),replay_stable=False),
      'mcp__remotion__read_file':ToolContract(('path',),True,('path','sha256','text'),replay_stable=False),
      'mcp__remotion__write_file':ToolContract(('path','text'),False),
      'mcp__remotion__run_command':ToolContract(('command',),False),
    }
    traces=[];summaries=[]
    for task in tasks:
        tid=task['id'];work=BASE/'workspaces'/tid
        event_path=BASE/'events'/tid/'agent-events.jsonl'
        if not event_path.exists():event_path=work/'agent-events.jsonl'
        if not (event_path).exists():continue
        events=readlines(event_path);audit=readlines(BASE/'workspaces'/f'{tid}-tool-audit.jsonl')
        trace=extract_dsh_trace(events,contracts,trace_id=tid,task_fingerprint=hashlib.sha256(task['instruction'].encode()).hexdigest());traces.append(trace)
        ids=sorted(r for r in per_task[tid] if r not in diagnostic_ids)
        ledger=[rows_by_id[r] for r in ids if r in rows_by_id]
        cats=Counter();assistant_rows=[]
        for e in events:
            if e.get('type')!='assistant/message':continue
            data=e.get('data',{});msg=data.get('message',{});content=msg.get('content',[])
            calls=[b for b in content if b.get('type')=='tool-call'];text=''.join(b.get('text','') for b in content if b.get('type')=='text')
            labels=[classify(c) for c in calls];cats.update(labels)
            assistant_rows.append({'step':data.get('step'),'has_assistant_text':bool(text.strip()),'tools':labels,'text_excerpt':text[:200],'usage':data.get('usage'), 'strict_tools_only':bool(calls) and not text.strip()})
        metrics=json.loads((BASE/'results'/f'{tid}.json').read_text()) if (BASE/'results'/f'{tid}.json').exists() else {}
        item={'task':tid,'result':metrics,'request_ids':ids,'upstream_requests':len(ids),'settled_ledger_rows':len(ledger),
          'observed_cost_usd':sum(r['observed_peak_usd'] for r in ledger if r.get('observed_peak_usd') is not None),
          'unknown_usage_requests':[r['request_id'] for r in ledger if r.get('observed_peak_usd') is None],
          'tokens':{k:sum((r.get('response_usage') or {}).get(k,0) or 0 for r in ledger) for k in ('prompt_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens')},
          'tool_calls':len(trace.records),'tool_categories':dict(cats),'eligible_read_records':sum(r.eligible for r in trace.records),'barriers':dict(Counter(r.reason for r in trace.records if not r.eligible)),
          'tools_only_response_count':sum(r['strict_tools_only'] for r in assistant_rows),
          'nonzero_command_exits':sum(a.get('result',{}).get('exit_code',0)!=0 for a in audit),
          'events_sha256':sha(event_path),'source_sha256':sha(work/'src/index.tsx') if (work/'src/index.tsx').exists() else None,
          'video_sha256':sha(work/'out/video.mp4') if (work/'out/video.mp4').exists() else None,
          'verified_skips':0,'quality':'not_blind_reviewed'}
        summaries.append(item)
        OUT.mkdir(exist_ok=True)
        (OUT/f'{tid}-request-boundaries.json').write_text(json.dumps(assistant_rows,ensure_ascii=False,indent=2))
    # Frozen split: tasks 1-4 train; 5-6 certify; 7-10 remain unseen evaluation.
    qualified={s['task'] for s in summaries if s['result'].get('finish_reason')=='completed' and s['result'].get('video_exists')}
    split=json.loads(args.split_file.read_text()) if args.split_file else {'train':[t['id'] for t in tasks[:4]],'certification':[t['id'] for t in tasks[4:6]]}
    train_ids=set(split['train']);cert_ids=set(split['certification'])
    train=[r for r in traces if r.trace_id in train_ids and r.trace_id in qualified]
    cert=[r for r in traces if r.trace_id in cert_ids and r.trace_id in qualified]
    compiler={'excluded_failed_training_tasks':sorted(train_ids-qualified),'status':'waiting_for_frozen_split','training':[r.trace_id for r in train],'certification':[r.trace_id for r in cert]}
    if len(train)>=2 and len(cert)>=1:
        library=build_read_motif_library(train,cert,contracts)
        (OUT/'library.json').write_text(json.dumps(library,ensure_ascii=False,indent=2))
        compiler.update(status='compiled',candidates=len(mine_dsh_traces(train)),certified_artifacts=len(library['artifacts']),rejected=library['rejected'],library_digest=library['library_digest'])
    settled=[r for r in ledgers if r.get('observed_peak_usd') is not None]
    total={'experiment_id':'remotion-motivation-20261027-v1','tasks':summaries,'compiler':compiler,
      'all_real_requests_including_failed_probe':len(requests),'task_registry_sha256':sha(args.tasks),'registry_task_count':len(tasks),'ledger_rows':len(ledgers),
      'observed_cost_usd_including_failed_probe':sum(r['observed_peak_usd'] for r in settled),
      'diagnostic_probe_requests':len(diagnostic_ids),'diagnostic_probe_cost_usd':sum(r.get('observed_peak_usd') or 0 for r in ledgers if r['request_id'] in diagnostic_ids),
      'unknown_or_pending_request_ids':sorted(set(requests)-set(r['request_id'] for r in settled)),
      'cost_basis':'repository peak-price estimator; provider bill not reconciled','actual_verified_model_request_skips':0,
      'interpretation':'Descriptive categories are not certified savings. Generic shell and source writes are barriers. No online Remotion library has been admitted.'}
    (OUT/'summary.json').write_text(json.dumps(total,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in total.items() if k!='tasks'},ensure_ascii=False))
if __name__=='__main__':main()
