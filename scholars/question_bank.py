"""Database-owned question metadata and conflict-checked local analysis updates."""
from copy import deepcopy
import hashlib
import json
import re

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from .importer import CONTENT_LOCK, digest
from .models import Question, QuestionChange, QuestionRevision

PEI_ID = 'typed-study-4d63edb1fc7cb7163d3b-1'
PEI_OLD = ('Born Ieoh Ming Pei in Guangzhou in 1917, this Chinese-American modernist designed the East Building of the '
           'National Gallery of Art and a glass-and-steel landmark for the Louvre. Which architect received the Pritzker Prize in 1983?')
PEI_NEW = PEI_OLD.replace('Born Ieoh Ming Pei in', 'Born in')


def content_lock():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [CONTENT_LOCK])


def fingerprint(question, payload=None):
    payload = payload if payload is not None else question.current_revision.payload
    source = {'question_id': question.pk, 'study_topic_id': question.topic_id,
              'format': question.format, 'question': payload['question'], 'answer': payload['correct_answer']}
    # Exactly matches the frozen Batch source_sha256 algorithm.
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def state(question):
    return {'current_revision_id': question.current_revision_id, 'active': question.active,
            'edit_version': question.edit_version, 'difficulty': question.difficulty,
            'difficulty_metadata': deepcopy(question.difficulty_metadata)}


def record_change(question, before, author=None, kind='edit'):
    QuestionChange.objects.create(question=question, before=before, after=state(question), author=author, kind=kind)


def bank_queryset():
    return Question.objects.select_related('current_revision', 'topic__category').only(
        'id', 'topic_id', 'format', 'origin', 'active', 'edit_version', 'difficulty',
        'difficulty_metadata', 'current_revision', 'current_revision__payload',
        'topic__title', 'topic__active', 'topic__category_id', 'topic__category__active').order_by('id')


@transaction.atomic
def adopt_difficulty(data, *, apply=False):
    """One-time cutover, also safe to rerun. No blanket repository replacement."""
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('questions'), dict) or not data['questions']:
        raise ValidationError('Expected the version-1 difficulty analysis file.')
    content_lock()
    questions = {q.pk: q for q in bank_queryset()}
    proposed, errors = [], []
    provenance = {k: data[k] for k in ('model', 'reasoning_effort', 'prompt_sha256', 'batch_ids') if k in data}
    for qid, result in data['questions'].items():
        q = questions.get(qid)
        if not q or not q.current_revision_id:
            errors.append(f'{qid}: missing question or current revision')
            continue
        if not isinstance(result, dict) or result.get('difficulty') not in {'easy', 'medium', 'hard'} or not re.fullmatch('[0-9a-f]{64}', str(result.get('source_sha256', ''))):
            errors.append(f'{qid}: invalid classification')
            continue
        payload = deepcopy(q.current_revision.payload)
        fix = qid == PEI_ID and payload.get('question') == PEI_OLD and payload.get('correct_answer') == 'I. M. Pei'
        if fix:
            payload['question'] = PEI_NEW
        if fingerprint(q, payload) != result['source_sha256']:
            errors.append(f'{qid}: question/answer changed since analysis')
            continue
        metadata = {**provenance, **result, 'kind': 'batch_analysis'}
        metadata.pop('difficulty')
        if q.difficulty and (q.difficulty != result['difficulty'] or q.difficulty_metadata != metadata):
            errors.append(f'{qid}: already has a different assessment; use a versioned bulk update')
            continue
        if fix or q.difficulty != result['difficulty'] or q.difficulty_metadata != metadata:
            proposed.append((q, payload, fix, result['difficulty'], metadata))
    if errors:
        raise ValidationError(f'Nothing applied. {len(errors)} conflicts: ' + '; '.join(errors[:20]))
    report = {'apply': apply, 'assessed': len(data['questions']), 'changes': len(proposed),
              'pei_corrections': sum(p[2] for p in proposed),
              'unassessed_database_questions': len(set(questions) - set(data['questions']))}
    if apply:
        changes, rows = [], []
        for q, payload, fix, difficulty, metadata in proposed:
            before = state(q)
            if fix:
                context = q.current_revision.context
                q.current_revision, _ = QuestionRevision.objects.get_or_create(question=q, digest=digest([payload, context]),
                    defaults={'payload': payload, 'context': context})
            q.difficulty = difficulty
            q.difficulty_metadata = metadata
            q.edit_version += 1
            rows.append(q)
            changes.append(QuestionChange(question=q, kind='database_cutover', before=before, after=state(q)))
        Question.objects.bulk_update(rows, ['current_revision', 'difficulty', 'difficulty_metadata', 'edit_version'], batch_size=500)
        QuestionChange.objects.bulk_create(changes, batch_size=500)
    return report


