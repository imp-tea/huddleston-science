"""Resumable full typed-question generation plus one automatic giveaway review turn.

Writes research artifacts only. Reuses identical v5 pilot generations. Every paid
attempt is saved; correction turns replay the full original Responses output.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

import typed_question_pilot as p
import typed_question_giveaways as g

RUN = p.ROOT / 'research/typed-questions/full-2026-09-25'
PILOT = p.DEFAULT_RUN.with_name(p.DEFAULT_RUN.name + '-v5')
CORRECTION = p.ROOT / 'docs/TYPED_QUESTION_CORRECTION_PROMPT.md'
CODE_FILES = [Path(__file__), Path(g.__file__), Path(p.__file__)]


def code_hashes():
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in CODE_FILES}


def initialize(run):
    manifest_path = run / 'manifest.json'
    if manifest_path.exists():
        return p.read(manifest_path)
    topics, content, sources, taxonomy = [p.read(p.ROOT / 'data' / (n + '.json')) for n in ('topics', 'content', 'sources', 'taxonomy')]
    subs = {s['subcategory_id']: s for s in taxonomy['subcategories']}
    prior = p.read(PILOT / 'manifest.json')
    first = {e['context']['study_topic_id']: i for i, e in enumerate(prior['topics'])}
    prompt = p.PROMPT_V5.read_text()
    entries = []; reused = 0
    for t in sorted(topics, key=lambda x: (first.get(x['study_topic_id'], 99999), x['primary_category'], x['study_topic_id'])):
        c = p.topic_context(t, content, sources, subs)
        c['requested_question_count'] = max(2, c['requested_question_count'])
        tid = c['study_topic_id']; request = p.make_request(c, prompt, 'v5')
        base = run / 'generation/attempt-1'
        p.write(base / 'requests' / (tid + '.json'), request)
        readable = run / 'supplied-context' / (tid + '.txt')
        readable.parent.mkdir(parents=True, exist_ok=True); readable.write_text(p.readable_context(c))
        metadata = {k: c[k] for k in ('study_topic_id', 'topic', 'category', 'source_question_count', 'requested_question_count')}
        e = {'context': metadata, 'version': 'v5', 'request_sha256': p.digest(request), 'reused_generation': False}
        old_request, old_response = PILOT / 'requests' / (tid + '.json'), PILOT / 'responses' / (tid + '.json')
        if old_request.exists() and old_response.exists() and p.read(old_request) == request:
            r = p.read(old_response)
            if r.get('validation', {}).get('valid') and r.get('status') == 'completed':
                r['reused_from'] = str(old_response.relative_to(p.ROOT))
                p.write(base / 'responses' / (tid + '.json'), r)
                e['reused_generation'] = True; reused += 1
        entries.append(e)
    m = {'created_at': p.now(), 'model': p.MODEL, 'reasoning_effort': 'xhigh', 'max_output_tokens': 16000,
         'topics': entries, 'topic_count': len(entries), 'question_count': sum(e['context']['requested_question_count'] for e in entries),
         'reused_pilot_generations': reused, 'data_hashes_before': p.data_hashes(),
         'prompt_sha256': p.digest(prompt), 'correction_prompt_sha256': p.digest(CORRECTION.read_text()),
         'schema_sha256': p.digest(p.SCHEMA_V4), 'code_hashes': code_hashes(), 'detector_version': g.VERSION,
         'local_budget_usd': 15, 'pricing_usd_per_million': p.RATES,
         'authorization': 'User authorized full synchronous generation with automatic giveaway correction; existing .env key reuse authorized.',
         'policy': 'One giveaway correction turn per flagged topic; same answers, only flagged stems applied; residual matches remain review flags. Up to four transport attempts for transient errors, all archived. No production import.'}
    p.write(manifest_path, m)
    (run / 'prompt.md').write_text(prompt); (run / 'correction-prompt.md').write_text(CORRECTION.read_text())
    return m


def correction_request(original_request, response, flags, template):
    request = copy.deepcopy(original_request)
    request['input'] = ([{'role': 'user', 'content': original_request['input']}]
                        + copy.deepcopy(response['output'])
                        + [{'role': 'user', 'content': template.replace('{flags}', json.dumps(flags, ensure_ascii=False, indent=2))}])
    return request


def merge_correction(original, corrected, flags):
    if len(original['questions']) != len(corrected['questions']):
        raise ValueError('Correction changed count')
    if [q['answer'] for q in original['questions']] != [q['answer'] for q in corrected['questions']]:
        raise ValueError('Correction changed answers or order')
    result = copy.deepcopy(original); allowed = {f['slot'] for f in flags}; ignored = []
    for slot, q in enumerate(corrected['questions'], 1):
        if slot in allowed:
            result['questions'][slot-1] = q
        elif q != original['questions'][slot-1]:
            ignored.append(slot)
    return result, ignored


def stage_call(run, stage, entry, request, api_key):
    records = []
    for attempt in range(1, 5):
        base = run / stage / f'attempt-{attempt}'
        req_path = base / 'requests' / (entry['context']['study_topic_id'] + '.json')
        if req_path.exists() and p.read(req_path) != request:
            raise ValueError('Frozen request mismatch')
        if not req_path.exists():
            p.write(req_path, request)
        record = p.run_one(base, {**entry, 'request_sha256': p.digest(request)}, api_key)
        records.append(record)
        if record.get('status') == 'completed' and record.get('validation', {}).get('valid'):
            return record, records
        transient = record.get('http_status') in (408, 429, 500, 502, 503, 504) or record.get('status') == 'transport_error'
        if not transient or attempt == 4:
            return record, records
        time.sleep(min(30, 2 ** attempt))
    raise AssertionError('Unreachable')


def process_topic(run, entry, api_key):
    c = entry['context']; tid = c['study_topic_id']; target = run / 'outcomes' / (tid + '.json')
    if target.exists() and p.read(target)['status'] == 'completed':
        return p.read(target)
    original_request = p.read(run / 'generation/attempt-1/requests' / (tid + '.json'))
    if p.digest(original_request) != entry['request_sha256']:
        raise ValueError('Generation request changed')
    generated, calls = stage_call(run, 'generation', entry, original_request, api_key)
    outcome = {'topic_id': tid, 'topic': c['topic'], 'category': c['category'], 'status': 'generation_failed',
               'reused_generation': entry['reused_generation'], 'flags_before': [], 'flags_after': [],
               'correction_requested': False, 'changed_slots': [], 'result': None}
    if generated.get('status') == 'completed' and generated.get('validation', {}).get('valid'):
        original = generated['result']; outcome['original'] = original
        flags = g.scan(original, c['topic']); outcome['flags_before'] = flags
        outcome['result'] = original; outcome['status'] = 'completed'
        if flags:
            outcome['correction_requested'] = True
            request = correction_request(original_request, generated['response'], flags, (run / 'correction-prompt.md').read_text())
            reviewed, review_calls = stage_call(run, 'correction', entry, request, api_key); calls += review_calls
            if reviewed.get('status') == 'completed' and reviewed.get('validation', {}).get('valid'):
                try:
                    outcome['result'], outcome['ignored_unflagged_changes'] = merge_correction(original, reviewed['result'], flags)
                    outcome['correction_status'] = 'completed'
                except ValueError as error:
                    outcome['correction_status'] = str(error); outcome['status'] = 'correction_failed'
            else:
                outcome['correction_status'] = reviewed.get('status'); outcome['status'] = 'correction_failed'
            outcome['changed_slots'] = [i for i, (a,b) in enumerate(zip(original['questions'],outcome['result']['questions']),1) if a != b]
        outcome['flags_after'] = g.scan(outcome['result'], c['topic'])
    totals = Counter()
    for r in calls:
        if not r.get('reused_from'):
            totals.update(r.get('usage_cost', {}))
    outcome.update(usage_cost=dict(totals), new_api_attempts=sum(not r.get('reused_from') for r in calls),
                   http_statuses=dict(Counter(str(r['http_status']) for r in calls if r.get('http_status'))),
                   billing_unknown_attempts=sum(bool(r.get('billing_unknown')) for r in calls), completed_at=p.now())
    p.write(target, outcome)
    return outcome


def summarize(run, manifest, outcomes, running=False, active=0, stop_reason=None):
    vals = list(outcomes.values()); totals = Counter(); http = Counter()
    for o in vals:
        totals.update(o.get('usage_cost', {})); http.update(o.get('http_statuses', {}))
    report = {'updated_at':p.now(), 'running':running, 'process_id':os.getpid() if running else None,
              'active_topics':active, 'target_topics':manifest['topic_count'], 'target_questions':manifest['question_count'],
              'processed_topics':len(vals), 'completed_topics':sum(o['status']=='completed' for o in vals),
              'generated_questions':sum(len(o['result']['questions']) for o in vals if o.get('result')),
              'failed_topics':sum(o['status']!='completed' for o in vals),
              'correction_topics':sum(o['correction_requested'] for o in vals),
              'flagged_questions_before':sum(len(o['flags_before']) for o in vals),
              'flagged_questions_after':sum(len(o['flags_after']) for o in vals),
              'changed_questions':sum(len(o['changed_slots']) for o in vals),
              'reused_generations':sum(o['reused_generation'] for o in vals),
              'new_api_attempts':sum(o.get('new_api_attempts',0) for o in vals),
              'billing_unknown_attempts':sum(o.get('billing_unknown_attempts',0) for o in vals),
              'http_statuses':dict(http),'totals':dict(totals),'stop_reason':stop_reason,
              'cost_note':'New run only, excluding the 69 previously paid pilot generations. Estimated from returned usage; uncertain transport attempts may add unreported billing.'}
    p.write(run/'summary.json',report)
    return report


def export(run, manifest, outcomes):
    rows=[];review=[]
    for e in manifest['topics']:
        c=e['context'];o=outcomes.get(c['study_topic_id'])
        if not o or not o.get('result'):continue
        before={f['slot']:f['reasons'] for f in o['flags_before']}; after={f['slot']:f['reasons'] for f in o['flags_after']}
        for slot,q in enumerate(o['result']['questions'],1):
            row={'question_id':f"typed-{c['study_topic_id']}-{slot}",'study_topic_id':c['study_topic_id'],
                 'topic':c['topic'],'category':c['category'],'slot':slot,**q}
            rows.append(row)
            if before.get(slot) or after.get(slot):
                review.append({**row,'original_question':o['original']['questions'][slot-1]['question'],
                               'changed':slot in o['changed_slots'],'flags_before':before.get(slot,[]),'flags_after':after.get(slot,[]),
                               'correction_status':o.get('correction_status')})
    p.write(run/'typed-questions.json',rows);p.write(run/'giveaway-review.json',review)
    p.write(run/'remaining-flags.json',[r for r in review if r['flags_after']])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','run','status','export'])
    parser.add_argument('--run-dir',type=Path,default=RUN)
    parser.add_argument('--workers',type=int,default=64)
    parser.add_argument('--limit',type=int)
    args=parser.parse_args();run=args.run_dir.resolve()
    if not run.is_relative_to(p.ROOT/'research') or not 1<=args.workers<=96 or (args.limit is not None and args.limit<1):
        raise SystemExit('Invalid run path, worker count, or limit')
    run.mkdir(parents=True,exist_ok=True)
    with (run/'.run.lock').open('a') as lock:
        if args.action in ('init','run','export'):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m=initialize(run)
        outcomes={f.stem:p.read(f) for f in (run/'outcomes').glob('*.json')}
        if args.action=='status':
            print(json.dumps(p.read(run/'summary.json') if (run/'summary.json').exists() else summarize(run,m,outcomes),indent=2));return
        if args.action=='run':
            if m['data_hashes_before']!=p.data_hashes() or m['code_hashes']!=code_hashes() or m['prompt_sha256']!=p.digest(p.PROMPT_V5.read_text()) or m['correction_prompt_sha256']!=p.digest(CORRECTION.read_text()):
                raise SystemExit('Frozen run inputs/code changed')
            # A leftover marker means a prior process might have dispatched without recording a response.
            if list(run.glob('*/attempt-*/inflight/*.json')):
                raise SystemExit('Unresolved in-flight dispatch; inspect before resuming')
            from dotenv import dotenv_values
            api_key=dotenv_values(p.ROOT/'.env').get('OPENAI_API_KEY')
            if not api_key:raise SystemExit('Missing authorized API key')
            remaining=[e for e in m['topics'] if outcomes.get(e['context']['study_topic_id'],{}).get('status')!='completed']
            if args.limit:remaining=remaining[:args.limit]
            iterator=iter(remaining);active={};exhausted=False;reason=None;last_report=0
            report=summarize(run,m,outcomes,True)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                while active or not exhausted:
                    while not exhausted and len(active)<args.workers:
                        spent=sum(o.get('usage_cost',{}).get('estimated_usd',0) for o in outcomes.values())
                        if spent+.05*(len(active)+1)>m['local_budget_usd']:
                            reason='Local budget reservation reached';exhausted=True;break
                        e=next(iterator,None)
                        if e is None:exhausted=True;break
                        active[pool.submit(process_topic,run,e,api_key)]=e['context']['study_topic_id']
                    if not active:break
                    done,_=wait(active,timeout=5,return_when=FIRST_COMPLETED)
                    for f in done:
                        tid=active.pop(f);outcomes[tid]=f.result()
                        if outcomes[tid]['http_statuses'].get('401') or outcomes[tid]['http_statuses'].get('403'):
                            exhausted=True;reason='Authentication/access failure'
                    if time.monotonic()-last_report>=15:
                        report=summarize(run,m,outcomes,True,len(active),reason)
                        print(json.dumps({k:report[k] for k in ('processed_topics','completed_topics','active_topics','failed_topics','correction_topics','changed_questions','flagged_questions_after')}|{'usd':report['totals'].get('estimated_usd',0)}),flush=True)
                        last_report=time.monotonic()
            report=summarize(run,m,outcomes,False,0,reason)
        else:report=summarize(run,m,outcomes)
        export(run,m,outcomes)
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
