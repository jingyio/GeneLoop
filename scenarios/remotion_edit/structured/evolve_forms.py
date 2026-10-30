"""Run a finite, frozen form-search round through existing Harness entry points.

No new Agent loop: execute the declared paired jobs, independently verify/review,
account for every request, retain rejected hypotheses and publish the cheapest
eligible form. A later round consumes the resulting parent policy normally.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from src.adapters.reuse_form_rsi import evaluate_form,publish_form,resolve_form
from src.adapters.script_motif_compiler import digest
from src.motif_core.offline.experience_registry import read,durable,sha
from scenarios.remotion_edit.structured.analyze_programs import measurement


def frozen(path,value):
    if path.exists():
        if read(path)!=value:raise ValueError('form_search_frozen_input_changed')
    else:durable(path,value,exclusive=True)


def can_still_qualify(proposal,report,library):
    """Visual review cannot repair a failed artifact, unknown fee or insufficient gain."""
    candidate_runs=[r for r in report['runs'] if r['arm']=='program']
    if not candidate_runs or not all(r['narrow_quality_pass'] for r in candidate_runs):return False
    verdict=evaluate_form(proposal,report,library)
    waiting={'quality_regression','candidate_quality_unreviewed_or_failed'}
    return not set(verdict['reasons'])-waiting


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--call-model',action='store_true');a=p.parse_args();plan=read(a.plan)
    tasks=read(plan['tasks']);candidates={c['name']:c for c in plan['candidates']}
    conditions={'baseline',*candidates}
    if len(candidates)!=len(plan['candidates']) or 'baseline' in candidates or not candidates:
        raise ValueError('form_search_candidate_names')
    if {r['task'] for r in plan['schedule']}!={t['id'] for t in tasks} or len(plan['schedule'])!=len(tasks):
        raise ValueError('form_search_tasks_incomplete')
    if any(set(r['order'])!=conditions or len(r['order'])!=len(conditions) for r in plan['schedule']):
        raise ValueError('form_search_unpaired_schedule')
    trials=[plan['baseline_trial'],*[c['trial'] for c in candidates.values()]]
    if len(set(trials))!=len(trials):raise ValueError('form_search_duplicate_trial')
    snapshot={'plan':plan,'tasks_sha256':sha(plan['tasks']),'library_sha256':sha(plan['library']),
        'proposals_sha256':{name:sha(c['proposal']) for name,c in candidates.items()},
        'evaluation_sha256':{name:sha(Path(__file__).with_name(name)) for name in
            ('verify_runs.py','review_program_runs.py','analyze_programs.py')},
        'orchestrator_sha256':sha(Path(__file__))}
    if plan.get('baseline_form'):snapshot['baseline_form_sha256']=sha(plan['baseline_form'])
    if plan.get('post_publication'):snapshot['post_tasks_sha256']=sha(plan['post_publication']['tasks'])
    mode=plan.get('review_mode','deepseek')
    if mode not in ('deepseek','external_selected_frames'):raise ValueError('review_mode_unsupported')
    if mode=='external_selected_frames':snapshot['review_protocol_sha256']=sha(plan['review_protocol'])
    out=Path(plan['output_root']);round_dir=out/'form-searches'/sha(a.plan)[:24]
    if not a.call_model:
        print(json.dumps({'jobs':len(tasks)*len(conditions),'candidates':list(candidates),
            'baseline_shared':True,'paid_requests':0,'plan_sha256':sha(a.plan)}));return
    round_dir.mkdir(parents=True,exist_ok=True);frozen(round_dir/'frozen-inputs.json',snapshot)
    receipt=round_dir/'evolution-receipt.json'
    def continue_if_published(result):
        if result['publication']['published'] and plan.get('post_publication'):
            from scenarios.remotion_edit.structured.continue_form import continue_form
            return {**result,'continuation':continue_form(plan,result['publication']['digest'])}
        return result
    if receipt.exists():print(json.dumps(continue_if_published(read(receipt))));return
    library=read(plan['library']);store=Path(plan['store']);owner=plan['owner']
    parent=resolve_form(store,owner)[0]['digest'] if (store/'latest.json').exists() else None
    proposals={name:read(c['proposal']) for name,c in candidates.items()}
    if any(v['owner']!=owner or v['parent_digest']!=parent for v in proposals.values()):
        raise ValueError('form_search_parent_changed')
    if plan.get('baseline_form'):
        shared=read(plan['baseline_form'])['form'].get('agent_instruction','')
        if any(v['form'].get('agent_instruction','')!=shared for v in proposals.values()):
            raise ValueError('shared_baseline_instruction_changed')
    def run(entry,args):
        subprocess.run([sys.executable,str(ROOT/entry),*map(str,args)],cwd=ROOT,check=True)
    native='scenarios/remotion_edit/structured/'
    for job in plan['schedule']:
        for condition in job['order']:
            candidate=candidates.get(condition)
            run(native+'run_trial.py',['--phase','evaluate','--trial',candidate['trial'] if candidate else plan['baseline_trial'],
                '--tasks',plan['tasks'],'--output-root',out,'--program-library',plan['library'],
                '--task',job['task'],'--arm','program' if candidate else 'fused',
                *(['--form-file',candidate['proposal']] if candidate else
                  ['--form-file',plan['baseline_form']] if plan.get('baseline_form') else []),
                *(['--form-instruction-scope','both'] if plan.get('baseline_form') else []),'--call-model'])
    for trial in trials:
        run(native+'verify_runs.py',['--output-root',out,'--trial',trial])
    possible=[]
    for name,candidate in candidates.items():
        preliminary=measurement(Path(os.environ['REMOTION_EXPERIMENT_ROOT']),out,Path(plan['tasks']),candidate['trial'],plan['baseline_trial'])
        if can_still_qualify(proposals[name],preliminary,library):possible.append(name)
    if possible:
        if mode=='external_selected_frames':
            from scenarios.remotion_edit.structured.review_program_runs import external_reviews
            pending=[path for trial in [plan['baseline_trial'],*[candidates[n]['trial'] for n in possible]]
                     for path in external_reviews(out,trial,snapshot['review_protocol_sha256'])]
            if pending:
                print(json.dumps({'status':'awaiting_external_pixel_reviews','pending':pending,
                    'protocol_sha256':snapshot['review_protocol_sha256'],'publication':False}));return
        else:
            run(native+'review_program_runs.py',['--output-root',out,'--trial',plan['baseline_trial'],
                '--max-attempts',plan.get('review_attempts',1),'--call-model'])
            for name in possible:
                run(native+'review_program_runs.py',['--output-root',out,'--trial',candidates[name]['trial'],
                    '--max-attempts',plan.get('review_attempts',1),'--call-model'])
    verdicts={};reports={}
    for name,candidate in candidates.items():
        report=measurement(Path(os.environ['REMOTION_EXPERIMENT_ROOT']),out,Path(plan['tasks']),candidate['trial'],plan['baseline_trial'])
        file=round_dir/(name+'-measurements.json');frozen(file,report);reports[name]=file
        verdicts[name]=evaluate_form(proposals[name],report,library)
        frozen(round_dir/(name+'-verdict.json'),verdicts[name])
    eligible=[name for name in candidates if verdicts[name]['accepted']]
    winner=min(eligible,key=lambda name:read(reports[name])['arms']['program']['observed_peak_usd']) if eligible else None
    rejected={}
    for name in candidates:
        if not verdicts[name]['accepted']:
            rejected[name]=publish_form(store,proposals[name],verdicts[name],library,reports[name],expected_parent=parent)
    publication=publish_form(store,proposals[winner],verdicts[winner],library,reports[winner],expected_parent=parent) if winner else {'published':False}
    result={'format':'reuse_form_evolution_v1','plan_sha256':sha(a.plan),'parent_digest':parent,
        'winner':winner,'publication':publication,'verdicts':verdicts,'rejections':rejected,
        'candidate_reports':{name:str(file) for name,file in reports.items()},
        'baseline_runs':len(tasks),'candidate_runs':len(tasks)*len(candidates),
        'visual_review_candidates':possible,'visual_review_strategy':'only_candidates_still_eligible; existing reviews/failures retained',
        'comparison_scope':'one shared physical baseline; technical public-film parameter variants, selected checks/review',
        'billing_usd':None}
    frozen(receipt,result);print(json.dumps(continue_if_published(result),ensure_ascii=False))


if __name__=='__main__':main()
