"""Account for every attempted paired run, learning call and observed program use."""
from __future__ import annotations
import argparse,hashlib,json,os
from pathlib import Path

TOKEN_FIELDS=('prompt_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens')


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def measurement(base,experiment,registry,trial,baseline_trial=None):
    from scenarios.remotion_edit.structured.review_program_runs import visual_review_status
    from src.adapters.script_motif_compiler import digest
    ledger=[json.loads(s) for s in (base/'cost-ledger.jsonl').read_text().splitlines()]
    provider={r['request_id']:r for r in ledger if 'request_id' in r}
    auth=read(experiment/'authorized-experiment.json')
    prefix=(base/'cost-ledger.jsonl').read_bytes()[:auth['initial_ledger_bytes']]
    if hashlib.sha256(prefix).hexdigest()!=auth['initial_ledger_sha256']:
        raise ValueError('old_cumulative_ledger_changed')
    used=set();runs=[];forms={}
    def amounts(ids):
        rows=[provider.get(rid,{}) for rid in ids]
        unknown=[rid for rid,row in zip(ids,rows) if row.get('observed_peak_usd') is None]
        return {'model_requests':len(ids),'request_ids':ids,'unknown_request_ids':unknown,
            'observed_peak_usd':None if unknown else sum(row['observed_peak_usd'] for row in rows),
            'known_observed_peak_usd':sum(row['observed_peak_usd'] for row in rows if row.get('observed_peak_usd') is not None),
            'known_usage_requests':sum(all(isinstance(row.get('response_usage',{}).get(k),int) for k in TOKEN_FIELDS) for row in rows),
            'known_tokens':{k:sum(row['response_usage'][k] for row in rows if all(isinstance(row.get('response_usage',{}).get(f),int) for f in TOKEN_FIELDS)) for k in TOKEN_FIELDS},
            'accounted_upper_bound_usd':sum(row['observed_peak_usd'] if row.get('observed_peak_usd') is not None else row['reserved_upper_usd'] for row in rows) if all(row.get('observed_peak_usd') is not None or row.get('reserved_upper_usd') is not None for row in rows) else None,
            'tokens':{key:sum(row['response_usage'][key] for row in rows) if all(isinstance(row.get('response_usage',{}).get(key),int) for row in rows) else None for key in TOKEN_FIELDS}}
    paths=list((experiment/'runs'/trial).glob('*/*/result.json'))
    if baseline_trial:
        if any(p.parent.parent.name=='fused' for p in paths):raise ValueError('duplicate_native_baseline')
        paths+=list((experiment/'runs'/baseline_trial/'fused').glob('*/result.json'))
    for path in sorted(paths):
        run=path.parent;result=read(path);effective=read(run/'effective.json');ids=result['request_ids']
        if (run/'form-snapshot.json').exists():
            snapshot=read(run/'form-snapshot.json');record=snapshot.get('policy',snapshot)
            forms[record['digest']]=record['form']
        if used.intersection(ids):raise ValueError('duplicate_request_attribution')
        used.update(ids)
        qa=read(run/'qa/verification.json') if (run/'qa/verification.json').exists() else {}
        review=read(run/'qa/semantic-review.json') if (run/'qa/semantic-review.json').exists() else None
        review_status=visual_review_status(review,run,effective['task'],qa) if review else 'unknown'
        audio=qa.get('audio_windows',[])
        narrow=bool(result['status']=='completed' and result['video_exists'] and qa.get('technical_pass') is True
            and qa.get('selected_source_frames_pass') is True and qa.get('published_video_matches_current_source') is True
            and all(w['pass'] for w in audio))
        audit=run/'source-program-audit.jsonl'
        entries=[json.loads(s) for s in audit.read_text().splitlines()] if audit.exists() else []
        rendered=[r for r in entries if r['kind']=='source_program_rendered' and r['source_current']]
        events=run/'events.jsonl'
        calls=[r['data'] for r in map(json.loads,events.read_text().splitlines()) if r.get('type')=='tool/call'] if events.exists() else []
        runs.append({'task':effective['task']['id'],'arm':effective['arm'],'trial':effective.get('trial',trial),'run':str(run),
            'status':result['status'],'video_exists':result['video_exists'],'wall_seconds':result['elapsed_seconds'],
            'task_sha256':digest(effective['task']),'artifact_sha256':qa.get('video_sha256'),
            'quality_status':review_status,'quality_sha256':sha(run/'qa/semantic-review.json') if review else None,
            'narrow_quality_pass':narrow,'review':review,'reviewed_quality_pass':narrow and review_status=='passed',
            'source_program_renders':len(rendered),'final_video_from_program':any(r['render']['video_sha256']==qa.get('video_sha256') for r in rendered),
            'tool_calls':len(calls),'source_write_calls':sum(r['name'].endswith(('write_source','render_source')) for r in calls),
            'tool_order':effective['tool_order'],'prompt_sha256':effective['prompt_sha256'],
            'learned_program_tools':effective.get('learned_program_tools',[]),
            'program_interface_tools':effective.get('program_interface_tools',effective.get('learned_program_tools',[])),
            'representation':effective.get('source_program_representation','program_catalog'),
            'library_scope':effective.get('source_program_library_scope','all'),
            'visible_program_ids':effective.get('source_program_visible_ids'),
            'form_proposal_digest':effective.get('source_form_proposal_digest'),
            'form_policy_digest':effective.get('source_form_policy_digest'),
            'library_digest':effective.get('source_program_library_digest'),'events_sha256':sha(events) if events.exists() else None,
            'verification_sha256':sha(run/'qa/verification.json') if qa else None,**amounts(ids)})
    tasks=read(registry);expected={(t['id'],arm) for t in tasks for arm in t['arm_order']}
    observed={(r['task'],r['arm']) for r in runs}
    if not observed<=expected:raise ValueError('unplanned_evaluation_run')
    pairs=[]
    for task in tasks:
        pair={r['arm']:r for r in runs if r['task']==task['id']}
        if len(pair)!=2:continue
        native,candidate=pair['fused'],pair['program']
        native_common=[t for t in native['tool_order'] if t not in native['program_interface_tools']]
        candidate_common=[t for t in candidate['tool_order'] if t not in candidate['program_interface_tools']]
        if native_common!=candidate_common:raise ValueError('paired_native_tool_order_changed')
        pairs.append({'task':task['id'],'native_requests':native['model_requests'],'program_requests':candidate['model_requests'],
            'native_cost_usd':native['observed_peak_usd'],'program_cost_usd':candidate['observed_peak_usd'],
            'both_narrow_quality_pass':native['narrow_quality_pass'] and candidate['narrow_quality_pass'],
            'both_reviewed_quality_pass':native['reviewed_quality_pass'] and candidate['reviewed_quality_pass']})
    def total(rows):
        return {'runs':len(rows),'narrow_quality_pass':sum(r['narrow_quality_pass'] for r in rows),
            'reviewed_quality_pass':sum(r['reviewed_quality_pass'] for r in rows),
            'source_program_renders':sum(r['source_program_renders'] for r in rows),
            'final_videos_from_program':sum(r['final_video_from_program'] for r in rows),
            **amounts([rid for r in rows for rid in r['request_ids']])}
    groups={arm:total([r for r in runs if r['arm']==arm]) for arm in ('fused','program')}
    learning_ids=sorted({rid for p in experiment.glob('learning-*/learning-summary.json') for rid in read(p)['request_ids']})
    learning=amounts(learning_ids)
    prior_ids=sorted({rid for path in (experiment/'runs').glob('*/*/*/result.json')
                      if path.parent.parent.parent.name!=trial for rid in read(path)['request_ids']}-used)
    prior=amounts(prior_ids)
    initial=auth['initial_checkpoint']['request_count'] if 'initial_checkpoint' in auth else 0
    checkpoint=read(base/'budget-checkpoint.json') if (base/'budget-checkpoint.json').exists() else {'request_count':max(provider,default=0)}
    study_ids=list(range(initial+1,checkpoint['request_count']+1))
    overhead=amounts(sorted(set(study_ids)-used-set(prior_ids)))
    native,candidate=groups['fused']['observed_peak_usd'],groups['program']['observed_peak_usd']
    complete=observed==expected
    gain=native-candidate if complete and native is not None and candidate is not None else None
    return {'format':'reuse_form_measurements_v1','trial':trial,'complete':complete,'expected_runs':len(expected),
        'baseline_trial':baseline_trial,'baseline_reused_for_comparison':baseline_trial is not None,
        'evaluated_forms':forms,
        'runs':runs,'arms':groups,'pairs':pairs,'learning':learning,'old_ledger_preserved':True,
        'previous_exploration':prior,'learning_review_and_meta_overhead':overhead,'all_new_study_requests':amounts(study_ids),
        'registry_sha256':sha(registry),'evaluator_sha256':sha(Path(__file__)),
        'gross_model_cost_saving_usd':gain,'gross_model_cost_reduction':gain/native if gain is not None and native else None,
        'saving_after_all_learning_usd':gain-learning['observed_peak_usd'] if gain is not None and learning['observed_peak_usd'] is not None else None,
        'saving_after_all_new_exploration_and_overhead_usd':gain-prior['observed_peak_usd']-overhead['observed_peak_usd'] if gain is not None and prior['observed_peak_usd'] is not None and overhead['observed_peak_usd'] is not None else None,
        'conservative_cold_study_net_lower_bound_usd':gain-prior['accounted_upper_bound_usd']-overhead['accounted_upper_bound_usd'] if gain is not None and prior['accounted_upper_bound_usd'] is not None and overhead['accounted_upper_bound_usd'] is not None else None,
        'full_quality':'selected_gates_and_optional_agent_review_not_human_blind',
        'billing_usd':None,'cost_basis':'existing_proxy_peak_estimate_not_provider_bill',
        'failed_attempts_retained':True,'synthetic_provider_skips_claimed':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--tasks',type=Path,required=True);parser.add_argument('--trial',required=True)
    parser.add_argument('--baseline-trial');args=parser.parse_args()
    report=measurement(Path(os.environ['REMOTION_EXPERIMENT_ROOT']),args.output_root,args.tasks,args.trial,args.baseline_trial)
    out=args.output_root/('analysis-'+args.trial);out.mkdir(exist_ok=True)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('runs','pairs')},ensure_ascii=False))
