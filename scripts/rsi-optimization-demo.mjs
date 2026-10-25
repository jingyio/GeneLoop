/** Free Python assessment -> TS start -> Python independent comparison demo. */
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {bytesSha256} from '../src/adapters/rsi_protocol.ts';
import {startRsiOptimization} from '../src/adapters/rsi_optimization.ts';

const python=process.env.SSS_PYTHON??(process.platform==='win32'?'python':'python3');
const cwd=fileURLToPath(new URL('../',import.meta.url));
const encode=JSON.stringify;
function offline(action,source){
 const run=spawnSync(python,['scripts/rsi-optimization.py',action,...(source?['--stdin']:[])],
  {cwd,input:source?encode(source):undefined,encoding:'utf8',maxBuffer:1_000_000,timeout:30000});
 if(run.status!==0)throw Error(run.stderr||'optimization_demo_failed');
 return JSON.parse(run.stdout);
}
const x=offline('demo-data');
const assessment=x.assessments[0],policy=encode(x.policy),raw=encode(assessment);
const host={versions:x.versions,sourceSha256:bytesSha256(encode(x.discovery)),policySha256:bytesSha256(policy),
 conditionsSha256:x.conditions_sha256,rubricSha256:x.rubric_sha256,evaluator:x.evaluator,
 approvedAssessments:new Map([[assessment.payload.id,bytesSha256(raw)]]),
 diagnoses:new Map([[x.diagnosis.payload.id,x.diagnosis]]),validationTasks:new Map(Object.entries(x.validation_tasks))};
const plan=startRsiOptimization(raw,policy,{diagnosisId:x.diagnosis.payload.id,validationTaskIds:[...host.validationTasks.keys()]},host);
const compare=measurements=>offline('evaluate',{plan:encode(plan),policy,candidate:encode(x.candidate),measurements:encode(measurements)}).payload;
const cases=[{case:'有独立重复、完整请求见证且预期收益覆盖开销',action:assessment.payload.action}];
for(const [name,mutate]of [
 ['仍混有语义判断，先核验',d=>{d.audits[0].payload.disposition='mixed_semantics';}],
 ['只是同一任务换名，不启动',d=>{d.runs[1].payload.task_sha256=d.runs[0].payload.task_sha256;}],
]){
 const d=structuredClone(x.discovery);mutate(d);
 const out=offline('assess',{source:encode(d),policy})[0].payload;
 cases.push({case:name,action:out.action,reasons:out.reasons});
}
const expensive=structuredClone(x.policy);expensive.payload.estimated_overhead_usd=10;
const skipped=offline('assess',{source:encode(x.discovery),policy:encode(expensive)})[0].payload;
cases.push({case:'预计收益抵不过开销',action:skipped.action,reasons:skipped.reasons});
cases.push({case:'质量通过、实际采用、含额外请求后仍有收益',...compare(x.measurements)});
for(const [name,mutate]of [
 ['质量变差，即使便宜也不通过',d=>{d.runs.find(r=>r.payload.arm==='candidate').payload.quality='failed';}],
 ['没有实际采用新版本，不通过',d=>{d.runs.forEach(r=>{r.payload.actual_adoptions=0;});}],
 ['额外开销抵消收益，不通过',d=>{d.providers.at(-1).payload.observed_peak_usd=1;}],
 ['费用未知，保留待核验',d=>{d.providers.at(-1).payload.observed_peak_usd=null;}],
]){
 const d=structuredClone(x.measurements);mutate(d);cases.push({case:name,...compare(d)});
}
if(process.argv.includes('--json'))console.log(JSON.stringify({scope:x.scope,plan:plan.payload,cases},null,2));
else{
 console.log(x.scope+'。不调用模型。');
 const labels={start:'值得试验',defer:'待核验',skip:'跳过',accept:'可进入发布审核',reject:'不接受更新'};
 cases.forEach(c=>console.log(`- ${c.case} → ${labels[c.action]}`));
 console.log('启动时固定：改动组件、允许修改类型、基线版本、留出任务与输入、质量标准、停止条件。');
 console.log('计费同时展示：配对差额减额外开销；以及实验实际总支出。人工/耗时另列，未折算为模型费。');
 console.log('查看记录可加 -- --json；真实生成修改由 F05/F08 接入，生产发布仍需独立审核及原生守卫。');
}
