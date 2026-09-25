"""Verify frozen requests, conversation replay, exports and costs without API calls."""
from collections import Counter
import json
import math
import typed_question_full as f


def verify(run):
    m=f.p.read(run/'manifest.json');summary=f.p.read(run/'summary.json')
    errors=[];costs=Counter();calls=Counter();responses={}
    def check(condition,message):
        if not condition:errors.append(message)
    check(not summary['running'],'Run is still active')
    check(m['code_hashes']==f.code_hashes(),'Frozen code changed')
    check(m['data_hashes_before']==f.p.data_hashes(),'Production data changed')
    check(not list(run.glob('*/attempt-*/inflight/*.json')),'Unresolved API dispatch')
    for stage in ('generation','correction','quality-repair'):
        for path in (run/stage).glob('attempt-*/responses/*.json'):
            r=f.p.read(path);body=f.p.read(path.parent.parent/'requests'/path.name)
            check(f.p.digest(body)==r['request_sha256'],f'{stage}/{path.stem}: request hash mismatch')
            check(body['model']=='gpt-6-luna' and body['reasoning']['effort']=='xhigh' and body['max_output_tokens']==16000,f'{path.stem}: settings mismatch')
            check(body['text']['format']['schema']==f.p.SCHEMA_V4,f'{path.stem}: schema mismatch')
            check(r.get('status')=='completed' and r.get('validation',{}).get('valid'),f'{stage}/{path.stem}: invalid response')
            responses[(stage,path.stem)]=r
            if not r.get('reused_from'):
                costs.update(r.get('usage_cost',{}));calls[stage]+=1
    expected=[];corrections=0
    for e in m['topics']:
        c=e['context'];tid=c['study_topic_id'];o=f.p.read(run/'outcomes'/(tid+'.json'))
        body=f.p.read(run/'generation/attempt-1/requests'/(tid+'.json'))
        check(f.p.digest(body)==e['request_sha256'],f'{tid}: manifest request mismatch')
        check((run/'supplied-context'/(tid+'.txt')).read_text() in body['input'],f'{tid}: readable context mismatch')
        check(c['requested_question_count']==max(2,min(5,c['source_question_count'])),f'{tid}: quota mismatch')
        check(responses[('generation',tid)]['result']==o['original'],f'{tid}: original output mismatch')
        if o['correction_requested']:
            corrections+=1
            replay=f.correction_request(body,responses[('generation',tid)]['response'],o['flags_before'],(run/'correction-prompt.md').read_text())
            saved=f.p.read(run/'correction/attempt-1/requests'/(tid+'.json'))
            check(replay==saved,f'{tid}: incomplete conversation replay')
        for slot,q in enumerate(o['result']['questions'],1):
            expected.append({'question_id':f'typed-{tid}-{slot}','study_topic_id':tid,'topic':c['topic'],'category':c['category'],'slot':slot,**q})
    check(f.p.read(run/'typed-questions.json')==expected,'Question export differs from outcomes')
    review=f.p.read(run/'giveaway-review.json');remaining=f.p.read(run/'remaining-flags.json')
    check(remaining==[r for r in review if r['flags_after']],'Remaining flags export mismatch')
    check(len(remaining)==summary['flagged_questions_after'],'Remaining flag count mismatch')
    check(sum(calls.values())==summary['new_api_attempts'],'API attempt count mismatch')
    for k,v in costs.items():check(math.isclose(v,summary['totals'][k],rel_tol=1e-10,abs_tol=1e-8),f'Cost/usage mismatch: {k}')
    report={'verified_at':f.p.now(),'errors':errors,'verified_topics':len(m['topics']),'verified_questions':len(expected),
            'verified_correction_conversations':corrections,'new_api_calls_by_stage':dict(calls),
            'reused_generations':m['reused_pilot_generations'],'estimated_new_api_usd':costs['estimated_usd'],
            'checks':'Frozen code/data, request hashes/settings/schema, readable context, quotas, complete correction conversation replay, original outputs, question/flag exports, saved API usage totals.'}
    f.p.write(run/'verification.json',report)
    return report


if __name__=='__main__':
    report=verify(f.RUN);print(json.dumps(report,indent=2));raise SystemExit(bool(report['errors']))
