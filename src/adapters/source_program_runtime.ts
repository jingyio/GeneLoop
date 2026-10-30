/** Instantiate learned source as data. The scene owns execution and write rights. */
import {readFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {assertSupportedJsonSchema,validateJsonSchemaValue} from '@deepseek-ai/dsh-tools';
import {digest} from '../motif_core/online_skill_runtime.mjs';
import {validateRsiRecord} from './rsi_protocol.ts';

export const parameterToken='__GENELOOP_PARAMETERS__';
export function sourceProgramIdentity(program:any){
 return Object.fromEntries(['format','language','template','parameters_schema'].map(key=>[key,program[key]]));
}
export function validateSourceProgram(program:any){
 if(program?.format!=='parameterized_source_program_v1'||!['tsx','javascript'].includes(program.language)||
   typeof program.template!=='string'||Buffer.byteLength(program.template)>100000||program.template.split(parameterToken).length!==2||
   program.id!=='source_'+digest(sourceProgramIdentity(program)).slice(0,24)||program.parameters_schema?.type!=='object')throw Error('source_program_changed');
 assertSupportedJsonSchema(program.parameters_schema);
 return program;
}
export function materializeSource(program:any,supplied:any,binding='full'){
 validateSourceProgram(program);
 if(!['full','defaults'].includes(binding)||!supplied||typeof supplied!=='object'||Array.isArray(supplied))throw Error('source_program_binding_invalid');
 const parameters=binding==='defaults'?{...program.default_parameters,...supplied}:supplied;
 if(validateJsonSchemaValue(program.parameters_schema,parameters).length)throw Error('source_program_parameters_invalid');
 const serialized=JSON.stringify(parameters);
 if(serialized.length>32000)throw Error('source_program_parameters_too_large');
 // Substitution emits one JSON value, never evaluates a caller-supplied string.
 const source=program.template.replace(parameterToken,()=>serialized);
 return {source,source_sha256:createHash('sha256').update(source).digest('hex'),program_id:program.id,
   parameters_sha256:digest(parameters),parameters,supplied_parameters_sha256:digest(supplied),parameter_binding:binding};
}
export function loadSourceLibrary(path:string){
 const library=JSON.parse(readFileSync(path,'utf8')),{digest:claimed,...body}=library;
 if(library.format!=='source_program_library_v1'||digest(body)!==claimed||!Array.isArray(library.programs))throw Error('source_library_changed');
 for(const program of library.programs){
  validateSourceProgram(program);
  if(program.status!=='certified'||program.certification?.program_identity!==digest(sourceProgramIdentity(program))||
    program.certification.source_equivalent!==true)throw Error('source_program_not_certified');
 }
 return library;
}
export function sourceCatalog(library:any,includeSource=false){
 return library.programs.map((p:any)=>({id:p.id,description:p.description,parameters_schema:p.parameters_schema,
   example_parameters:p.default_parameters,...(includeSource?{language:p.language,template:p.template}:{})}));
}

/** Generic lexical retrieval controls exposure, never permissions or semantic validity. */
export function selectSourcePrograms(library:any,intent:string,scope='all'){
 const programs=library.programs;
 if(scope==='all')return programs;
 if(scope!=='lexical_top1')throw Error('source_program_scope_unsupported');
 if(programs.length<2)return programs;
 const words=(text:string)=>text.replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase().match(/[a-z]{2,}/g)??[];
 const counts=(tokens:string[])=>{const out=new Map<string,number>();for(const t of tokens)out.set(t,(out.get(t)??0)+1);return out;};
 const docs=programs.map((p:any)=>counts(words(p.description+' '+Object.keys(p.parameters_schema.properties??{}).join(' '))));
 const frequency=new Map<string,number>();
 for(const doc of docs)for(const term of doc.keys())frequency.set(term,(frequency.get(term)??0)+1);
 const weights=(terms:Map<string,number>)=>new Map([...terms].map(([term,n])=>[term,(1+Math.log(n))*(1+Math.log((docs.length+1)/((frequency.get(term)??0)+1)))]));
 const query=weights(counts(words(intent)));const norm=(v:Map<string,number>)=>Math.sqrt([...v.values()].reduce((s,n)=>s+n*n,0));
 const queryNorm=norm(query);
 const ranked=docs.map((doc:Map<string,number>,i:number)=>{const vector=weights(doc);let dot=0;
  for(const [term,value] of vector)dot+=value*(query.get(term)??0);
  return {program:programs[i],score:dot/(norm(vector)*queryNorm||1)};
 }).sort((a:any,b:any)=>b.score-a.score||(a.program.id<b.program.id?-1:a.program.id>b.program.id?1:0));
 // A zero-overlap query retains the pool. Scores are retrieval heuristics, not confidence.
 return ranked[0].score>0?[ranked[0].program]:programs;
}

/** Freeze one published form/library for a new task. Later pointers do not affect it. */
export function loadSourceForm(store:string,owner:string){
 const root=realpathSync(store),raw=readFileSync(join(root,'latest.json'),'utf8'),pointer=JSON.parse(raw);
 if(pointer.format!=='reuse_form_pointer_v1'||pointer.owner!==owner)throw Error('reuse_form_foreign_owner');
 const pattern=/^round-[a-f0-9]{24}\/(?:policy|source-library)\.json$/;
 if(!pattern.test(pointer.policy)||!pattern.test(pointer.library)||pointer.policy.split('/')[0]!==pointer.library.split('/')[0])throw Error('reuse_form_pointer_invalid');
 const policyPath=join(root,pointer.policy),libraryPath=join(root,pointer.library);
 if(realpathSync(policyPath)!==policyPath||realpathSync(libraryPath)!==libraryPath)throw Error('reuse_form_pointer_symlink');
 const policy=JSON.parse(readFileSync(policyPath,'utf8')),{digest:claimed,...body}=policy;
 if(policy.owner!==owner||policy.digest!==pointer.digest||policy.generation!==pointer.generation||digest(body)!==claimed||policy.verdict?.accepted!==true||
   !['program_catalog','typed_tools'].includes(policy.form?.representation))throw Error('reuse_form_policy_changed');
 const library=loadSourceLibrary(libraryPath);
 if(library.digest!==policy.library_digest)throw Error('reuse_form_library_changed');
 if(policy.rsi_update_digest){
  const directory=join(root,pointer.policy.split('/')[0]);
  const bundle=JSON.parse(readFileSync(join(directory,'rsi-update.json'),'utf8'));
  const publicationBytes=readFileSync(join(directory,'rsi-publication.json'),'utf8');
  const publication=validateRsiRecord(JSON.parse(publicationBytes)),p=publication.payload;
  if(digest(bundle)!==policy.rsi_update_digest||createHash('sha256').update(publicationBytes).digest('hex')!==pointer.rsi_publication_sha256||
    publication.record_type!=='publication_receipt'||p.manifest_sha256!==policy.digest||p.candidate_id!==policy.proposal_digest||
    p.next_versions.reuse_form?.sha256!==policy.proposal_digest)throw Error('reuse_form_protocol_receipt_changed');
 }
 return {policy,library_path:libraryPath,pointer_sha256:createHash('sha256').update(raw).digest('hex')};
}
