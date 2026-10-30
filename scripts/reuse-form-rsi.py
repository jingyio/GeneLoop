"""Assess a frozen paired report, retain rejections, and publish accepted forms.

This command never runs a paid model or changes a validation threshold. The
proposal comes from propose-reuse-form.py and measurements from the scene's
independent verifier/reviewer/accounting pipeline. New tasks resolve latest once.
"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.adapters.reuse_form_rsi import evaluate_form,publish_form,resolve_form,interface_variants
from src.motif_core.offline.experience_registry import read,durable


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True);p.add_argument('--owner',required=True)
    p.add_argument('--proposal',type=Path);p.add_argument('--measurements',type=Path)
    p.add_argument('--library',type=Path);p.add_argument('--publish',action='store_true')
    p.add_argument('--expand',type=Path,help='save finite interface variants for a frozen validation plan')
    a=p.parse_args()
    if a.proposal is None:
        policy,library=resolve_form(a.store,a.owner)
        print(json.dumps({'policy':policy,'library':str(library)},ensure_ascii=False));return
    proposal=read(a.proposal)
    if proposal['owner']!=a.owner:raise ValueError('reuse_form_foreign_owner')
    if a.expand:
        variants=interface_variants(proposal)
        for variant in variants:durable(a.expand/(variant['digest']+'.json'),variant,exclusive=True)
        print(json.dumps({'candidate_count':len(variants),'paid_requests':0,'published':False}));return
    if a.measurements is None or a.library is None:p.error('proposal requires measurements and library')
    measured=read(a.measurements);library=read(a.library)
    verdict=evaluate_form(proposal,measured,library)
    result={'verdict':verdict,'published':False}
    if a.publish:
        result.update(publish_form(a.store,proposal,verdict,library,a.measurements,
            expected_parent=proposal['parent_digest']))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
