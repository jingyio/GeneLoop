"""Offline outer RSI loop for the representation used by the next learner.

Forms configure a compiler and its interface, rather than editing the evaluator
or granting new tool rights. Existing durable publication and writer ownership
are reused. Unknown measurements and rejected candidates never move latest.
"""
from __future__ import annotations
import json
from pathlib import Path
from itertools import product
from .source_program_compiler import json_numbers
from .script_motif_compiler import digest
from src.motif_core.offline.experience_registry import durable,read,sha


def validate_form(form):
    required={'representation','catalog_format','compiler_instruction'}
    if not isinstance(form,dict) or not required<=set(form)<=required|{'agent_instruction','tool_naming','parameter_binding','program_evidence','library_scope'}:
        raise ValueError('reuse_form_shape')
    if form['representation'] not in ('program_catalog','typed_tools') or form['catalog_format'] not in ('example','full'):
        raise ValueError('reuse_form_unsupported')
    if not isinstance(form['compiler_instruction'],str) or not 1<=len(form['compiler_instruction'])<=6000:
        raise ValueError('reuse_form_instruction')
    if form.get('tool_naming','opaque') not in ('opaque','description'):raise ValueError('reuse_form_tool_naming')
    if form.get('parameter_binding','full') not in ('full','defaults'):raise ValueError('reuse_form_parameter_binding')
    if form.get('program_evidence','interface') not in ('interface','source'):raise ValueError('reuse_form_program_evidence')
    if form.get('library_scope','all') not in ('all','lexical_top1'):raise ValueError('reuse_form_library_scope')
    if not isinstance(form.get('agent_instruction',''),str) or len(form.get('agent_instruction',''))>4000:
        raise ValueError('reuse_form_agent_instruction')
    return form


def propose_form(form,*,owner,evidence_sha256,parent_digest=None):
    body={'format':'reuse_form_proposal_v1','owner':owner,'parent_digest':parent_digest,
          'evidence_sha256':evidence_sha256,'form':validate_form(form)}
    return {**body,'digest':digest(body)}


def split_model_form(response):
    """Keep explanatory model notes outside the executable form contract."""
    if not isinstance(response,dict):raise ValueError('reuse_form_shape')
    notes={k:v for k,v in response.items() if k.endswith('_note') or k in ('notes','rationale')}
    return validate_form({k:v for k,v in response.items() if k not in notes}),notes


def interface_variants(proposal):
    """Generic finite interface search; compiler/selection policy stay identical.

    Enumeration proposes hypotheses, never permissions or a publication. A run
    plan must freeze which variants receive real validation before results exist.
    """
    variants={proposal['digest']:proposal}
    for representation in ('program_catalog','typed_tools'):
        for display,naming,binding,evidence,scope in product(
            ('example','full') if representation=='program_catalog' else ('example',),
            ('opaque','description') if representation=='typed_tools' else ('opaque',),
            ('full','defaults'),('interface','source'),('all','lexical_top1')):
            form={**proposal['form'],'representation':representation,'catalog_format':display,
                  'tool_naming':naming,'parameter_binding':binding,'program_evidence':evidence}
            if scope!='all' or 'library_scope' in form:form['library_scope']=scope
            candidate=propose_form(form,owner=proposal['owner'],evidence_sha256=proposal['evidence_sha256'],
                                   parent_digest=proposal['parent_digest'])
            variants[candidate['digest']]=candidate
    return list(variants.values())


