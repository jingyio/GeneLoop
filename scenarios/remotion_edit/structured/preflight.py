"""Real stdio/container diagnostics, without any model request."""
from __future__ import annotations
import asyncio,base64,hashlib,io,json,os,shutil,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
from mcp import Client,StdioServerParameters
from PIL import Image

HERE=Path(__file__).resolve().parent
BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve()

def value(result):
    projected=result.structured_content
    if projected is None and result.content and result.content[0].type=='text':
        projected=json.loads(result.content[0].text)
    if not isinstance(projected,dict):raise ValueError('complete MCP JSON observation required')
    return projected

async def main():
    root=BASE/'structured-v1/diagnostics'/('preflight-'+uuid4().hex)
    work=root/'t00_preflight';(work/'src').mkdir(parents=True);(work/'out').mkdir();(work/'public').mkdir()
    name='bunny_b_30.mp4';original=(BASE/'assets'/name).read_bytes();(work/'public'/name).write_bytes(original)
    version=hashlib.sha256(original).hexdigest();(work/'node_modules').symlink_to('/runtime/node_modules')
    (work/'package.json').write_text('{"private":true}')
    source="""import React from 'react';import {registerRoot,Composition,AbsoluteFill,OffthreadVideo,staticFile,useCurrentFrame} from 'remotion';
const Edit=()=> {const f=useCurrentFrame();return <AbsoluteFill><OffthreadVideo src={staticFile('bunny_b_30.mp4')} trimBefore={24} muted style={{width:'100%',height:'100%',objectFit:'cover'}}/><div style={{position:'absolute',left:0,top:0,width:16,height:16,backgroundColor:f<24?'#ff0000':'#0000ff'}}/></AbsoluteFill>};
registerRoot(()=> <Composition id='Main' component={Edit} durationInFrames={48} fps={24} width={320} height={180}/>);
"""
    (work/'src/index.tsx').write_text(source)
    env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','LD_LIBRARY_PATH') if k in os.environ}
    env.update(REMOTION_WORK=str(work),REMOTION_RUNTIME=str(BASE/'runtime'),REMOTION_IMAGE=os.environ['REMOTION_IMAGE'],
               REMOTION_MEDIA_TOOLS=str(BASE/'qa-runtime'),REMOTION_TASK_ASSETS=json.dumps({name:version}),
               REMOTION_TASK_NONCE=uuid4().hex,REMOTION_FUSED_PROBE='0')
    before=(BASE/'budget-checkpoint.json').read_bytes();checks={};started=time.monotonic();complete=False
    try:
        params=StdioServerParameters(command=sys.executable,args=[str(HERE/'server.py')],cwd=str(HERE.parents[2]),env=env)
        async with Client(params,read_timeout_seconds=300) as client:
            tools=(await client.list_tools()).tools
            schemas=[t.model_dump(mode='json',by_alias=True) for t in tools]
            (root/'mcp-tools.json').write_text(json.dumps(schemas,ensure_ascii=False,indent=2))
            checks['schema_tools']=len(tools)==8
            checks['no_arbitrary_shell']=not any(t.name=='run_command' for t in tools)
            selected=await client.call_tool('pin_asset',{'name':name});assert not selected.is_error
            pinned=value(selected)
            probed=await client.call_tool('probe_media',{'source_id':pinned['source_id']});assert not probed.is_error
            checks['versioned_probe']=value(probed)['source_version']==version
            checks['source_actual_fps']=next(s for s in value(probed)['streams'] if s['codec_type']=='video')['r_frame_rate']=='30/1'
            checks['unknown_handle_rejected']=(await client.call_tool('probe_media',{'source_id':'source-'+'0'*32})).is_error
            checks['path_escape_rejected']=(await client.call_tool('pin_asset',{'name':'../'+name})).is_error
            stale=await client.call_tool('render_composition',{'source_version':'0'*64})
            checks['stale_source_rejected']=stale.is_error
            checks['stale_source_reason_visible']='current source digest required' in str(stale.content)
            (work/'public'/name).write_bytes(original+b'changed')
            checks['mutated_input_rejected']=(await client.call_tool('probe_media',{'source_id':pinned['source_id']})).is_error
            (work/'public'/name).write_bytes(original)
            bad_source=source.replace("staticFile('bunny_b_30.mp4')", "'bunny_b_30.mp4'")
            written=await client.call_tool('write_source',{'text':bad_source});assert not written.is_error
            failed=await client.call_tool('render_composition',{'source_version':value(written)['source_version']})
            checks['render_failure_reason_visible']=failed.is_error and '404' in str(failed.content)
            checks['failed_render_not_published']=not (work/'out/video.mp4').exists()
            restored=await client.call_tool('write_source',{'text':source});assert not restored.is_error
            rendered=await client.call_tool('render_composition',{'source_version':hashlib.sha256(source.encode()).hexdigest()})
            if rendered.is_error:raise ValueError('render preflight failed: '+str(rendered.content))
            receipt=value(rendered)
            video=next(s for s in receipt['streams'] if s['codec_type']=='video')
            checks['actual_video']=video['width']==320 and video['height']==180 and video['r_frame_rate']=='24/1' and int(video['nb_frames'])==48 and receipt['full_video_decode'] is True
            preview=await client.call_tool('inspect_render',{'seconds':[0,.25,.5,.75,1.25,1.5]})
            if preview.is_error:raise ValueError('pixel preflight failed: '+str(preview.content))
            images=[b for b in preview.content if b.type=='image']
            checks['actual_image_blocks']=len(images)==6
            checks['actual_image_bytes']=all(Image.open(io.BytesIO(base64.b64decode(im.data))).size==(320,180) for im in images)
            boundary=await client.call_tool('inspect_render',{'seconds':[.999,1.0]});assert not boundary.is_error
            checks['actual_frame_indices']=[r['frame_index'] for r in value(boundary)['selected_output_frames']]==[23,24]
            colors=[Image.open(io.BytesIO(base64.b64decode(im.data))).convert('RGB').getpixel((4,4)) for im in boundary.content if im.type=='image']
            checks['cut_boundary_pixels']=colors[0][0]>180 and colors[0][2]<80 and colors[1][2]>180 and colors[1][0]<80
            (root/'preview-content-shapes.json').write_text(json.dumps({'types':[b.type for b in preview.content],'image_bytes':[len(base64.b64decode(im.data)) for im in images],'receipt':value(preview)},indent=2))
        checks['no_paid_requests']=(BASE/'budget-checkpoint.json').read_bytes()==before
        assert all(checks.values()),checks
        complete=True
    finally:
        ids=subprocess.check_output(['docker','ps','-aq','--filter','label=geneloop.experiment=remotion-motivation-20261027-v1','--filter','label=geneloop.task=t00_preflight'],text=True).split()
        if ids:subprocess.run(['docker','rm','-f',*ids],capture_output=True,timeout=30)
        record={'checks':checks,'all_pass':complete,'elapsed_seconds':time.monotonic()-started,'model_requests':0,'scope':'actual MCP and container diagnostics, not model behavior or savings'}
        (root/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2));print(json.dumps({'directory':str(root),**record},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
