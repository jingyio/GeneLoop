"""Scene-independent quality evidence; scene adapters choose checks and inspect artifacts."""
from pathlib import Path
from .rsi_protocol import validate_record
import hashlib


def quality_status(record, *, task_sha256, artifact_sha256, rubric_sha256, required_checks):
    record = validate_record(record)
    if record['record_type'] != 'quality_evaluation':
        raise ValueError('quality_record_kind')
    p = record['payload']
    if any(p[k] != value for k, value in (
        ('task_sha256', task_sha256), ('artifact_sha256', artifact_sha256), ('rubric_sha256', rubric_sha256))):
        raise ValueError('quality_artifact_binding_changed')
    checks = {c['id']: c for c in p['checks']}
    if len(checks) != len(p['checks']) or not required_checks or not set(required_checks) <= checks.keys():
        raise ValueError('quality_required_checks_missing_or_duplicate')
    for c in checks.values():
        if not c['observation'].strip() or (c['status'] != 'unknown' and not c['evidence']):
            raise ValueError('quality_observation_or_evidence_missing')
    selected = [checks[key]['status'] for key in required_checks]
    return 'failed' if 'failed' in selected else 'unknown' if 'unknown' in selected else 'passed'


def verify_quality_files(record, root):
    """Verify referenced bytes independently of the reviewer-provided verdict."""
    root = Path(root).resolve()
    for check in record['payload']['checks']:
        for ref in check['evidence']:
            path = (root / ref['ref']).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('quality_evidence_missing_or_outside_run')
            if hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
                raise ValueError('quality_evidence_changed')
