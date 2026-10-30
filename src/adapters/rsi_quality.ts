/** Common quality interpretation; required criteria and artifact authority come from the scene. */
import {validateRsiRecord} from './rsi_protocol.ts';
export function qualityStatus(record:unknown,binding:{task_sha256:string;artifact_sha256:string;rubric_sha256:string},requiredChecks:string[]){
 const r=validateRsiRecord(record);
 if(r.record_type!=='quality_evaluation')throw Error('quality_record_kind');
 const p=r.payload;
 if(Object.entries(binding).some(([key,value])=>p[key]!==value))throw Error('quality_artifact_binding_changed');
 const checks=new Map<string,any>(p.checks.map((c:any)=>[c.id,c]));
 if(checks.size!==p.checks.length||!requiredChecks.length||requiredChecks.some(id=>!checks.has(id)))throw Error('quality_required_checks_missing_or_duplicate');
 for(const c of checks.values())if(!c.observation.trim()||(c.status!=='unknown'&&!c.evidence.length))throw Error('quality_observation_or_evidence_missing');
 const statuses=requiredChecks.map(id=>checks.get(id).status);
 return statuses.includes('failed')?'failed':statuses.includes('unknown')?'unknown':'passed';
}
