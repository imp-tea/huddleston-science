"""Validate authoritative data and build a portable static site using Python 3 only."""
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = ROOT / 'dist'


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_and_validate(data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else DATA
    taxonomy = read(data_dir / 'taxonomy.json')
    topics = read(data_dir / 'topics.json')
    content = read(data_dir / 'content.json')
    sources = read(data_dir / 'sources.json')
    redirects = read(data_dir / 'topic-redirects.json')
    practice = [q for path in sorted((data_dir / 'practice').glob('*.json')) for q in read(path)]
    categories = {c['primary_category'] for c in taxonomy['categories']}
    subs = {s['subcategory_id']: s for s in taxonomy['subcategories']}
    topic_map = {t['study_topic_id']: t for t in topics}
    require(len(categories) == len(taxonomy['categories']), 'Duplicate category')
    require(len(subs) == len(taxonomy['subcategories']), 'Duplicate subcategory')
    require(len(topic_map) == len(topics), 'Duplicate topic')
    require(all(s['primary_category'] in categories for s in subs.values()), 'Unknown subcategory category')
    for t in topics:
        tid = t['study_topic_id']
        require(t['primary_category'] in categories, f'Unknown category: {tid}')
        require(bool(t['subcategory_ids']) and len(set(t['subcategory_ids'])) == len(t['subcategory_ids']), f'Invalid memberships: {tid}')
        require(all(s in subs and subs[s]['primary_category'] == t['primary_category'] for s in t['subcategory_ids']), f'Cross-category membership: {tid}')
        require(t['source_question_count'] == len(set(t['source_ids'])) and set(t['source_ids']) <= sources.keys(), f'Invalid sources: {tid}')
    for sid, source in sources.items():
        require(source['custom_id'] == sid, 'Source ID mismatch')
        require(source['question_type'] in ['bonuses', 'tossups'], f'Unknown source kind: {sid}')
        if source['question_type'] == 'bonuses':
            require([p['label'] for p in source['parts']] == ['L', 'A', 'B', 'C'], f'Broken bonus grouping: {sid}')
    require(set(content) <= topic_map.keys(), 'Unknown content topic')
    for tid, c in content.items():
        require(bool(c['overview']) and bool(c['key_facts']), f'Empty study page: {tid}')
        references = c['source'].get('references', [c['source']])
        require(bool(references), f'Missing study sources: {tid}')
        for source in references:
            require(all(source.get(k) for k in ['title', 'url', 'publisher']), f'Missing attribution: {tid}')
            require(source['url'].startswith(('https://', 'http://')), f'Invalid citation URL: {tid}')
            # An original factual summary may cite a copyrighted source without
            # asserting that the source has a reusable-content license.
            require(bool(source.get('license')) == bool(source.get('license_url')), f'Incomplete source license: {tid}')
            if source.get('license_url'):
                require(source['license_url'].startswith(('https://', 'http://')), f'Invalid license URL: {tid}')
        urls = {source['url'] for source in references}
        blocks = c['overview'] + c['key_facts']
        require(len({b['id'] for b in blocks}) == len(blocks), f'Duplicate study block ID: {tid}')
        for block in blocks:
            require(isinstance(block.get('text'), str) and block['text'].strip(), f'Empty study block: {tid}')
            if 'source_urls' in block:
                require(bool(block['source_urls']) and set(block['source_urls']) <= urls, f'Unknown block citation: {tid}')
    require(all(target in topic_map and old not in topic_map for old, target in redirects.items()), 'Invalid redirect')
    require(len({q['question_id'] for q in practice}) == len(practice), 'Duplicate practice question')
    counts = Counter(); topic_answers = set()
    for q in practice:
        tid = q['study_topic_id']; require(tid in topic_map, f'Unknown question topic: {tid}')
        counts[tid] += 1
        choices = [q['correct_answer']] + q['distractors']
        require(len(choices) == 4 and all(isinstance(a,str) and a.strip() for a in choices), f'Invalid choices: {q["question_id"]}')
        require(len({a.casefold().strip() for a in choices}) == 4, f'Duplicate choices: {q["question_id"]}')
        require(q['question'] and q['explanation'] and q['canonical_correct_answer'], 'Missing question text')
        evidence = {'description'} | set(topic_map[tid]['source_ids'])
        if tid in content:
            evidence |= {b['id'] for b in content[tid]['overview'] + content[tid]['key_facts']}
        require(bool(q['evidence_ids']) and set(q['evidence_ids']) <= evidence, f'Unknown question evidence: {q["question_id"]}')
        if q['answer_kind'] == 'topic': topic_answers.add(tid)
    require(set(counts) == set(topic_map) == topic_answers, 'Missing practice coverage or topic-answer question')
    require(all(counts[tid] <= min(t['source_question_count'],5) for tid,t in topic_map.items()), 'Question cap exceeded')
    return taxonomy, topics, content, sources, practice, redirects


def build():
    taxonomy, topics, content, sources, practice, redirects = load_and_validate()
    # Only the generated directory is replaced. Authoritative data is never written here.
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    for path in (ROOT / 'src').iterdir():
        if path.is_file(): shutil.copy2(path, OUT / path.name)
    shutil.copytree(ROOT / 'public', OUT, dirs_exist_ok=True)
    (OUT / 'data').mkdir()
    def asset(name, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        name = f'data/{name}-{hashlib.sha256(raw).hexdigest()[:12]}.json'
        (OUT / name).write_bytes(raw)
        return name
    topic_map = {t['study_topic_id']: t for t in topics}
    categories = []
    assets = {}
    for i, category in enumerate(taxonomy['categories'],1):
        name = category['primary_category']
        group = [t for t in topics if t['primary_category'] == name]
        categories.append(dict(category, subcategory_count=sum(s['primary_category']==name for s in taxonomy['subcategories']), current_study_topic_count=len(group)))
        details = {t['study_topic_id']: dict(t, **({'study_content':content[t['study_topic_id']]} if t['study_topic_id'] in content else {})) for t in group}
        questions = [q for q in practice if topic_map[q['study_topic_id']]['primary_category']==name]
        assets[name] = dict(details=asset(f'topics-{i:02d}',details), practice=asset(f'practice-{i:02d}',questions))
    shards = {prefix: asset(f'sources-{prefix}',{k:v for k,v in sources.items() if k[3:4]==prefix}) for prefix in '0123456789abcdef'}
    index = dict(categories=categories, subcategories=taxonomy['subcategories'], redirects=redirects, assets=assets, source_shards=shards,
                 topics=[{**{k:t[k] for k in ['study_topic_id','subject_id','topic','primary_category','subcategory_ids']},'has_content':t['study_topic_id'] in content} for t in topics])
    (OUT / 'data/index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')))
    shutil.copy2(ROOT / 'ATTRIBUTION.md', OUT / 'ATTRIBUTION.md')
    stats=dict(categories=len(categories), subcategories=len(taxonomy['subcategories']), topics=len(topics), detailed_pages=len(content), practice_questions=len(practice), source_questions=len(sources), browse_index_bytes=(OUT/'data/index.json').stat().st_size)
    (OUT / 'build-info.json').write_text(json.dumps(stats,indent=2)+'\n')
    print(json.dumps(stats,indent=2))
    return stats


if __name__ == '__main__':
    build()
