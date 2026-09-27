"""Frozen, resumable difficulty pilot; writes review artifacts only, never data/."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import fcntl
import hashlib
import html
import json
from pathlib import Path
import random
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from luna_topic_pilot import now, read, write, SYSTEM_CA

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / 'research/question-difficulty/pilot-2026-09-27'
LABELS = ('Easy', 'Medium', 'Hard')


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'data').rglob('*.json'))}


def initialize(run, prompt_path, sample_from=None):
    if (run / 'manifest.json').exists():
        manifest = read(run / 'manifest.json')
        if manifest['prompt'] != prompt_path.read_text():
            raise ValueError('Prompt changed; use a new run directory.')
        if sample_from and manifest['sample'] != read(sample_from / 'manifest.json')['sample']:
            raise ValueError('Sample changed; use a new run directory.')
        return manifest
    topics = {t['study_topic_id']: t for t in read(ROOT / 'data/topics.json')}
    groups = defaultdict(list)
    for q in read(ROOT / 'data/typed-questions.json'):
        groups[topics[q['study_topic_id']]['primary_category']].append(q)
    rng = random.Random(20260927)
    selected = []
    for category, pool in sorted(groups.items()):
        for q in rng.sample(sorted(pool, key=lambda q: q['question_id']), 10):
            selected.append({**q, 'category': category})
    if sample_from:
        prior = read(sample_from / 'manifest.json')
        if hashes() != prior['data_hashes_before']:
            raise ValueError('Question data changed since the reference pilot.')
        selected = prior['sample']
    prompt = prompt_path.read_text()
    manifest = {'created_at': now(), 'model': 'gpt-6-sol', 'reasoning_effort': 'low',
                'seed': 20260927, 'prompt': prompt, 'sample': selected,
                'sample_from': str(sample_from) if sample_from else None,
                'selection': '10 uniformly sampled typed questions per category; category-balanced, not population-proportional.',
                'population_by_category': {k: len(v) for k, v in sorted(groups.items())},
                'data_hashes_before': hashes(), 'max_output_tokens': 1024,
                'pricing_per_million_usd': {'input': 2, 'cached_input': .2, 'output': 10},
                'pricing_source': 'https://developers.openai.com/api/docs/models/gpt-6-sol'}
    write(run / 'manifest.json', manifest)
    return manifest


def classify(run, manifest, q, api_key):
    path = run / 'responses' / (q['question_id'] + '.json')
    if path.exists():
        return read(path)  # No automatic paid retries, including failed calls.
    request = {'model': manifest['model'], 'reasoning': {'effort': 'low'},
               'store': False, 'service_tier': 'default',
               'max_output_tokens': manifest['max_output_tokens'],
               'instructions': manifest['prompt'],
               'input': 'Question:\n' + q['question'] + '\n\nAnswer:\n' + q['answer']}
    write(run / 'requests' / (q['question_id'] + '.json'), request)
    req = Request('https://api.openai.com/v1/responses', data=json.dumps(request).encode(),
                  headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    result = {'question_id': q['question_id'], 'created_at': now()}
    try:
        tls = ssl.create_default_context(cafile=str(SYSTEM_CA) if SYSTEM_CA.exists() else None)
        with urlopen(req, timeout=120, context=tls) as response:
            raw = json.load(response)
        label = ''.join(c.get('text', '') for item in raw.get('output', [])
                        for c in item.get('content', []) if c.get('type') == 'output_text').strip()
        result.update(response=raw, label=label,
                      valid=raw.get('status') == 'completed' and label in LABELS)
    except HTTPError as exc:
        result.update(valid=False, http_status=exc.code)
    except (URLError, TimeoutError):
        result.update(valid=False, error='Transport error')
    write(path, result)
    return result


def report(run, manifest):
    rows, usages = [], Counter()
    for q in manifest['sample']:
        path = run / 'responses' / (q['question_id'] + '.json')
        r = read(path) if path.exists() else {}
        rows.append({**q, 'difficulty': r.get('label', '') if r.get('valid') else 'ERROR'})
        u = r.get('response', {}).get('usage', {})
        usages.update({k: u.get(k, 0) for k in ('input_tokens', 'output_tokens')})
        usages['cached_tokens'] += u.get('input_tokens_details', {}).get('cached_tokens', 0)
    counts = Counter(q['difficulty'] for q in rows)
    cost = ((usages['input_tokens'] - usages['cached_tokens']) * 2
            + usages['cached_tokens'] * .2 + usages['output_tokens'] * 10) / 1_000_000
    summary = {'counts': dict(counts), 'usage': dict(usages), 'estimated_cost_usd': cost,
               'data_unchanged': hashes() == manifest['data_hashes_before'],
               'by_category': {c: dict(Counter(q['difficulty'] for q in rows if q['category'] == c))
                               for c in manifest['population_by_category']}}
    if manifest.get('sample_from'):
        previous = {q['question_id']: q for q in read(Path(manifest['sample_from']) / 'results.json')}
        for q in rows:
            old = previous[q['question_id']]
            if any(q[k] != old[k] for k in ('question', 'answer')):
                raise ValueError('Reference question content changed.')
            q['previous_difficulty'] = old['difficulty']
        summary['transitions'] = dict(Counter(q['previous_difficulty'] + ' → ' + q['difficulty'] for q in rows))
        summary['changed'] = sum(q['previous_difficulty'] != q['difficulty'] for q in rows)
    write(run / 'summary.json', summary)
    write(run / 'results.json', rows)
    with (run / 'results.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    esc = html.escape
    cards = ''.join('<article data-label="' + esc(q['difficulty']) + '"><small>'
                    + esc(q['category']) + ' · <b>'
                    + esc((q['previous_difficulty'] + ' → ') if 'previous_difficulty' in q else '')
                    + esc(q['difficulty'])
                    + '</b></small><p>' + esc(q['question']) + '</p><p><strong>Answer: </strong>'
                    + esc(q['answer']) + '</p><small>' + esc(q['question_id']) + '</small></article>'
                    for q in rows)
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Question difficulty pilot</title>
<style>body{font:17px/1.5 system-ui;max-width:950px;margin:40px auto;padding:0 20px;background:#f7f8fa;color:#17202a}article{background:white;padding:20px;margin:14px 0;border:1px solid #ddd;border-radius:10px}small{color:#536274}select{font:inherit;padding:6px}h1{margin-bottom:0}</style>
<h1>Question difficulty pilot</h1><p>120 typed questions · 10 per category · GPT-6 Sol · low reasoning</p>
<p>Category-balanced review sample; these percentages do not estimate the full bank. Model estimates, pending human review. Question files were not modified.</p>'''
    page += '<p>' + esc(' · '.join(f'{k}: {counts[k]}' for k in LABELS)) + '</p>'
    page += '<label>Difficulty <select onchange="document.querySelectorAll(\'article\').forEach(a=>a.hidden=this.value!==\'All\' && a.dataset.label!==this.value)"><option>All</option><option>Easy</option><option>Medium</option><option>Hard</option></select></label>'
    (run / 'review.html').write_text(page + cards + '</html>')
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--prompt', type=Path, default=ROOT / 'docs/QUESTION_DIFFICULTY_PROMPT.md')
    parser.add_argument('--sample-from', type=Path)
    args = parser.parse_args()
    run = args.run_dir
    run.mkdir(parents=True, exist_ok=True)
    with (run / '.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = initialize(run, args.prompt, args.sample_from)
        if args.execute:
            from dotenv import dotenv_values
            key = dotenv_values(ROOT / '.env').get('OPENAI_API_KEY')
            if not key:
                raise SystemExit('OPENAI_API_KEY missing')
            first = classify(run, manifest, manifest['sample'][0], key)
            if not first['valid']:
                raise SystemExit('First request failed; inspect safe response metadata.')
            print('Completed 1/' + str(len(manifest['sample'])), flush=True)
            with ThreadPoolExecutor(max_workers=6) as pool:
                jobs = [pool.submit(classify, run, manifest, q, key) for q in manifest['sample'][1:]]
                for n, job in enumerate(as_completed(jobs), 2):
                    r = job.result()
                    print(f'Completed {n}/{len(manifest["sample"])}; valid={r["valid"]}', flush=True)
        report(run, manifest)


if __name__ == '__main__':
    main()
