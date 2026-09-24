"""Generate the authorized remaining two-source topics with one Luna request each.

Reuses the pilot's request, source requirements, usage calculation and TLS setup.
Only writes research artifacts; integration is a separate validated operation.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import os
from pathlib import Path

import luna_topic_pilot as pilot

ROOT = pilot.ROOT
RUN = ROOT / 'research/topic-enrichment/luna-two-source-2026-09-24'
PILOT = ROOT / 'research/topic-enrichment/luna-pilot-2026-09-24'


def initialize():
    path = RUN / 'manifest.json'
    if path.exists():
        return pilot.read(path)
    previous = pilot.read(PILOT / 'manifest.json')
    completed_pilot = {t['study_topic_id'] for t in previous['topics']
                       if (PILOT / 'responses' / f"{t['study_topic_id']}.json").exists()}
    topics = pilot.read(ROOT / 'data/topics.json')
    content = pilot.read(ROOT / 'data/content.json')
    sources = pilot.read(ROOT / 'data/sources.json')
    eligible = [t for t in topics if t['study_topic_id'] not in content
                and len(set(t['source_ids'])) >= 2]
    selected = [{**t, 'source_questions': [sources[sid] for sid in t['source_ids']]}
                for t in sorted(eligible, key=lambda t: (t['primary_category'], t['study_topic_id']))
                if t['study_topic_id'] not in completed_pilot]
    manifest = {'created_at': pilot.now(), 'model': pilot.MODEL, 'count': len(selected),
                'selection': 'All currently unenriched topics with at least two distinct original tournament source IDs, excluding completed pilot topics.',
                'eligible_count_before': len(eligible), 'pilot_topics_reused': sorted(completed_pilot),
                'sample_by_category': dict(Counter(t['primary_category'] for t in selected)),
                'data_hashes_before': pilot.data_hashes(), 'budget_usd': 40,
                'max_tool_calls': previous['max_tool_calls'],
                'max_output_tokens': previous['max_output_tokens'],
                'reasoning_effort': previous['reasoning_effort'], 'service_tier': 'default',
                'pricing_usd': pilot.RATES, 'pricing_url': previous['pricing_url'],
                'authorization': 'User accepted pilot quality and authorized the remaining two-original-source topics on September 24, 2026; existing API key reuse remains authorized.',
                'acceptance_policy': 'Researcher self-checks and automatic structural checks; minimum search and one direct source open. No routine independent factual audit. Per-reference open trace gaps are informational.',
                'topics': selected}
    pilot.write(path, manifest)
    return manifest


def summarize(manifest, records, *, running=False, active=0, stop_reason=None, started_at=None):
    totals = Counter()
    errors = Counter()
    for record in records.values():
        totals.update(record.get('usage_cost', {}))
        errors.update(set(e.split(':')[0] for e in record.get('validation', {}).get('errors', [])))
    report = {'updated_at': pilot.now(), 'model_requested': pilot.MODEL,
              'selected_topics': len(manifest['topics']), 'requests_finished': len(records),
              'responses_completed': sum(r.get('status') == 'completed' for r in records.values()),
              'requests_remaining': len(manifest['topics']) - len(records),
              'running': running, 'active_requests': active, 'process_id': os.getpid() if running else None,
              'run_started_at': started_at, 'stop_reason': stop_reason,
              'strict_pilot_checks_passed': sum(r.get('validation', {}).get('valid', False) for r in records.values()),
              'topics_by_strict_pilot_error_type': dict(errors),
              'response_statuses': dict(Counter(r.get('status') for r in records.values())),
              'models_returned': dict(Counter(r['response'].get('model') for r in records.values() if r.get('response'))),
              'totals': dict(totals),
              'billing_unknown_requests': sum(bool(r.get('billing_unknown')) for r in records.values()),
              'price_is_estimate_from_api_usage_not_invoice': True,
              'site_data_unchanged_since_selection': pilot.data_hashes() == manifest['data_hashes_before'],
              'nothing_imported_by_generator': True}
    pilot.write(RUN / 'summary.json', report)
    return report


def can_dispatch(spent, active, budget):
    # Conservative local reservation, not a server-enforced billing cap.
    return spent + .25 * (active + 1) <= budget


def run_recorded(topic, manifest, key):
    marker = RUN / 'inflight' / f"{topic['study_topic_id']}.json"
    pilot.write(marker, {'topic_id': topic['study_topic_id'], 'dispatched_at': pilot.now(),
                         'process_id': os.getpid()})
    result = pilot.run_one(topic, manifest, key)
    marker.unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'run', 'status'])
    parser.add_argument('--workers', type=int, default=20)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if not 1 <= args.workers <= 20 or (args.limit is not None and args.limit < 1):
        raise SystemExit('Workers must be 1–20; limit must be positive')
    RUN.mkdir(parents=True, exist_ok=True)
    pilot.RUN = RUN
    with (RUN / '.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = initialize()
        ids = {t['study_topic_id'] for t in manifest['topics']}
        records = {r['topic_id']: r for r in
                   (pilot.read(p) for p in sorted((RUN / 'responses').glob('*.json')))}
        if not set(records) <= ids:
            raise SystemExit('Unexpected response IDs outside the fixed manifest')
        report = summarize(manifest, records)
        if args.action != 'run':
            print(pilot.json.dumps(report, indent=2))
            return
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / '.env').get('OPENAI_API_KEY')
        if not key:
            raise SystemExit('OPENAI_API_KEY absent from ignored local .env')
        if report['billing_unknown_requests']:
            raise SystemExit('Resolve uncertain request outcomes before resuming; existing requests will not be repeated')
        unfinished = [p.stem for p in (RUN / 'inflight').glob('*.json') if p.stem not in records]
        if unfinished:
            raise SystemExit('Interrupted dispatch records require reconciliation before any new requests')
        remaining = [t for t in manifest['topics'] if t['study_topic_id'] not in records]
        if args.limit is not None:
            remaining = remaining[:args.limit]
        iterator = iter(remaining)
        pending = {}
        exhausted = False
        stop_reason = None
        started_at = pilot.now()
        spent = report['totals'].get('estimated_usd', 0)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            while pending or not exhausted:
                while not stop_reason and len(pending) < args.workers and not exhausted:
                    if not can_dispatch(spent, len(pending), manifest['budget_usd']):
                        stop_reason = 'Local $40 cost guardrail reached; remaining topics retained in manifest'
                        break
                    try:
                        topic = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    pending[pool.submit(run_recorded, topic, manifest, key)] = topic
                summarize(manifest, records, running=True, active=len(pending),
                          stop_reason=stop_reason, started_at=started_at)
                if not pending:
                    break
                done, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                for future in done:
                    topic = pending.pop(future)
                    try:
                        record = future.result()
                    except Exception as error:
                        # Do not print arbitrary exception messages or redispatch an uncertain call.
                        stop_reason = 'Unexpected worker exception: ' + type(error).__name__
                        record = {'topic_id': topic['study_topic_id'], 'topic': topic['topic'],
                                  'category': topic['primary_category'], 'status': 'worker_error',
                                  'error_type': type(error).__name__, 'billing_unknown': True,
                                  'completed_at': pilot.now()}
                        pilot.write(RUN / 'responses' / f"{topic['study_topic_id']}.json", record)
                    records[record['topic_id']] = record
                    spent += record.get('usage_cost', {}).get('estimated_usd', 0)
                    if record.get('billing_unknown'):
                        stop_reason = 'Uncertain request outcome; stopped dispatch to prevent duplicate charges'
                    if record.get('status') == 'http_error':
                        stop_reason = f"HTTP {record.get('http_status')}; pending requests will finish, remaining topics stay queued"
                    print(pilot.json.dumps({'finished': len(records), 'selected': len(manifest['topics']),
                                           'topic': record['topic'], 'status': record.get('status'),
                                           'estimated_usd': round(spent, 5)}), flush=True)
        report = summarize(manifest, records, stop_reason=stop_reason, started_at=started_at)
        print(pilot.json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
