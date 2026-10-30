"""Cross-scene evidence interpretation, never a substitute for real quality review."""
from copy import deepcopy
import hashlib,json,subprocess
from pathlib import Path
import pytest
from src.adapters.rsi_protocol import envelope
from src.adapters.rsi_quality import quality_status,verify_quality_files


def sample(scene='paper'):
    return envelope('quality_evaluation',{'id':'quality-'+scene,'task_id':'task-'+scene,
        'task_sha256':'a'*64,'artifact_sha256':'b'*64,'rubric_sha256':'c'*64,
        'evaluator':'fixture-'+scene,'scope':'synthetic protocol diagnostic','limitations':['not measured task quality'],
        'checks':[{'id':'requirements','status':'passed','observation':'Explicit fixture content is present.',
            'evidence':[{'ref':'evidence.txt','sha256':'d'*64}]}]})


def status(record):
    return quality_status(record,task_sha256='a'*64,artifact_sha256='b'*64,rubric_sha256='c'*64,required_checks=['requirements'])


@pytest.mark.parametrize('scene',['paper','video','data'])
def test_same_contract_interprets_each_scene_without_domain_rules(scene):
    r=sample(scene);assert status(r)=='passed'
    r['payload']['checks'][0]['status']='unknown';assert status(r)=='unknown'
    r['payload']['checks'][0]['status']='failed';assert status(r)=='failed'


def test_pass_cannot_hide_missing_evidence_or_required_check():
    r=sample();r['payload']['checks'][0]['evidence']=[]
    with pytest.raises(ValueError,match='evidence_missing'):status(r)
    r=sample();r['payload']['checks']=[]
    with pytest.raises(ValueError,match='required_checks'):status(r)
    r=sample();r['payload']['checks']*=2
    with pytest.raises(ValueError,match='duplicate'):status(r)


@pytest.mark.parametrize('key',['task_sha256','artifact_sha256','rubric_sha256'])
def test_old_task_artifact_or_rubric_cannot_borrow_a_pass(key):
    r=sample();r['payload'][key]='e'*64
    with pytest.raises(ValueError,match='binding_changed'):status(r)


def test_reviewed_evidence_is_verified_against_actual_bytes(tmp_path):
    p=tmp_path/'evidence.txt';p.write_text('observed fixture')
    r=sample();r['payload']['checks'][0]['evidence'][0]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    verify_quality_files(r,tmp_path)
    p.write_text('changed fixture')
    with pytest.raises(ValueError,match='evidence_changed'):verify_quality_files(r,tmp_path)
    r['payload']['checks'][0]['evidence'][0]['ref']='../outside'
    with pytest.raises(ValueError,match='outside_run'):verify_quality_files(r,tmp_path)


def test_python_and_authoritative_typescript_agree():
    r=sample('video');binding={k:r['payload'][k] for k in ('task_sha256','artifact_sha256','rubric_sha256')}
    script="import {qualityStatus} from './src/adapters/rsi_quality.ts'; const x=JSON.parse(process.argv[1]); console.log(qualityStatus(x.r,x.binding,['requirements']));"
    for expected in ('passed','failed','unknown'):
        r['payload']['checks'][0]['status']=expected
        actual=subprocess.check_output(['node','--experimental-strip-types','--input-type=module','-e',script,json.dumps({'r':r,'binding':binding})],
            cwd=Path(__file__).resolve().parents[1],text=True).strip()
        assert actual==status(r)==expected


def test_meta_feedback_retains_quality_findings_and_missing_review_stays_unknown(tmp_path):
    import runpy
    module=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/propose-reuse-form.py'))
    run=tmp_path/'run';run.mkdir()
    (run/'effective.json').write_text(json.dumps({'task':{'id':'task','instruction':'Current public fixture'}}))
    (run/'events.jsonl').write_text('')
    row={'task':'task','arm':'program','run':str(run),'review':None}
    assert module['bounded_feedback']({'runs':[row]},tmp_path)[0]['independent_quality_findings']==[]
    checks=sample()['payload']['checks'];checks[0]['status']='failed'
    row['review']={'payload':{'checks':checks}}
    actual=module['bounded_feedback']({'runs':[row]},tmp_path)[0]
    assert actual['independent_quality_findings']==checks
    native={**row,'arm':'fused','reviewed_quality_pass':False}
    row['review']=None
    actual=module['bounded_feedback']({'runs':[native,row]},tmp_path)[0]
    assert actual['independent_quality_findings']==[]
    assert actual['paired_native_measurements']['reviewed_quality_pass'] is False
    assert actual['paired_native_measurements']['independent_quality_findings']==checks
