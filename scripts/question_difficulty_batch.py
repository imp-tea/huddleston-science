"""Submit, reconcile, and collect the full question difficulty Batch API run.

Uses the approved v2 rubric; keeps immutable inputs and matches outputs by ID.
No synchronous model calls. publish writes a versioned data sidecar only after
every question succeeds and its source question and answer still match.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from luna_topic_pilot import now, read, write, SYSTEM_CA

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'research/question-difficulty/full-batch-2026-09-27'
PROMPT = ROOT / 'docs/QUESTION_DIFFICULTY_PROMPT_V2.md'
TERMINAL = {'completed', 'failed', 'expired', 'cancelled'}
LABELS = {'Easy', 'Medium', 'Hard'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_questions(root=ROOT):
    topics = {t['study_topic_id']: t for t in read(root / 'data/topics.json')}
    rows = []
    paths = [root / 'data/typed-questions.json', *sorted((root / 'data/practice').glob('*.json'))]
    for path in paths:
        typed = path.name == 'typed-questions.json'
        for q in read(path):
            row = {'question_id': q['question_id'], 'study_topic_id': q['study_topic_id'],
                   'question': q['question'], 'answer': q['answer'] if typed else q['correct_answer'],
                   'format': 'typed' if typed else 'multiple_choice',
                   'category': topics[q['study_topic_id']]['primary_category'],
                   'source_file': str(path.relative_to(root))}
            row['source_sha256'] = digest({k: row[k] for k in
                ('question_id', 'study_topic_id', 'question', 'answer', 'format')})
            rows.append(row)
    if len({q['question_id'] for q in rows}) != len(rows) or not rows:
        raise ValueError('Question IDs must be unique; bank must not be empty.')
    return sorted(rows, key=lambda q: q['question_id'])


def prepare(run):
    path = run / 'manifest.json'
    if path.exists():
        manifest = read(path)
        validate_input(run, manifest)
        return manifest
    questions = source_questions()
    prompt = PROMPT.read_text()
    input_path = run / 'input.jsonl'
    with input_path.open('w') as stream:
        for q in questions:
            body = {'model': 'gpt-6-sol', 'reasoning': {'effort': 'low'}, 'store': False,
                    'max_output_tokens': 1024, 'instructions': prompt,
                    'input': 'Question:\n' + q['question'] + '\n\nAnswer:\n' + q['answer']}
            stream.write(json.dumps({'custom_id': q['question_id'], 'method': 'POST',
                                    'url': '/v1/responses', 'body': body}, ensure_ascii=False) + '\n')
    if len(questions) > 50000 or input_path.stat().st_size > 200_000_000:
        raise ValueError('Input exceeds a single Batch API file limit.')
    manifest = {'schema_version': 1, 'created_at': now(), 'run_id': str(uuid.uuid4()),
                'model': 'gpt-6-sol', 'reasoning_effort': 'low', 'prompt': prompt,
                'prompt_sha256': digest(prompt), 'questions': questions,
                'input_sha256': hashlib.sha256(input_path.read_bytes()).hexdigest(),
                'counts_by_format': dict(Counter(q['format'] for q in questions)),
                'pricing_usd_per_million': {'input': 1, 'cached_input': .1, 'output': 5},
                'pricing_source': 'https://developers.openai.com/api/docs/models/gpt-6-sol',
                'policy': 'Question and answer only; no choices. All questions submitted, including pilot questions. No automatic paid retries.'}
    write(path, manifest)
    return manifest


def validate_input(run, manifest):
    if hashlib.sha256((run / 'input.jsonl').read_bytes()).hexdigest() != manifest['input_sha256']:
        raise ValueError('Frozen batch input changed.')


def prepare_parts(run, manifest):
    """Small uploads avoid long transport timeouts; requests are unchanged."""
    index = run / 'parts.json'
    if index.exists():
        parts = read(index)
        for name in parts:
            validate_input(run / name, read(run / name / 'manifest.json'))
        return parts
    lines = (run / 'input.jsonl').read_text().splitlines(keepends=True)
    parts = []
    for start in range(0, len(lines), 4000):
        name = f'part-{len(parts) + 1:02d}'
        path = run / name
        path.mkdir(exist_ok=True)
        text = ''.join(lines[start:start + 4000])
        (path / 'input.jsonl').write_text(text)
        questions = manifest['questions'][start:start + 4000]
        child = {**manifest, 'run_id': str(uuid.uuid4()), 'questions': questions,
                 'parent_run_id': manifest['run_id'],
                 'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
                 'counts_by_format': dict(Counter(q['format'] for q in questions))}
        write(path / 'manifest.json', child)
        parts.append(name)
    write(index, parts)
    return parts


def split_pending(run, manifest):
    """Halve only parts with no attempted batch submission after upload failures."""
    parts = prepare_parts(run, manifest)
    updated = []
    for name in parts:
        path = run / name
        if (path / 'batch.json').exists() or (path / 'submission-pending.json').exists():
            updated.append(name)
            continue
        child = read(path / 'manifest.json')
        lines = (path / 'input.jsonl').read_text().splitlines(keepends=True)
        if len(lines) <= 500:
            updated.append(name)
            continue
        size = (len(lines) + 1) // 2
        for number, start in enumerate(range(0, len(lines), size), 1):
            subname = name + f'-{number}'
            subpath = run / subname
            subpath.mkdir(exist_ok=True)
            text = ''.join(lines[start:start + size])
            (subpath / 'input.jsonl').write_text(text)
            questions = child['questions'][start:start + size]
            sub = {**child, 'run_id': str(uuid.uuid4()), 'questions': questions,
                   'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
                   'counts_by_format': dict(Counter(q['format'] for q in questions))}
            write(subpath / 'manifest.json', sub)
            updated.append(subname)
    if b''.join((run / n / 'input.jsonl').read_bytes() for n in updated) != (run / 'input.jsonl').read_bytes():
        raise ValueError('Splitting changed the frozen requests.')
    write(run / 'parts.json', updated)
    return {'parts': updated}


class API:
    def __init__(self):
        from dotenv import dotenv_values
        self.key = dotenv_values(ROOT / '.env').get('OPENAI_API_KEY')
        if not self.key:
            raise ValueError('OPENAI_API_KEY missing from .env')
        self.tls = ssl.create_default_context(cafile=str(SYSTEM_CA) if SYSTEM_CA.exists() else None)

    def call(self, path, payload=None, *, raw=False, content_type='application/json'):
        data = json.dumps(payload).encode() if isinstance(payload, dict) else payload
        req = Request('https://api.openai.com/v1' + path, data=data,
                      headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': content_type})
        try:
            with urlopen(req, timeout=180, context=self.tls) as response:
                data = response.read()
        except HTTPError as exc:
            # Never emit request headers, credentials, or arbitrary exception bodies.
            raise RuntimeError(f'API HTTP {exc.code} for {path.split("?")[0]}') from None
        return data if raw else json.loads(data)

    def upload(self, path):
        # curl streams multipart uploads reliably on this host. Supply the
        # credential via stdin config, never argv, disk, logs, or shell expansion.
        header = json.dumps('Authorization: Bearer ' + self.key)
        result = subprocess.run(['curl', '--http1.1', '--silent', '--show-error', '--max-time', '180',
            '--config', '-', '--form', 'purpose=batch', '--form', 'file=@' + str(path.resolve()),
            '--write-out', '\n%{http_code}', 'https://api.openai.com/v1/files'],
            input='header = ' + header + '\n', capture_output=True, text=True)
        if result.returncode:
            detail = result.stderr.replace(self.key, '[REDACTED]').strip()[:500]
            raise RuntimeError(f'File upload transport failure (curl {result.returncode}): {detail}')
        body, status = result.stdout.rsplit('\n', 1)
        if status != '200':
            raise RuntimeError(f'File upload HTTP {status}.')
        return json.loads(body)


def submit(run, manifest, api):
    validate_input(run, manifest)
    if (run / 'batch.json').exists():
        return read(run / 'batch.json')
    marker = run / 'submission-pending.json'
    if marker.exists():
        # A process may have stopped after the API accepted a batch. Reconcile
        # by metadata rather than blindly submitting and charging again.
        after = ''
        while True:
            page = api.call('/batches?limit=100' + after)
            matches = [b for b in page['data'] if (b.get('metadata') or {}).get('run_id') == manifest['run_id']]
            if len(matches) > 1:
                raise ValueError('Multiple remote batches match; inspect before continuing.')
            if matches:
                write(run / 'batch.json', matches[0])
                return matches[0]
            if not page.get('has_more'):
                break
            after = '&after=' + page['last_id']
        raise ValueError('Submission outcome uncertain. No matching batch found; do not resubmit automatically.')
    file_path = run / 'uploaded-file.json'
    if not file_path.exists():
        write(file_path, api.upload(run / 'input.jsonl'))
    payload = {'input_file_id': read(file_path)['id'], 'endpoint': '/v1/responses',
               'completion_window': '24h', 'metadata': {'run_id': manifest['run_id'],
               'description': 'Full question difficulty, v2 rubric, Sol low'}}
    write(marker, {'created_at': now(), 'payload': payload})
    batch = api.call('/batches', payload)
    write(run / 'batch.json', batch)
    return batch


def parse_outputs(lines, questions):
    expected = {q['question_id']: q for q in questions}
    seen, results, failures, usage = set(), {}, [], Counter()
    for line in lines:
        record = json.loads(line)
        qid = record.get('custom_id')
        if qid not in expected or qid in seen:
            raise ValueError('Unknown or duplicate output question ID.')
        seen.add(qid)
        response = record.get('response') or {}
        body = response.get('body') or {}
        u = body.get('usage') or {}
        usage.update({k: u.get(k, 0) for k in ('input_tokens', 'output_tokens')})
        usage['cached_tokens'] += (u.get('input_tokens_details') or {}).get('cached_tokens', 0)
        text = ''.join(c.get('text', '') for item in body.get('output', [])
                       for c in item.get('content', []) if c.get('type') == 'output_text').strip()
        if (record.get('error') or response.get('status_code') != 200
                or body.get('status') != 'completed' or text not in LABELS):
            failures.append({'question_id': qid, 'status': body.get('status'),
                             'http_status': response.get('status_code'), 'label': text,
                             'error': record.get('error') or body.get('error')})
            continue
        results[qid] = {'difficulty': text.lower(), 'source_sha256': expected[qid]['source_sha256'],
                        'response_id': body['id'], 'model_returned': body.get('model')}
    missing = sorted(set(expected) - seen)
    return results, failures, missing, dict(usage)


def collect(run, manifest, api):
    batch = api.call('/batches/' + read(run / 'batch.json')['id'])
    write(run / 'batch.json', batch)
    if batch['status'] not in TERMINAL:
        return batch
    lines = []
    for field in ('output_file_id', 'error_file_id'):
        if not batch.get(field):
            continue
        path = run / (field + '.jsonl')
        if not path.exists():
            data = api.call('/files/' + batch[field] + '/content', raw=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
        lines.extend(line for line in path.read_text().splitlines() if line.strip())
    return summarize(run, manifest, batch, lines)


def summarize(run, manifest, batch, lines):
    results, failures, missing, usage = parse_outputs(lines, manifest['questions'])
    write(run / 'failures.json', {'failed': failures, 'missing': missing})
    summary = {'batch_ids': batch.get('batch_ids', [batch['id']]), 'status': batch['status'], 'valid': len(results),
               'failed': len(failures), 'missing': len(missing), 'usage': usage,
               'counts': dict(Counter(q['difficulty'] for q in results.values())),
               'counts_by_format': {fmt: dict(Counter(results[q['question_id']]['difficulty']
                    for q in manifest['questions'] if q['format'] == fmt and q['question_id'] in results))
                    for fmt in manifest['counts_by_format']},
               'estimated_cost_usd': (usage.get('input_tokens', 0) - .9 * usage.get('cached_tokens', 0)
                                      + 5 * usage.get('output_tokens', 0)) / 1_000_000}
    write(run / 'summary.json', summary)
    annotations = {'schema_version': 1, 'batch_ids': batch.get('batch_ids', [batch['id']]), 'model': manifest['model'],
                   'reasoning_effort': 'low', 'prompt_sha256': manifest['prompt_sha256'],
                   'completed_at': batch.get('completed_at'), 'questions': results}
    write(run / 'annotations.json', annotations)
    return {**batch, 'local_summary': summary}


def operate_parts(run, manifest, api, action):
    batches_by_name = {}
    parts = prepare_parts(run, manifest)

    def operate(name):
        path = run / name
        child = read(path / 'manifest.json')
        batch = submit(path, child, api) if action == 'submit' else collect(path, child, api)
        return name, batch

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(operate, name) for name in parts]
        errors = []
        for future in as_completed(futures):
            try:
                name, batch = future.result()
            except Exception as exc:
                name = parts[futures.index(future)]
                detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                errors.append({'part': name, 'error': detail})
                write(run / name / 'last-error.json', {'at': now(), 'error': detail})
                print(json.dumps(errors[-1]), flush=True)
                continue
            batches_by_name[name] = batch
            print(json.dumps({'part': name, 'id': batch['id'], 'status': batch['status'],
                              'request_counts': batch.get('request_counts'), 'errors': batch.get('errors')}), flush=True)
    if errors:
        raise RuntimeError(f'{len(errors)} parts need attention; see part last-error.json files.')
    batches = [batches_by_name[name] for name in parts]
    write(run / 'batches.json', batches)
    if action != 'submit' and all(b['status'] in TERMINAL for b in batches):
        lines = []
        for name in parts:
            for field in ('output_file_id', 'error_file_id'):
                path = run / name / (field + '.jsonl')
                if path.exists():
                    lines.extend(line for line in path.read_text().splitlines() if line.strip())
        state = 'completed' if all(b['status'] == 'completed' for b in batches) else 'partial_or_failed'
        combined = {'id': None, 'batch_ids': [b['id'] for b in batches], 'status': state,
                    'completed_at': max((b.get('completed_at') or 0) for b in batches)}
        return summarize(run, manifest, combined, lines)
    return {'id': None, 'status': 'submitted' if action == 'submit' else 'in_progress',
            'request_counts': dict(sum((Counter(b.get('request_counts') or {}) for b in batches), Counter()))}


def publish(run, manifest):
    summary = read(run / 'summary.json')
    annotations = read(run / 'annotations.json')
    expected = {q['question_id']: q['source_sha256'] for q in manifest['questions']}
    actual = {qid: q['source_sha256'] for qid, q in annotations['questions'].items()}
    current = {q['question_id']: q['source_sha256'] for q in source_questions()}
    if summary['failed'] or summary['missing'] or expected != actual or current != expected:
        raise ValueError('Refusing to publish incomplete results or stale question assessments.')
    if any(q['difficulty'] not in {'easy', 'medium', 'hard'} for q in annotations['questions'].values()):
        raise ValueError('Invalid difficulty label.')
    target = ROOT / 'data/question-difficulty.json'
    if target.exists() and read(target) != annotations:
        raise ValueError('Existing difficulty data differs; review before replacing.')
    write(target, annotations)
    return {'published': str(target), 'count': len(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'split-pending', 'submit', 'status', 'collect', 'publish'])
    parser.add_argument('--run-dir', type=Path, default=RUN)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare(args.run_dir)
        if args.action == 'prepare':
            result = {'count': len(manifest['questions']), 'formats': manifest['counts_by_format'],
                      'input_bytes': (args.run_dir / 'input.jsonl').stat().st_size}
        elif args.action == 'publish':
            result = publish(args.run_dir, manifest)
        elif args.action == 'split-pending':
            result = split_pending(args.run_dir, manifest)
        else:
            api = API()
            batch = operate_parts(args.run_dir, manifest, api, args.action)
            result = {k: batch.get(k) for k in ('id', 'status', 'request_counts', 'errors', 'local_summary')}
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Exception type is safe; known local validation messages contain no key.
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
