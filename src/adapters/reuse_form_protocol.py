"""Adapt a measured source-form update to F02's shared validation contract.

The form snapshot owns its linked source pool. The legacy tool-Motif component
is inactive here; the source runtime is the separately versioned matcher.
"""
import hashlib,json,shutil,subprocess
from pathlib import Path
from .rsi_protocol import envelope

ROOT=Path(__file__).resolve().parents[2]


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n'
def sha(value):return hashlib.sha256(value.encode()).hexdigest()


def form_update_bundle(proposal,verdict,library,measurements,previous,payload_sha256):
    version=lambda value:{'id':'form-'+value[:24],'sha256':value}
    base=version(previous['proposal_digest'] if previous else sha('reuse-form/genesis'))
    runtime=ROOT/'src/adapters/source_program_runtime.ts'
    versions={'motif':{'id':'legacy-tool-motif-inactive','sha256':sha('legacy-tool-motif-inactive')},
        'matcher':{'id':'source-program-runtime','sha256':hashlib.sha256(runtime.read_bytes()).hexdigest()},'reuse_form':base}
    feedback_id='form-feedback-'+proposal['evidence_sha256'][:24]
    training={p.get('source_witness',{}).get('task_id') for p in library['programs']}-{None}
    training.add(feedback_id)
    feedback=envelope('evidence',{'id':feedback_id,'task_id':feedback_id,'subject':'prior_form_measurements',
        'sha256':proposal['evidence_sha256'],'version':proposal['evidence_sha256'],'role':'training',
        'status':'valid','observation_id':feedback_id,'origin':'python'})
    ref=lambda e:{k:e['payload'][k] for k in ('id','sha256','version')}
    diagnosis=envelope('diagnosis',{'id':'diagnosis-'+proposal['digest'][:24],'component':'reuse_form',
        'reason':'Measured source-program representation and interface update','base_version':base,'feedback':[ref(feedback)]})
    candidate=envelope('candidate_patch',{'id':proposal['digest'],'diagnosis_id':diagnosis['payload']['id'],
        'component':'reuse_form','patch_kind':'reuse_form_revision','base_version':base,
        'next_version':version(proposal['digest']),'compatible_versions':versions,'feedback':[ref(feedback)],
        'affected_operator_ids':[p['id'] for p in library['programs']],'payload_sha256':payload_sha256,
        'diff_ref':'reuse-form/proposal','training_task_ids':sorted(training)})
    validation=[]
    for row in measurements['runs']:
        if row['arm']!='program':continue
        task=row['task'];value=row.get('quality_sha256') or row.get('verification_sha256')
        if not value:raise ValueError('form_validation_evidence_missing')
        validation.append(envelope('evidence',{'id':'validation-'+task,'task_id':task,'subject':'paired_task_quality',
            'sha256':value,'version':value,'role':'validation','status':'valid','observation_id':'validation-'+task,'origin':'python'}))
    tasks=sorted({e['payload']['task_id'] for e in validation})
    if len(tasks)!=len(validation):raise ValueError('form_duplicate_validation_task')
    evaluator={'id':'reuse-form-qualified-forward-cost','sha256':measurements['evaluator_sha256']}
    report=envelope('validation_report',{'id':'validation-'+verdict['digest'][:24],'candidate_id':proposal['digest'],
        'candidate_sha256':sha(encoded(candidate)),'base_version':base,'validator':evaluator,'passed':verdict['accepted'],
        'checks':[{'name':name,'passed':True} for name in ('paired_conditions','task_quality','actual_adoption','full_model_cost')],
        'evidence':[ref(e) for e in validation],'independent_task_ids':tasks})
    return {'candidate':encoded(candidate),'report':encoded(report),'versions':versions,
        'payload_sha256':payload_sha256,'evidence':[feedback,*validation],'diagnoses':[diagnosis]}


def validate_form_update(bundle):
    node=shutil.which('node')
    if not node:raise ValueError('form_protocol_node_required')
    process=subprocess.run([node,'--experimental-strip-types',str(ROOT/'scripts/validate-reuse-form-update.mjs')],
        input=encoded(bundle),capture_output=True,text=True,cwd=ROOT)
    if process.returncode:raise ValueError('form_protocol_update_rejected: '+process.stderr[-1500:])
    return json.loads(process.stdout)
