"""Counterexamples for opportunity selection and independent paired evaluation."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from src.adapters.rsi_optimization import assess_opportunities, evaluate_optimization, digest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('optimization_example', ROOT / 'examples/rsi-protocol-v1/optimization_example.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
encode = module.encode


def context():
    x = module.example()
    a = x['assessments'][0]
    # TS constructs this same plan from independently approved hashes. Python
    # fixtures here exercise measurement policy, never authorize a publication.
    x['plan'] = dict(protocol='geneloop.rsi/v1', record_type='optimization_plan', payload=dict(
        id='diagnostic-plan', assessment_id=a['payload']['id'], assessment_sha256=digest(encode(a)),
        source_sha256=digest(encode(x['discovery'])), policy_sha256=digest(encode(x['policy'])),
        component='motif', structure_key='table.group_count', diagnosis_id=x['diagnosis']['payload']['id'],
        base_versions=x['versions'], discovery_task_ids=a['payload']['discovery_task_ids'],
        discovery_task_sha256s=a['payload']['discovery_task_sha256s'],
        validation_task_ids=list(x['validation_tasks']),
        validation_inputs=[dict(task_id=k, sha256=v) for k, v in x['validation_tasks'].items()],
        conditions_sha256=x['conditions_sha256'], rubric_sha256=x['rubric_sha256'], evaluator=x['evaluator'],
        allowed_patch_kinds=['rule_revision', 'motif_split'], required_checks=['native_guards'], stop_conditions=['quality_regression']))
    return x


def evaluate(x):
    return evaluate_optimization(encode(x['plan']), encode(x['policy']), encode(x['candidate']), encode(x['measurements']))['payload']


def test_whole_request_witnesses_only_start_a_trial_not_claim_a_saving():
    x = context()
    a = x['assessments'][0]['payload']
    assert a['action'] == 'start'
    assert a['avoidable_request_count'] == 4
    assert 'not_a_saving_result' in a['reasons'][0]


@pytest.mark.parametrize('change,reason', [
    (lambda d: d['runs'][1]['payload'].update(task_sha256=d['runs'][0]['payload']['task_sha256']), 'insufficient_independent_tasks'),
    (lambda d: d['runs'][0]['payload'].update(quality='unreviewed'), 'task_quality_not_verified'),
    (lambda d: d['audits'][0]['payload'].update(disposition='mixed_semantics'), 'whole_request_semantics_unresolved'),
    (lambda d: d['audits'][0]['payload'].update(cause='unknown'), 'whole_request_semantics_unresolved'),
    (lambda d: d['audits'][0]['payload'].update(cause='matcher_miss'), 'component_attribution_unresolved'),
    (lambda d: d['runs'][0]['payload'].update(conditions_sha256='0'*64), 'discovery_conditions_changed'),
    (lambda d: d['providers'][0]['payload'].update(observed_peak_usd=None), 'unsettled_or_missing_cost'),
])
def test_uncertain_opportunities_do_not_start(change, reason):
    x = context()
    change(x['discovery'])
    a = assess_opportunities(encode(x['discovery']), encode(x['policy']))[0]['payload']
    assert a['action'] == 'defer'
    assert reason in a['reasons']


def test_overlap_in_attribution_cannot_multiply_potential_savings():
    x = context()
    audit = deepcopy(x['discovery']['audits'][0])
    audit['payload']['id'] = 'overlapping-audit'
    x['discovery']['audits'].append(audit)
    a = assess_opportunities(encode(x['discovery']), encode(x['policy']))[0]['payload']
    assert a['avoidable_request_count'] == 4
    assert a['avoidable_model_usd'] == pytest.approx(.04)


def test_high_overhead_skips_an_otherwise_valid_opportunity():
    x = context()
    x['policy']['payload']['estimated_overhead_usd'] = 10
    assert assess_opportunities(encode(x['discovery']), encode(x['policy']))[0]['payload']['action'] == 'skip'


def test_accept_requires_paired_quality_actual_adoption_and_net_benefit():
    out = evaluate(context())
    assert out['action'] == 'accept'
    assert out['comparison_net_usd'] == pytest.approx(.03)
    assert out['experiment_total_model_usd'] == pytest.approx(.05)
    assert out['known_model_usd'] == pytest.approx(.05)
    assert out['projected_future_net_usd'] == pytest.approx(.27)
    assert (out['baseline_requests'], out['candidate_requests'], out['overhead_requests']) == (4, 2, 1)


def candidate_run(x):
    return next(r['payload'] for r in x['measurements']['runs'] if r['payload']['arm'] == 'candidate')


@pytest.mark.parametrize('change,reason', [
    (lambda x: candidate_run(x).update(quality='failed'), 'quality_regression'),
    (lambda x: candidate_run(x).update(conditions_sha256='0'*64), 'comparison_conditions_changed'),
    (lambda x: candidate_run(x).update(candidate_sha256='0'*64), 'candidate_not_loaded_or_version_changed'),
    (lambda x: candidate_run(x).update(task_sha256='0'*64), 'paired_task_input_changed'),
    (lambda x: [r['payload'].update(actual_adoptions=0) for r in x['measurements']['runs']], 'no_actual_candidate_adoption'),
    (lambda x: x['measurements']['providers'][-1]['payload'].update(observed_peak_usd=1), 'net_model_cost_not_improved'),
])
def test_cheaper_or_passing_schema_alone_cannot_pass(change, reason):
    x = context()
    change(x)
    out = evaluate(x)
    assert out['action'] == 'reject'
    assert reason in out['reasons']


def test_unknown_usage_is_not_zero_and_reservation_and_known_cost_survive():
    x = context()
    x['measurements']['providers'][-1]['payload'].update(phase='failed', observed_peak_usd=None)
    out = evaluate(x)
    assert out['action'] == 'defer'
    assert out['comparison_net_usd'] is None
    assert out['known_model_usd'] == pytest.approx(.048)
    assert out['unsettled_requests'] == 1
    assert out['reserved_upper_usd'] == .02


def test_failed_request_with_known_cost_is_counted_and_booking_is_deduplicated():
    x = context()
    terminal = x['measurements']['providers'][-1]
    terminal['payload']['phase'] = 'failed'
    booking = deepcopy(terminal)
    booking['payload'].update(phase='booked', observed_peak_usd=None)
    x['measurements']['providers'].insert(0, booking)
    out = evaluate(x)
    assert out['action'] == 'accept'
    assert out['overhead_requests'] == 1
    assert out['overhead_model_usd'] == .002


@pytest.mark.parametrize('change,reason', [
    (lambda x: x['measurements']['runs'].pop(), 'run_inventory_incomplete'),
    (lambda x: x['measurements']['providers'].pop(), 'request_missing'),
    (lambda x: x['measurements']['runs'][-1]['payload']['provider_requests'].append(x['measurements']['runs'][0]['payload']['provider_requests'][0]), 'request_double_counted'),
    (lambda x: x['measurements']['runs'][0]['payload'].update(split='test'), 'frozen_test_prohibited'),
    (lambda x: x['candidate']['payload'].update(training_task_ids=['validation-report-D']), 'training_scope_changed'),
    (lambda x: x['policy']['payload'].update(horizon_tasks=21), 'policy_changed'),
    (lambda x: x['plan']['payload']['evaluator'].update(sha256='0'*64), 'evaluator_changed'),
    (lambda x: x['measurements']['providers'][0]['payload'].update(observed_peak_usd=-1), 'negative_measurement'),
])
def test_missing_failures_leaks_and_changed_policies_fail_closed(change, reason):
    x = context()
    change(x)
    with pytest.raises(ValueError, match=reason):
        evaluate(x)


def test_renamed_training_input_cannot_be_used_as_independent_validation():
    x = context()
    task = x['plan']['payload']['validation_task_ids'][0]
    sha = x['plan']['payload']['discovery_task_sha256s'][0]
    for r in x['measurements']['runs']:
        if r['payload']['task_id'] == task:
            r['payload']['task_sha256'] = sha
    assert 'renamed_training_task_in_validation' in evaluate(x)['reasons']


def test_retries_remain_in_the_same_task_denominator_and_the_full_request_cost():
    x = context()
    retry = deepcopy(x['measurements']['runs'][1])
    retry['payload']['id'] += '-retry'
    retry['payload']['provider_requests'][0]['ledger_ref'] += '-retry'
    provider = deepcopy(x['measurements']['providers'][2])
    provider['payload']['ledger_ref'] += '-retry'
    x['measurements']['runs'].append(retry)
    x['measurements']['expected_run_ids'].append(retry['payload']['id'])
    x['measurements']['providers'].append(provider)
    out = evaluate(x)
    assert out['candidate_requests'] == 3
    assert len(out['validation_task_ids']) == 2
    assert out['candidate_model_usd'] == pytest.approx(.012)


def test_projection_uses_the_whole_registered_population_not_only_hits():
    x = context()
    run = deepcopy(x['discovery']['runs'][0])
    run['payload'].update(id='non-hit-C', task_id='invitation-C', task_sha256=digest(b'no-count-needed'), provider_requests=[])
    x['discovery']['runs'].append(run)
    x['discovery']['expected_run_ids'].append('non-hit-C')
    a = assess_opportunities(encode(x['discovery']), encode(x['policy']))[0]['payload']
    assert a['population_task_count'] == 3
    assert a['projected_net_usd'] == pytest.approx(.04 / 3 * 20 - .03)


def test_small_future_horizon_cannot_ignore_the_trial_investment():
    x = context()
    x['policy']['payload']['horizon_tasks'] = 1
    x['plan']['payload']['policy_sha256'] = digest(encode(x['policy']))
    out = evaluate(x)
    assert out['comparison_net_usd'] > 0
    assert out['projected_future_net_usd'] < 0
    assert out['action'] == 'reject'
    assert 'projected_gain_does_not_repay_trial' in out['reasons']
