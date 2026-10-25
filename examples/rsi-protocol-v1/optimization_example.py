"""Synthetic accounting/quality witnesses, not benchmark or saved real dollars."""
import json
from pathlib import Path

from src.adapters.rsi_protocol import envelope
from src.adapters.rsi_optimization import digest, assess_opportunities

ROOT = Path(__file__).resolve().parents[2]


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def example():
    fixtures = json.loads((ROOT / 'examples/rsi-protocol-v1/fixtures.json').read_text())
    versions = fixtures['versions']
    candidate = next(r for r in fixtures['records'] if r['record_type'] == 'candidate_patch' and r['payload']['patch_kind'] == 'rule_revision')
    candidate['payload']['training_task_ids'] = ['experimental-report-A', 'registration-summary-B']
    diagnosis = next(r for r in fixtures['records'] if r['record_type'] == 'diagnosis' and r['payload']['component'] == 'motif')
    conditions, rubric = digest(b'fixed-model-tools-prompts-mode-v1'), digest(b'synthetic-exact-counts-and-rejections-v1')
    policy = envelope('optimization_policy', dict(id='diagnostic-policy-not-paper-threshold',
        min_discovery_tasks=2, min_validation_tasks=2, horizon_tasks=20,
        estimated_overhead_usd=.03, min_net_gain_usd=0, min_request_reduction=0, max_additional_failures=0))

    def bundle(tasks, validation=False):
        runs, providers, audits = [], [], []
        for task in tasks:
            for arm in (['baseline', 'candidate'] if validation else ['baseline']):
                run_id = task + '-' + arm
                refs = []
                for i in range(2 if arm == 'baseline' else 1):
                    ref = dict(ledger_ref='synthetic-' + run_id, id=str(i))
                    refs.append(ref)
                    providers.append(envelope('provider_request', dict(**ref, task_id=task,
                        model='synthetic-no-api', phase='completed', prompt_tokens=100, cache_hit_tokens=0,
                        cache_miss_tokens=100, output_tokens=10, observed_peak_usd=.01 if arm == 'baseline' else .004,
                        reserved_upper_usd=.02)))
                current = json.loads(json.dumps(versions))
                if arm == 'candidate':
                    current['motif'] = candidate['payload']['next_version']
                runs.append(envelope('optimization_run', dict(id=run_id, task_id=task,
                    task_sha256=digest(task.encode()), task_family='counting',
                    split='validation' if validation else 'training', arm=arm,
                    conditions_sha256=conditions, trace_sha256=digest(run_id.encode()), versions=current,
                    candidate_sha256=digest(encode(candidate)) if arm == 'candidate' else None,
                    provider_requests=refs, quality='passed', quality_sha256=rubric,
                    actual_adoptions=1 if arm == 'candidate' else 0, wall_time_ms=10, manual_review_seconds=1)))
                if not validation:
                    audits.append(envelope('optimization_boundary', dict(id='audit-' + run_id, run_id=run_id,
                        structure_key='table.group_count', component='motif', cause='repeated_execution',
                        disposition='verified_determinate', request_refs=refs,
                        witness_sha256=digest(('synthetic-whole-request-review-' + run_id).encode()))))
        return dict(expected_run_ids=[r['payload']['id'] for r in runs], runs=runs, providers=providers, audits=audits)

    discovery = bundle(['experimental-report-A', 'registration-summary-B'])
    measurement = bundle(['validation-report-D', 'validation-registration-E'], True)
    # A single additional model request covers diagnosis/proposal/validation in
    # this accounting example only. Real exporters must retain every attempt.
    overhead = json.loads(json.dumps(measurement['runs'][0]))
    overhead['payload'].update(id='optimization-overhead', task_id='optimization-overhead', arm='overhead', split='training',
        provider_requests=[dict(ledger_ref='synthetic-overhead', id='0')], actual_adoptions=0)
    measurement['runs'].append(overhead)
    measurement['expected_run_ids'].append(overhead['payload']['id'])
    provider = json.loads(json.dumps(measurement['providers'][0]))
    provider['payload'].update(ledger_ref='synthetic-overhead', task_id='optimization-overhead', observed_peak_usd=.002)
    measurement['providers'].append(provider)
    return dict(scope='人工费用与评审见证；只验证协议决策，不是实际节省',
        policy=policy, discovery=discovery, assessments=assess_opportunities(encode(discovery), encode(policy)),
        versions=versions, diagnosis=diagnosis, candidate=candidate,
        conditions_sha256=conditions, rubric_sha256=rubric, measurements=measurement,
        evaluator=dict(id='offline-evaluator-v1',sha256=digest((ROOT / 'src/adapters/rsi_optimization.py').read_bytes())),
        validation_tasks={task: digest(task.encode()) for task in ['validation-report-D', 'validation-registration-E']})
