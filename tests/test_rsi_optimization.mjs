import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {bytesSha256,validateRsiRecord} from '../src/adapters/rsi_protocol.ts';
import {startRsiOptimization,publishOptimizedRsiUpdate} from '../src/adapters/rsi_optimization.ts';
import {fixtureRecord} from '../examples/rsi-protocol-v1/host.mjs';

const cwd=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.SSS_PYTHON??(process.platform==='win32'?'python':'python3');
const encode=JSON.stringify;
function offline(action,source){
 const run=spawnSync(python,['scripts/rsi-optimization.py',action,...(source?['--stdin']:[])],
  {cwd,input:source?encode(source):undefined,encoding:'utf8',maxBuffer:1_000_000,timeout:30000});
 assert.equal(run.status,0,run.stderr);return JSON.parse(run.stdout);
}
const example=offline('demo-data');
function context(){
 const x=structuredClone(example),assessment=x.assessments[0],policy=encode(x.policy),raw=encode(assessment);
 const host={versions:x.versions,sourceSha256:bytesSha256(encode(x.discovery)),policySha256:bytesSha256(policy),
  conditionsSha256:x.conditions_sha256,rubricSha256:x.rubric_sha256,evaluator:x.evaluator,
  approvedAssessments:new Map([[assessment.payload.id,bytesSha256(raw)]]),
  diagnoses:new Map([[x.diagnosis.payload.id,x.diagnosis]]),validationTasks:new Map(Object.entries(x.validation_tasks))};
 const selection={diagnosisId:x.diagnosis.payload.id,validationTaskIds:[...host.validationTasks.keys()]};
 return {x,assessment,raw,policy,host,selection};
}
const planFor=x=>startRsiOptimization(x.raw,x.policy,x.selection,x.host);

test('new records cross the Python -> TS -> Python wire and freeze the actual task inputs',()=>{
 const x=context(),plan=planFor(x);
 const records=[x.x.policy,...x.x.discovery.runs,...x.x.discovery.providers,...x.x.discovery.audits,x.assessment,plan];
 records.forEach(validateRsiRecord);
 assert.equal(plan.payload.validation_inputs.length,2);
 const out=offline('evaluate',{plan:encode(plan),policy:x.policy,candidate:encode(x.x.candidate),measurements:encode(x.x.measurements)});
 validateRsiRecord(out);assert.equal(out.payload.action,'accept');
 assert.equal(out.payload.plan_sha256,bytesSha256(encode(plan)));
});

for(const [name,change,reason]of [
 ['unapproved assessment',x=>x.host.approvedAssessments.clear(),'not_independently_approved'],
 ['changed source',x=>{x.host.sourceSha256='0'.repeat(64);},'source_changed'],
 ['changed policy',x=>{x.host.policySha256='0'.repeat(64);},'policy_changed'],
 ['stale component',x=>{x.host.versions=structuredClone(x.host.versions);x.host.versions.motif.id='stale';},'stale_parent'],
 ['missing diagnosis',x=>x.host.diagnoses.clear(),'diagnosis_binding_invalid'],
 ['training task used for validation',x=>{x.selection.validationTaskIds[0]='experimental-report-A';},'validation_scope_invalid'],
 ['renamed training bytes',x=>{x.host.validationTasks.set(x.selection.validationTaskIds[0],x.assessment.payload.discovery_task_sha256s[0]);},'validation_scope_invalid'],
 ['unknown heldout task',x=>{x.host.validationTasks.clear();},'validation_scope_invalid'],
 ['duplicate validation task',x=>{x.selection.validationTaskIds.fill(x.selection.validationTaskIds[0]);},'validation_scope_invalid'],
])test(`${name} cannot initiate an optimization`,()=>{
 const x=context();change(x);assert.throws(()=>planFor(x),new RegExp(reason));
});

test('an independently reviewed defer/skip assessment still cannot start',()=>{
 for(const action of ['defer','skip']){
  const x=context();x.assessment.payload.action=action;x.raw=encode(x.assessment);
  x.host.approvedAssessments.set(x.assessment.payload.id,bytesSha256(x.raw));
  assert.throws(()=>planFor(x),/not_worth_starting/);
 }
});

