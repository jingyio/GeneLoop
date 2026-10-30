from pathlib import Path
import hashlib,json,os,shutil,subprocess,time
ROOT=Path(__file__).resolve().parents[2]
b=Path(os.environ.get('REMOTION_EXPERIMENT_ROOT',str(ROOT/'.local/experiments/remotion-motivation-20261027-v1'))).resolve()
source=b/'source-media-v2/BigBuckBunny.mp4';tool=b/'qa-runtime/node_modules/@ffmpeg-installer/linux-x64/ffmpeg';started=time.monotonic()
source_sha=hashlib.sha256(source.read_bytes()).hexdigest();rows=json.loads((b/'asset-manifest.json').read_text())
for name,offset,fps in [('bunny_a_24.mp4',20,24),('bunny_b_30.mp4',80,30),('bunny_c_60.mp4',150,60)]:
 out=b/'assets'/name
 args=[str(tool),'-v','error','-y','-ss',str(offset),'-i',str(source),'-t','12','-vf','scale=640:360','-r',str(fps),'-c:v','libx264','-preset','fast','-crf','23','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)]
 if out.exists(): raise FileExistsError('preserve existing derived asset; use a fresh trial directory for preparation')
 subprocess.run(args,check=True,timeout=240,capture_output=True)
 rows.append(dict(name=name,url='https://remotion.media/BigBuckBunny.mp4',sha256=hashlib.sha256(out.read_bytes()).hexdigest(),bytes=out.stat().st_size,parent_sha256=source_sha,parent_segment_seconds=[offset,offset+12],derived=True,output_fps=fps,width=640,height=360,preparation_args=args,credit='Big Buck Bunny, Blender Foundation; Remotion official example source',independence='different scene excerpt from the same film, not independent filming'))
g=b/'assets/greenscreen.mp4'
if not g.exists():shutil.copyfile(b/'source-media-v2/greenscreen.mp4',g)
rows.append(dict(name=g.name,url='https://remotion.media/greenscreen.mp4',sha256=hashlib.sha256(g.read_bytes()).hexdigest(),bytes=g.stat().st_size,derived=False,credit='Remotion public test media'))
(b/'asset-manifest-v2.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));(b/'asset-preparation-v2.json').write_text(json.dumps(dict(parent_sha256=source_sha,parent_bytes=source.stat().st_size,elapsed_seconds=time.monotonic()-started,model_calls=0,kind='deterministic input preparation, not an Agent trajectory'),indent=2))
print(json.dumps([{'name':r['name'],'bytes':r['bytes'],'sha256':r['sha256'],'fps':r.get('output_fps')} for r in rows]))
