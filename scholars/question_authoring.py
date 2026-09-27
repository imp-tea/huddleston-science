"""Teacher writes share the import lock and preserve immutable session evidence."""
from copy import deepcopy
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from .importer import CONTENT_LOCK, digest
from .models import Question, QuestionRevision, Source, Topic
from .services import lock_active_account
from .typed_answers import rebuild_banks


class StaleQuestion(ValidationError):
    pass


def lock_author(user):
    author = lock_active_account(user)
    if not author.is_admin:
        raise PermissionDenied("Administrator access required.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CONTENT_LOCK])
    return author


def editable_topic(topic_id):
    try:
        return Topic.objects.get(pk=topic_id, active=True, category__active=True)
    except Topic.DoesNotExist as exc:
        raise ValidationError("This topic is no longer available for editing.") from exc


def snapshot(topic):
    return deepcopy({"topic": topic.payload, "study_content": topic.study_content,
        "sources": {source.pk: source.payload for source in
                    Source.objects.filter(pk__in=topic.payload.get('source_ids', []))}})


def checked_question(question_id, version):
    question = Question.objects.select_for_update(of=('self',)).select_related('current_revision').get(pk=question_id)
    if type(version) is not int or question.edit_version != version:
        raise StaleQuestion("This question changed in another tab or content import. Reload to review the latest version before saving.")
    return question


def validated_payload(question, data):
    # Validate at the service boundary too, rather than trusting a caller's form.
    from .teacher_forms import QuestionContentForm
    form = QuestionContentForm(data, question_format=question.format)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    values = form.cleaned_data
    payload = deepcopy(question.current_revision.payload) if question.current_revision_id else {}
    payload.update(question_id=question.pk, study_topic_id=question.topic_id,
                   question=values['question'], correct_answer=values['correct_answer'])
    if question.format == 'typed':
        payload['format'] = 'typed'
    else:
        payload.update(distractors=values['distractors'], explanation=values['explanation'],
                       canonical_correct_answer=values['correct_answer'])
    return payload


def save_revision(question, payload, topic, author):
    context = snapshot(topic)
    revision, _ = QuestionRevision.objects.get_or_create(question=question, digest=digest([payload, context]),
        defaults={'payload': payload, 'context': context, 'author': author})
    question.current_revision = revision
    if question.origin == Question.Origin.IMPORTED:
        question.override_revision = revision
        question.override_base_revision_id = question.imported_revision_id
    question.edit_version += 1
    question.save()
    rebuild_banks([topic.category_id])
    return question


@transaction.atomic
def create_question(user, topic_id, request_key, data):
    author = lock_author(user)
    topic = editable_topic(topic_id)
    try:
        question_id = f'teacher-{uuid.UUID(str(request_key))}'
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Invalid question creation request. Reload and try again.") from exc
    previous = Question.objects.filter(pk=question_id).first()
    if previous:
        if previous.topic_id != topic_id or previous.origin != Question.Origin.TEACHER:
            raise ValidationError("This creation request belongs to a different question.")
        return previous  # A repeated successful POST cannot create another question.
    question = Question(id=question_id, topic=topic, format='typed', origin=Question.Origin.TEACHER)
    payload = validated_payload(question, data)
    question.save(force_insert=True)
    return save_revision(question, payload, topic, author)


@transaction.atomic
def edit_question(user, question_id, version, data):
    author = lock_author(user)
    question = checked_question(question_id, version)
    topic = editable_topic(question.topic_id)
    if not question.active:
        raise ValidationError("Restore this archived question before editing it.")
    return save_revision(question, validated_payload(question, data), topic, author)


@transaction.atomic
def change_question_status(user, question_id, version, action):
    lock_author(user)
    question = checked_question(question_id, version)
    topic = editable_topic(question.topic_id)
    if action == 'restore_imported' and question.origin == Question.Origin.IMPORTED:
        if not question.imported_revision_id or not question.active:
            raise ValidationError("No active imported version is available to restore.")
        question.override_revision = None
        question.override_base_revision = None
        question.current_revision_id = question.imported_revision_id
    elif action in {'archive', 'reactivate'} and question.origin == Question.Origin.TEACHER:
        question.active = action == 'reactivate'
    else:
        raise ValidationError("This action is not available for this question.")
    question.edit_version += 1
    question.save()
    rebuild_banks([topic.category_id])
    return question


def topic_tools(user, topic_id):
    """Never fetch teacher-only answer/source payloads for student requests."""
    if not user.is_admin:
        return {}
    topic = Topic.objects.filter(pk=topic_id).first()
    if not topic:
        return {}
    return {'teacher_topic': topic,
            'teacher_questions': Question.objects.filter(topic=topic).select_related(
                'current_revision', 'current_revision__author', 'imported_revision').order_by('-format', 'id'),
            'teacher_sources': Source.objects.filter(pk__in=topic.payload.get('source_ids', [])).order_by('pk')}
