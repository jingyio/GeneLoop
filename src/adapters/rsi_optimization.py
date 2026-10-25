"""Offline opportunity assessment and paired measurement; not an online policy.

Input inventories and boundary/quality witnesses must come from a trusted trace
exporter/reviewer. No label inferred from tool names is proof a whole model
request can be removed. TS separately checks authorization to start/publish.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections import defaultdict

from .rsi_protocol import envelope, validate_record


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def record(raw: bytes, kind: str) -> dict:
    value = validate_record(json.loads(raw))
    if value['record_type'] != kind:
        raise ValueError('optimization_record_kind_mismatch')
    return value['payload']


def policy_record(raw: bytes) -> dict:
    p = record(raw, 'optimization_policy')
    for key in ('min_discovery_tasks', 'min_validation_tasks', 'horizon_tasks'):
        if p[key] < 1:
            raise ValueError('optimization_policy_invalid')
    for key in ('estimated_overhead_usd', 'min_net_gain_usd', 'min_request_reduction', 'max_additional_failures'):
        if p[key] < 0:
            raise ValueError('optimization_policy_invalid')
    return p


def _key(ref):
    return ref['ledger_ref'], ref['id']


def inventory(raw: bytes):
    """Fail closed on missing/duplicate/unallocated requests or attempts.

    Bookings may precede a terminal entry. Conflicting terminal costs are not
    silently overwritten. A trusted exporter must supply expected_run_ids from
    the run registry, not reconstruct it from cherry-picked successful runs.
    """
    value = json.loads(raw)
    runs = {}
    for r in value['runs']:
        validate_record(r)
        if r['record_type'] != 'optimization_run':
            raise ValueError('optimization_run_required')
        r = r['payload']
        if r['id'] in runs:
            raise ValueError('optimization_duplicate_run')
        if r['actual_adoptions'] < 0 or any(r[k] is not None and r[k] < 0 for k in ('wall_time_ms', 'manual_review_seconds')):
            raise ValueError('optimization_negative_measurement')
        runs[r['id']] = r
    expected = value['expected_run_ids']
    if len(set(expected)) != len(expected) or set(expected) != set(runs):
        raise ValueError('optimization_run_inventory_incomplete')
    providers = {}
    for row in value['providers']:
        validate_record(row)
        if row['record_type'] != 'provider_request':
            raise ValueError('optimization_provider_required')
        p = row['payload']
        if any(p[k] is not None and p[k] < 0 for k in ('observed_peak_usd', 'reserved_upper_usd', 'prompt_tokens', 'cache_hit_tokens', 'cache_miss_tokens', 'output_tokens')):
            raise ValueError('optimization_negative_measurement')
        key = _key(p)
        previous = providers.get(key)
        if previous and previous != p:
            if previous['phase'] == 'booked':
                providers[key] = p
            elif p['phase'] != 'booked':
                raise ValueError('optimization_conflicting_request')
        else:
            providers[key] = p
    allocated = set()
    for r in runs.values():
        for ref in r['provider_requests']:
            key = _key(ref)
            if key in allocated:
                raise ValueError('optimization_request_double_counted')
            allocated.add(key)
            if key not in providers or providers[key]['task_id'] != r['task_id']:
                raise ValueError('optimization_request_missing_or_wrong_task')
    if allocated != set(providers):
        raise ValueError('optimization_unallocated_request')
    audits, ids = [], set()
    for a in value.get('audits', []):
        validate_record(a)
        if a['record_type'] != 'optimization_boundary':
            raise ValueError('optimization_boundary_required')
        a = a['payload']
        if a['id'] in ids or a['run_id'] not in runs:
            raise ValueError('optimization_audit_binding_invalid')
        ids.add(a['id'])
        refs = [_key(r) for r in a['request_refs']]
        if len(set(refs)) != len(refs) or not set(refs) <= {_key(r) for r in runs[a['run_id']]['provider_requests']}:
            raise ValueError('optimization_audit_request_invalid')
        audits.append(a)
    return runs, providers, audits


def _cost(refs, providers):
    rows = [providers[_key(ref)] for ref in refs]
    # Failed requests with known billed usage count; unknown is never zero.
    if any(p['phase'] not in ('completed', 'failed') or p['observed_peak_usd'] is None for p in rows):
        return None
    return sum(p['observed_peak_usd'] for p in rows)


def assess_opportunities(source: bytes, policy: bytes) -> list[dict]:
    p = policy_record(policy)
    runs, providers, audits = inventory(source)
    if any(r['split'] == 'test' for r in runs.values()):
        raise ValueError('optimization_frozen_test_prohibited')
    groups = defaultdict(list)
    for a in audits:
        r = runs[a['run_id']]
        if r['split'] == 'test':
            raise ValueError('optimization_frozen_test_prohibited')
        if r['split'] != 'training' or r['arm'] != 'baseline':
            raise ValueError('optimization_discovery_scope_invalid')
        groups[(a['component'], a['structure_key'])].append(a)
    results = []
    for (component, structure), group in sorted(groups.items()):
        observed = [runs[i] for i in sorted({a['run_id'] for a in group})]
        task_ids = sorted({r['task_id'] for r in observed})
        # A changed name is not independence: deduplicate exact task bytes too.
        independent = len({r['task_sha256'] for r in observed})
        reasons = []
        if min(len(task_ids), independent) < p['min_discovery_tasks']:
            reasons.append('insufficient_independent_tasks')
        if any(r['quality'] != 'passed' or r['quality_sha256'] is None for r in observed):
            reasons.append('task_quality_not_verified')
        if any(r['versions'] != observed[0]['versions'] or r['conditions_sha256'] != observed[0]['conditions_sha256'] for r in observed):
            reasons.append('discovery_conditions_changed')
        if any(a['disposition'] != 'verified_determinate' or a['cause'] == 'unknown' for a in group):
            reasons.append('whole_request_semantics_unresolved')
        if any((a['cause'] == 'matcher_miss') != (component == 'matcher') for a in group):
            reasons.append('component_attribution_unresolved')
        # Overlapping audits never multiply potential savings.
        refs = {_key(ref): ref for a in group for ref in a['request_refs']}
        if not refs:
            reasons.append('no_whole_request_witness')
        avoidable = _cost(refs.values(), providers)
        if avoidable is None or any(_cost(r['provider_requests'], providers) is None for r in observed):
            reasons.append('unsettled_or_missing_cost')
        population = {r['task_sha256'] for r in runs.values() if r['split'] == 'training' and r['arm'] == 'baseline'}
        projected = None if avoidable is None else avoidable / len(population) * p['horizon_tasks'] - p['estimated_overhead_usd']
        action = 'defer' if reasons else 'start'
        if not reasons and projected <= p['min_net_gain_usd']:
            action, reasons = 'skip', ['projected_gain_does_not_cover_overhead']
        if action == 'start':
            reasons = ['bounded_trial_worth_attempting_not_a_saving_result']
        results.append(envelope('optimization_assessment', dict(
            id='assessment-' + digest((component + ':' + structure).encode())[:16],
            structure_key=structure, component=component, action=action, reasons=reasons,
            source_sha256=digest(source), policy_sha256=digest(policy), versions=observed[0]['versions'],
            discovery_task_ids=task_ids, discovery_task_sha256s=sorted({r['task_sha256'] for r in observed}),
            run_ids=[r['id'] for r in observed], audit_ids=[a['id'] for a in group],
            avoidable_request_count=len(refs), avoidable_model_usd=avoidable,
            population_task_count=len(population), projected_net_usd=projected)))
    return sorted(results, key=lambda r: ({'start': 0, 'defer': 1, 'skip': 2}[r['payload']['action']],
                   -(r['payload']['projected_net_usd'] or 0), r['payload']['id']))


def evaluate_optimization(plan_bytes: bytes, policy_bytes: bytes, candidate_bytes: bytes, measurements: bytes) -> dict:
    plan, p = record(plan_bytes, 'optimization_plan'), policy_record(policy_bytes)
    c = record(candidate_bytes, 'candidate_patch')
    if plan['policy_sha256'] != digest(policy_bytes):
        raise ValueError('optimization_policy_changed')
    if plan['evaluator']['sha256'] != digest(Path(__file__).read_bytes()):
        raise ValueError('optimization_evaluator_changed')
    if c['component'] != plan['component'] or c['diagnosis_id'] != plan['diagnosis_id'] or c['base_version'] != plan['base_versions'][c['component']] or c['compatible_versions'] != plan['base_versions']:
        raise ValueError('optimization_candidate_binding_invalid')
    if c['patch_kind'] not in plan['allowed_patch_kinds']:
        raise ValueError('optimization_patch_kind_not_planned')
    if set(c['training_task_ids']) != set(plan['discovery_task_ids']):
        raise ValueError('optimization_training_scope_changed')
    heldout = plan['validation_task_ids']
    if len(set(heldout)) != len(heldout) or len(heldout) < p['min_validation_tasks'] or set(heldout) & set(plan['discovery_task_ids']):
        raise ValueError('optimization_validation_scope_invalid')
    runs, providers, _ = inventory(measurements)
    costs, counts = dict(baseline=0., candidate=0., overhead=0.), dict(baseline=0, candidate=0, overhead=0)
    pairs = defaultdict(lambda: defaultdict(list))
    reasons, incomplete, failures, adoptions = [], False, dict(baseline=0, candidate=0), 0
    unknown_arms = set()
    candidate_sha = digest(candidate_bytes)
    expected_candidate = {**plan['base_versions'], c['component']: c['next_version']}
    for r in runs.values():
        if r['split'] == 'test':
            raise ValueError('optimization_frozen_test_prohibited')
        arm = r['arm']
        cost = _cost(r['provider_requests'], providers)
        counts[arm] += len(r['provider_requests'])
        if cost is None:
            incomplete = True
            unknown_arms.add(arm)
        else:
            costs[arm] += cost
        if arm == 'overhead':
            continue  # Includes diagnosis, proposal, validation, retries, maintenance.
        if r['split'] != 'validation' or r['task_id'] not in heldout:
            raise ValueError('optimization_unplanned_validation_task')
        if not any(i['task_id'] == r['task_id'] and i['sha256'] == r['task_sha256'] for i in plan['validation_inputs']):
            reasons.append('planned_validation_input_changed')
        pairs[r['task_id']][arm].append(r)
        if r['conditions_sha256'] != plan['conditions_sha256']:
            reasons.append('comparison_conditions_changed')
        expected = expected_candidate if arm == 'candidate' else plan['base_versions']
        if r['versions'] != expected or r['candidate_sha256'] != (candidate_sha if arm == 'candidate' else None):
            reasons.append('candidate_not_loaded_or_version_changed')
        if r['quality'] == 'unreviewed' or r['quality_sha256'] != plan['rubric_sha256']:
            incomplete = True
        if r['quality'] == 'failed':
            failures[arm] += 1
        if arm == 'candidate':
            adoptions += r['actual_adoptions']
    if set(pairs) != set(heldout) or any(set(arms) != {'baseline', 'candidate'} for arms in pairs.values()):
        raise ValueError('optimization_validation_matrix_incomplete')
    hashes = []
    for task, arms in pairs.items():
        # Retried attempts remain in the same denominator and all count in cost.
        task_hashes = {r['task_sha256'] for rows in arms.values() for r in rows}
        if len(task_hashes) != 1:
            reasons.append('paired_task_input_changed')
        hashes.extend(task_hashes)
    if len(set(hashes)) != len(heldout):
        reasons.append('validation_tasks_not_independent')
    if set(hashes) & set(plan['discovery_task_sha256s']):
        reasons.append('renamed_training_task_in_validation')
    if failures['candidate'] - failures['baseline'] > p['max_additional_failures']:
        reasons.append('quality_regression')
    if failures['baseline']:
        reasons.append('baseline_quality_failed')
    if not adoptions:
        reasons.append('no_actual_candidate_adoption')
    net = None if incomplete else costs['baseline'] - costs['candidate'] - costs['overhead']
    # Validation is an investment, not free evidence. This is a prospective
    # amortization estimate; actual cumulative savings require later tasks.
    projected = (None if incomplete else
                 (costs['baseline'] - costs['candidate']) / len(heldout) * p['horizon_tasks'] - sum(costs.values()))
    if net is not None and net <= p['min_net_gain_usd']:
        reasons.append('net_model_cost_not_improved')
    if projected is not None and projected <= p['min_net_gain_usd']:
        reasons.append('projected_gain_does_not_repay_trial')
    if (counts['baseline'] - counts['candidate'] - counts['overhead']) / len(heldout) < p['min_request_reduction']:
        reasons.append('net_model_requests_not_improved')
    action = 'reject' if reasons else 'defer' if incomplete else 'accept'
    if incomplete:
        reasons.append('quality_or_cost_evidence_incomplete')
    if not reasons:
        reasons = ['paired_quality_cost_and_actual_adoption_verified']
    return envelope('optimization_verdict', dict(
        id='verdict-' + digest(measurements)[:16], plan_id=plan['id'], plan_sha256=digest(plan_bytes),
        candidate_id=c['id'], candidate_sha256=candidate_sha, measurement_sha256=digest(measurements), evaluator=plan['evaluator'],
        action=action, reasons=sorted(set(reasons)), baseline_model_usd=None if 'baseline' in unknown_arms else costs['baseline'],
        candidate_model_usd=None if 'candidate' in unknown_arms else costs['candidate'], overhead_model_usd=None if 'overhead' in unknown_arms else costs['overhead'],
        comparison_net_usd=net, experiment_total_model_usd=None if incomplete else sum(costs.values()),
        projected_future_net_usd=projected,
        known_model_usd=sum(row['observed_peak_usd'] for row in providers.values()
                            if row['phase'] in ('completed', 'failed') and row['observed_peak_usd'] is not None),
        unsettled_requests=sum(row['phase'] not in ('completed', 'failed') or row['observed_peak_usd'] is None for row in providers.values()),
        reserved_upper_usd=(None if any(row['reserved_upper_usd'] is None for row in providers.values()
                            if row['phase'] not in ('completed', 'failed') or row['observed_peak_usd'] is None)
                            else sum(row['reserved_upper_usd'] for row in providers.values()
                            if row['phase'] not in ('completed', 'failed') or row['observed_peak_usd'] is None)),
        baseline_requests=counts['baseline'], candidate_requests=counts['candidate'], overhead_requests=counts['overhead'],
        baseline_failures=failures['baseline'], candidate_failures=failures['candidate'], actual_adoptions=adoptions,
        validation_task_ids=heldout))
