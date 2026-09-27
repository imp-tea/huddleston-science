"""Saved lists follow effective bank revisions; writes serialize with authoring/imports."""
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Question, SavedQuiz, SavedQuizItem
from .question_authoring import lock_author
from .question_selection import group_questions

MAX_QUESTIONS = 100


class StaleQuiz(ValidationError):
    pass


def available_questions():
    return Question.objects.filter(active=True, format='typed', topic__active=True,
        topic__category__active=True, current_revision__isnull=False)


def quiz_items(quiz):
    items = list(quiz.items.select_related('question__current_revision', 'question__topic__category',
        'reviewed_revision').defer('question__current_revision__context', 'reviewed_revision__context',
                                 'question__topic__payload', 'question__topic__study_content'))
    for item in items:
        q = item.question
        item.available = bool(q.active and q.format == 'typed' and q.topic.active and q.topic.category.active and q.current_revision_id)
        item.changed = q.current_revision_id != item.reviewed_revision_id
        item.duplicate = False
    for group in group_questions([i for i in items if i.question.current_revision_id],
                                  lambda i: i.question.current_revision.payload):
        if len(group) > 1:
            for item in group:
                item.duplicate = True
    return items


def ready_items(quiz):
    """Preflight for future hosting; never silently drop unavailable items."""
    items = quiz_items(quiz)
    if quiz.archived or not items:
        raise ValidationError('Choose an active quiz with at least one question.')
    if any(not item.available or item.changed for item in items):
        raise ValidationError('Review changed questions and remove or replace unavailable questions before hosting.')
    return items


def checked_quiz(user, quiz_id, version, *, allow_archived=False):
    quiz = get_object_or_404(SavedQuiz.objects.select_for_update(), pk=quiz_id, owner=user)
    if type(version) is not int or quiz.edit_version != version:
        raise StaleQuiz('This quiz changed in another tab. Reload the latest version before saving.')
    if quiz.archived and not allow_archived:
        raise ValidationError('Restore this archived quiz before changing it.')
    return quiz


def valid_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
        raise ValidationError('Enter a quiz name between 1 and 160 characters.')
    return name.strip()


def creation_id(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError('Invalid quiz request. Reload and try again.') from exc


def touch(quiz):
    quiz.edit_version += 1
    quiz.save(update_fields=['name', 'archived', 'edit_version', 'updated_at'])


@transaction.atomic
def create_quiz(user, name, request_key, *, selected=None, settings=None):
    lock_author(user)
    key = creation_id(request_key)
    previous = SavedQuiz.objects.filter(pk=key, owner=user).first()
    if previous:
        return previous
    name = valid_name(name)
    selected = selected or []  # Ordered (question ID, reviewed revision ID) pairs.
    if len(selected) > MAX_QUESTIONS or len({q for q, r in selected}) != len(selected):
        raise ValidationError('Choose at most 100 distinct questions.')
    questions = {q.pk: q for q in available_questions().filter(pk__in=[q for q, r in selected])}
    if any(qid not in questions or questions[qid].current_revision_id != rid for qid, rid in selected):
        raise StaleQuiz('The question bank changed since this preview. Generate a fresh preview before saving.')
    quiz = SavedQuiz.objects.create(id=key, owner=user, name=name, generation_settings=settings or {})
    SavedQuizItem.objects.bulk_create([SavedQuizItem(quiz=quiz, question_id=qid, reviewed_revision_id=rid, position=i)
                                     for i, (qid, rid) in enumerate(selected, 1)])
    return quiz


@transaction.atomic
def update_quiz(user, quiz_id, version, action, *, item_id=None, revision_id=None, name=None, request_key=None):
    lock_author(user)
    if action == 'duplicate':
        previous = SavedQuiz.objects.filter(pk=creation_id(request_key), owner=user).first()
        if previous:
            return previous
    quiz = checked_quiz(user, quiz_id, version, allow_archived=action in {'restore', 'duplicate'})
    if action == 'rename':
        quiz.name = valid_name(name)
    elif action in {'archive', 'restore'}:
        quiz.archived = action == 'archive'
    elif action == 'duplicate':
        duplicate = SavedQuiz.objects.create(id=creation_id(request_key), owner=user, name=valid_name(name),
                                            generation_settings=quiz.generation_settings)
        # Preserve review status: copying a stale list must not approve its contents.
        SavedQuizItem.objects.bulk_create([SavedQuizItem(quiz=duplicate, question_id=i.question_id,
            reviewed_revision_id=i.reviewed_revision_id, position=i.position) for i in quiz.items.all()])
        return duplicate
    elif action in {'remove', 'up', 'down', 'review'}:
        items = list(quiz.items.select_related('question').order_by('position'))
        item = next((i for i in items if i.pk == item_id), None)
        if not item:
            raise ValidationError('This question is no longer in this quiz. Reload the page.')
        if action == 'review':
            if not available_questions().filter(pk=item.question_id, current_revision_id=revision_id).exists():
                raise StaleQuiz('This question changed or became unavailable. Reload to review its latest wording.')
            item.reviewed_revision_id = revision_id
            item.save(update_fields=['reviewed_revision'])
        else:
            index = items.index(item)
            if action == 'remove':
                item.delete()
                items.remove(item)
            else:
                other = index + (-1 if action == 'up' else 1)
                if not 0 <= other < len(items):
                    raise ValidationError('This question is already at the end of that direction.')
                items[index], items[other] = items[other], items[index]
            for position, entry in enumerate(items, 1):
                entry.position = position
            SavedQuizItem.objects.bulk_update(items, ['position'])
    else:
        raise ValidationError('Unknown quiz action.')
    touch(quiz)
    return quiz


@transaction.atomic
def add_question(user, quiz_id, version, question_id, revision_id):
    lock_author(user)
    quiz = checked_quiz(user, quiz_id, version)
    if quiz.items.filter(question_id=question_id).exists():
        return quiz, False
    question = available_questions().filter(pk=question_id, current_revision_id=revision_id).first()
    if not question:
        raise StaleQuiz('This question changed or became unavailable. Reload before adding it.')
    count = quiz.items.count()
    if count >= MAX_QUESTIONS:
        raise ValidationError('A quiz can contain at most 100 questions. Remove one or choose another quiz.')
    SavedQuizItem.objects.create(quiz=quiz, question=question, reviewed_revision_id=revision_id, position=count + 1)
    touch(quiz)
    return quiz, True
