"""Separate toolization, learned bypasses, simple fusion and cold-start costs."""
from __future__ import annotations
import argparse,hashlib,json,math,os
from collections import Counter
from pathlib import Path

BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve();EXP=BASE/'structured-v1'
HERE=Path(__file__).resolve().parent
TOKEN_FIELDS=('prompt_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--primary-trial',default='v1');parser.add_argument('--training-trial',default='v1');parser.add_argument('--tasks',type=Path,default=HERE/'tasks.json');args=parser.parse_args()
    raw=[json.loads(line) for line in (BASE/'cost-ledger.jsonl').read_text().splitlines()]
    model=[r for r in raw if 'request_id' in r];by_id={r['request_id']:r for r in model}
    auxiliary=[r for r in raw if r.get('kind')=='files_api']
    registry=json.loads(args.tasks.read_text());evaluation_tasks=[t for t in registry if t['partition']=='evaluation']
    planned=sum(len(t['arm_order']) for t in evaluation_tasks)
    jobs=[];used=set()
    for path in sorted((EXP/'runs').glob('*/*/*/result.json')):
        run=path.parent;result=json.loads(path.read_text());effective=json.loads((run/'effective.json').read_text())
        task=effective['task'];ids=result['request_ids']
        if used.intersection(ids):raise ValueError('model request attributed to more than one trial')
        used.update(ids);rows=[by_id[rid] for rid in ids if rid in by_id]
        unknown=[rid for rid in ids if rid not in by_id or by_id[rid].get('observed_peak_usd') is None]
        known=sum(r['observed_peak_usd'] for r in rows if r.get('observed_peak_usd') is not None)
        tokens={key:sum(r['response_usage'][key] for r in rows) if len(rows)==len(ids) and all(
            isinstance(r.get('response_usage',{}).get(key),int) for r in rows) else None for key in TOKEN_FIELDS}
        qa=json.loads((run/'qa/verification.json').read_text()) if (run/'qa/verification.json').exists() else {}
        review=json.loads((run/'qa/semantic-review.json').read_text()) if (run/'qa/semantic-review.json').exists() else None
        audio_pass=(qa.get('audio_streams',0)>0 and bool(qa.get('audio_windows')) and
                    all(w['pass'] for w in qa['audio_windows'])) if task['id']=='t36_music_window' or 'audio_windows' in task['qa'] else None
        narrow=(result['status']=='completed' and qa.get('technical_pass') is True and
                qa.get('selected_source_frames_pass') is not False and audio_pass is not False)
        work=run/task['id'];audit=work/'.local/online-motif'/(hashlib.sha256(effective['session_id'].encode()).hexdigest()+'.jsonl')
        decisions=[json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []
        verified=sum(r.get('kind')=='model_request_skipped_verified' for r in decisions)
        if verified!=result['verified_skips']:raise ValueError('actual audit/result verified skip mismatch')
        events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
        calls=[e['data'] for e in events if e.get('type')=='tool/call']
        attempts=[r for r in decisions if r.get('kind')=='motif_bypass_attempt']
        executed_ids={c.get('callId') for c in calls}
        if any(not set(a['call_ids'])<=executed_ids for a in attempts):raise ValueError('synthetic proposal missing actual DSH dispatch')
        item={'task':task['id'],'partition':task['partition'],'arm':effective['arm'],'trial':effective['trial'],
              'status':result['status'],'elapsed_seconds':result['elapsed_seconds'],'model_requests':len(ids),
              'request_ids':ids,'observed_peak_usd':None if unknown else known,'known_cost_lower_bound_usd':known,
              'unknown_usage_requests':unknown,'tokens':tokens,'video_exists':result['video_exists'],
              'technical_pass':qa.get('technical_pass'),'selected_source_frames_pass':qa.get('selected_source_frames_pass'),
              'published_video_matches_current_source':qa.get('published_video_matches_current_source'),
              'audio_windows_pass':audio_pass,'narrow_technical_source_gate':narrow,
              'full_quality':'not_human_blind_reviewed','verified_request_skips':verified,
              'sampled_semantic_review':review,
              'sampled_review_known_failure':bool(review and review.get('observed_failures')),
              'selected_gates_without_known_failure':bool(narrow and review and not review.get('observed_failures')),
              'bypass_attempt_batches':len(attempts),'bypass_failed_batches':sum(r.get('kind')=='bypass_result_unverified' for r in decisions),
              'deferred_reasons':dict(Counter(r.get('reason') for r in decisions if r.get('kind') in ('motif_deferred','motif_gate_deferred'))),
              'selection_bases':dict(Counter(b for a in attempts for b in a.get('selection_bases',[]))),
              'tool_calls':len(calls),'prompt_sha256':effective['prompt_sha256'],'tool_order':effective['tool_order'],
              'video_sha256':qa.get('video_sha256'),'events_sha256':hashlib.sha256((run/'events.jsonl').read_bytes()).hexdigest()}
        jobs.append(item)
    def total(rows):
        return {'jobs':len(rows),'actual_model_sessions':sum(r['model_requests']>0 for r in rows),
                'model_requests':sum(r['model_requests'] for r in rows),
                'completed_with_video':sum(r['status']=='completed' and r['video_exists'] for r in rows),
                'technical_pass':sum(r['technical_pass'] is True for r in rows),
                'narrow_technical_source_gate':sum(r['narrow_technical_source_gate'] for r in rows),
                'sampled_review_done':sum(r['sampled_semantic_review'] is not None for r in rows),
                'sampled_review_known_failure':sum(r['sampled_review_known_failure'] for r in rows),
                'selected_gates_without_known_failure':sum(r['selected_gates_without_known_failure'] for r in rows),
                'verified_request_skips':sum(r['verified_request_skips'] for r in rows),
                'known_cost_lower_bound_usd':sum(r['known_cost_lower_bound_usd'] for r in rows),
                'observed_peak_usd':sum(r['observed_peak_usd'] for r in rows) if all(r['observed_peak_usd'] is not None for r in rows) else None,
                'unknown_usage_requests':[rid for r in rows for rid in r['unknown_usage_requests']],
                'tokens':{key:sum(r['tokens'][key] for r in rows) if all(r['tokens'][key] is not None for r in rows) else None for key in TOKEN_FIELDS}}
    primary=[r for r in jobs if r['trial']==args.primary_trial];training=[r for r in jobs if r['trial']==args.training_trial and r['partition']!='evaluation']
    evaluate=[r for r in primary if r['partition']=='evaluation']
    groups={arm:total([r for r in evaluate if r['arm']==arm]) for arm in ('legacy','typed','execute','fused')}
    pairs=[]
    for task in evaluation_tasks:
        arms={r['arm']:r for r in evaluate if r['task']==task['id']}
        if 'typed' not in arms or 'execute' not in arms:continue
        t,x=arms['typed'],arms['execute']
        if t['prompt_sha256']!=x['prompt_sha256'] or t['tool_order']!=x['tool_order']:
            raise ValueError('paired prompt or tool order changed')
        pairs.append({'task':task['id'],'typed_requests':t['model_requests'],'execute_requests':x['model_requests'],
                      'net_request_difference':t['model_requests']-x['model_requests'],
                      'verified_request_skips':x['verified_request_skips'],
                      'typed_cost_usd':t['observed_peak_usd'],'execute_cost_usd':x['observed_peak_usd'],
                      'marginal_cost_difference_usd':t['observed_peak_usd']-x['observed_peak_usd'] if t['observed_peak_usd'] is not None and x['observed_peak_usd'] is not None else None,
                      'both_narrow_gate':t['narrow_technical_source_gate'] and x['narrow_technical_source_gate']})
    learning=total(training);b=groups['typed']['observed_peak_usd'];x=groups['execute']['observed_peak_usd'];l=learning['observed_peak_usd']
    marginal=b-x if b is not None and x is not None and len(pairs)==len(evaluation_tasks) else None
    closed_prefix=(EXP/'authorization.json')
    auth=json.loads(closed_prefix.read_text());original=(BASE/'cost-ledger.jsonl').read_bytes().splitlines(keepends=True)[:1518]
    if hashlib.sha256(b''.join(original)).hexdigest()!=auth['prior_ledger_prefix_sha256']:raise ValueError('prior cumulative ledger changed')
    request_files={int(p.stem) for p in (BASE/'requests').glob('*.json')}
    unknown_global=sorted(rid for rid in request_files if rid not in by_id or by_id[rid].get('observed_peak_usd') is None)
    attributed=set()
    for file in EXP.glob('request-attribution-'+args.primary_trial+'-*.json'):
        attributed.update(int(k) for k in json.loads(file.read_text()))
    phase_model=[r for r in model if r['request_id'] in attributed]
    phase_aux=[r for r in auxiliary if r.get('experiment_id')=='remotion-structured-reuse-20261028-'+args.primary_trial
               or (args.primary_trial=='v1' and not r.get('experiment_id'))]
    prior_protocol=total([r for r in jobs if r['trial']==args.training_trial and r['trial']!=args.primary_trial and r['partition']=='evaluation'])
    report={'experiment_id':'remotion-structured-reuse-20261028-'+args.primary_trial,'primary_trial':args.primary_trial,
            'registry_sha256':hashlib.sha256(args.tasks.read_bytes()).hexdigest(),'training_trial':args.training_trial,
            'status':'complete' if len(evaluate)==planned else 'running','planned_evaluation_jobs':planned,
            'ended_evaluation_jobs':len(evaluate),'jobs':jobs,'training':learning,'arms':groups,'paired_typed_execute':pairs,
            'all_attempts_included':True,'posthoc_failures_not_removed':True,
            'marginal_observed_cost_saving_usd':marginal,
            'cold_start_saving_if_all_seed_tasks_charged_as_extra_usd':marginal-l if marginal is not None and l is not None else None,
            'prior_protocol_evaluation_experiment':prior_protocol,
            'saving_after_seed_and_prior_protocol_evaluation_cost_usd':marginal-l-prior_protocol['observed_peak_usd'] if marginal is not None and l is not None and prior_protocol['observed_peak_usd'] is not None else None,
            'observational_linear_break_even_tasks':math.ceil(l/(marginal/len(evaluation_tasks))) if marginal is not None and marginal>0 and l is not None else None,
            'break_even_scope':'unstable five-pair extrapolation, not an observed result',
            'global_model_inference_requests':len(model),'global_files_api_http':len(auxiliary),
            'global_model_usage_unknown_or_pending':unknown_global,
            'phase_model_requests_including_failures_and_recoveries':len(phase_model),
            'phase_files_api_http':dict(Counter(str(r.get('method'))+' '+str(r.get('response_status')) for r in phase_aux)),
            'prior_1518_ledger_prefix_preserved':True,'cost_basis':'repository peak estimator; provider bill not reconciled',
            'files_api_cost_basis':'published free Files API; model image tokens included in inference usage; network/CPU not monetized',
            'full_quality':'not_human_blind_reviewed; technical and sampled content gates only',
            'interpretation':'Typed-vs-legacy is toolization. Execute-vs-typed is learned Motif marginal behavior. Fused is the ordinary simpler-tool comparison. Diagnostic receipts never count as actual skips.'}
    out=EXP/('analysis' if args.primary_trial=='v1' else 'analysis-'+args.primary_trial);out.mkdir(exist_ok=True);(out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('jobs','paired_typed_execute')},ensure_ascii=False))

if __name__=='__main__':main()
