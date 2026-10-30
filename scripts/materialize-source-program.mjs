/** Private JSON protocol used by existing MCP scenes; does not execute source. */
import {readFileSync} from 'node:fs';
import {loadSourceLibrary,materializeSource,sourceCatalog,loadSourceForm,selectSourcePrograms} from '../src/adapters/source_program_runtime.ts';
const input=JSON.parse(readFileSync(0,'utf8'));
try{
 if(input.operation==='resolve_form'){
  process.stdout.write(JSON.stringify(loadSourceForm(input.store,input.owner)));
 }else if(input.operation==='candidate_materialize'){
  process.stdout.write(JSON.stringify(materializeSource(input.program,input.parameters)));
 }else{
 const library=loadSourceLibrary(input.library);
 const programs=selectSourcePrograms(library,input.intent??'',input.library_scope??'all');
 if(input.operation==='catalog')process.stdout.write(JSON.stringify({digest:library.digest,programs:sourceCatalog({programs},input.include_source===true)}));
 else{
  const program=programs.find(p=>p.id===input.program_id);
  if(!program)throw Error('source_program_unknown');
  process.stdout.write(JSON.stringify({...materializeSource(program,input.parameters,input.parameter_binding??'full'),library_digest:library.digest}));
 }
 }
}catch(error){process.stderr.write(String(error.message));process.exitCode=1;}