@transaction.atomic
def apply_updates(user, data, *, apply=False):
    """All-or-nothing targeted patches from a server export; no new identities."""
    from .question_authoring import lock_author, validated_payload, snapshot
    from .typed_answers import rebuild_banks
    author = lock_author(user)
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('updates'), list) or not data['updates']:
        raise ValidationError('Expected schema_version 1 and a nonempty updates list.')
    patches = data['updates']
    seen, plans, errors = set(), [], []
    allowed = {'question_id', 'edit_version', 'source_sha256', 'question', 'answer', 'distractors', 'explanation', 'difficulty', 'active'}
    questions = {q.pk: q for q in bank_queryset()}
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) - allowed:
            raise ValidationError('Invalid patch fields.')
        qid = patch.get('question_id')
        if not isinstance(qid, str) or qid in seen:
            raise ValidationError('Invalid or duplicate question ID.')
        seen.add(qid)
        q = questions.get(qid)
        if not q or not q.current_revision_id or type(patch.get('edit_version')) is not int or q.edit_version != patch['edit_version'] or fingerprint(q) != patch.get('source_sha256'):
            errors.append(f'{qid}: stale or missing question; export again')
            continue
        if 'active' in patch and type(patch['active']) is not bool:
            raise ValidationError(f'{qid}: active must be a boolean.')
        if 'difficulty' in patch and patch['difficulty'] not in {'', 'easy', 'medium', 'hard'}:
            raise ValidationError(f'{qid}: invalid difficulty.')
        payload = deepcopy(q.current_revision.payload)
        content_fields = {'question', 'answer', 'distractors', 'explanation'} & set(patch)
        if content_fields:
            if q.format == 'typed' and content_fields & {'distractors', 'explanation'}:
                raise ValidationError(f'{qid}: typed questions do not have choices or explanations.')
            values = {**payload, **{k: patch[k] for k in content_fields - {'answer'}}}
            values['correct_answer'] = patch.get('answer', payload['correct_answer'])
            choices = values.get('distractors', [])
            if not isinstance(choices, list) or any(not isinstance(x, str) for x in choices):
                raise ValidationError(f'{qid}: distractors must be a string list.')
            values['distractors'] = '\n'.join(choices)
            payload = validated_payload(q, values)
        changed_content = payload != q.current_revision.payload
        if (content_fields or patch.get('active') is True) and (not q.topic.active or not q.topic.category.active):
            raise ValidationError(f'{qid}: topic is unavailable.')
        if changed_content and not q.active and patch.get('active') is not True:
            raise ValidationError(f'{qid}: restore before editing.')
        # A supplied rating explicitly assesses the new content; otherwise a
        # changed stem or answer invalidates the previous knowledge estimate.
        changed_fact = fingerprint(q, payload) != fingerprint(q)
        difficulty = patch.get('difficulty', '' if changed_fact else q.difficulty)
        metadata = q.difficulty_metadata
        if 'difficulty' in patch or changed_fact:
            metadata = {'kind': 'bulk_review', 'source_sha256': fingerprint(q, payload)} if difficulty else {}
        plans.append((q, payload, changed_content, difficulty, metadata, patch.get('active', q.active)))
    if errors:
        raise ValidationError(f'Nothing applied. {len(errors)} conflicts: ' + '; '.join(errors[:20]))
    changed, preview, categories = 0, [], set()
    for q, payload, content_changed, difficulty, metadata, active in plans:
        if not content_changed and (q.difficulty, q.difficulty_metadata, q.active) == (difficulty, metadata, active):
            continue
        changed += 1
        if len(preview) < 20:
            old = q.current_revision.payload
            preview.append({'question_id': q.pk,
                'before': {'question': old['question'], 'answer': old['correct_answer'],
                           'distractors': old.get('distractors', []), 'explanation': old.get('explanation', ''),
                           'difficulty': q.difficulty, 'active': q.active},
                'after': {'question': payload['question'], 'answer': payload['correct_answer'],
                          'distractors': payload.get('distractors', []), 'explanation': payload.get('explanation', ''),
                          'difficulty': difficulty, 'active': active}})
        if apply:
            before = state(q)
            if content_changed:
                context = snapshot(q.topic)
                q.current_revision, _ = QuestionRevision.objects.get_or_create(question=q, digest=digest([payload, context]),
                    defaults={'payload': payload, 'context': context, 'author': author})
            q.difficulty, q.difficulty_metadata, q.active = difficulty, metadata, active
            q.edit_version += 1
            q.save()
            record_change(q, before, author, 'bulk_update')
            if content_changed or before['active'] != active:
                categories.add(q.topic.category_id)
    if categories:
        rebuild_banks(categories)
    return {'apply': apply, 'reviewed': len(patches), 'changes': changed, 'preview': preview}
