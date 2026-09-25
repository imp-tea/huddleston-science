"""Validate the approved typed bank; no research files or API access at runtime."""
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_typed_questions(data_dir, topics, legacy_questions):
    path = Path(data_dir) / 'typed-questions.json'
    if not path.exists():
        return []  # Older content releases and small legacy fixtures remain importable.
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError('Typed question bank must be a nonempty list')
    topic_map = {t['study_topic_id']: t for t in topics}
    ids = {q['question_id'] for q in legacy_questions}
    counts = Counter(); answers = defaultdict(set); result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'question_id', 'study_topic_id', 'question', 'answer'}:
            raise ValueError('Invalid typed question fields')
        if any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in row.values()):
            raise ValueError('Typed question fields must be nonempty trimmed strings')
        qid, tid, answer = row['question_id'], row['study_topic_id'], row['answer']
        if qid in ids or len(qid) > 100 or tid not in topic_map or len(answer) > 240:
            raise ValueError(f'Invalid typed question identity, topic, or answer: {qid}')
        if answer.casefold() in answers[tid]:
            raise ValueError(f'Repeated typed answer within topic: {tid}')
        ids.add(qid); counts[tid] += 1; answers[tid].add(answer.casefold())
        result.append({'question_id': qid, 'study_topic_id': tid, 'question': row['question'],
                       'correct_answer': answer, 'format': 'typed'})
    if set(counts) != set(topic_map) or any(counts[tid] != max(2, min(5, t['source_question_count'])) for tid, t in topic_map.items()):
        raise ValueError('Typed question coverage or per-topic quota mismatch')
    return result
