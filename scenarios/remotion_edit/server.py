"""Thin workspace tools; DSH owns the loop and the model authors the edit."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import atexit
import threading
from typing import Annotated
from pydantic import Field
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

WORK = Path(os.environ['REMOTION_WORK']).resolve()
RUNTIME = Path(os.environ['REMOTION_RUNTIME']).resolve()
IMAGE = os.environ['REMOTION_IMAGE']
MEDIA_TOOLS = Path(os.environ['REMOTION_MEDIA_TOOLS']).resolve() if os.environ.get('REMOTION_MEDIA_TOOLS') else None
AUDIT = WORK.parent / (WORK.name + '-tool-audit.jsonl')
CONTAINER = None
CONTAINER_LOCK = threading.Lock()

def close_container():
    if CONTAINER: subprocess.run(['docker','rm','-f',CONTAINER],capture_output=True,timeout=30)
atexit.register(close_container)

def emit(name, args, result, started):
    row = {'tool':name,'arguments':args,'result':result,'elapsed_seconds':time.monotonic()-started,'time':time.time()}
    with AUDIT.open('a') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    AUDIT.chmod(0o600)
    return result

def local_path(path):
    p = (WORK / path.removeprefix('/work/')).resolve()
    if not p.is_relative_to(WORK) or p.is_relative_to(WORK/'node_modules'):
        raise ValueError('path must be inside the task workspace, outside node_modules')
    return p

def list_files(directory: str = '.') -> dict:
    """List task source files and immutable public sample media. Paths are relative to /work."""
    t=time.monotonic(); p=local_path(directory)
    result={'files':[{'path':str(x.relative_to(WORK)),'bytes':x.stat().st_size,'directory':x.is_dir()} for x in sorted(p.iterdir()) if x.name!='node_modules']}
    return emit('list_files',{'directory':directory},result,t)

def read_file(path: str) -> dict:
    """Read a UTF-8 source/config/brief. Returns its current SHA256 for provenance."""
    t=time.monotonic(); p=local_path(path); raw=p.read_bytes()
    if len(raw)>150000: raise ValueError('read a smaller source file')
    return emit('read_file',{'path':path},{'path':path,'sha256':hashlib.sha256(raw).hexdigest(),'text':raw.decode()},t)

def write_file(path: str, text: str) -> dict:
    """Write task source/config/notes. Cannot modify sample media or dependencies."""
    t=time.monotonic(); p=local_path(path)
    if p.is_relative_to(WORK/'public') or len(text)>200000: raise ValueError('write outside immutable media and within size limit')
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)
    return emit('write_file',{'path':path,'text':text},{'path':path,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size},t)

def run_command(command: str, timeout_seconds: Annotated[int, Field(ge=1, le=240)] = 180) -> dict:
    """Run a shell command in this task's persistent isolated Debian12 container at /work. Files AND background processes persist between calls until the task ends. No network or credentials. Node, Remotion, ffprobe and ffmpeg are in PATH. Prefer foreground rendering and wait for its exit status. CLI: node /runtime/node_modules/@remotion/cli/remotion-cli.js render src/index.tsx Main out/video.mp4 --browser-executable=/usr/bin/chromium-headless-shell --concurrency=2 --log=error ."""
    if not 1<=timeout_seconds<=240: raise ValueError('timeout must be 1..240 seconds')
    t=time.monotonic()
    global CONTAINER
    with CONTAINER_LOCK:
        if CONTAINER is None:
            launch=['docker','run','-d','--rm','--label','geneloop.experiment=remotion-motivation-20261027-v1','--label',f'geneloop.task={WORK.name}','--user',f'{os.getuid()}:{os.getgid()}','--network','none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=512','--memory=4g','--cpus=2','--shm-size=512m','--tmpfs','/tmp:rw,size=1g','--entrypoint','/bin/sh','-v',f'{RUNTIME}:/runtime:ro','-v',f'{WORK}:/work:rw','-v',f'{WORK}/public:/work/public:ro','-w','/work','-e','HOME=/tmp','-e','PATH=/runtime/node_modules/@remotion/compositor-linux-x64-gnu:/usr/local/bin:/usr/bin:/bin:/home/frappe/.nvm/current/bin',IMAGE,'-c','while :; do sleep 3600; done']
            if MEDIA_TOOLS:
                image_index=launch.index(IMAGE)
                launch[image_index:image_index]=['-v',f'{MEDIA_TOOLS}:/media-tools:ro','-e','PATH=/media-tools/node_modules/@ffmpeg-installer/linux-x64:/runtime/node_modules/@remotion/compositor-linux-x64-gnu:/usr/local/bin:/usr/bin:/bin:/home/frappe/.nvm/current/bin']
            CONTAINER=subprocess.check_output(launch,text=True,stderr=subprocess.PIPE,timeout=45).strip()
    argv=['docker','exec','-w','/work',CONTAINER,'/bin/sh','-c',command]
    try:
        p=subprocess.run(argv,text=True,capture_output=True,timeout=timeout_seconds+15)
        result={'exit_code':p.returncode,'stdout':p.stdout[-14000:],'stderr':p.stderr[-8000:]}
    except subprocess.TimeoutExpired:
        result={'exit_code':124,'stderr':'command timeout; output may be partial, inspect before retry'}
    return emit('run_command',{'command':command,'timeout_seconds':timeout_seconds},result,t)

if __name__=='__main__':
    s=MCPServer('Remotion isolated editing workspace')
    for fn in (list_files,read_file,write_file,run_command):
        s.tool(annotations=ToolAnnotations(readOnlyHint=fn in (list_files,read_file),destructiveHint=False))(fn)
    s.run(transport='stdio')
