"""Same render tools in both arms; learned programs supply source, not old output."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import asyncio
import sys
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT))
spec = importlib.util.spec_from_file_location('remotion_structured', HERE/'server.py')
scene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)
LIBRARY = os.environ.get('REMOTION_SOURCE_LIBRARY')
BINDING = os.environ.get('REMOTION_PARAMETER_BINDING','full')
SHOW_SOURCE = os.environ.get('REMOTION_PROGRAM_EVIDENCE','interface')=='source'
SCOPE = os.environ.get('REMOTION_LIBRARY_SCOPE','all')
INTENT = os.environ.get('REMOTION_PROGRAM_INTENT','')


def program_request(value):
    if not LIBRARY:
        raise ToolError('no learned program is installed for this task; use render_source')
    request = {'library': LIBRARY, 'parameter_binding': BINDING,'library_scope':SCOPE,'intent':INTENT, **value}
    result = subprocess.run(['node', '--experimental-strip-types', str(ROOT/'scripts/materialize-source-program.mjs')],
        input=json.dumps(request), capture_output=True, text=True, timeout=15, cwd=ROOT)
    if result.returncode:
        raise ToolError(result.stderr[-1500:])
    return json.loads(result.stdout)


def list_programs() -> dict:
    """List the frozen learned source programs and their current parameter interfaces; may be empty."""
    return program_request({'operation': 'catalog','include_source':SHOW_SOURCE}) if LIBRARY else {'programs': []}


def render_source(text: str) -> dict:
    """Write the current model-authored TSX and render it in one ordinary operation. Available in both arms."""
    with scene.LOCK:
        version = scene.write_source(text)['source_version']
        return scene.render_composition(version)


def render_program(program_id: str, parameters: dict) -> dict:
    """Select a learned program with explicit CURRENT task parameters, instantiate and actually render it.

    This writes task source/output. It reuses computation, never a historical video
    or old semantic decision. Review the returned video with inspect_render.
    """
    with scene.LOCK:
        materialized = program_request({'operation': 'materialize', 'program_id': program_id, 'parameters': parameters})
        record = {'kind': 'source_program_selected', 'time': time.time(),
                  **{key: materialized[key] for key in ('program_id','parameters_sha256','source_sha256','library_digest')}}
        record['supplied_parameters'] = parameters
        record['parameters'] = materialized['parameters']
        record['parameter_binding'] = materialized['parameter_binding']
        audit = scene.WORK.parent/'source-program-audit.jsonl'
        with audit.open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False)+'\n')
        audit.chmod(0o600)
        version = scene.write_source(materialized['source'])['source_version']
        result = scene.render_composition(version)
        with audit.open('a') as stream:
            stream.write(json.dumps({**record, 'kind': 'source_program_rendered', 'render': result,
                                     'source_current': scene.current_source_version()==version}, ensure_ascii=False)+'\n')
        return {**result, 'program_id': program_id, 'library_digest': materialized['library_digest']}


if __name__ == '__main__':
    server = MCPServer('Remotion learned program experiment')
    readers = [scene.list_assets, scene.probe_asset, scene.read_source, scene.inspect_render, list_programs]
    for fn in readers + [scene.write_source, scene.render_composition, scene.write_notes, render_source, render_program]:
        if fn in (list_programs,render_program) and (not LIBRARY or os.environ.get('REMOTION_PROGRAM_INTERFACE')=='typed_tools'):
            continue
        server.tool(annotations=ToolAnnotations(readOnlyHint=fn in readers, destructiveHint=False))(fn)
    if os.environ.get('REMOTION_PROGRAM_INTERFACE')=='typed_tools':
        from src.adapters.source_program_mcp import serve_source_tools
        programs=list_programs()['programs']
        asyncio.run(serve_source_tools(server,programs,render_program,os.environ.get('REMOTION_PROGRAM_TOOL_NAMING','opaque'),BINDING))
    else:
        server.run(transport='stdio')
