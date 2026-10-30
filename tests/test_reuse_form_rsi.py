"""Outer-loop publication diagnostics; fixtures are not measured video effects."""
from copy import deepcopy
import json
import shutil,subprocess
from pathlib import Path
import pytest
from src.adapters.reuse_form_rsi import propose_form,evaluate_form,publish_form,resolve_form,interface_variants,split_model_form
from src.adapters.source_program_compiler import source_library

FORM={'representation':'program_catalog','catalog_format':'example',
      'compiler_instruction':'Learn a compact current-input interface from the actual witnessed source.'}


def evidence(form=FORM,parent=None):
    library=source_library([])
    native={'runs':2,'reviewed_quality_pass':2,'observed_peak_usd':.1}
    candidate={'runs':2,'reviewed_quality_pass':2,'observed_peak_usd':.05,'source_program_renders':2}
    report={'format':'reuse_form_measurements_v1','complete':True,'old_ledger_preserved':True,
            'arms':{'fused':native,'program':candidate},'gross_model_cost_reduction':.5,
            'runs':[{'task':'validation-'+str(i),'arm':'program','library_digest':library['digest'],
                     'quality_sha256':'d'*64,'narrow_quality_pass':True,
                     'form_proposal_digest':propose_form(form,owner='owner',evidence_sha256='b'*64,parent_digest=parent)['digest']} for i in range(2)],
            'full_quality':'fixture_only','evaluator_sha256':'a'*64}
    return library,report


def test_rejected_or_unknown_measurement_never_publishes(tmp_path):
    library,report=evidence();report['arms']['program']['observed_peak_usd']=None
    proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    verdict=evaluate_form(proposal,report,library)
    assert not verdict['accepted'] and 'unsettled_cost' in verdict['reasons']
    file=tmp_path/'measurement.json';file.write_text(json.dumps(report))
    result=publish_form(tmp_path/'store',proposal,verdict,library,file)
    assert result['published'] is False and not (tmp_path/'store/latest.json').exists()


def test_publication_parent_and_next_learner_snapshot(tmp_path):
    library,report=evidence();file=tmp_path/'measurement.json';file.write_text(json.dumps(report))
    proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    verdict=evaluate_form(proposal,report,library);store=tmp_path/'store'
    first=publish_form(store,proposal,verdict,library,file)
    policy,path=resolve_form(store,'owner')
    assert policy['form']==FORM and path.exists() and first['generation']==1
    with pytest.raises(ValueError,match='foreign_owner'):resolve_form(store,'other')
    with pytest.raises(ValueError,match='parent_changed'):publish_form(store,proposal,verdict,library,file)
    updated={**FORM,'representation':'typed_tools'}
    next_proposal=propose_form(updated,owner='owner',evidence_sha256='b'*64,parent_digest=first['digest'])
    _,report=evidence(updated,first['digest']);file.write_text(json.dumps(report))
    next_verdict=evaluate_form(next_proposal,report,library)
    second=publish_form(store,next_proposal,next_verdict,library,file,expected_parent=first['digest'])
    assert second['generation']==2 and second['parent_digest']==first['digest']
    assert resolve_form(store,'owner')[0]['form']['representation']=='typed_tools'


def test_changed_measurements_cannot_reuse_old_accepted_verdict(tmp_path):
    library,report=evidence();proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    verdict=evaluate_form(proposal,report,library)
    altered=deepcopy(report);altered['arms']['program']['reviewed_quality_pass']=0
    file=tmp_path/'measurement.json';file.write_text(json.dumps(altered))
    with pytest.raises(ValueError,match='measurements_changed'):
        publish_form(tmp_path/'store',proposal,verdict,library,file)


