"""Resumable, direct-Responses Luna pilot. Never writes data/ or submits a Batch job."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
from pathlib import Path
import random
import re
import ssl
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from luna_topic_pilot import cost, extract, now, obj, read, write, MODEL, ENDPOINT, SYSTEM_CA, RATES
from research_redaction import sanitize_record

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / 'research/typed-questions/pilot-2026-09-25'
PROMPT = ROOT / 'docs/TYPED_QUESTION_PROMPT.md'
PROMPT_V2 = ROOT / 'docs/TYPED_QUESTION_PROMPT_V2.md'
PROMPT_V4 = ROOT / 'docs/TYPED_QUESTION_PROMPT_V4.md'
PROMPT_V5 = ROOT / 'docs/TYPED_QUESTION_PROMPT_V5.md'
EXAMPLES_V2 = ROOT / 'docs/TYPED_QUESTION_EXAMPLES_V2.json'
MODEL_V3 = 'gpt-5.6-luna'
RATES_V3 = {'input': .20, 'cached_input': .02, 'cache_write': .25, 'output': 1.20, 'search_call': .01}
STRING = {'type': 'string'}
STRINGS = {'type': 'array', 'items': STRING}
QUESTION = obj({
    'slot': {'type': 'integer'},
    'status': {'type': 'string', 'enum': ['ready', 'insufficient_evidence']},
    'question': STRING, 'canonical_answer': STRING,
    'accepted_answers': STRINGS, 'prompt_answers': STRINGS, 'rejected_answers': STRINGS,
    'answer_relation': {'type': 'string', 'enum': ['topic', 'related']},
    'difficulty': {'type': 'string', 'enum': ['easy', 'medium', 'hard']},
    'explanation': STRING,
    'evidence': {'type': 'array', 'items': obj({'claim': STRING, 'evidence_ids': STRINGS})},
    'concerns': STRINGS,
})
SCHEMA = obj({'study_topic_id': STRING, 'questions': {'type': 'array', 'items': QUESTION}})
SCHEMA_V4 = obj({'questions': {'type': 'array', 'items': obj({'question': STRING, 'answer': STRING})}})


def prompt_path_for(version):
    if version == 'v5':
        return PROMPT_V5
    return PROMPT_V4 if version == 'v4' else PROMPT_V2 if version in ('v2', 'v3') else PROMPT


def schema_for(version):
    return SCHEMA_V4 if version in ('v4', 'v5') else SCHEMA


def natural_topic_name(title):
    """Drop a trailing category disambiguator for the readable pilot context."""
    return re.sub(r'\s+\([^()]+\)$', '', title).strip()


def readable_context(context):
    lines = ['Topic: ' + natural_topic_name(context['topic']),
             'Category: ' + context['category'],
             'Subcategories: ' + ', '.join('(' + s['label'] + ')' for s in context['subcategories']),
             'Description: ' + context['description']]
    study = context.get('study_content') or {}
    if study.get('overview'):
        lines.append('Overview: ' + '\n\n'.join(b['text'] for b in study['overview']))
    if study.get('key_facts'):
        lines.append('Key Facts:\n' + '\n'.join('- ' + b['text'] for b in study['key_facts']))
    lines.append('Source Questions:')
    for i, source in enumerate(context['source_questions'], 1):
        for part in source['parts']:
            suffix = '' if part['label'] in ('L', 'tossup') else part['label']
            line = f"- Question {i}{suffix}: " + part['question']
            if part['answer']:
                line += '\n  Answer: ' + part['answer']
            lines.append(line)
    return '\n\n'.join(lines)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def data_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'data').rglob('*.json'))}


def stratum(topic, content):
    n = min(5, len(set(topic['source_ids'])))
    bucket = ('1-enriched' if topic['study_topic_id'] in content else '1-sparse') if n == 1 else str(n)
    return topic['primary_category'] + ' | ' + bucket


def topic_context(topic, content, sources, subcategories):
    sid_list = list(dict.fromkeys(topic['source_ids']))
    evidence = {'description': topic['description']}
    detailed = content.get(topic['study_topic_id'])
    if detailed:
        for block in detailed['overview'] + detailed['key_facts']:
            evidence['study:' + block['id']] = block['text']
    tournaments = []
    for sid in sid_list:
        source = sources[sid]
        tournaments.append(source)
        for part in source['parts']:
            evidence[sid + ':' + part['label']] = {'question': part['question'], 'answer': part['answer']}
    return {
        'study_topic_id': topic['study_topic_id'], 'topic': topic['topic'],
        'category': topic['primary_category'],
        'subcategories': [subcategories[s] for s in topic['subcategory_ids']],
        'aliases': topic.get('aliases', []), 'topic_type': topic.get('topic_type'),
        'source_question_count': len(sid_list), 'requested_question_count': min(5, len(sid_list)),
        'description': topic['description'], 'study_content': detailed,
        'source_questions': tournaments, 'evidence_map': evidence,
    }


def make_request(context, instructions, version='v1'):
    if version in ('v4', 'v5'):
        return {'model': MODEL, 'store': False, 'service_tier': 'default',
                'reasoning': {'effort': 'xhigh'}, 'max_output_tokens': 16000,
                'input': instructions.strip().replace('{count}', str(context['requested_question_count']))
                         + ('\n\n---\n\n' + readable_context(context) if version == 'v5'
                            else '\n\n' + json.dumps(context, ensure_ascii=False, indent=2)),
                'text': {'format': {'type': 'json_schema', 'name': 'typed_questions',
                                    'strict': True, 'schema': SCHEMA_V4}}}
    inputs = json.dumps(context, ensure_ascii=False)
    if version in ('v2', 'v3'):
        inputs = []
        for example in read(EXAMPLES_V2):
            inputs.extend([{'role': 'user', 'content': json.dumps(example['input'], ensure_ascii=False)},
                           {'role': 'assistant', 'content': json.dumps(example['output'], ensure_ascii=False)}])
        inputs.append({'role': 'user', 'content': json.dumps(context, ensure_ascii=False)})
    return {'model': MODEL_V3 if version == 'v3' else MODEL, 'store': False, 'service_tier': 'default',
            'reasoning': {'effort': 'high' if version in ('v2', 'v3') else 'medium'},
            'max_output_tokens': 12000 if version in ('v2', 'v3') else 6500,
            'instructions': instructions, 'input': inputs,
            'text': {'format': {'type': 'json_schema', 'name': 'typed_questions',
                                'strict': True, 'schema': SCHEMA}}}


def initialize(run, version='v1'):
    path = run / 'manifest.json'
    if path.exists():
        manifest = read(path)
        if manifest.get('version', 'v1') != version:
            raise ValueError('Run version mismatch; use a separate directory')
        return manifest
    topics, content, sources, taxonomy = [read(ROOT / 'data' / (f + '.json'))
                                         for f in ('topics', 'content', 'sources', 'taxonomy')]
    subcategories = {s['subcategory_id']: s for s in taxonomy['subcategories']}
    groups = defaultdict(list)
    for topic in topics:
        groups[stratum(topic, content)].append(topic)
    rng = random.Random(20260925)
    prompt_path = prompt_path_for(version)
    instructions = prompt_path.read_text()
    selected = []
    for group, pool in sorted(groups.items()):
        topic = rng.choice(sorted(pool, key=lambda t: t['study_topic_id']))
        context = topic_context(topic, content, sources, subcategories)
        if version in ('v4', 'v5'):
            context['requested_question_count'] = max(2, context['requested_question_count'])
        request = make_request(context, instructions, version)
        selected.append({'stratum': group, 'population_weight': len(pool), 'context': context, 'version': version,
                         'request_sha256': digest(request)})
        write(run / 'requests' / (topic['study_topic_id'] + '.json'), request)
        if version == 'v5':
            context_path = run / 'supplied-context' / (topic['study_topic_id'] + '.txt')
            context_path.parent.mkdir(parents=True, exist_ok=True)
            context_path.write_text(readable_context(context))
    manifest = {'created_at': now(), 'seed': 20260925, 'model': MODEL_V3 if version == 'v3' else MODEL, 'version': version,
                'reasoning_effort': 'xhigh' if version in ('v4', 'v5') else 'high' if version in ('v2', 'v3') else 'medium',
                'max_output_tokens': 16000 if version in ('v4', 'v5') else 12000 if version in ('v2', 'v3') else 6500,
                'prompt_path': str(prompt_path.relative_to(ROOT)),
                'examples_sha256': digest(read(EXAMPLES_V2)) if version in ('v2', 'v3') else None,
                'selection': 'One seeded random topic per nonempty category × capped source-count stratum; count-one split by detailed study content presence.',
                'limitations': 'Disproportionate exploratory coverage sample, one topic per stratum; not a precise quality-rate or cost confidence estimate.',
                'population_topics': len(topics),
                'population_questions': sum(max(2 if version in ('v4', 'v5') else 0, min(5, len(set(t['source_ids'])))) for t in topics),
                'population_by_stratum': {g: len(p) for g, p in sorted(groups.items())},
                'data_hashes_before': data_hashes(), 'prompt_sha256': digest(instructions),
                'schema_sha256': digest(schema_for(version)), 'pricing_usd_per_million': {k: (RATES_V3 if version == 'v3' else RATES)[k] for k in ('input', 'cached_input', 'cache_write', 'output')},
                'pricing_url': 'https://developers.openai.com/api/docs/models/' + (MODEL_V3 if version == 'v3' else MODEL),
                'authorization': 'User authorized synchronous Luna pilots and reuse of .env key on September 25, 2026; v3 explicitly requests GPT-5.6 Luna.',
                'budget_usd': 3 if version == 'v3' else 2, 'topics': selected}
    write(path, manifest)
    (run / 'prompt.md').write_text(instructions)
    if version in ('v2', 'v3'):
        write(run / 'examples.json', read(EXAMPLES_V2))
    return manifest


def key(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))
    text = ' '.join(re.findall(r'\w+', text))
    return re.sub(r'^(?:the|a|an) ', '', text)


def validate(result, context, version='v1'):
    errors, warnings = [], []
    if version in ('v4', 'v5'):
        questions = result.get('questions', [])
        if set(result) != {'questions'} or not isinstance(questions, list):
            errors.append('Expected questions array only')
            questions = []
        if len(questions) != context['requested_question_count']:
            errors.append('Wrong question count')
        for slot, q in enumerate(questions, 1):
            if not isinstance(q, dict) or set(q) != {'question', 'answer'} or any(not isinstance(q.get(f), str) or not q[f].strip() for f in ('question', 'answer')):
                errors.append(f'slot {slot}: Expected nonempty question and answer only')
        return {'valid': not errors, 'errors': errors, 'warnings': [],
                'scope': 'Output shape, count, and nonempty text only; editorial review evaluates question quality separately.'}
    if result.get('study_topic_id') != context['study_topic_id']:
        errors.append('Topic ID mismatch')
    questions = result.get('questions', [])
    if [q.get('slot') for q in questions] != list(range(1, context['requested_question_count'] + 1)):
        errors.append('Wrong count or slot order')
    aliases = {key(x) for x in [context['topic'], *context['aliases']]}
    seen_answers, seen_stems = set(), set()
    for q in questions:
        prefix = f"slot {q['slot']}: "
        if q['status'] == 'insufficient_evidence':
            if not q['concerns'] or any(q[f] for f in ('question', 'canonical_answer', 'explanation', 'accepted_answers', 'prompt_answers', 'rejected_answers', 'evidence')):
                errors.append(prefix + 'Invalid blocked slot')
            continue
        if any(not q[f].strip() for f in ('question', 'canonical_answer', 'explanation')):
            errors.append(prefix + 'Missing text')
        if not q['evidence']:
            errors.append(prefix + 'No evidence')
        for claim in q['evidence']:
            if not claim['claim'].strip() or not claim['evidence_ids'] or not set(claim['evidence_ids']) <= context['evidence_map'].keys():
                errors.append(prefix + 'Missing or unknown evidence')
        accepted = {key(x) for x in [q['canonical_answer'], *q['accepted_answers']]}
        prompt, reject = [{key(x) for x in q[f]} for f in ('prompt_answers', 'rejected_answers')]
        if accepted & prompt or accepted & reject or prompt & reject:
            errors.append(prefix + 'Conflicting answer policy')
        if version == 'v1' and context['source_question_count'] == 1 and (q['answer_relation'] == 'topic' or aliases & accepted):
            errors.append(prefix + 'Single-source topic answer prohibited')
        if re.search(r'\b(?:which|what) of (?:these|the following)\b', q['question'], re.I):
            errors.append(prefix + 'Choice-dependent wording')
        # Shared answer strings are allowed under the user's revised review policy.
        # Keep legacy validation unchanged for reproducibility of old runs.
        if key(q['question']) in seen_stems or (version != 'v3' and accepted & seen_answers):
            errors.append(prefix + 'Duplicate question or target answer')
        seen_stems.add(key(q['question'])); seen_answers.update(accepted)
        if any(len(a) >= 4 and (' ' + a + ' ') in (' ' + key(q['question']) + ' ') for a in accepted):
            warnings.append(prefix + 'Possible answer leakage')
        if len(q['canonical_answer'].split()) > 7:
            warnings.append(prefix + 'Long answer')
        if q['concerns']:
            warnings.append(prefix + 'Writer concern: ' + '; '.join(q['concerns']))
    if version == 'v1' and sum(q['status'] == 'ready' and q['answer_relation'] == 'topic' for q in questions) > 1:
        errors.append('More than one topic-identity question')
    return {'valid': not errors, 'errors': errors, 'warnings': warnings,
            'scope': 'Structural and lexical checks only; not semantic/factual certification.'}


def request_cost(response, model):
    if model == MODEL:
        return cost(response)
    if model != MODEL_V3:
        raise ValueError('No pricing configured for requested model')
    usage = response.get('usage') or {}
    details = usage.get('input_tokens_details') or {}
    incoming, outgoing = usage.get('input_tokens', 0), usage.get('output_tokens', 0)
    cached, written = details.get('cached_tokens', 0), details.get('cache_write_tokens', 0)
    rates = RATES_V3
    token_usd = (max(0, incoming - cached - written) * rates['input']
                 + cached * rates['cached_input'] + written * rates['cache_write']
                 + outgoing * rates['output']) / 1_000_000
    return {'input_tokens': incoming, 'cached_input_tokens': cached,
            'cache_write_input_tokens': written, 'output_tokens': outgoing,
            'reasoning_tokens': (usage.get('output_tokens_details') or {}).get('reasoning_tokens', 0),
            'search_calls': 0, 'token_usd': token_usd, 'search_usd': 0, 'estimated_usd': token_usd}


def run_one(run, entry, api_key):
    context = entry['context']; tid = context['study_topic_id']
    target = run / 'responses' / (tid + '.json')
    if target.exists():
        return read(target)
    request_body = read(run / 'requests' / (tid + '.json'))
    if digest(request_body) != entry['request_sha256']:
        raise ValueError('Saved request changed')
    marker = run / 'inflight' / (tid + '.json')
    write(marker, {'topic_id': tid, 'started_at': now()})
    record = {'topic_id': tid, 'topic': context['topic'], 'started_at': now(),
              'request_sha256': entry['request_sha256']}
    start = time.monotonic()
    request = Request(ENDPOINT, data=json.dumps(request_body).encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    try:
        tls = ssl.create_default_context(cafile=str(SYSTEM_CA) if SYSTEM_CA.exists() else None)
        with urlopen(request, timeout=420, context=tls) as handle:
            response = json.load(handle)
            record['request_id'] = handle.headers.get('x-request-id')
        record.update(status=response.get('status'), response=response, usage_cost=request_cost(response, request_body['model']))
        # Save returned usage even if extraction/validation later fails.
        write(target, sanitize_record(record))
        try:
            result = extract(response)
            record['result'] = result
            record['validation'] = validate(result, context, entry.get('version', 'v1'))
            if response.get('status') != 'completed' or not (response.get('model') == request_body['model'] or response.get('model', '').startswith(request_body['model'] + '-')):
                record['validation']['errors'].append('Incomplete response or wrong model')
                record['validation']['valid'] = False
        except (ValueError, TypeError, KeyError, AttributeError):
            record['validation'] = {'valid': False, 'errors': ['Cannot parse/validate output'], 'warnings': []}
    except HTTPError as error:
        # Never persist response error messages or headers that might echo credentials.
        record.update(status='http_error', http_status=error.code, billing_unknown=error.code >= 500)
    except (URLError, TimeoutError, OSError, ValueError) as error:
        record.update(status='transport_error', error_type=type(error).__name__, billing_unknown=True)
    record['completed_at'] = now()
    record['elapsed_seconds'] = round(time.monotonic() - start, 3)
    record = sanitize_record(record)
    write(target, record)
    marker.unlink(missing_ok=True)
    return record


def summarize(run, manifest):
    records = {p.stem: read(p) for p in sorted((run / 'responses').glob('*.json'))}
    total = Counter(); ready = blocked = valid = 0; projection = 0
    issues = []; drafts = []
    for entry in manifest['topics']:
        c = entry['context']; r = records.get(c['study_topic_id'])
        if not r:
            continue
        total.update(r.get('usage_cost', {}))
        projection += r.get('usage_cost', {}).get('estimated_usd', 0) * entry['population_weight']
        valid += bool(r.get('validation', {}).get('valid'))
        for slot, q in enumerate(r.get('result', {}).get('questions', []), 1):
            ready += q.get('status', 'ready') == 'ready'; blocked += q.get('status', 'ready') != 'ready'
            drafts.append({'question_id': f"typed-pilot-{c['study_topic_id']}-{q.get('slot', slot)}",
                           'study_topic_id': c['study_topic_id'], 'topic': c['topic'], 'category': c['category'], **q})
        if not r.get('validation', {}).get('valid') or r.get('validation', {}).get('warnings'):
            issues.append({'topic': c['topic'], 'status': r['status'], 'validation': r.get('validation')})
    complete = len(records) == len(manifest['topics']) and all(r.get('status') == 'completed' and r.get('usage_cost') for r in records.values())
    report = {'updated_at': now(), 'selected_topics': len(manifest['topics']),
              'target_questions': sum(t['context']['requested_question_count'] for t in manifest['topics']),
              'finished_requests': len(records), 'structurally_valid_topics': valid,
              'ready_questions': ready, 'blocked_slots': blocked, 'totals': dict(total),
              'models_returned': dict(Counter(r['response'].get('model') for r in records.values() if r.get('response'))),
              'statuses': dict(Counter(r['status'] for r in records.values())), 'issues': issues,
              'billing_unknown_requests': sum(bool(r.get('billing_unknown')) for r in records.values()),
              'weighted_full_standard_usd': projection if complete else None,
              'weighted_full_batch_usd': projection / 2 if complete else None,
              'projection_note': 'Generation only, stratified weights; excludes review/retries, not a billing invoice or confidence interval.',
              'data_unchanged': data_hashes() == manifest['data_hashes_before']}
    write(run / 'summary.json', report); write(run / 'draft-questions.json', drafts)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'run', 'status'])
    parser.add_argument('--version', choices=['v1', 'v2', 'v3', 'v4', 'v5'], default='v1')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12 or (args.limit is not None and args.limit < 1):
        raise SystemExit('Workers must be 1–12 and limit positive')
    run = (args.run_dir or (DEFAULT_RUN if args.version == 'v1' else DEFAULT_RUN.with_name(DEFAULT_RUN.name + '-' + args.version))).resolve()
    if not run.is_relative_to(ROOT / 'research'):
        raise SystemExit('Pilot artifacts must stay under ignored research/')
    run.mkdir(parents=True, exist_ok=True)
    with (run / '.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = initialize(run, args.version)
        if args.action == 'run':
            prompt_path = prompt_path_for(args.version)
            if data_hashes() != manifest['data_hashes_before'] or digest(prompt_path.read_text()) != manifest['prompt_sha256'] or digest(schema_for(args.version)) != manifest['schema_sha256']:
                raise SystemExit('Data/prompt/schema changed; create a separate pilot version')
            if args.version in ('v2', 'v3') and digest(read(EXAMPLES_V2)) != manifest['examples_sha256']:
                raise SystemExit('Few-shot examples changed; create a separate pilot version')
            report = summarize(run, manifest)
            if report['billing_unknown_requests'] or list((run / 'inflight').glob('*.json')):
                raise SystemExit('Reconcile uncertain prior dispatch before continuing; no automatic retries')
            remaining = [e for e in manifest['topics'] if not (run / 'responses' / (e['context']['study_topic_id'] + '.json')).exists()]
            if args.limit:
                remaining = remaining[:args.limit]
            # Local reservation for bounded output and these short pilot contexts, not a provider cap.
            reservation = .03 if args.version == 'v3' else .02
            if report['totals'].get('estimated_usd', 0) + reservation * len(remaining) > manifest['budget_usd']:
                raise SystemExit('Pilot local cost guardrail reached')
            from dotenv import dotenv_values
            api_key = dotenv_values(ROOT / '.env').get('OPENAI_API_KEY')
            if not api_key:
                raise SystemExit('OPENAI_API_KEY missing from .env')
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(run_one, run, entry, api_key) for entry in remaining]
                for future in as_completed(futures):
                    r = future.result()
                    print(json.dumps({'topic': r['topic'], 'status': r['status'],
                                      'valid': r.get('validation', {}).get('valid'),
                                      'usd': r.get('usage_cost', {}).get('estimated_usd'),
                                      'seconds': r['elapsed_seconds']}), flush=True)
                    summarize(run, manifest)
        print(json.dumps(summarize(run, manifest), indent=2))


if __name__ == '__main__':
    main()
