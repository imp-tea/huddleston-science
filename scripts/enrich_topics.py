"""Resumable work queue for human/agent-researched topic enrichment.

This script makes no model calls. Researchers read assignments, search the web,
and write results; a reviewer accepts each batch before it reaches site data.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'research/topic-enrichment/2026-09-24'
QUEUE = RUN / 'queue.json'
sys.path.insert(0, str(ROOT / 'scripts'))
from build import load_and_validate


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def locked():
    lock = ROOT / '.local/topic-enrichment.lock'
    lock.parent.mkdir(exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def require(condition, message):
    if not condition:
        raise ValueError(message)


def http_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ('https', 'http') and bool(parsed.netloc)


def initialize():
    require(not QUEUE.exists(), 'Queue already exists; use status or claim.')
    topics = read(ROOT / 'data/topics.json')
    content = read(ROOT / 'data/content.json')
    remaining = {t['study_topic_id']: t for t in topics if t['study_topic_id'] not in content}
    batches = []
    for batch_id in ('science', 'history', 'humanities'):
        path = RUN / f'{batch_id}-assignment.json'
        if not path.exists():
            continue
        ids = [t['study_topic_id'] for t in read(path)['topics']]
        require(set(ids) <= remaining.keys(), f'Duplicate or enriched initial assignment: {batch_id}')
        batches.append(dict(batch_id=batch_id, topic_ids=ids, status='assigned', worker=f'{batch_id}_researcher'))
        for tid in ids:
            del remaining[tid]
    # Keep related topics near one another while preserving stable input order.
    categories = list(dict.fromkeys(t['primary_category'] for t in topics))
    for category in categories:
        ids = [tid for tid, t in remaining.items() if t['primary_category'] == category]
        for start in range(0, len(ids), 10):
            batches.append(dict(batch_id=f'batch-{len(batches)+1:04d}', topic_ids=ids[start:start+10], status='pending'))
    RUN.mkdir(parents=True, exist_ok=True)
    write(QUEUE, dict(schema_version=1, created_at=now(), model='gpt-6-sol',
                     baseline_content={tid: digest(value) for tid, value in content.items()}, batches=batches))


def batch_for(queue, batch_id):
    return next(b for b in queue['batches'] if b['batch_id'] == batch_id)


def assignment(batch):
    topics = {t['study_topic_id']: t for t in read(ROOT / 'data/topics.json')}
    sources = read(ROOT / 'data/sources.json')
    path = RUN / f"{batch['batch_id']}-assignment.json"
    if path.exists():
        existing_ids = [t['study_topic_id'] for t in read(path)['topics']]
        require(existing_ids == batch['topic_ids'], f'Stale assignment for {batch["batch_id"]}')
    else:
        write(path, {'batch_id': batch['batch_id'], 'topics': [
            {**topics[tid], 'source_questions': [sources[sid] for sid in topics[tid]['source_ids']]}
            for tid in batch['topic_ids']]})
    return path


def validate_payload(topics, research_records, expected_ids):
    require(set(topics) == set(expected_ids), 'Result topics differ from assignment')
    require(set(research_records) == set(expected_ids), 'Missing research record')
    for tid, content in topics.items():
        require(len(content['overview']) == 1, f'{tid}: expected one paragraph')
        words = len(content['overview'][0]['text'].split())
        require(80 <= words <= 150, f'{tid}: overview has {words} words; expected 80–150')
        require(4 <= len(content['key_facts']) <= 6, f'{tid}: expected 4–6 facts')
        refs = content['source']['references']
        require(bool(refs), f'{tid}: no sources')
        for ref in refs:
            require(all(isinstance(ref.get(k), str) and ref[k].strip() for k in ('title', 'url', 'publisher', 'retrieved_at')), f'{tid}: incomplete reference')
            require(http_url(ref['url']), f'{tid}: invalid URL')
            require(datetime.fromisoformat(ref['retrieved_at'].replace('Z', '+00:00')).tzinfo is not None, f'{tid}: retrieval time must have timezone')
            require(bool(ref.get('license')) == bool(ref.get('license_url')), f'{tid}: incomplete license')
            if ref.get('license_url'):
                require(http_url(ref['license_url']), f'{tid}: invalid license URL')
        urls = {ref['url'] for ref in refs}
        require(len(urls) == len(refs), f'{tid}: duplicate source URL')
        blocks = content['overview'] + content['key_facts']
        require([b['id'] for b in content['overview']] == ['o1'], f'{tid}: invalid overview ID')
        require([b['id'] for b in content['key_facts']] == [f'f{i+1}' for i in range(len(content['key_facts']))], f'{tid}: invalid fact IDs')
        for block in blocks:
            require(isinstance(block['text'], str) and block['text'].strip(), f'{tid}: empty text')
            require(bool(block.get('source_urls')) and set(block['source_urls']) <= urls, f'{tid}/{block["id"]}: missing/unknown citation')
        research = research_records[tid]
        require(bool(research.get('queries')) and all(isinstance(q, str) and q.strip() for q in research['queries']), f'{tid}: missing search trail')
        evidence = research.get('sources', [])
        require({s['url'] for s in evidence} == urls, f'{tid}: evidence does not cover source list')
        require(all(s.get('supports', '').strip() for s in evidence), f'{tid}: empty evidence notes')


def validate_result(batch):
    path = RUN / f"{batch['batch_id']}-results.json"
    result = read(path)
    require(result.get('batch_id') == batch['batch_id'], 'Wrong batch ID')
    validate_payload(result['topics'], result['research'], batch['topic_ids'])
    return result


def accept(queue, batch, reviewer, notes):
    require(reviewer and notes, 'Acceptance requires reviewer and concrete review notes')
    result = validate_result(batch)
    content_path = ROOT / 'data/content.json'
    content = read(content_path)
    for tid, expected in queue['baseline_content'].items():
        require(tid in content and digest(content[tid]) == expected, f'Original study content changed: {tid}')
    for tid, value in result['topics'].items():
        require(tid not in content or content[tid] == value, f'Would overwrite different existing study content: {tid}')
    merged = {**content, **result['topics']}
    # Validate against all authoritative data without making a partial data write.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='enrichment-') as temporary:
        data = Path(temporary)
        for original in (ROOT / 'data').iterdir():
            if original.name != 'content.json':
                (data / original.name).symlink_to(original, target_is_directory=original.is_dir())
        write(data / 'content.json', merged)
        load_and_validate(data)
    write(content_path, merged)
    batch.update(status='accepted', accepted_at=now(), reviewer=reviewer, review_notes=notes,
                 result_sha256=digest(result))
    write(QUEUE, queue)
    return {'accepted': batch['batch_id'], 'topics': len(result['topics']), 'detailed_pages': len(merged)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'status', 'claim', 'validate', 'accept', 'release'])
    parser.add_argument('--batch')
    parser.add_argument('--worker')
    parser.add_argument('--reviewer')
    parser.add_argument('--notes')
    args = parser.parse_args()
    with locked():
        if args.action == 'init':
            initialize()
        queue = read(QUEUE)
        if args.action in ('init', 'status'):
            states = Counter(b['status'] for b in queue['batches'])
            topics = Counter()
            for b in queue['batches']:
                topics[b['status']] += len(b['topic_ids'])
            external = queue.get('external_acceptances', {})
            topics['external_accepted'] = sum(v['status'] == 'accepted' for v in external.values())
            topics['external_prepared'] = sum(v['status'] == 'prepared' for v in external.values())
            print(json.dumps({'batches': states, 'topics': topics,
                              'ready_for_review': [b['batch_id'] for b in queue['batches'] if b['status'] not in ('accepted', 'absorbed') and (RUN / f"{b['batch_id']}-results.json").exists()]}, indent=2))
        elif args.action == 'claim':
            require(args.worker, 'claim requires --worker')
            existing = [b for b in queue['batches'] if b['status'] == 'assigned' and b.get('worker') == args.worker and not (RUN / f"{b['batch_id']}-results.json").exists()]
            batch = existing[0] if existing else next((b for b in queue['batches'] if b['status'] == 'pending' and b['topic_ids']), None)
            if batch is None:
                print(json.dumps({'complete': True}))
                return
            path = assignment(batch)
            batch.update(status='assigned', worker=args.worker, assigned_at=now())
            write(QUEUE, queue)
            print(json.dumps({'batch_id': batch['batch_id'], 'assignment': str(path), 'result': str(RUN / f"{batch['batch_id']}-results.json")}))
        else:
            require(args.batch, f'{args.action} requires --batch')
            batch = batch_for(queue, args.batch)
            if args.action == 'validate':
                result = validate_result(batch)
                print(json.dumps({'valid': args.batch, 'topics': len(result['topics'])}))
            elif args.action == 'accept':
                print(json.dumps(accept(queue, batch, args.reviewer, args.notes)))
            elif args.action == 'release':
                require(batch['status'] not in ('accepted', 'absorbed'), 'Cannot release accepted content')
                require(not (RUN / f"{batch['batch_id']}-results.json").exists(), 'Batch has results; review them before releasing')
                batch.update(status='pending')
                batch.pop('worker', None)
                write(QUEUE, queue)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, StopIteration) as error:
        sys.exit(str(error) or 'Unknown batch')
