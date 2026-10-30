/** Online boundaries for the offline evaluator. Approved hashes belong to the
 * trusted reviewer/registry, never the model or the proposed patch itself. */
import {randomUUID} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {decodeRsiRecord, rsiRecord, publishRsiUpdate} from './rsi_protocol.ts';
import type {RsiRecord, Versions, UpdateHost} from './rsi_protocol.ts';

const equal=isDeepStrictEqual;
const check=(ok:boolean,reason:string)=>{if(!ok)throw Error(reason);};

export type OptimizationStartHost={
 versions:Versions;
 sourceSha256:string;
 policySha256:string;
 conditionsSha256:string;
 rubricSha256:string;
 evaluator:{id:string;sha256:string}; // Independently checked protected evaluator bytes.
 approvedAssessments:Map<string,string>;
 diagnoses:Map<string,RsiRecord>;
 /** Independent task inventory, excluding training and frozen Test. */
 validationTasks:Map<string,string>; // task id -> current input SHA-256
};

/** Freeze scope before asking any optimizer to generate a patch. A plan is an
 * experiment instruction, not permission to execute arbitrary code or tools. */
export function startRsiOptimization(assessmentBytes:string|Buffer,policyBytes:string|Buffer,
 selection:{diagnosisId:string;validationTaskIds:string[]},host:OptimizationStartHost):RsiRecord {
 const assessment=decodeRsiRecord(assessmentBytes),policy=decodeRsiRecord(policyBytes);
 check(assessment.record.record_type==='optimization_assessment'&&policy.record.record_type==='optimization_policy','optimization_record_kind_mismatch');
 const a=assessment.record.payload,p=policy.record.payload;
 check(a.action==='start','optimization_not_worth_starting');
 check(host.approvedAssessments.get(a.id)===assessment.sha256,'optimization_assessment_not_independently_approved');
 check(a.source_sha256===host.sourceSha256,'optimization_source_changed');
 check(a.policy_sha256===policy.sha256&&host.policySha256===policy.sha256,'optimization_policy_changed');
 check(equal(a.versions,host.versions),'optimization_stale_parent');
 check(p.min_discovery_tasks>=1&&p.min_validation_tasks>=1&&p.horizon_tasks>=1&&
  [p.estimated_overhead_usd,p.min_net_gain_usd,p.min_request_reduction,p.max_additional_failures].every(n=>n>=0),'optimization_policy_invalid');
 check(new Set(a.discovery_task_ids).size>=p.min_discovery_tasks&&
  new Set(a.discovery_task_sha256s).size>=p.min_discovery_tasks,'optimization_discovery_insufficient');
 const diagnosis=host.diagnoses.get(selection.diagnosisId);
 check(diagnosis?.record_type==='diagnosis'&&diagnosis.payload.component===a.component&&
  equal(diagnosis.payload.base_version,host.versions[a.component as keyof Versions]),'optimization_diagnosis_binding_invalid');
 const ids=selection.validationTaskIds,hashes=ids.map(id=>host.validationTasks.get(id));
 check(ids.length>=p.min_validation_tasks&&new Set(ids).size===ids.length&&
  !ids.some(id=>a.discovery_task_ids.includes(id))&&hashes.every(Boolean)&&
  new Set(hashes).size===ids.length&&!hashes.some(sha=>a.discovery_task_sha256s.includes(sha)),
  'optimization_validation_scope_invalid');
 return rsiRecord('optimization_plan',{
  id:randomUUID(),assessment_id:a.id,assessment_sha256:assessment.sha256,
  source_sha256:a.source_sha256,policy_sha256:policy.sha256,component:a.component,
  structure_key:a.structure_key,diagnosis_id:selection.diagnosisId,base_versions:host.versions,
  discovery_task_ids:a.discovery_task_ids,discovery_task_sha256s:a.discovery_task_sha256s,
  validation_task_ids:ids,conditions_sha256:host.conditionsSha256,rubric_sha256:host.rubricSha256,
  evaluator:host.evaluator,
  validation_inputs:ids.map((id,index)=>({task_id:id,sha256:hashes[index]})),
  allowed_patch_kinds:a.component==='reuse_form'?['reuse_form_revision']:a.component==='matcher'?['matcher_code_patch']:['rule_revision','motif_split'],
  required_checks:['task_quality','paired_conditions','independent_tasks','full_model_cost','actual_adoption','native_guards'],
  stop_conditions:['stale_parent','evidence_changed','quality_regression','no_net_gain','native_guard_denied']});
}

export type OptimizationPublicationHost=UpdateHost&{
 planSha256:string;
 verdictSha256:string;
 /** Independent evaluation approval over exact stored verdict bytes. */
 approvedVerdicts:Map<string,string>;
 evaluator:{id:string;sha256:string};
};

/** For optimized publication, both the measured benefit gate AND the original
 * native update/certification gate must succeed. Rollback uses the existing
 * bound publication receipt. The old generic API remains a compatibility seam. */
export async function publishOptimizedRsiUpdate(candidateBytes:string|Buffer,reportBytes:string|Buffer,
 planBytes:string|Buffer,verdictBytes:string|Buffer,readHost:()=>OptimizationPublicationHost,
 commit:Parameters<typeof publishRsiUpdate>[3]){
 const host=readHost(),plan=decodeRsiRecord(planBytes),verdict=decodeRsiRecord(verdictBytes);
 const candidate=decodeRsiRecord(candidateBytes);
 const report=decodeRsiRecord(reportBytes);
 check(plan.record.record_type==='optimization_plan'&&verdict.record.record_type==='optimization_verdict'&&
  candidate.record.record_type==='candidate_patch'&&report.record.record_type==='validation_report','optimization_record_kind_mismatch');
 const p=plan.record.payload,v=verdict.record.payload,c=candidate.record.payload;
 check(plan.sha256===host.planSha256&&verdict.sha256===host.verdictSha256,'optimization_review_bytes_changed');
 check(host.approvedVerdicts.get(v.id)===verdict.sha256,'optimization_verdict_not_independently_approved');
 check(v.action==='accept','optimization_evaluation_not_accepted');
 check(equal(v.evaluator,p.evaluator)&&equal(p.evaluator,host.evaluator),'optimization_evaluator_changed');
 check(v.plan_id===p.id&&v.plan_sha256===plan.sha256&&v.candidate_id===c.id&&
  v.candidate_sha256===candidate.sha256,'optimization_verdict_binding_invalid');
 check(p.component===c.component&&p.diagnosis_id===c.diagnosis_id&&equal(p.base_versions,host.versions),
  'optimization_plan_binding_invalid');
 check(p.allowed_patch_kinds.includes(c.patch_kind),'optimization_patch_kind_not_planned');
 check(equal([...v.validation_task_ids].sort(),[...p.validation_task_ids].sort()),'optimization_validation_scope_changed');
 check(equal([...report.record.payload.independent_task_ids].sort(),[...p.validation_task_ids].sort()),'optimization_report_scope_changed');
 check(p.required_checks.length>0&&p.required_checks.every((name:string)=>
  report.record.payload.checks.some((check:any)=>check.name===name&&check.passed)),
  'optimization_required_check_missing');
 return publishRsiUpdate(candidateBytes,reportBytes,()=>host,commit);
}
