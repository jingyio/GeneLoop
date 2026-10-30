"""Only ordinary witnessed source can seed the next program-learning round."""
import importlib.util,json
from pathlib import Path
import pytest
from src.adapters.script_motif_compiler import sha

FILE=Path(__file__).resolve().parents[1]/'scenarios/remotion_edit/structured/learn_programs.py'
spec=importlib.util.spec_from_file_location('source_learner',FILE)
learner=importlib.util.module_from_spec(spec);spec.loader.exec_module(learner)


@pytest.mark.parametrize('tool',['write_source','render_source'])
@pytest.mark.parametrize('arm',['fused','program'])
def test_current_ordinary_source_is_usable_after_native_render_or_program_fallback(tmp_path,tool,arm):
    task={'id':'new-task'};source='observed model TSX';video_sha='a'*64
    work=tmp_path/task['id'];(work/'src').mkdir(parents=True);(work/'out/render-1').mkdir(parents=True)
    (tmp_path/'qa').mkdir();(work/'src/index.tsx').write_text(source)
    def save(path,value):path.write_text(json.dumps(value))
    save(tmp_path/'effective.json',{'arm':arm,'task':task})
    save(tmp_path/'result.json',{'status':'completed'})
    save(tmp_path/'qa/verification.json',{'technical_pass':True,'selected_source_frames_pass':True,'video_sha256':video_sha})
    save(work/'out/render-1/receipt.json',{'source_version':sha(source),'video_sha256':video_sha})
    save(tmp_path/'events.jsonl',{'type':'tool/call','data':{'name':'mcp__remotion__'+tool,'callId':'call-1','arguments':{'text':source}}})
    assert learner.collect(tmp_path)[0]['call_id']=='call-1'
    # A program render alone cannot serve as its own model-authored source witness.
    save(tmp_path/'events.jsonl',{'type':'tool/call','data':{'name':'mcp__remotion__render_program','callId':'call-2','arguments':{'parameters':{}}}})
    with pytest.raises(ValueError,match='current_source_not_witnessed'):learner.collect(tmp_path)
