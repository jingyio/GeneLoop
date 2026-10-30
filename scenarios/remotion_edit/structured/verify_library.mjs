/** Synthetic protocol diagnostics only. Never count these receipts as paid-task savings. */
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {createOnlineInterceptor} from '../../../src/adapters/dsh_online_motif.mjs';
import {digest,validateOnlineManifest,parseStructuredTask} from '../../../src/motif_core/online_skill_runtime.mjs';
import {apply as installScene} from './plugin.ts';

const base=process.env.REMOTION_EXPERIMENT_ROOT,exp=join(base,'structured-v1');
const manifestPath=join(exp,'library/online-manifest.json');
const manifest=JSON.parse(readFileSync(manifestPath,'utf8'));
validateOnlineManifest(manifest);
const run=join(exp,'runs/v1/execute/t34_two_views');
const task=JSON.parse(readFileSync(join(run,'structured-task.json'),'utf8'));
const effective=JSON.parse(readFileSync(join(run,'effective.json'),'utf8'));
parseStructuredTask(task,manifest);
const train=join(exp,'runs/v1/typed/t31_train_zoom');
const original=JSON.parse(readFileSync(join(train,'result.json'),'utf8'));
const request=JSON.parse(readFileSync(join(base,'requests',String(original.request_ids[0]).padStart(6,'0')+'.json'),'utf8'));
const tools=request.tools.map(t=>({name:t.function.name,parameters:t.function.parameters}));
const pin='mcp__remotion__pin_asset',read='mcp__remotion__probe_media';
const name='bunny_c_60.mp4',version=effective.assets[name],source='source-'+'a'.repeat(32);
const output={name,source_id:source,source_version:version,bytes:1};
const ok=value=>({isError:false,value,content:[{type:'text',text:JSON.stringify(value)}]});
const checks={};let modelFallbacks=0;
function setup(){
 const audit=[];
 const interceptor=createOnlineInterceptor({manifest,task,mode:'execute',
   similarity:async()=>{throw Error('semantic matching intentionally unavailable');},audit:r=>audit.push(r)});
 return {audit,interceptor};
}
function observePin(interceptor,value=output){interceptor.observe(task.session_id,
 {name:pin,callId:'diagnostic-pin',arguments:{name}},ok(value));}
const next=()=>{modelFallbacks++;return(async function*(){})();};
async function drain(stream){for await(const item of stream){void item;}}
{
 const {audit,interceptor}=setup();observePin(interceptor);
 await drain(await interceptor.intercept(task.session_id,{tools,messages:[]},next));
 const attempt=audit.find(r=>r.kind==='motif_bypass_attempt');assert(attempt);
 assert.deepEqual(attempt.tools,[read]);assert.equal(modelFallbacks,0);
 interceptor.observe(task.session_id,{name:read,callId:attempt.call_ids[0],arguments:{source_id:source}},ok(output));
 assert.equal(audit.filter(r=>r.kind==='model_request_skipped_verified').length,1);
 checks.complete_verified_batch_diagnostic=true;
}
{
 const {audit,interceptor}=setup();observePin(interceptor,{...output,source_version:'0'.repeat(64)});
 await drain(await interceptor.intercept(task.session_id,{tools,messages:[]},next));
 assert(!audit.some(r=>r.kind==='motif_bypass_attempt'));checks.stale_version_falls_back=true;
}
{
 const {audit,interceptor}=setup();observePin(interceptor);
 const changed=structuredClone(tools);changed.find(t=>t.name===read).parameters.properties.unapproved={type:'string'};
 await drain(await interceptor.intercept(task.session_id,{tools:changed,messages:[]},next));
 assert(!audit.some(r=>r.kind==='motif_bypass_attempt'));checks.changed_schema_falls_back=true;
}
{
 const {audit,interceptor}=setup();observePin(interceptor);
 await drain(await interceptor.intercept(task.session_id,{tools,messages:[]},next));
 const attempt=audit.find(r=>r.kind==='motif_bypass_attempt');assert(attempt);
 interceptor.observe(task.session_id,{name:read,callId:attempt.call_ids[0],arguments:{source_id:source}},{isError:true});
 assert(audit.some(r=>r.kind==='bypass_result_unverified'));
 assert(!audit.some(r=>r.kind==='model_request_skipped_verified'));
 assert(interceptor.state(task.session_id).halted);checks.failed_result_never_verified=true;
}
process.env.SSS_ONLINE_MOTIF_MANIFEST=manifestPath;
process.env.SSS_ONLINE_MOTIF_TASK=join(run,'structured-task.json');
process.env.SSS_ONLINE_MOTIF_MODE='execute';
process.env.SSS_ONLINE_MOTIF_PROMPT_SHA256=effective.prompt_sha256;
process.env.SSS_REMOTION_IMAGE=effective.image;
installScene({on(){}});checks.scene_installs_with_actual_locks=true;
const diagnostic=join(exp,'diagnostics');mkdirSync(diagnostic,{recursive:true});
const changed=structuredClone(manifest);changed.scene_code_locks['scenarios/remotion_edit/structured/server.py']='0'.repeat(64);
changed.manifest_digest=digest(Object.fromEntries(Object.entries(changed).filter(([k])=>k!=='manifest_digest')));
const bad=join(diagnostic,'changed-code-manifest.json');writeFileSync(bad,JSON.stringify(changed));
process.env.SSS_ONLINE_MOTIF_MANIFEST=bad;
assert.throws(()=>installScene({on(){}}),/implementation changed/);checks.changed_code_rejected=true;
const report={checks,all_pass:true,model_requests:0,actual_task_verified_skips:0,
 scope:'synthetic protocol diagnostics against the real learned library; never count as model behavior or actual savings'};
writeFileSync(join(diagnostic,'compiled-library-validation.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
