"""Exercise matched MCP schemas and real learned-program binding without a model."""
import argparse,asyncio,hashlib,json,os
from pathlib import Path
from mcp import Client,StdioServerParameters


async def check(output,trial,task):
    schemas=[];catalogs={};checks={};sizes={}
    for arm in ('fused','program'):
        file=output/'runs'/trial/arm/task/'scenario.json'
        config=json.loads(file.read_text());server=config['servers'][0]
        params=StdioServerParameters(command=server['command'],args=server['args'],cwd=server['cwd'],env=server['env'])
        async with Client(params,read_timeout_seconds=60) as client:
            tools=(await client.list_tools()).tools
            schemas.append([t.model_dump(mode='json',by_alias=True) for t in tools])
            names={t.name for t in tools};typed=[t for t in tools if t.name.startswith('reuse_')];sizes[arm]=len(tools)
            if 'list_programs' in names:
                response=await client.call_tool('list_programs',{});assert not response.is_error
                value=response.structured_content or json.loads(response.content[0].text);catalogs[arm]=value['programs']
            else:catalogs[arm]=[{'parameters_schema':t.input_schema,'tool_name':t.name} for t in typed]
            native=[t for t in tools if not t.name.startswith('reuse_') and t.name not in ('list_programs','render_program')]
            checks[arm+'_native_tools']=len(native)==8
            if arm=='program':
                assert catalogs[arm]
                key,field=next((k,v) for k,v in catalogs[arm][0]['parameters_schema']['properties'].items() if v.get('type'))
                invalid_value={} if field['type'] in ('string','number','integer','array','boolean') else 'invalid'
                invalid_args={key:invalid_value}
                result=await client.call_tool(typed[0].name,invalid_args) if typed else await client.call_tool('render_program',{'program_id':catalogs[arm][0]['id'],'parameters':invalid_args})
                checks['invalid_parameters_rejected_before_render']=result.is_error
                if typed:
                    checks['typed_parameters_rejected_before_render']=result.is_error
                    effective=json.loads(file.with_name('effective.json').read_text())
                    visible=effective.get('source_program_visible_ids')
                    expected=len(visible) if visible is not None else len(json.loads(Path(server['env']['REMOTION_SOURCE_LIBRARY']).read_text())['programs'])
                    checks['typed_tools_follow_library']=len(typed)==expected
                    checks['no_duplicate_catalog_api']='list_programs' not in names and 'render_program' not in names
            else:checks['baseline_has_only_native_tools']=not typed and 'list_programs' not in names and 'render_program' not in names
    def native(rows):return [t for t in rows if not t['name'].startswith('reuse_') and t['name'] not in ('list_programs','render_program')]
    checks['same_native_tool_schemas']=native(schemas[0])==native(schemas[1])
    checks['baseline_empty_program_catalog']=catalogs['fused']==[]
    checks['program_catalog_loaded']=len(catalogs['program'])>0
    assert all(checks.values()),checks
    report={'checks':checks,'model_requests':0,'tool_counts':sizes,'tool_schema_sha256':hashlib.sha256(json.dumps(schemas[0],sort_keys=True).encode()).hexdigest()}
    (output/('program-preflight-'+trial+'-'+task+'.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--trial',required=True);parser.add_argument('--task',required=True);a=parser.parse_args()
    asyncio.run(check(a.output_root,a.trial,a.task))
