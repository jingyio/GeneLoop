"""Mine and independently certify actual parameter flow; no model calls."""
from __future__ import annotations
import hashlib,importlib.util,json,os,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from src.adapters.dsh_trajectory import extract_dsh_trace,infer_dsh_provenance,mine_witnessed_parameter_edges
from src.adapters.task_identity import load_trace_identity,require_distinct_decisions
from src.adapters.tool_contract_loader import parse_tool_contracts
from src.adapters.tool_schema_contracts import bind_mcp_descriptions
from src.motif_core.offline.edge_compiler import compile_witnessed_edge_motif,certify_witnessed_edge_motif
from src.motif_core.offline.library_builder import library_from_certified

HERE=Path(__file__).resolve().parent
BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve();EXP=BASE/'structured-v1'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2));path.chmod(0o600)

def main():
    target=EXP/'library'
    if target.exists():raise ValueError('preserve prior library; use a new trial for another learning attempt')
    tasks=[t for t in json.loads((HERE/'tasks.json').read_text()) if t['partition']!='evaluation']
    contracts=parse_tool_contracts(json.loads((HERE/'contracts.json').read_text()))
    traces=[];identities=[];inputs=[];schema_rows=None;schema_hashes=None
    for task in tasks:
        run=EXP/'runs/v1/typed'/task['id'];effective=json.loads((run/'effective.json').read_text());result=json.loads((run/'result.json').read_text())
        if result['status']!='completed' or not result['video_exists'] or effective['task']!=task or effective['tasks_sha256']!=sha(HERE/'tasks.json'):
            raise ValueError('completed frozen normal task required: '+task['id'])
        for path in (HERE/'server.py',HERE.parent/'server.py'):
            if effective['experiment_code'][str(path.relative_to(ROOT))]!=sha(path):
                raise ValueError('media tool implementation changed since the normal trace')
        quality=json.loads((run/'qa/verification.json').read_text())
        if not quality['technical_pass']:raise ValueError('independent media gate failed: '+task['id'])
        events=run/'events.jsonl'
        manifest={'task_id':task['id'],'question':task['instruction'],'frozen_effective_sha256':sha(run/'effective.json'),
                  'input_versions':effective['assets'],'model':'deepseek-flash','provider_mode':'real','mode':'baseline'}
        save(run/'manifest.json',manifest)
        lock={'schema_version':1,'research_decision_id':task['id'],'manifest_sha256':sha(run/'manifest.json'),'events_sha256':sha(events),
              'scope':'distinct frozen synthetic editing decisions; not independent real clients'}
        save(run/'task-identity.json',lock)
        # Execution code is an export inside .local; data remains at the
        # explicitly authorized private experiment root, a narrower boundary.
        identity=load_trace_identity(run/'task-identity.json',events,BASE);identities.append(identity)
        raw=[json.loads(line) for line in events.read_text().splitlines()]
        provenance=infer_dsh_provenance(raw,contracts)
        trace=extract_dsh_trace(raw,contracts,trace_id=task['id'],task_fingerprint=identity['research_decision_id'],provenance_by_call_id=provenance)
        traces.append(trace)
        request=json.loads((BASE/'requests'/f"{result['request_ids'][0]:06d}.json").read_text())
        current=[]
        for tool in request['tools']:
            function=tool.get('function',tool)
            current.append({'name':function['name'],'description':function['description'],
                            'inputSchema':function.get('parameters',function.get('input_schema'))})
        chosen=[r for r in current if r['name'] in contracts]
        hashes={r['name']:digest(r['inputSchema']) for r in chosen}
        if schema_hashes is not None and hashes!=schema_hashes:raise ValueError('training tool schema drift')
        schema_rows=chosen;schema_hashes=hashes
        inputs.append({'task':task['id'],'events_sha256':sha(events),'effective_sha256':sha(run/'effective.json'),
                       'records':len(trace.records),'eligible_records':sum(r.eligible for r in trace.records),
                       'identity':identity,'quality_scope':'media gate, not human blind approval'})
    require_distinct_decisions(identities)
    contracts=bind_mcp_descriptions(contracts,schema_rows)
    training=[trace for task,trace in zip(tasks,traces) if task['partition']=='train']
    heldout=[trace for task,trace in zip(tasks,traces) if task['partition']=='certification']
    if len(training)!=2 or len(heldout)!=1:raise ValueError('frozen two-training/one-certification split required')
    candidates=mine_witnessed_parameter_edges(training,min_task_support=2)
    artifacts=[];rejected=[]
    for candidate in candidates:
        try:
            compiled=compile_witnessed_edge_motif(candidate,training,contracts)
            artifacts.append(certify_witnessed_edge_motif(compiled,heldout[0],contracts))
        except ValueError as error:rejected.append({'candidate':candidate,'reason':str(error)})
    report={'status':'certified_structure_only' if artifacts else 'no_certified_artifact','inputs':inputs,
            'mining_basis':'existing witnessed parameter-edge miner and compiler','candidates':candidates,
            'rejected':rejected,'artifacts':len(artifacts),'model_requests':0,
            'quality':'not_human_blind_reviewed','notice':'not yet evidence of online skips or net savings'}
    save(EXP/'learning-report.json',report)
    if not artifacts:print(json.dumps(report,ensure_ascii=False));raise SystemExit(2)
    library=library_from_certified(artifacts)
    library.update(certification_scope='independent_decisions',tool_schema_hashes=schema_hashes,
                   task_identity_evidence={row['research_decision_id']:row for row in identities})
    library['library_digest']=digest({k:v for k,v in library.items() if k!='library_digest'})
    rows={name:{'required_params':list(c.required_params),'read_only':c.read_only,'output_fields':list(c.output_fields),
                'provenance_params':list(c.provenance_params),'description':c.description,'replay_stable':c.replay_stable}
          for name,c in contracts.items()}
    module_spec=importlib.util.spec_from_file_location('export_online',ROOT/'scripts/export-online-motif-manifest.py')
    exporter=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(exporter)
    manifest=exporter.export_manifest(library,rows,{},
        {name:'source_version' for name in rows},source_dereferences=('mcp__remotion__probe_media',))
    lock_files=['scenarios/remotion_edit/structured/server.py','scenarios/remotion_edit/server.py',
                'scenarios/remotion_edit/structured/contracts.json','src/adapters/dsh_online_motif.mjs',
                'src/motif_core/online_skill_runtime.mjs','src/motif_core/source_dereference.generated.mjs','package-lock.json']
    manifest['scene_code_locks']={name:sha(ROOT/name) for name in lock_files}
    manifest['scene_runtime_locks']={name:sha(BASE/'runtime'/name) for name in
        ['package-lock.json','node_modules/@remotion/compositor-linux-x64-gnu/ffprobe']}
    manifest['scene_image']=effective['image']
    manifest['manifest_digest']=digest({k:v for k,v in manifest.items() if k!='manifest_digest'})
    save(target/'library.json',library);save(target/'contracts.json',rows);save(target/'online-manifest.json',manifest)
    report.update(library_digest=library['library_digest'],manifest_digest=manifest['manifest_digest'],
                  learning_code_sha256=sha(Path(__file__)),exporter_sha256=sha(ROOT/'scripts/export-online-motif-manifest.py'))
    save(EXP/'learning-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('inputs','candidates','rejected')},ensure_ascii=False))

if __name__=='__main__':main()
