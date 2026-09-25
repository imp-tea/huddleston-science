"""Targeted follow-up repairs discovered during correction spot-checks.

Stage preserves complete conversation history. Apply runs only after the main run
stops, keeping original output and all additional requests/responses for review.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import typed_question_full as f

REPAIRS={
    'study-23fe0fa4598b6e023632': {'slots':[2], 'note':'The correction dropped the required topic lymph node from question 2. Restore lymph node naturally in the fluid-filtering question while preserving the answer Lymph. The overlap with the required topic name is acceptable here; do not remove the topic to avoid that match.'},
    'study-255784d04be5580323f0': {'slots':[2], 'note':'The correction dropped the required topic wave interference from question 2. Restore the phrase wave interference naturally as a clue to the experiment, preserving the intended answer and the two closely spaced openings and light fringes. Do not name Young or the full experiment in the stem.'},
    'study-ef732d9b998eea883518': {'slots':[5], 'note':'The correction dropped the required topic electric charge from question 5. Restore electric charge naturally, preserving the answer and the distinguishing 1909, oil droplets, electric field, and Harvey Fletcher clues. Do not name Millikan in the stem.'},
    'study-77b2dbfefcc77034ed8a': {'slots':[2], 'note':'The correction dropped the topic Minaret from question 2. Restore the word minaret naturally while preserving the answer Qutb Minar and the distinguishing Delhi/location/date clues. Do not restore the revealing Qutb name in the stem.'},
    'study-7a6351c0bae24030a0fd': {'slots':[2], 'note':'The correction introduced a factual reversal: the exiles who rejected the egg decree were Big-Endians, but the intended answer must remain Little-Endians. Rewrite question 2 to describe supporters of cracking the smaller end of an egg, not the exiles. Keep the topic egg in the question. The detector match between the ordinary word end and Endians is a false positive; retain clear factual context rather than concealing it.'},
}


def stage(run):
    from dotenv import dotenv_values
    key=dotenv_values(f.p.ROOT/'.env').get('OPENAI_API_KEY')
    if not key:raise SystemExit('Missing authorized API key')
    m=f.p.read(run/'manifest.json');entries={e['context']['study_topic_id']:e for e in m['topics']}
    for tid,fix in REPAIRS.items():
        o=f.p.read(run/'outcomes'/(tid+'.json'))
        if o.get('quality_repair_applied'):continue
        for attempt in range(4,0,-1):
            path=run/'correction'/f'attempt-{attempt}'/'responses'/(tid+'.json')
            if path.exists():
                r=f.p.read(path)
                if r.get('validation',{}).get('valid'):
                    request=f.p.read(path.parent.parent/'requests'/(tid+'.json'));break
        else:raise ValueError('Expected prior completed correction')
        body=copy.deepcopy(request)
        body['input']+=copy.deepcopy(r['response']['output'])+[{'role':'user','content':fix['note']+' Return the complete question/answer list in the same order. Preserve every answer exactly, and leave all other questions unchanged. Return only the same question/answer JSON format.'}]
        response,calls=f.stage_call(run,'quality-repair',entries[tid],body,key)
        if not response.get('validation',{}).get('valid'):raise ValueError('Quality repair failed')
        result,ignored=f.merge_correction(o['result'],response['result'],[{'slot':s} for s in fix['slots']])
        total=Counter()
        for call in calls:total.update(call.get('usage_cost',{}))
        f.p.write(run/'quality-repairs'/(tid+'.json'),{'topic_id':tid,'slots':fix['slots'],'note':fix['note'],
                'previous_result_sha256':f.p.digest(o['result']),'result':result,'usage_cost':dict(total),
                'new_api_attempts':len(calls),'ignored_unflagged_changes':ignored})
        print(json.dumps({'topic':o['topic'],'repair_staged':True,'result':result},ensure_ascii=False))


def apply(run):
    if f.p.read(run/'summary.json').get('running'):raise SystemExit('Wait until main run finishes before applying repairs')
    m=f.p.read(run/'manifest.json')
    for path in sorted((run/'quality-repairs').glob('*.json')):
        fix=f.p.read(path);target=run/'outcomes'/(fix['topic_id']+'.json');o=f.p.read(target)
        if o.get('quality_repair_applied'):continue
        if f.p.digest(o['result'])!=fix['previous_result_sha256']:raise ValueError('Outcome changed since repair')
        o['result']=fix['result'];o['quality_repair_applied']=True;o['quality_repair_slots']=fix['slots'];o['quality_repair_note']=fix['note']
        total=Counter(o['usage_cost']);total.update(fix['usage_cost']);o['usage_cost']=dict(total);o['new_api_attempts']+=fix['new_api_attempts']
        o['changed_slots']=[i for i,(a,b) in enumerate(zip(o['original']['questions'],o['result']['questions']),1) if a!=b]
        o['flags_after']=f.g.scan(o['result'],o['topic']);f.p.write(target,o)
    outcomes={path.stem:f.p.read(path) for path in (run/'outcomes').glob('*.json')}
    print(json.dumps(f.summarize(run,m,outcomes),indent=2));f.export(run,m,outcomes)
    for name in ('giveaway-review.json','remaining-flags.json'):
        rows=f.p.read(run/name)
        for row in rows:
            outcome=outcomes[row['study_topic_id']]
            if row['slot'] in outcome.get('quality_repair_slots',[]):
                row['quality_repair_note']=outcome['quality_repair_note']
        f.p.write(run/name,rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['stage','apply']);parser.add_argument('--run-dir',type=Path,default=f.RUN)
    args=parser.parse_args();(stage if args.action=='stage' else apply)(args.run_dir)
