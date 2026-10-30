"""Expose the SAME learned programs as typed MCP tools instead of a text catalog.

Only presentation changes. The scene callback still owns write permission,
materialization and actual execution. No scene names or task routes are encoded.
"""
from __future__ import annotations
import asyncio,json,re
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool,ToolAnnotations,ListToolsResult,CallToolResult,TextContent


def learned_tool_name(program,naming='opaque',max_length=49):
    if naming=='description':
        words=re.findall(r'[a-z0-9]+',program['description'].lower())[:7]
        label='_'.join(words)[:max_length-len('reuse__')-6] or 'program'
        return 'reuse_'+label+'_'+program['id'][-6:]
    return 'reuse_'+program['id']


def learned_tool_definitions(programs,naming='opaque',binding='full'):
    return [Tool(name=learned_tool_name(p,naming),description=p['description']+
        '\nExecute this learned computation on CURRENT task parameters and produce a fresh artifact. '+
        ('Supply current overrides; omitted top-level fields keep the frozen example defaults; arrays/objects replace whole values. '
         if binding=='defaults' else '')+'Examples describe the interface, not the current task.'+
        ('\nActual learned implementation (parameter object is supplied at execution):\n'+p['template'] if 'template' in p else ''),
        input_schema={**p['parameters_schema'],**({'required':[]} if binding=='defaults' else {}),'examples':[p['example_parameters']]},
        annotations=ToolAnnotations(read_only_hint=False,destructive_hint=False)) for p in programs]


async def serve_source_tools(base,programs,execute,naming='opaque',binding='full'):
    mapping={learned_tool_name(p,naming):p for p in programs}
    async def listed(context,params):
        return ListToolsResult(tools=[*(await base.list_tools()),*learned_tool_definitions(programs,naming,binding)])
    async def called(context,params):
        try:
            if params.name not in mapping:
                return await base.call_tool(params.name,params.arguments or {})
            program=mapping[params.name]
            value=await asyncio.to_thread(execute,program['id'],params.arguments or {})
            return CallToolResult(content=[TextContent(type='text',text=json.dumps(value,ensure_ascii=False))],
                                  structured_content=value)
        except Exception as error:
            return CallToolResult(content=[TextContent(type='text',text=str(error)[:3000])],is_error=True)
    server=Server(base.name,on_list_tools=listed,on_call_tool=called)
    async with stdio_server() as (incoming,outgoing):
        await server.run(incoming,outgoing,server.create_initialization_options())
