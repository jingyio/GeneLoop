import pytest
from src.adapters.source_program_compiler import compile_source_program, source_library
from src.adapters.script_motif_compiler import sha


def sample():
    proposal = {'description':'Render a parameterized composition','language':'tsx',
                'template':'const p=__GENELOOP_PARAMETERS__; console.log(p);',
                'parameters_schema':{'type':'object','properties':{'start':{'type':'number'}},'required':['start']},
                'default_parameters':{'start':1}}
    witness = {'task_id':'observed-task','source':'observed code','source_sha256':sha('observed code'),'events_sha256':'a'*64}
    return proposal,witness


def test_source_program_keeps_trace_identity_and_dynamic_parameters():
    proposal,witness=sample()
    program=compile_source_program(proposal,witness)
    assert program['status']=='candidate'
    assert program['source_witness']['source_sha256']==witness['source_sha256']
    assert 'source' not in program['source_witness']
    changed={**proposal,'default_parameters':{'start':4}}
    assert compile_source_program(changed,witness)['id']==program['id']
    assert source_library([program])['parent_digest'] is None
    floating={**proposal,'parameters_schema':{**proposal['parameters_schema'],'minProperties':1.0},
              'default_parameters':{'start':1.0}}
    assert compile_source_program(floating,witness)['default_parameters']['start']==1
    assert type(source_library([compile_source_program(floating,witness)])['programs'][0]['default_parameters']['start']) is int


def test_source_program_rejects_changed_witness_and_duplicate_publication():
    proposal,witness=sample()
    with pytest.raises(ValueError,match='witness_changed'):
        compile_source_program(proposal,{**witness,'source':'changed'})
    program=compile_source_program(proposal,witness)
    with pytest.raises(ValueError,match='duplicate'):
        source_library([program,program])
