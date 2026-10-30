"""Accounting diagnostics: unknown and failed requests must not become savings."""
import hashlib,json
from pathlib import Path
from scenarios.remotion_edit.structured.analyze_programs import measurement


def test_failed_and_unsettled_attempts_remain_in_pair_inventory(tmp_path):
    base=tmp_path/'base';exp=base/'experiment';exp.mkdir(parents=True)
    rows=[{'request_id':1,'observed_peak_usd':.02,'response_usage':{}},
          {'request_id':2,'observed_peak_usd':None,'response_usage':{}}]
    (base/'cost-ledger.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (exp/'authorized-experiment.json').write_text(json.dumps({'initial_ledger_bytes':0,
        'initial_ledger_sha256':hashlib.sha256(b'').hexdigest()}))
    tasks=tmp_path/'tasks.json';tasks.write_text(json.dumps([{'id':'case','arm_order':['fused','program']}]))
    for arm,rid in [('fused',1),('program',2)]:
        run=exp/'runs/round'/arm/'case';run.mkdir(parents=True)
        (run/'result.json').write_text(json.dumps({'request_ids':[rid],'status':'failed',
            'video_exists':False,'elapsed_seconds':1}))
        (run/'effective.json').write_text(json.dumps({'task':{'id':'case'},'arm':arm,
            'tool_order':[],'prompt_sha256':'frozen'}))
    report=measurement(base,exp,tasks,'round')
    assert report['complete'] is True
    assert report['arms']['fused']['observed_peak_usd']==.02
    assert report['arms']['program']['observed_peak_usd'] is None
    assert report['arms']['program']['unknown_request_ids']==[2]
    assert report['gross_model_cost_reduction'] is None
    assert not any(pair['both_narrow_quality_pass'] for pair in report['pairs'])


def test_shared_baseline_is_one_physical_cost_not_extra_exploration(tmp_path):
    base=tmp_path/'base';exp=base/'experiment';exp.mkdir(parents=True)
    rows=[{'request_id':1,'observed_peak_usd':.02,'response_usage':{}},
          {'request_id':2,'observed_peak_usd':.01,'response_usage':{}}]
    (base/'cost-ledger.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (exp/'authorized-experiment.json').write_text(json.dumps({'initial_ledger_bytes':0,
        'initial_ledger_sha256':hashlib.sha256(b'').hexdigest()}))
    tasks=tmp_path/'tasks.json';tasks.write_text(json.dumps([{'id':'case','arm_order':['fused','program']}]))
    for arm,rid,trial in [('fused',1,'native'),('program',2,'candidate')]:
        run=exp/'runs'/trial/arm/'case';run.mkdir(parents=True)
        (run/'result.json').write_text(json.dumps({'request_ids':[rid],'status':'failed',
            'video_exists':False,'elapsed_seconds':1}))
        (run/'effective.json').write_text(json.dumps({'task':{'id':'case'},'arm':arm,'trial':trial,
            'tool_order':[],'prompt_sha256':'frozen'}))
    report=measurement(base,exp,tasks,'candidate','native')
    assert report['complete'] and report['baseline_reused_for_comparison']
    assert report['arms']['fused']['model_requests']==1
    assert report['all_new_study_requests']['model_requests']==2
    assert report['previous_exploration']['model_requests']==0
    assert report['gross_model_cost_reduction']==.5
    candidate=exp/'runs/candidate/program/case/effective.json'
    config=json.loads(candidate.read_text());config.update(tool_order=['catalog','typed_program'],
        program_interface_tools=['catalog','typed_program'],learned_program_tools=['typed_program'])
    candidate.write_text(json.dumps(config))
    assert measurement(base,exp,tasks,'candidate','native')['complete']