def evaluate_form(proposal,measurements,library,*,min_cost_reduction=.2,max_additional_failures=0):
    validate_form(proposal['form'])
    if proposal['digest']!=digest({k:v for k,v in proposal.items() if k!='digest'}):
        raise ValueError('reuse_form_proposal_changed')
    if measurements.get('format')!='reuse_form_measurements_v1':
        raise ValueError('reuse_form_measurements_required')
    reasons=[];native=measurements['arms']['fused'];candidate=measurements['arms']['program']
    if not measurements.get('complete'):reasons.append('validation_incomplete')
    if native['observed_peak_usd'] is None or candidate['observed_peak_usd'] is None:
        reasons.append('unsettled_cost')
    if not measurements.get('old_ledger_preserved'):reasons.append('cost_history_changed')
    if candidate['runs']!=native['runs'] or not candidate['runs']:reasons.append('unpaired_validation')
    if candidate['reviewed_quality_pass']<native['reviewed_quality_pass']-max_additional_failures:
        reasons.append('quality_regression')
    if candidate['reviewed_quality_pass']!=candidate['runs'] and max_additional_failures==0:
        reasons.append('candidate_quality_unreviewed_or_failed')
    used=[r for r in measurements['runs'] if r['arm']=='program']
    if not candidate['source_program_renders']:reasons.append('program_not_actually_used')
    if any(r['library_digest']!=library['digest'] for r in used):reasons.append('validation_library_changed')
    if any(r.get('form_proposal_digest')!=proposal['digest'] for r in used):
        reasons.append('validation_form_changed')
    reduction=measurements.get('gross_model_cost_reduction')
    if reduction is None or reduction<min_cost_reduction:reasons.append('insufficient_measured_gain')
    overhead=measurements.get('learning_review_and_meta_overhead',{})
    if overhead and overhead.get('observed_peak_usd') is None and overhead.get('accounted_upper_bound_usd') is None:
        reasons.append('unbounded_optimization_overhead')
    body={'format':'reuse_form_verdict_v1','proposal_digest':proposal['digest'],
          'accepted':not reasons,'reasons':reasons,'library_digest':library['digest'],
          'min_cost_reduction':min_cost_reduction,'max_additional_failures':max_additional_failures,
          'measured_cost_reduction':reduction,'quality_scope':measurements['full_quality'],
          'cold_study_net_usd':measurements.get('saving_after_all_new_exploration_and_overhead_usd'),
          'conservative_cold_study_net_lower_bound_usd':measurements.get('conservative_cold_study_net_lower_bound_usd'),
          'overhead_unknown_request_ids':overhead.get('unknown_request_ids',[]),
          'promotion_objective':'qualified_forward_model_cost; cold learning/exploration retained separately',
          'measurements_digest':digest(json_numbers(measurements)),
          'evaluator_sha256':measurements['evaluator_sha256']}
    body=json_numbers(body)
    return {**body,'digest':digest(body)}


