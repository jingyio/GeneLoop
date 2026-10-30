import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
const options={skip:!process.features?.typescript};
const root=new URL('../',import.meta.url),library=new URL('motif-libraries/',root);
const versions=readdirSync(library).filter(name=>/^file-v[1-9][0-9]*$/.test(name)).sort((a,b)=>Number(b.slice(6))-Number(a.slice(6)));
const sourceCurrent=manifest=>Object.entries(manifest.runtime_source).every(([name,sha])=>
 createHash('sha256').update(readFileSync(new URL(name,root))).digest('hex')===sha);
test('public File provenance accepts current runtime binding and rejects altered witnesses',options,async()=>{
 const {validatePublicManagementSeed}=await import('../src/adapters/management_seed.ts');
 // This verifies publication provenance. Admission and execution separately
 // compare the policy's tool contracts and execution version with the task.
 const version=versions[0];
 const release=new URL('../motif-libraries/'+version+'/',import.meta.url);
 const manifest=JSON.parse(readFileSync(new URL('entry.json',release)));
 const runtime=Object.fromEntries(Object.keys(manifest.runtime_source).map(name=>
  [name,createHash('sha256').update(readFileSync(new URL(name,root))).digest('hex')]));
 assert.equal(manifest.entries.length,4,'all four certified graph shapes remain available');
 for(const entry of manifest.entries){
  const bytes=readFileSync(new URL(entry.payload,release)),policy=JSON.parse(bytes),cert=JSON.parse(readFileSync(new URL(entry.certificate,release)));
  const sha=createHash('sha256').update(bytes).digest('hex');
  assert.doesNotThrow(()=>validatePublicManagementSeed(policy,cert,sha,runtime));
  assert.throws(()=>validatePublicManagementSeed(policy,{...cert,grants_execution:true},sha,runtime));
  assert.throws(()=>validatePublicManagementSeed(policy,{...cert,witnesses:cert.witnesses.map((row,index)=>index?row:{...row,accepted:false})},sha,runtime));
  assert.throws(()=>validatePublicManagementSeed(policy,cert,sha,{...runtime,'fake-source':'changed'}));
 }
});

for(const version of versions.filter(name=>Number(name.slice(6))>=5))test(version+' File seeds cannot acquire execution authority with changed source bytes',options,async()=>{
 const {validatePublicManagementSeed}=await import('../src/adapters/management_seed.ts');
 const release=new URL('../motif-libraries/'+version+'/',import.meta.url),manifest=JSON.parse(readFileSync(new URL('entry.json',release)));
 const entry=manifest.entries[0],bytes=readFileSync(new URL(entry.payload,release));
 const runtime=sourceCurrent(manifest)?{...manifest.runtime_source,'fake-source':'changed'}:manifest.runtime_source;
 assert.throws(()=>validatePublicManagementSeed(JSON.parse(bytes),JSON.parse(readFileSync(new URL(entry.certificate,release))),createHash('sha256').update(bytes).digest('hex'),runtime),/seed source\/manifest changed/);
});
