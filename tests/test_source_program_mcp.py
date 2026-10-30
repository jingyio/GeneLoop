"""Actual MCP stdio transport for generated interfaces; no model/render claims."""
import asyncio,json,sys
import pytest
from pathlib import Path
from mcp import Client,StdioServerParameters
from src.adapters.source_program_mcp import learned_tool_name
from src.adapters.scenario import prepare_scenario


@pytest.mark.parametrize('binding',['full','defaults'])
def test_learned_schema_dispatches_current_values_over_real_stdio(binding):
    script='''
import asyncio
from mcp.server import MCPServer
from src.adapters.source_program_mcp import serve_source_tools
server=MCPServer('typed-source-diagnostic')
@server.tool()
def ordinary(value:int)->dict:return {'value':value}
programs=[{'id':'source_diagnostic','description':'Observed computation',
 'parameters_schema':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']},
 'example_parameters':{'value':1}}]
def execute(program_id,parameters):return {'program_id':program_id,'current':parameters}
asyncio.run(serve_source_tools(server,programs,execute,binding=BINDING))
'''
    script=script.replace('BINDING',repr(binding))
    async def check():
        params=StdioServerParameters(command=sys.executable,args=['-c',script],cwd=str(Path(__file__).resolve().parents[1]))
        async with Client(params,read_timeout_seconds=15) as client:
            tools=(await client.list_tools()).tools
            assert [t.name for t in tools]==['ordinary','reuse_source_diagnostic']
            assert tools[1].input_schema['properties']['value']['type']=='integer'
            assert tools[1].input_schema['required']==(['value'] if binding=='full' else [])
            result=await client.call_tool('reuse_source_diagnostic',{'value':9})
            assert not result.is_error
            assert result.structured_content=={'program_id':'source_diagnostic','current':{'value':9}}
            native=await client.call_tool('ordinary',{'value':4})
            assert not native.is_error
            unknown=await client.call_tool('reuse_source_unknown',{})
            assert unknown.is_error
    asyncio.run(check())


def test_generated_description_tool_survives_actual_scenario_qualified_name_limit(tmp_path):
    program={'id':'source_123456789abcdef','description':'Repeatedly render parametrized computational compositions with current inputs'}
    name='mcp__remotion__'+learned_tool_name(program,'description')
    brief=tmp_path/'brief.md';brief.write_text('Current public fixture')
    config={'schema_version':1,'name':'description_transport','prompt':str(brief),
        'servers':[{'server_name':'remotion','transport':'stdio','command':sys.executable,'args':['-c','pass']}],
        'allowed_tools':[name]}
    path=tmp_path/'scenario.json';path.write_text(json.dumps(config))
    assert prepare_scenario(path)['allowed_tools']==[name]
