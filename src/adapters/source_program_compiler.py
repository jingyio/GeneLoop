"""Compile model-proposed source programs; execution remains in the scene sandbox.

The compiler checks transport and provenance, not whether a program is suitable
for a new task. Current semantic selection and independent execution checks are
required. Unlike the older Python reader compiler, this supports generated
artifacts (including TSX) without treating their writes as read-only operations.
"""
from __future__ import annotations

from jsonschema import Draft202012Validator
from .script_motif_compiler import digest, sha

PARAMETER_TOKEN = '__GENELOOP_PARAMETERS__'
FORMAT = 'parameterized_source_program_v1'


def json_numbers(value):
    """JSON has one number type; agree with JS for integral Python floats."""
    if isinstance(value, dict):return {k:json_numbers(v) for k,v in value.items()}
    if isinstance(value, list):return [json_numbers(v) for v in value]
    if isinstance(value, float) and value.is_integer():return int(value)
    return value


def program_identity(program):
    return {key: program[key] for key in ('format', 'language', 'template', 'parameters_schema')}


def compile_source_program(proposal, witness):
    proposal = json_numbers(proposal)
    required = {'description', 'language', 'template', 'parameters_schema', 'default_parameters'}
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise ValueError('source_program_proposal_shape')
    if proposal['language'] not in ('tsx', 'javascript'):
        raise ValueError('source_program_language')
    template = proposal['template']
    if not isinstance(template, str) or not 1 <= len(template.encode()) <= 100000 or template.count(PARAMETER_TOKEN) != 1:
        raise ValueError('source_program_parameter_token')
    if not isinstance(proposal['description'], str) or not 1 <= len(proposal['description']) <= 600:
        raise ValueError('source_program_description')
    schema = proposal['parameters_schema']
    Draft202012Validator.check_schema(schema)
    if schema.get('type') != 'object':
        raise ValueError('source_program_object_parameters')
    Draft202012Validator(schema).validate(proposal['default_parameters'])
    if not witness.get('task_id') or not witness.get('events_sha256') or not witness.get('source_sha256'):
        raise ValueError('source_program_witness_required')
    if witness.get('source_sha256') != sha(witness.get('source', '')):
        raise ValueError('source_program_witness_changed')
    program = {'format': FORMAT, **proposal}
    program['id'] = 'source_' + digest(program_identity(program))[:24]
    program['source_witness'] = {key: value for key, value in witness.items() if key != 'source'}
    program['status'] = 'candidate'
    return program


def source_library(programs, *, parent_digest=None, generation=0):
    if len({p['id'] for p in programs}) != len(programs):
        raise ValueError('duplicate_source_program')
    body = json_numbers({'format': 'source_program_library_v1', 'generation': generation,
                         'parent_digest': parent_digest, 'programs': programs})
    return {**body, 'digest': digest(body)}
