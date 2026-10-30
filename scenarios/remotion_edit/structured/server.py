"""Bounded media tools. DSH and the model still own the editing decisions."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import threading
from fractions import Fraction

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

spec = importlib.util.spec_from_file_location(
    'remotion_workspace', Path(__file__).resolve().parents[1] / 'server.py')
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)
WORK = workspace.WORK
ASSETS = json.loads(os.environ['REMOTION_TASK_ASSETS'])
NONCE = os.environ['REMOTION_TASK_NONCE']
FUSED = os.environ.get('REMOTION_FUSED_PROBE') == '1'
LOCK = threading.RLock()
RECEIPT = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset(name):
    if name not in ASSETS or Path(name).name != name:
        raise ToolError('asset is outside the frozen task input')
    path = WORK / 'public' / name
    if path.is_symlink() or not path.is_file() or sha(path) != ASSETS[name]:
        raise ToolError('asset version changed')
    return path


def handle(name):
    return 'source-' + hashlib.sha256(
        (NONCE + '\0' + name + '\0' + ASSETS[name]).encode()).hexdigest()[:32]


def pin_asset(name: str) -> dict:
    """Select and pin one current task asset by exact filename; returns a versioned source handle."""
    path = asset(name)
    return {'name': name, 'source_id': handle(name),
            'source_version': ASSETS[name], 'bytes': path.stat().st_size}


def list_assets() -> dict:
    """List only current task input filenames and versions. Use media probing for actual stream properties."""
    return {'assets': [{'name': name, 'bytes': asset(name).stat().st_size,
                        'sha256': ASSETS[name]} for name in sorted(ASSETS)]}


def command(text, timeout=180):
    result = workspace.run_command(text, timeout)
    if result['exit_code']:
        raise ToolError('media command failed: ' + json.dumps(result, ensure_ascii=False)[-3000:])
    return result['stdout']


def probe(path):
    value = json.loads(command('ffprobe -v error -show_streams -show_format -of json '
                               + shlex.quote(path)))
    keys = ('index', 'codec_type', 'codec_name', 'width', 'height', 'r_frame_rate',
            'avg_frame_rate', 'duration', 'nb_frames', 'sample_rate', 'channels')
    return {'duration_seconds': float(value['format']['duration']),
            'streams': [{k: s[k] for k in keys if k in s} for s in value['streams']]}


def probe_media(source_id: str) -> dict:
    """Read actual media properties of a previously selected source_id. No source selection or editing choice."""
    names = [name for name in ASSETS if handle(name) == source_id]
    if len(names) != 1:
        raise ToolError('unknown source handle for this task')
    name = names[0]
    asset(name)
    result = probe('/work/public/' + name)
    asset(name)
    return {'source_id': source_id, 'source_version': ASSETS[name],
            'name': name, **result}


def probe_asset(name: str) -> dict:
    """Direct ordinary-tool baseline: select a filename and read its actual properties in one call."""
    return probe_media(pin_asset(name)['source_id'])


def current_source_version():
    return sha(WORK / 'src/index.tsx')


def read_source() -> dict:
    """Read the current single-file composition and its exact entry-file SHA256."""
    with LOCK:
        return {'text': (WORK / 'src/index.tsx').read_text(),
                'source_version': current_source_version(), 'digest_scope': 'src/index.tsx'}


def write_source(text: str) -> dict:
    """Write src/index.tsx only. Return its SHA256 for the explicit render guard; this is a write operation."""
    if not 1 <= len(text.encode()) <= 100000:
        raise ToolError('source must be 1..100000 UTF-8 bytes')
    with LOCK:
        workspace.write_file('src/index.tsx', text)
        return {'source_version': current_source_version(), 'digest_scope': 'src/index.tsx'}


def render_composition(source_version: str) -> dict:
    """Render Main from the current entry-file digest, independently probe/decode it, then publish out/video.mp4.

    This writes task outputs; it is never admitted as a read-only Motif. Source
    digest is scoped to the entry file, not a proof of arbitrary JS dependencies.
    """
    global RECEIPT
    with LOCK:
        if not re.fullmatch(r'[a-f0-9]{64}', source_version) or source_version != current_source_version():
            raise ToolError('current source digest required; read or write source again')
        for name in ASSETS:
            asset(name)
        index = 1
        while (WORK / f'out/render-{index:03d}').exists():
            index += 1
        folder = f'out/render-{index:03d}'
        virtual = '/work/' + folder + '/video.mp4'
        command('mkdir -p ' + shlex.quote(folder) + ' && '
                'node /runtime/node_modules/@remotion/cli/remotion-cli.js render '
                'src/index.tsx Main ' + shlex.quote(virtual) +
                ' --browser-executable=/usr/bin/chromium-headless-shell --concurrency=2 --log=error', 240)
        metadata = probe(virtual)
        command('ffmpeg -v error -xerror -i ' + shlex.quote(virtual) +
                ' -map 0:v:0 -c:v libx264 -preset ultrafast -f null -', 180)
        if source_version != current_source_version():
            raise ToolError('source changed during render; output not published')
        target = WORK / 'out/video.mp4'
        shutil.copyfile(WORK / folder / 'video.mp4', target.with_suffix('.mp4.tmp'))
        target.with_suffix('.mp4.tmp').replace(target)
        RECEIPT = {'source_version': source_version, 'video_sha256': sha(target),
                   'video_path': 'out/video.mp4', 'render_directory': folder,
                   'full_video_decode': True, **metadata}
        (WORK / folder / 'receipt.json').write_text(json.dumps(RECEIPT, indent=2))
        return RECEIPT


def inspect_render(seconds: list[float]) -> CallToolResult:
    """Return native-size pixels for each requested video frame, with exact frame indices and times."""
    with LOCK:
        if RECEIPT is None or RECEIPT['source_version'] != current_source_version():
            raise ToolError('render the current source before inspecting')
        video = WORK / 'out/video.mp4'
        if sha(video) != RECEIPT['video_sha256']:
            raise ToolError('render output version changed')
        stream=next(s for s in RECEIPT['streams'] if s['codec_type']=='video')
        fps=Fraction(stream['r_frame_rate']);count=int(stream['nb_frames'])
        if not seconds or any(
                isinstance(x, bool) or not 0 <= x < count/float(fps) for x in seconds):
            raise ToolError('request times inside the actual video duration')
        selected=[{'requested_seconds':value,'frame_index':int(Fraction(str(value))*fps),
                   'frame_seconds':float(int(Fraction(str(value))*fps)/fps)} for value in seconds]
        metadata = {**RECEIPT, 'selected_output_seconds': seconds,
                    'selected_output_frames':selected,'preview_width':stream['width'],'preview_height':stream['height'],
                    'quality': 'model_must_review_real_pixels; not_independently_passed'}
        blocks = [TextContent(type='text', text=json.dumps(metadata, ensure_ascii=False))]
        for index, frame in enumerate(selected):
            path = WORK / RECEIPT['render_directory'] / f'preview-{index}.jpg'
            path.unlink(missing_ok=True)
            command('ffmpeg -v error -y -i /work/out/video.mp4 -vf '+
                    shlex.quote('select=eq(n\\,'+str(frame['frame_index'])+')')+' -vsync 0 -frames:v 1 -q:v 3 ' +
                    shlex.quote('/work/' + str(path.relative_to(WORK))))
            blocks.append(ImageContent(type='image', data=base64.b64encode(path.read_bytes()).decode(),
                                       mimeType='image/jpeg'))
        return CallToolResult(content=blocks, structuredContent=metadata)


def write_notes(text: str) -> dict:
    """Save bounded edit notes in this task's out/edit-notes.md; never modify user originals."""
    if len(text.encode()) > 20000:
        raise ToolError('notes exceed the bounded output')
    return workspace.write_file('out/edit-notes.md', text)


if __name__ == '__main__':
    server = MCPServer('Remotion structured experiment workspace')
    readonly = [list_assets, probe_asset] if FUSED else [list_assets, pin_asset, probe_media]
    for fn in readonly + [read_source, write_source, render_composition, inspect_render, write_notes]:
        server.tool(annotations=ToolAnnotations(
            readOnlyHint=fn not in (write_source, render_composition, write_notes),
            destructiveHint=False))(fn)
    server.run(transport='stdio')
