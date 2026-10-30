import test from 'node:test';
import assert from 'node:assert/strict';
import {digest} from '../src/motif_core/online_skill_runtime.mjs';
const options={skip:!process.features?.typescript};
test('source program binds new structured parameters and preserves literal strings',options,async()=>{
 const {materializeSource,sourceProgramIdentity}=await import('../src/adapters/source_program_runtime.ts');
 const p={format:'parameterized_source_program_v1',language:'tsx',template:'const p=__GENELOOP_PARAMETERS__; console.log(p);',
  parameters_schema:{type:'object',properties:{label:{type:'string'},start:{type:'number'}},required:['label','start'],additionalProperties:false}};
 p.id='source_'+digest(sourceProgramIdentity(p)).slice(0,24);
 const args={label:'new "title"; process.exit(1)',start:4.5};
 const out=materializeSource(p,args);
 assert.equal(out.source,'const p='+JSON.stringify(args)+'; console.log(p);');
 assert.equal(out.parameters_sha256,digest(args));
 assert.throws(()=>materializeSource(p,{label:'x',start:'4.5'}),/parameters_invalid/);
 assert.throws(()=>materializeSource({...p,template:p.template+'changed'},args),/source_program_changed/);
});
test('default binding replaces complete current fields while preserving frozen style defaults',options,async()=>{
 const {materializeSource,sourceProgramIdentity}=await import('../src/adapters/source_program_runtime.ts');
 const p={format:'parameterized_source_program_v1',language:'tsx',template:'const p=__GENELOOP_PARAMETERS__;',
  default_parameters:{label:'old',segments:[1,2],style:{size:10,color:'blue'}},
  parameters_schema:{type:'object',properties:{label:{type:'string'},segments:{type:'array',items:{type:'number'}},style:{type:'object'}},required:['label','segments','style'],additionalProperties:false}};
 p.id='source_'+digest(sourceProgramIdentity(p)).slice(0,24);
 const current={label:'new',segments:[9],style:{size:20}};
 assert.deepEqual(materializeSource(p,current,'defaults').parameters,current);
 assert.deepEqual(materializeSource(p,{label:'new'},'defaults').parameters,{...p.default_parameters,label:'new'});
 assert.equal(p.default_parameters.label,'old');
 assert.throws(()=>materializeSource(p,{label:'new'}),/parameters_invalid/);
 assert.throws(()=>materializeSource(p,{segments:'wrong'},'defaults'),/parameters_invalid/);
});
test('implementation evidence exposes actual control flow only when the form requests it',options,async()=>{
 const {sourceCatalog}=await import('../src/adapters/source_program_runtime.ts');
 const program={id:'fixture',description:'Two examples',language:'tsx',template:'P.items.map(render)',parameters_schema:{type:'object'},default_parameters:{items:[1,2]}};
 assert.equal(sourceCatalog({programs:[program]})[0].template,undefined);
 assert.equal(sourceCatalog({programs:[program]},true)[0].template,'P.items.map(render)');
});
test('nullable schemas use the Harness supported oneOf contract with clear dialect errors',options,async()=>{
 const {materializeSource,sourceProgramIdentity}=await import('../src/adapters/source_program_runtime.ts');
 const p={format:'parameterized_source_program_v1',language:'tsx',template:'const p=__GENELOOP_PARAMETERS__;',
  parameters_schema:{type:'object',properties:{maximum:{type:['number','null']}},required:['maximum']}};
 p.id='source_'+digest(sourceProgramIdentity(p)).slice(0,24);
 assert.throws(()=>materializeSource(p,{maximum:24}),/type arrays are not supported/);
 p.parameters_schema.properties.maximum={oneOf:[{type:'number'},{type:'null'}]};
 p.id='source_'+digest(sourceProgramIdentity(p)).slice(0,24);
 assert.equal(materializeSource(p,{maximum:24}).parameters.maximum,24);
 assert.equal(materializeSource(p,{maximum:null}).parameters.maximum,null);
 assert.throws(()=>materializeSource(p,{maximum:'24'}),/parameters_invalid/);
});
test('library exposure retrieves by task metadata without changing the certified pool',options,async()=>{
 const {selectSourcePrograms}=await import('../src/adapters/source_program_runtime.ts');
 const programs=[
  {id:'table',description:'Aggregate numeric table totals',parameters_schema:{properties:{rows:{type:'array'}}}},
  {id:'photo',description:'Crop images into a chosen rectangle',parameters_schema:{properties:{width:{type:'number'}}}},
  {id:'audio',description:'Mix an audio segment at a chosen volume',parameters_schema:{properties:{volume:{type:'number'}}}},
 ];
 assert.deepEqual(selectSourcePrograms({programs},'Crop images to a square','lexical_top1').map(p=>p.id),['photo']);
 assert.deepEqual(selectSourcePrograms({programs},'Mix the audio segment','lexical_top1').map(p=>p.id),['audio']);
 assert.deepEqual(selectSourcePrograms({programs},'Aggregate table totals','lexical_top1').map(p=>p.id),['table']);
 assert.deepEqual(programs.map(p=>p.id),['table','photo','audio']);
 assert.equal(selectSourcePrograms({programs},'Crop images','all'),programs);
});
test('unmatched retrieval retains the pool and unsupported scopes have clear errors',options,async()=>{
 const {selectSourcePrograms}=await import('../src/adapters/source_program_runtime.ts');
 const programs=[{id:'a',description:'Crop images',parameters_schema:{}},{id:'b',description:'Mix audio',parameters_schema:{}}];
 assert.equal(selectSourcePrograms({programs},'zebra','lexical_top1'),programs);
 assert.throws(()=>selectSourcePrograms({programs},'zebra','unknown'),/scope_unsupported/);
});