def publish_form(store,proposal,verdict,library,measurements_file,*,expected_parent=None):
    from .continuous_rsi import writer_lock
    store=Path(store);store.mkdir(parents=True,exist_ok=True)
    if verdict['proposal_digest']!=proposal['digest'] or verdict['library_digest']!=library['digest']:
        raise ValueError('reuse_form_verdict_binding_changed')
    measured=read(measurements_file)
    if verdict!=evaluate_form(proposal,measured,library,min_cost_reduction=verdict['min_cost_reduction'],
                              max_additional_failures=verdict['max_additional_failures']):
        raise ValueError('reuse_form_verdict_or_measurements_changed')
    with writer_lock(store,'reuse-form'):
        pointer_file=store/'latest.json';previous=read(pointer_file) if pointer_file.exists() else None
        parent=previous['digest'] if previous else None
        if parent!=expected_parent or proposal['parent_digest']!=expected_parent:
            raise ValueError('reuse_form_parent_changed')
        if previous and previous['owner']!=proposal['owner']:raise ValueError('reuse_form_foreign_owner')
        if not verdict['accepted']:
            rejection={'proposal':proposal,'verdict':verdict,'measurements_sha256':sha(measurements_file),'published':False}
            rejected=store/'rejections'/(proposal['digest']+'.json')
            if not rejected.exists():durable(rejected,rejection,exclusive=True)
            return {'published':False,'parent_digest':parent,'reasons':verdict['reasons']}
        if library['digest']!=digest(json_numbers({k:v for k,v in library.items() if k!='digest'})):
            raise ValueError('reuse_form_library_changed')
        from .reuse_form_protocol import form_update_bundle,validate_form_update,encoded,sha as text_sha
        from .rsi_protocol import envelope
        payload_sha=text_sha(encoded({'proposal':proposal,'verdict':verdict,'library_digest':library['digest'],
            'measurements_sha256':sha(measurements_file)}))
        bundle=form_update_bundle(proposal,verdict,library,measured,
            read(store/previous['policy']) if previous else None,payload_sha)
        change=validate_form_update(bundle)
        generation=previous['generation']+1 if previous else 1
        body=json_numbers({'format':'reuse_form_policy_v1','owner':proposal['owner'],'generation':generation,
            'parent_digest':parent,'form':proposal['form'],'proposal_digest':proposal['digest'],
            'verdict':verdict,'measurements_sha256':sha(measurements_file),'library_digest':library['digest'],
            'rsi_update_digest':digest(json_numbers(bundle))})
        policy={**body,'digest':digest(body)};directory=store/('round-'+policy['digest'][:24])
        publication=envelope('publication_receipt',{'id':'form-publication-'+policy['digest'][:24],
            'candidate_id':proposal['digest'],'report_id':json.loads(bundle['report'])['payload']['id'],
            'previous_versions':change['previous'],'next_versions':change['next'],'manifest_sha256':policy['digest']})
        for path,value in [(directory/'source-library.json',library),(directory/'policy.json',policy),
                           (directory/'rsi-update.json',bundle),(directory/'rsi-publication.json',publication)]:
            if path.exists():
                if read(path)!=value:raise ValueError('reuse_form_generation_changed')
            else:durable(path,value,exclusive=True)
        # All immutable records above are staged. Only this atomic pointer commit
        # publishes the form AND its shared receipt to subsequent tasks.
        durable(pointer_file,{'format':'reuse_form_pointer_v1','owner':proposal['owner'],'generation':generation,
            'digest':policy['digest'],'policy':(directory/'policy.json').relative_to(store).as_posix(),
            'library':(directory/'source-library.json').relative_to(store).as_posix(),
            'rsi_publication_sha256':sha(directory/'rsi-publication.json')})
        return {'published':True,'generation':generation,'digest':policy['digest'],'parent_digest':parent,
            'rsi_publication_sha256':sha(directory/'rsi-publication.json')}


def resolve_form(store,owner):
    store=Path(store);pointer=read(store/'latest.json')
    if pointer['owner']!=owner:raise ValueError('reuse_form_foreign_owner')
    policy_path=store/pointer['policy'];library_path=store/pointer['library']
    if not policy_path.resolve().is_relative_to(store.resolve()) or not library_path.resolve().is_relative_to(store.resolve()):
        raise ValueError('reuse_form_pointer_outside_store')
    policy=read(policy_path);library=read(library_path)
    if (pointer['digest']!=policy['digest'] or pointer['generation']!=policy['generation']
        or pointer['digest']!=digest(json_numbers({k:v for k,v in policy.items() if k!='digest'}))
        or policy['owner']!=owner or policy['verdict'].get('accepted') is not True
        or policy['library_digest']!=library['digest']
        or library['digest']!=digest(json_numbers({k:v for k,v in library.items() if k!='digest'}))):
        raise ValueError('reuse_form_pointer_changed')
    if 'rsi_update_digest' in policy:
        directory=policy_path.parent;bundle=read(directory/'rsi-update.json')
        publication=read(directory/'rsi-publication.json')
        from .rsi_protocol import validate_record
        validate_record(publication)
        p=publication['payload']
        if (policy['rsi_update_digest']!=digest(json_numbers(bundle))
            or pointer.get('rsi_publication_sha256')!=sha(directory/'rsi-publication.json')
            or publication['record_type']!='publication_receipt' or p['manifest_sha256']!=policy['digest']
            or p['candidate_id']!=policy['proposal_digest'] or p['next_versions']['reuse_form']['sha256']!=policy['proposal_digest']):
            raise ValueError('reuse_form_protocol_receipt_changed')
    return policy,library_path
