"""After publication, test a new task and feed its normal source into next RSI.

This finite continuation calls existing entry points; the next library/form stay
candidates. It never promotes them using the task that produced their evidence.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from src.adapters.reuse_form_rsi import resolve_form
from src.adapters.source_program_compiler import source_library
from src.motif_core.offline.experience_registry import read,durable,sha
from scenarios.remotion_edit.structured.analyze_programs import measurement


def next_candidate_library(library,certification,directory):
    previous=read(library);certified=read(Path(certification)/'library.json')
    programs={p['id']:p for p in previous['programs']}
    programs.update({p['id']:p for p in certified['programs']})
    pool=source_library(list(programs.values()),parent_digest=previous['digest'],generation=previous['generation']+1)
    path=Path(directory)/'next-source-library.json'
    if path.exists() and read(path)!=pool:raise ValueError('next_candidate_pool_changed')
    if not path.exists():durable(path,pool,exclusive=True)
    return path,pool


def continue_form(plan,expected_digest=None):
    config=plan['post_publication'];out=Path(plan['output_root']);store=Path(plan['store']);owner=plan['owner']
    policy,library=resolve_form(store,owner)
    if expected_digest and policy['digest']!=expected_digest:raise ValueError('continuation_policy_changed')
    suffix=policy['digest'][:12];trial=config.get('trial_prefix','published-followup')+'-'+suffix
    directory=out/'continuations'/suffix;directory.mkdir(parents=True,exist_ok=True)
    receipt=directory/'receipt.json'
    inputs={'policy_digest':policy['digest'],'tasks_sha256':sha(config['tasks']),
        'config':config,'continuation_sha256':sha(Path(__file__))}
    if config.get('review_mode')=='external_selected_frames':inputs['review_protocol_sha256']=sha(config['review_protocol'])
    file=directory/'frozen-inputs.json'
    if file.exists() and read(file)!=inputs:raise ValueError('continuation_inputs_changed')
    if not file.exists():durable(file,inputs,exclusive=True)
    if receipt.exists():return read(receipt)
    native='scenarios/remotion_edit/structured/'
    def run(entry,args):subprocess.run([sys.executable,str(ROOT/entry),*map(str,args)],cwd=ROOT,check=True)
    run(native+'run_trial.py',['--phase','evaluate','--trial',trial,'--tasks',config['tasks'],
        '--output-root',out,'--form-store',store,'--form-owner',owner,'--form-instruction-scope','both','--call-model'])
    run(native+'verify_runs.py',['--output-root',out,'--trial',trial])
    if config.get('review_mode')=='external_selected_frames':
        from scenarios.remotion_edit.structured.review_program_runs import external_reviews
        pending=external_reviews(out,trial,sha(config['review_protocol']))
        if pending:return {'status':'awaiting_external_pixel_reviews','pending':pending,
            'policy_digest':policy['digest'],'candidate_learning_started':False}
    else:
        run(native+'review_program_runs.py',['--output-root',out,'--trial',trial,
            '--max-attempts',config.get('review_attempts',1),'--call-model'])
    tasks=read(config['tasks']);normal=[]
    for task in tasks:
        for arm in ('fused','program'):
            effective=read(out/'runs'/trial/arm/task['id']/'effective.json')
            if effective.get('source_form_policy_digest')!=policy['digest']:
                raise ValueError('continuation_did_not_load_published_policy')
        normal.append(out/'runs'/trial/'fused'/task['id'])
    learning=out/('learning-followup-'+suffix)
    if not (learning/'learning-summary.json').exists():
        run(native+'learn_programs.py',['--output',learning,'--form-store',store,'--form-owner',owner,
            *[v for path in normal for v in ('--run',path)],'--call-model'])
    summary=read(learning/'learning-summary.json')
    if summary.get('parent_policy_digest')!=policy['digest']:raise ValueError('next_learner_parent_changed')
    certification=out/('certification-followup-'+suffix)
    if not (certification/'library.json').exists():
        run(native+'certify_programs.py',['--library',learning/'candidate-library.json','--output',certification])
    # The next reflection must see what the published compiler actually learned.
    # Keep this pool a candidate: current tasks still resolve the published pool.
    next_library,next_pool=next_candidate_library(library,certification,directory)
    measured=directory/'measurements.json'
    if not measured.exists():
        report=measurement(Path(os.environ['REMOTION_EXPERIMENT_ROOT']),out,Path(config['tasks']),trial)
        report['next_compiler_round']={'parent_policy_digest':summary['parent_policy_digest'],
            'candidates':summary['candidates'],'request_ids':summary['request_ids'],
            'source_equivalent_candidates':len(read(certification/'library.json')['programs']),
            'candidate_pool_digest':next_pool['digest'],'candidate_pool_parent_digest':next_pool['parent_digest'],
            'published':False}
        durable(measured,report,exclusive=True)
    proposal=out/('meta-followup-'+suffix)
    if not (proposal/'proposal.json').exists():
        run('scripts/propose-reuse-form.py',['--measurements',measured,'--store',store,'--owner',owner,
            '--output',proposal,'--library',next_library,'--include-feedback','--call-model'])
    next_proposal=read(proposal/'proposal.json')
    if next_proposal['parent_digest']!=policy['digest']:raise ValueError('next_form_parent_changed')
    report=read(measured)
    result={'format':'reuse_form_continuation_v1','policy_digest':policy['digest'],'trial':trial,
        'program_renders':report['arms']['program']['source_program_renders'],
        'reviewed_quality':{arm:report['arms'][arm]['reviewed_quality_pass'] for arm in ('fused','program')},
        'next_learner_parent_digest':summary['parent_policy_digest'],'learning_request_ids':summary['request_ids'],
        'next_source_equivalent_candidates':len(read(certification/'library.json')['programs']),
        'next_source_library':str(next_library),'next_source_library_digest':next_pool['digest'],
        'next_source_library_parent_digest':next_pool['parent_digest'],
        'next_form_parent_digest':next_proposal['parent_digest'],'next_proposal_digest':next_proposal['digest'],
        'next_candidates_published':False,'measurements_sha256':sha(measured),'billing_usd':None}
    durable(receipt,result,exclusive=True);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--policy-digest');p.add_argument('--call-model',action='store_true');a=p.parse_args();plan=read(a.plan)
    if not a.call_model:print(json.dumps({'post_publication':plan['post_publication'],'paid_requests':0}));return
    print(json.dumps(continue_form(plan,a.policy_digest),ensure_ascii=False))


if __name__=='__main__':main()
