"""Build the v1 wire contract using the already enforced DSH schema subset."""
from pathlib import Path
import argparse
import json

ROOT = Path(__file__).resolve().parents[1]


def obj(**fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


def arr(item):
    return dict(type='array', items=item)


def enum(*values):
    return dict(type='string', enum=list(values))


def build():
    s, b, n = {'type': 'string'}, {'type': 'boolean'}, {'type': 'integer'}
    nullable = {'oneOf': [s, {'type': 'null'}]}
    nullable_count = {'oneOf': [n, {'type': 'null'}]}
    nullable_cost = {'oneOf': [{'type': 'number'}, {'type': 'null'}]}
    version = obj(id=s, sha256=s)
    versions = obj(motif=version, matcher=version)
    reference = obj(id=s, sha256=s, version=s)
    refs = arr(reference)
    request_ref = obj(ledger_ref=s, id=s)
    payloads = {
        'provider_request': obj(id=s, task_id=s, ledger_ref=s, model=s,
                        phase=enum('booked', 'completed', 'failed', 'unknown'),
                        prompt_tokens=nullable_count, cache_hit_tokens=nullable_count,
                        cache_miss_tokens=nullable_count, output_tokens=nullable_count,
                        observed_peak_usd=nullable_cost, reserved_upper_usd=nullable_cost),
        'evidence': obj(id=s, task_id=s, subject=s, sha256=s, version=s,
                        role=enum('training', 'validation', 'current', 'test'),
                        status=enum('valid', 'invalidated'), observation_id=s,
                        origin=enum('tool', 'bash', 'python', 'user')),
        'operator': obj(id=s, operation=s, description=s,
                        source_kind=enum('tool', 'bash', 'python'),
                        structure_signature=arr(s), input_schema={}, output_schema={},
                        parameter_sources=arr(obj(parameter=s, source=enum('task_input', 'evidence', 'prior_output'), ref=s, pointer=s)),
                        dependencies=refs, effect=enum('read', 'workspace_write', 'external_write', 'opaque'),
                        code_sha256=nullable, opaque=b, certificate_ref=s),
        'execution_event': obj(id=s, task_id=s, sequence=n, call_id=s,
                        source_kind=enum('tool', 'bash', 'python'), operation=s,
                        phase=enum('started', 'succeeded', 'failed'),
                        arguments_sha256=s, result_sha256=nullable,
                        dependencies=refs, permission_ref=s, versions=versions,
                        provider_call_id=nullable, error=nullable),
        'runtime_request': obj(id=s, task_id=s, operator_id=s, operation=s,
                        arguments_sha256=s, dependencies=refs, versions=versions,
                        obligation_ref=s, state_version=s),
        'runtime_decision': obj(request_id=s, task_id=s,
                        action=enum('execute', 'handoff', 'reject'), reason=s,
                        versions=versions, evidence_ids=arr(s)),
        'diagnosis': obj(id=s, component=enum('motif', 'matcher'), reason=s,
                        base_version=version, feedback=refs),
        'candidate_patch': obj(id=s, diagnosis_id=s,
                        patch_kind=enum('rule_revision', 'motif_split', 'matcher_code_patch'),
                        component=enum('motif', 'matcher'), base_version=version,
                        next_version=version, compatible_versions=versions,
                        feedback=refs, affected_operator_ids=arr(s),
                        payload_sha256=s, diff_ref=s, training_task_ids=arr(s)),
        'validation_report': obj(id=s, candidate_id=s, candidate_sha256=s,
                        base_version=version, validator=version, passed=b,
                        checks=arr(obj(name=s, passed=b)), evidence=refs,
                        independent_task_ids=arr(s)),
        'publication_receipt': obj(id=s, candidate_id=s, report_id=s,
                        previous_versions=versions, next_versions=versions,
                        manifest_sha256=s),
        'rollback_receipt': obj(id=s, publication_id=s, reason=s,
                        previous_versions=versions, restored_versions=versions,
                        manifest_sha256=s),
        # Candidate v1 extensions; these describe measured evidence, never grants.
        'optimization_policy': obj(id=s, min_discovery_tasks=n, min_validation_tasks=n,
                        horizon_tasks=n, estimated_overhead_usd={'type': 'number'},
                        min_net_gain_usd={'type': 'number'}, min_request_reduction={'type': 'number'},
                        max_additional_failures=n),
        'optimization_run': obj(id=s, task_id=s, task_sha256=s, task_family=s,
                        split=enum('training', 'validation', 'test'),
                        arm=enum('baseline', 'candidate', 'overhead'),
                        conditions_sha256=s, trace_sha256=s, versions=versions,
                        candidate_sha256=nullable, provider_requests=arr(request_ref),
                        quality=enum('passed', 'failed', 'unreviewed'), quality_sha256=nullable,
                        actual_adoptions=n, wall_time_ms=nullable_cost, manual_review_seconds=nullable_cost),
        'optimization_boundary': obj(id=s, run_id=s, structure_key=s,
                        component=enum('motif', 'matcher'),
                        cause=enum('repeated_execution', 'rule_failure', 'matcher_miss', 'unknown'),
                        disposition=enum('verified_determinate', 'mixed_semantics', 'unknown'),
                        request_refs=arr(request_ref), witness_sha256=s),
        'optimization_assessment': obj(id=s, structure_key=s, component=enum('motif', 'matcher'),
                        action=enum('start', 'defer', 'skip'), reasons=arr(s),
                        source_sha256=s, policy_sha256=s, versions=versions,
                        discovery_task_ids=arr(s), discovery_task_sha256s=arr(s), run_ids=arr(s), audit_ids=arr(s),
                        avoidable_request_count=n, avoidable_model_usd=nullable_cost,
                        population_task_count=n, projected_net_usd=nullable_cost),
        'optimization_plan': obj(id=s, assessment_id=s, assessment_sha256=s,
                        source_sha256=s, policy_sha256=s, component=enum('motif', 'matcher'),
                        structure_key=s, diagnosis_id=s, base_versions=versions,
                        discovery_task_ids=arr(s), discovery_task_sha256s=arr(s), validation_task_ids=arr(s),
                        validation_inputs=arr(obj(task_id=s, sha256=s)),
                        conditions_sha256=s, rubric_sha256=s, evaluator=version,
                        allowed_patch_kinds=arr(enum('rule_revision', 'motif_split', 'matcher_code_patch')),
                        required_checks=arr(s),
                        stop_conditions=arr(s)),
        'optimization_verdict': obj(id=s, plan_id=s, plan_sha256=s,
                        candidate_id=s, candidate_sha256=s, measurement_sha256=s, evaluator=version,
                        action=enum('accept', 'reject', 'defer'), reasons=arr(s),
                        baseline_model_usd=nullable_cost, candidate_model_usd=nullable_cost,
                        overhead_model_usd=nullable_cost, comparison_net_usd=nullable_cost,
                        experiment_total_model_usd=nullable_cost,
                        projected_future_net_usd=nullable_cost,
                        known_model_usd={'type': 'number'}, unsettled_requests=n, reserved_upper_usd=nullable_cost,
                        baseline_requests=n, candidate_requests=n, overhead_requests=n,
                        baseline_failures=n, candidate_failures=n, actual_adoptions=n,
                        validation_task_ids=arr(s)),
    }
    return {'title': 'GeneLoop RSI Protocol v1',
            'description': 'Transport validation is not execution authorization. Trusted host guards remain mandatory.',
            'oneOf': [obj(protocol={'type': 'string', 'const': 'geneloop.rsi/v1'},
                          record_type={'type': 'string', 'const': kind}, payload=payload)
                      for kind, payload in payloads.items()]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'schemas/rsi-protocol-v1.schema.json'
    rendered = json.dumps(build(), ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if target.read_text(encoding='utf-8') != rendered:
            raise SystemExit('RSI schema differs; run python scripts/build-rsi-schema.py')
    else:
        target.write_text(rendered, encoding='utf-8')
