"""Read-only structural and correction-integrity audit of a full generation run."""
import argparse
from collections import Counter
from pathlib import Path
import typed_question_full as f


def contains_topic(text, topic):
    hay=' '+' '.join(f.g.tokens(text))+' '
    words=f.g.tokens(f.p.natural_topic_name(topic))
    if not words:return False
    variants=[words]
    last=words[-1]
    variants.append(words[:-1]+[last+'s'])
    if last.endswith('y'):variants.append(words[:-1]+[last[:-1]+'ies'])
    return any(' '+' '.join(v)+' ' in hay for v in variants)


def audit(run):
    m=f.p.read(run/'manifest.json');outcomes={p.stem:f.p.read(p) for p in (run/'outcomes').glob('*.json')}
    missing=[];errors=[];duplicates=[];topic_loss=[];unflagged_changes=[];answer_changes=[];identifiers=[]
    for entry in m['topics']:
        c=entry['context'];tid=c['study_topic_id'];o=outcomes.get(tid)
        if not o:missing.append(tid);continue
        if o['status']!='completed':errors.append({'topic_id':tid,'topic':c['topic'],'status':o['status'],'detail':o.get('correction_status')})
        result=o.get('result')
        if not result:continue
        shape=f.p.validate(result,c,'v5')
        if not shape['valid']:errors.append({'topic_id':tid,'errors':shape['errors']})
        original=o.get('original',result);allowed={v['slot'] for v in o['flags_before']}
        allowed.update(o.get('quality_repair_slots',[]))
        answers=[q['answer'].casefold() for q in result['questions']]
        if len(set(answers))!=len(answers):duplicates.append({'topic_id':tid,'topic':c['topic'],'answers':answers})
        for slot,(a,b) in enumerate(zip(original['questions'],result['questions']),1):
            identifiers.append(f'typed-{tid}-{slot}')
            if a['answer']!=b['answer']:answer_changes.append({'topic_id':tid,'slot':slot})
            if a!=b and slot not in allowed:unflagged_changes.append({'topic_id':tid,'slot':slot})
            if slot>1 and contains_topic(a['question'],c['topic']) and not contains_topic(b['question'],c['topic']):
                topic_loss.append({'topic_id':tid,'topic':c['topic'],'slot':slot,'answer':b['answer'],'before':a['question'],'after':b['question']})
    report={'updated_at':f.p.now(),'expected_topics':m['topic_count'],'outcome_topics':len(outcomes),'expected_questions':m['question_count'],
            'result_questions':len(identifiers),'unique_question_ids':len(set(identifiers)),
            'missing_topics':missing,'errors':errors,'duplicate_answer_topics':duplicates,
            'changed_answers':answer_changes,'changed_unflagged_questions':unflagged_changes,
            'corrections_dropping_literal_topic':topic_loss,
            'data_unchanged':m['data_hashes_before']==f.p.data_hashes(),
            'scope':'Mechanical shape, count, identity and correction-integrity checks; topic loss is a review candidate, not a semantic verdict.'}
    f.p.write(run/'audit.json',report)
    return report


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,default=f.RUN)
    report=audit(parser.parse_args().run_dir)
    print(json.dumps({k:(len(v) if isinstance(v,list) else v) for k,v in report.items()},indent=2))
