"""A real failed API task remains failed; it is never a cheap completed sample."""
from scenarios.remotion_edit.structured.review_program_runs import failed_artifact_review,external_reviews
from src.adapters.research_requests import image_content
from src.adapters.script_motif_compiler import digest
import json,pytest


def test_review_frame_labels_stay_immediately_before_their_file_reference():
    frames=[{'frame_index':117,'frame_seconds':3.9},{'frame_index':183,'frame_seconds':6.1}]
    parts=image_content({'instruction':'observe edges'},['file-first','file-second'],frames)
    assert json.loads(parts[1]['text'])==frames[0] and parts[2]['file_id']=='file-first'
    assert json.loads(parts[3]['text'])==frames[1] and parts[4]['file_id']=='file-second'
    with pytest.raises(ValueError,match='image_label_count'):image_content({},['file-first'],[])


def test_missing_video_after_provider_error_is_actual_failure_without_visual_model_call():
    verdict=failed_artifact_review({'status':'failed','video_exists':False},
                                   {'technical_pass':False,'reason':'missing_video'})
    assert verdict['accepted'] is False and verdict['request_id'] is None
    assert 'video_missing' in verdict['observed_failures']
    assert 'no visual model review performed' in verdict['scope']
    assert failed_artifact_review({'status':'completed','video_exists':True},{'technical_pass':True}) is None


def test_failed_source_match_is_known_failure_without_paying_for_visual_review():
    verdict=failed_artifact_review({'status':'completed','video_exists':True},
        {'technical_pass':True,'selected_source_frames_pass':False})
    assert verdict['accepted'] is False and verdict['request_id'] is None
    assert verdict['observed_failures']==['selected_source_frames_pass_failed']


def test_external_pixel_review_waits_for_current_video_and_task_evidence(tmp_path):
    run=tmp_path/'runs/round/program/task';(run/'qa').mkdir(parents=True)
    def save(path,value):path.write_text(json.dumps(value))
    task={'id':'task','instruction':'Current output'}
    save(run/'result.json',{'status':'completed','video_exists':True})
    save(run/'effective.json',{'task':task})
    save(run/'qa/verification.json',{'technical_pass':True,'selected_source_frames_pass':True,'video_sha256':'current'})
    assert external_reviews(tmp_path,'round','protocol')==[str(run)]
    review={'accepted':True,'reviewer':'codex_actual_selected_frames','protocol_sha256':'protocol',
            'task_sha256':digest(task),'video_sha256':'another-video'}
    save(run/'qa/semantic-review.json',review)
    with pytest.raises(ValueError,match='artifact_binding'):external_reviews(tmp_path,'round','protocol')
    review['video_sha256']='current';save(run/'qa/semantic-review.json',review)
    assert external_reviews(tmp_path,'round','protocol')==[]
    save(run/'effective.json',{'task':{**task,'instruction':'Changed'}})
    with pytest.raises(ValueError,match='artifact_binding'):external_reviews(tmp_path,'round','protocol')


def test_shared_external_quality_requires_observed_files_and_pauses_unknown(tmp_path):
    from src.adapters.rsi_protocol import envelope
    from scenarios.remotion_edit.structured.review_program_runs import VISUAL_CHECKS
    import hashlib
    run=tmp_path/'runs/shared/program/task';(run/'qa').mkdir(parents=True)
    task={'id':'task','instruction':'Current task'};video='b'*64;rubric='c'*64
    def save(path,value):path.write_text(json.dumps(value))
    save(run/'result.json',{'status':'completed','video_exists':True})
    save(run/'effective.json',{'task':task})
    save(run/'qa/verification.json',{'technical_pass':True,'selected_source_frames_pass':True,'video_sha256':video})
    frame=run/'qa/frame.png';frame.write_bytes(b'explicit protocol fixture, not real image')
    record=envelope('quality_evaluation',{'id':'review','task_id':'task','task_sha256':digest(task),
        'artifact_sha256':video,'rubric_sha256':rubric,'evaluator':'fixture','scope':'protocol diagnostic','limitations':['not real quality'],
        'checks':[{'id':key,'status':'unknown','observation':'fixture awaiting review',
            'evidence':[{'ref':'qa/frame.png','sha256':hashlib.sha256(frame.read_bytes()).hexdigest()}]} for key in VISUAL_CHECKS]})
    save(run/'qa/semantic-review.json',record)
    assert external_reviews(tmp_path,'shared',rubric)==[str(run)]
    for check in record['payload']['checks']:check['status']='passed'
    save(run/'qa/semantic-review.json',record)
    assert external_reviews(tmp_path,'shared',rubric)==[]
    frame.write_bytes(b'changed after review')
    with pytest.raises(ValueError,match='evidence_changed'):external_reviews(tmp_path,'shared',rubric)