function publicationContext(){
 const x=context(),plan=planFor(x),candidate=x.x.candidate,candidateBytes=encode(candidate),planBytes=encode(plan);
 const verdict=offline('evaluate',{plan:planBytes,policy:x.policy,candidate:candidateBytes,measurements:encode(x.x.measurements)});
 const report=fixtureRecord('validation_report');
 report.payload.candidate_id=candidate.payload.id;report.payload.candidate_sha256=bytesSha256(candidateBytes);
 report.payload.independent_task_ids=plan.payload.validation_task_ids;
 report.payload.checks=plan.payload.required_checks.map(name=>({name,passed:true}));
 const training=fixtureRecord('evidence','training-failure');training.payload.task_id='experimental-report-A';
 const evidence=new Map([[training.payload.id,training]]);
 report.payload.evidence=plan.payload.validation_task_ids.map((id,index)=>{
  const e=fixtureRecord('evidence','validation-run');e.payload.id='heldout-'+index;e.payload.task_id=id;
  evidence.set(e.payload.id,e);return {id:e.payload.id,sha256:e.payload.sha256,version:e.payload.version};
 });
 const reportBytes=encode(report),verdictBytes=encode(verdict);
 const host={versions:x.x.versions,candidateSha256:bytesSha256(candidateBytes),payloadSha256:candidate.payload.payload_sha256,
  reportSha256:bytesSha256(reportBytes),approvedReports:new Map([[report.payload.id,bytesSha256(reportBytes)]]),
  evidence,diagnoses:x.host.diagnoses,planSha256:bytesSha256(planBytes),verdictSha256:bytesSha256(verdictBytes),
  approvedVerdicts:new Map([[verdict.payload.id,bytesSha256(verdictBytes)]]),evaluator:x.x.evaluator};
 return {candidateBytes,reportBytes,planBytes,verdictBytes,verdict,host};
}

test('benefit approval and the original certification must both pass before adapter commit',async()=>{
 const x=publicationContext();let commits=0;
 const receipt=await publishOptimizedRsiUpdate(x.candidateBytes,x.reportBytes,x.planBytes,x.verdictBytes,()=>x.host,
  async({next})=>{commits++;return {versions:next,manifestSha256:'a'.repeat(64)};});
 assert.equal(commits,1);assert.equal(receipt.record_type,'publication_receipt');
});

test('self-approved economics, changed records and failed certification never publish',async()=>{
 const base=publicationContext();
 for(const [change,reason]of [
  [x=>x.host.approvedVerdicts.clear(),'verdict_not_independently_approved'],
  [x=>{x.host.evaluator.sha256='0'.repeat(64);},'evaluator_changed'],
  [x=>{x.verdictBytes+=' ';},'review_bytes_changed'],
  [x=>{x.planBytes+=' ';},'review_bytes_changed'],
  [x=>x.host.approvedReports.clear(),'not_independently_approved'],
  [x=>{x.host.payloadSha256='0'.repeat(64);},'patch_payload_changed'],
  [x=>{
   const r=JSON.parse(x.reportBytes);r.payload.checks.pop();x.reportBytes=encode(r);
   x.host.reportSha256=bytesSha256(x.reportBytes);x.host.approvedReports.set(r.payload.id,x.host.reportSha256);
  },'required_check_missing'],
  [x=>{
   x.verdict.payload.action='reject';x.verdictBytes=encode(x.verdict);
   x.host.verdictSha256=bytesSha256(x.verdictBytes);
   x.host.approvedVerdicts.set(x.verdict.payload.id,x.host.verdictSha256);
  },'evaluation_not_accepted'],
 ]){
  const x=structuredClone(base);change(x);let commits=0;
  await assert.rejects(publishOptimizedRsiUpdate(x.candidateBytes,x.reportBytes,x.planBytes,x.verdictBytes,()=>x.host,
   async()=>{commits++;}),new RegExp(reason));
  assert.equal(commits,0);
 }
});
