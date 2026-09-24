"""Accept selected, normalized Luna topics into the durable enrichment queue.

The normalized input is produced by normalize_luna_topics.py. A two-phase queue
write reserves selected IDs before content is written, so interrupted imports
cannot leave an ID claimable while its page is already in site data. Rerunning
the same selection completes a prepared import or verifies an accepted one.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import enrich_topics as enrichment
from build import load_and_validate
from research_redaction import sanitize_value


def selected_ids(args):
    ids = list(args.topic_id)
    if args.ids_file:
        value = json.loads(args.ids_file.read_text())
        enrichment.require(isinstance(value, list), '--ids-file must contain a JSON array')
        ids.extend(value)
    enrichment.require(ids and all(isinstance(tid, str) and tid for tid in ids),
                       'Select IDs with --topic-id or --ids-file')
    enrichment.require(len(ids) == len(set(ids)), 'Duplicate selected topic ID')
    return ids


def validate_merged(merged):
    with TemporaryDirectory(prefix='luna-integration-') as temporary:
        data = Path(temporary)
        for original in (enrichment.ROOT / 'data').iterdir():
            if original.name != 'content.json':
                (data / original.name).symlink_to(original, target_is_directory=original.is_dir())
        enrichment.write(data / 'content.json', merged)
        load_and_validate(data)


def validate_provenance(tid, record):
    enrichment.require(isinstance(record, dict), f'{tid}: missing provenance')
    enrichment.require(record.get('self_check_complete') is True,
                       f'{tid}: researcher self-check incomplete')
    enrichment.require(record.get('automatic_validation_passed') is True,
                       f'{tid}: automatic validation incomplete')
    enrichment.require(record.get('model') == 'gpt-6-luna', f'{tid}: unexpected model')
    raw_hash = record.get('raw_sha256')
    enrichment.require(isinstance(raw_hash, str) and re.fullmatch(r'[0-9a-f]{64}', raw_hash),
                       f'{tid}: invalid raw response hash')
    raw_path = record.get('response_path')
    enrichment.require(isinstance(raw_path, str) and raw_path, f'{tid}: missing raw response path')
    path = Path(raw_path)
    if not path.is_absolute():
        path = enrichment.ROOT / path
    enrichment.require(path.is_file(), f'{tid}: raw response missing: {path}')
    raw_bytes = path.read_bytes()
    enrichment.require(hashlib.sha256(raw_bytes).hexdigest() == raw_hash,
                       f'{tid}: raw response hash mismatch')
    try:
        raw_record = json.loads(raw_bytes)
    except (ValueError, UnicodeDecodeError):
        raise ValueError(f'{tid}: raw response is invalid JSON') from None
    enrichment.require(sanitize_value(raw_record)[1]['changed_fields'] == 0,
                       f'{tid}: raw response contains unsanitized credential material')
    redaction = raw_record.get('redaction') if isinstance(raw_record, dict) else None
    enrichment.require(redaction is None or isinstance(redaction, dict),
                       f'{tid}: malformed raw response redaction metadata')
    if redaction is not None:
        enrichment.require(record.get('response_redaction') == redaction,
                           f'{tid}: response redaction provenance mismatch')
    enrichment.require(not (isinstance(redaction, dict) and
                            (redaction.get('result_changed') or redaction.get('citation_urls_changed'))),
                       f'{tid}: redacted generated result requires reviewed stable-source repair')
    timestamp = record.get('request_time')
    enrichment.require(isinstance(timestamp, str) and timestamp, f'{tid}: missing request time')
    enrichment.require(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).tzinfo is not None,
                       f'{tid}: request time lacks timezone')


def integrate(input_path, ids, dry_run=False):
    normalized = enrichment.read(input_path)
    enrichment.require(sanitize_value(normalized)[1]['changed_fields'] == 0,
                       'Normalized input contains unsanitized credential material')
    topics = normalized.get('topics', {})
    research = normalized.get('research', {})
    provenance = normalized.get('provenance', {})
    blocked = normalized.get('blocked_topics', {})
    enrichment.require(normalized.get('batch_id') == 'luna-normalized', 'Unexpected normalized batch ID')
    enrichment.require(normalized.get('model') == 'gpt-6-luna', 'Unexpected normalized model')
    for tid in ids:
        enrichment.require(tid not in blocked, f'{tid}: blocked by normalizer: {blocked.get(tid)}')
        enrichment.require(tid in topics and tid in research and tid in provenance,
                           f'{tid}: missing normalized topic, research, or provenance')
        validate_provenance(tid, provenance[tid])
    selected_topics = {tid: topics[tid] for tid in ids}
    selected_research = {tid: research[tid] for tid in ids}
    enrichment.validate_payload(selected_topics, selected_research, ids)

    queue = enrichment.read(enrichment.QUEUE)
    content_path = enrichment.ROOT / 'data/content.json'
    content = enrichment.read(content_path)
    known_ids = {t['study_topic_id'] for t in enrichment.read(enrichment.ROOT / 'data/topics.json')}
    for tid in ids:
        enrichment.require(tid in known_ids and tid not in queue['baseline_content'],
                           f'{tid}: not a queued enrichment topic')
    for tid, expected in queue['baseline_content'].items():
        enrichment.require(tid in content and enrichment.digest(content[tid]) == expected,
                           f'Original study content changed: {tid}')

    acceptances = queue.setdefault('external_acceptances', {})
    fresh = []
    resumed = []
    already = []
    touched = set()
    for tid in ids:
        value = selected_topics[tid]
        topic_hash = enrichment.digest(value)
        research_hash = enrichment.digest(selected_research[tid])
        existing = acceptances.get(tid)
        if existing:
            enrichment.require(existing['topic_sha256'] == topic_hash and
                               existing['research_sha256'] == research_hash and
                               existing['raw_sha256'] == provenance[tid]['raw_sha256'],
                               f'{tid}: conflicts with prior external acceptance')
            enrichment.require(existing['status'] in ('prepared', 'accepted'),
                               f'{tid}: invalid acceptance state')
            (already if existing['status'] == 'accepted' else resumed).append(tid)
        else:
            owners = [b for b in queue['batches'] if tid in b['topic_ids']]
            enrichment.require(len(owners) == 1, f'{tid}: expected exactly one queued batch')
            batch = owners[0]
            enrichment.require(batch['status'] == 'pending',
                               f'{tid}: batch {batch["batch_id"]} is not pending')
            for suffix in ('assignment', 'results'):
                enrichment.require(not (enrichment.RUN / f'{batch["batch_id"]}-{suffix}.json').exists(),
                                   f'{tid}: batch {batch["batch_id"]} has {suffix} file')
            enrichment.require(tid not in content or content[tid] == value,
                               f'{tid}: would overwrite different existing content')
            fresh.append(tid)
            touched.add(batch['batch_id'])
        enrichment.require(tid not in content or content[tid] == value,
                           f'{tid}: content differs from normalized topic')
        if tid in already:
            enrichment.require(tid in content, f'{tid}: accepted content is missing')

    merged = {**content, **selected_topics}
    validate_merged(merged)
    summary = {'selected': len(ids), 'new': len(fresh), 'resumed': len(resumed),
               'already_accepted': len(already), 'affected_batches': len(touched),
               'detailed_pages': len(merged), 'dry_run': dry_run}
    if dry_run:
        return summary

    # First commit: remove IDs from claimable batches and persist their full
    # research trail. These reservations make a retry safe after a crash.
    for batch in queue['batches']:
        removed = [tid for tid in batch['topic_ids'] if tid in fresh]
        if not removed:
            continue
        batch.setdefault('original_topic_ids', list(batch['topic_ids']))
        batch['topic_ids'] = [tid for tid in batch['topic_ids'] if tid not in fresh]
        if not batch['topic_ids']:
            batch['status'] = 'absorbed'
            batch['absorbed_at'] = enrichment.now()
    for tid in fresh:
        acceptances[tid] = {
            'status': 'prepared',
            'topic_sha256': enrichment.digest(selected_topics[tid]),
            'research_sha256': enrichment.digest(selected_research[tid]),
            'raw_sha256': provenance[tid]['raw_sha256'],
            'provenance': provenance[tid],
            'research': selected_research[tid],
            'reviewer': 'coordinator',
            'review_policy': 'User-approved Luna researcher self-check and automatic validation; no independent factual audit claimed.',
            'prepared_at': enrichment.now(),
        }
    if fresh:
        enrichment.write(enrichment.QUEUE, queue)
    if fresh or resumed or content != merged:
        enrichment.write(content_path, merged)
    for tid in fresh + resumed:
        acceptances[tid]['status'] = 'accepted'
        acceptances[tid]['accepted_at'] = enrichment.now()
    if fresh or resumed:
        enrichment.write(enrichment.QUEUE, queue)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Normalized Luna JSON file')
    parser.add_argument('--topic-id', action='append', default=[], help='One ID; repeat for multiple topics')
    parser.add_argument('--ids-file', type=Path, help='JSON array of selected topic IDs')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    with enrichment.locked():
        print(json.dumps(integrate(args.input, selected_ids(args), args.dry_run), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