def test_python_publication_is_loadable_by_authoritative_typescript(tmp_path):
    node=shutil.which('node')
    if not node or subprocess.check_output([node,'-p','Boolean(process.features.typescript)'],text=True).strip()!='true':
        pytest.skip('Node TypeScript stripping unavailable')
    library,report=evidence();file=tmp_path/'measurement.json';file.write_text(json.dumps(report))
    proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    verdict=evaluate_form(proposal,report,library);store=tmp_path/'store'
    publish_form(store,proposal,verdict,library,file)
    script="import {loadSourceForm} from './src/adapters/source_program_runtime.ts'; console.log(JSON.stringify(loadSourceForm(process.argv[1],'owner').policy.form));"
    actual=subprocess.check_output([node,'--experimental-strip-types','--input-type=module','-e',script,str(store)],
        cwd=Path(__file__).resolve().parents[1],text=True)
    assert json.loads(actual)==FORM
    policy,path=resolve_form(store,'owner')
    receipt=path.parent/'rsi-publication.json'
    value=json.loads(receipt.read_text());assert value['payload']['next_versions']['reuse_form']['sha256']==policy['proposal_digest']
    value['payload']['manifest_sha256']='e'*64;receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='protocol_receipt_changed'):resolve_form(store,'owner')
    failed=subprocess.run([node,'--experimental-strip-types','--input-type=module','-e',script,str(store)],
        cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True)
    assert failed.returncode!=0 and 'protocol_receipt_changed' in failed.stderr


def test_other_form_validation_cannot_promote_proposal():
    library,report=evidence()
    proposal=propose_form({**FORM,'representation':'typed_tools'},owner='owner',evidence_sha256='b'*64)
    assert 'validation_form_changed' in evaluate_form(proposal,report,library)['reasons']


def test_interface_search_never_changes_compiler_or_parent():
    proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64,parent_digest='c'*64)
    variants=interface_variants(proposal)
    assert proposal in variants
    assert len({v['digest'] for v in variants})==len(variants)
    assert all(v['parent_digest']=='c'*64 and v['form']['compiler_instruction']==FORM['compiler_instruction'] for v in variants)
    assert any(v['form'].get('parameter_binding')=='defaults' and v['form']['representation']=='typed_tools' for v in variants)
    assert any(v['form'].get('program_evidence')=='source' for v in variants)
    assert any(v['form'].get('library_scope')=='lexical_top1' for v in variants)


def test_failed_api_task_cannot_be_rescued_by_cheap_counts_or_more_visual_review():
    from scenarios.remotion_edit.structured.evolve_forms import can_still_qualify
    library,report=evidence();proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    for arm in report['arms'].values():arm['reviewed_quality_pass']=0
    for run in report['runs']:run['narrow_quality_pass']=True
    assert can_still_qualify(proposal,report,library)
    report['runs'][0]['narrow_quality_pass']=False
    assert not can_still_qualify(proposal,report,library)
    report['runs'][0]['narrow_quality_pass']=True
    report['arms']['program']['observed_peak_usd']=None
    assert not can_still_qualify(proposal,report,library)


def test_model_explanation_is_not_an_executable_form_field():
    form,notes=split_model_form({**FORM,'program_evidence_note':'unverified explanation'})
    assert form==FORM and notes=={'program_evidence_note':'unverified explanation'}
    with pytest.raises(ValueError,match='shape'):split_model_form({**FORM,'grant_permissions':'all'})


def test_qualified_candidate_can_improve_failed_native_baseline():
    from scenarios.remotion_edit.structured.evolve_forms import can_still_qualify
    library,report=evidence();proposal=propose_form(FORM,owner='owner',evidence_sha256='b'*64)
    report['arms']['fused']['reviewed_quality_pass']=1
    report['runs'][0]['narrow_quality_pass']=True
    report['runs'].append({'arm':'fused','narrow_quality_pass':False})
    assert can_still_qualify(proposal,report,library)
    assert evaluate_form(proposal,report,library)['accepted']
    report['arms']['program']['reviewed_quality_pass']=1
    assert not evaluate_form(proposal,report,library)['accepted']
