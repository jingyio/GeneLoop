"""New RSI entry points are read-only previews until explicitly enabled."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
from src.adapters.reuse_form_rsi import propose_form
from src.adapters.source_program_compiler import source_library


@pytest.mark.parametrize('entry',['evolve_forms.py','continue_form.py'])
def test_default_entry_needs_no_model_key_and_does_not_create_runtime_state(tmp_path,entry):
    root=Path(__file__).resolve().parents[1]
    def save(name,value):
        file=tmp_path/name;file.write_text(json.dumps(value));return str(file)
    form={'representation':'typed_tools','catalog_format':'example','compiler_instruction':'Learn current inputs.'}
    proposal=save('proposal.json',propose_form(form,owner='diagnostic',evidence_sha256='a'*64))
    tasks=save('tasks.json',[{'id':'case','arm_order':['fused','program']}])
    plan={'owner':'diagnostic','store':str(tmp_path/'store'),'output_root':str(tmp_path/'output'),
          'library':save('library.json',source_library([])),'tasks':tasks,'baseline_trial':'native',
          'candidates':[{'name':'candidate','trial':'candidate','proposal':proposal}],
          'schedule':[{'task':'case','order':['baseline','candidate']}],
          'post_publication':{'tasks':tasks}}
    file=save('plan.json',plan);env={k:v for k,v in os.environ.items() if k not in ('DEEPSEEK_API_KEY','REMOTION_EXPERIMENT_ROOT')}
    result=subprocess.run([sys.executable,str(root/'scenarios/remotion_edit/structured'/entry),'--plan',file],
                          cwd=tmp_path,env=env,text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)['paid_requests']==0
    assert not (tmp_path/'store').exists() and not (tmp_path/'output').exists()
