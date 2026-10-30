"""Recover exact recorded JPEG inputs by content hash, without replaying an Agent.

DSH events store content-addressed attachment metadata. MCP previews can be
overwritten by a later inspection. Render versions and recorded times permit
byte reconstruction; only an exact SHA256 match counts as preserved evidence.
"""
from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path

BASE=Path(os.environ['REMOTION_EXPERIMENT_ROOT']).resolve();EXP=BASE/'structured-v1'
FFMPEG=BASE/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg'

def main():
    reports=[]
    for effective_path in sorted((EXP/'runs').glob('*/*/*/effective.json')):
        run=effective_path.parent
        if not (run/'result.json').exists():continue
        effective=json.loads(effective_path.read_text());work=run/effective['task']['id']
        events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
        calls={};seen=set();records=[];failed_inspections=[]
        for event in events:
            data=event.get('data',{})
            if event.get('type')=='tool/call':calls[data.get('callId')]=data.get('name')
            if event.get('type')!='tool/result':continue
            message=data.get('message',{});cid=message.get('source',{}).get('callId')
            if not cid or cid in seen or calls.get(cid)!='mcp__remotion__inspect_render':continue
            seen.add(cid)
            if any(block.get('type')=='tool-result' and block.get('isError') for block in message.get('content',[])):
                failed_inspections.append(cid);continue
            blocks=[]
            for block in message.get('content',[]):
                if block.get('type')=='tool-result' and not block.get('isError'):blocks.extend(block.get('content',[]))
            metadata=None;images=[]
            for block in blocks:
                if block.get('type')=='text':
                    try:
                        parsed=json.loads(block.get('text',''))
                        if isinstance(parsed,dict) and 'selected_output_seconds' in parsed and 'render_directory' in parsed:metadata=parsed
                    except ValueError:pass
                elif block.get('type')=='image':images.append(block.get('attachment',{}))
            if metadata is None or len(images)!=len(metadata['selected_output_seconds']):
                records.append({'call_id':cid,'preserved':False,'reason':'recorded image metadata projection not recognized'});continue
            folder=metadata['render_directory']
            if not re.fullmatch(r'out/render-[0-9]{3,}',folder):raise ValueError('recorded render path outside fixed output')
            video=work/folder/'video.mp4'
            if hashlib.sha256(video.read_bytes()).hexdigest()!=metadata['video_sha256']:raise ValueError('historical rendered video changed')
            out=run/'evidence/images';out.mkdir(parents=True,exist_ok=True)
            for i,(attachment,seconds) in enumerate(zip(images,metadata['selected_output_seconds'])):
                aid=attachment.get('attachmentId','');match=re.fullmatch(r'sha256:([a-f0-9]{64})',aid)
                if not match:raise ValueError('recorded attachment is not content-addressed')
                expected=match.group(1);target=out/(expected+'.jpg');existing=work/folder/f'preview-{i}.jpg'
                if not target.exists():
                    if existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest()==expected:shutil.copyfile(existing,target)
                    else:
                        process=subprocess.run([str(FFMPEG),'-v','error','-y','-ss',str(seconds),'-i',str(video),
                            '-vf','scale=480:-1','-frames:v','1','-q:v','3',str(target)],capture_output=True,text=True,timeout=60)
                        if process.returncode:raise ValueError('recorded JPEG reconstruction failed')
                actual=hashlib.sha256(target.read_bytes()).hexdigest()
                records.append({'call_id':cid,'output_seconds':seconds,'attachment_id':aid,'expected_bytes':attachment.get('bytes'),
                                'actual_bytes':target.stat().st_size,'actual_sha256':actual,'preserved':actual==expected,
                                'render_directory':folder,'video_sha256':metadata['video_sha256'],
                                'method':'existing pixel bytes or deterministic JPEG reconstruction, strict SHA256 equality'})
        report={'task':effective['task']['id'],'arm':effective['arm'],'trial':effective['trial'],
                'records':records,'failed_inspections_without_pixels':failed_inspections,
                'all_recorded_pixels_preserved':all(r['preserved'] for r in records),
                'actual_model_requests':0,'scope':'evidence preservation, not an independent task or model quality test'}
        (run/'preview-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));reports.append(report)
    (EXP/'preview-evidence-summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    print(json.dumps([{'task':r['task'],'arm':r['arm'],'images':len(r['records']),'all_preserved':r['all_recorded_pixels_preserved']} for r in reports]))

if __name__=='__main__':main()
