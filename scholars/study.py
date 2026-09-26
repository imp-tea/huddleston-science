"""Account-owned read → quiz → review sessions. All mutations lock account first.

Imports take an exclusive content lock; creation takes a shared one and pins the
entire question pool and reading content. Later steps never consult live content.
"""
from collections import defaultdict
from copy import deepcopy
from math import ceil
import random

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .importer import CONTENT_LOCK
from .models import (Category, Question, StudyActivity, StudyAnswer, StudyAttempt,
                     StudyPreferences, StudyQuestion, StudySession, StudySessionTopic,
                     Subcategory, Topic, TopicCompletion)
from .services import lock_active_account
from .typed_answers import for_item, grade, search_key

rng = random.SystemRandom()
ACTIVE_PHASES = [StudySession.Phase.READING, StudySession.Phase.QUIZ, StudySession.Phase.REVIEW]


def active_session(user):
    return StudySession.objects.filter(user=user, phase__in=ACTIVE_PHASES).first()


def preferences_ready(user):
    return StudyPreferences.objects.filter(user=user, onboarded_at__isnull=False, categories__active=True).exists()


@transaction.atomic
def save_interests(user, category_ids):
    lock_active_account(user)
    ids = set(category_ids)
    categories = list(Category.objects.filter(pk__in=ids, active=True))
    if not ids or len(categories) != len(ids):
        raise ValidationError("Select at least one available category.")
    preferences, _ = StudyPreferences.objects.get_or_create(user=user)
    preferences.categories.set(categories)
    if preferences.onboarded_at is None:
        preferences.onboarded_at = timezone.now()
        preferences.save(update_fields=["onboarded_at"])
    return preferences


def unfinished_topics(user):
    return Topic.objects.filter(active=True, category__active=True).exclude(
        pk__in=TopicCompletion.objects.filter(user=user).values("topic_id"))


def picker(user, previous=()):
    interests = Category.objects.filter(studypreferences__user=user, active=True)
    completed = TopicCompletion.objects.filter(user=user).values("topic_id")
    rows = list(Subcategory.objects.filter(active=True, category__in=interests).annotate(
        total=Count("topic", filter=Q(topic__active=True), distinct=True),
        done=Count("topic", filter=Q(topic__active=True, topic__in=completed), distinct=True),
    ).order_by("pk"))
    eligible = [s for s in rows if s.total > s.done]
    old_ids = set(previous)
    fresh = [s for s in eligible if s.pk not in old_ids]
    old = [s for s in eligible if s.pk in old_ids]
    rng.shuffle(fresh)
    rng.shuffle(old)
    choices = (fresh + old)[:10]
    for sub in choices:
        sub.percent = sub.done * 100 // sub.total
        sub.session_size = min(5, sub.total - sub.done)
    return choices


def reading_snapshot(topic):
    study = topic.study_content
    source = study.get("source", {})
    references = source.get("references", [source] if source else [])
    # Explicit allowlist, including reference fields. Never embed source questions.
    return deepcopy({
        "id": topic.pk, "title": topic.title, "category": topic.category_id,
        "description": topic.payload.get("description", ""),
        "overview": [{"text": row.get("text", "")} for row in study.get("overview", [])],
        "facts": [{"text": row.get("text", "")} for row in study.get("key_facts", [])],
        "references": [{"url": r["url"], "title": r.get("title") or r.get("publisher") or "Reference"}
                       for r in references if isinstance(r.get("url"), str) and r["url"].startswith(("https://", "http://"))],
    })


@transaction.atomic
def start_study(user, request_key, subcategory_id):
    lock_active_account(user)
    previous = StudySession.objects.filter(user=user, request_key=request_key).first()
    if previous:
        return previous
    if active_session(user):
        raise ValidationError("A study session is already in progress. Resume it or start over from Study.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [CONTENT_LOCK])
    if not preferences_ready(user):
        raise ValidationError("Choose your interests before starting Study.")
    sub = Subcategory.objects.filter(pk=subcategory_id, active=True, category__active=True,
                                    category__studypreferences__user=user).first()
    if not sub:
        raise ValidationError("Choose a subject from your selected interests.")
    topics = list(unfinished_topics(user).filter(subcategories=sub).select_related("category").order_by("pk"))
    if not topics:
        raise ValidationError("All topics in this subject are complete. Choose another subject.")
    topics = rng.sample(topics, min(5, len(topics)))
    pool = defaultdict(list)
    for question in Question.objects.filter(topic__in=topics, active=True, format="typed", current_revision__isnull=False).select_related("current_revision").order_by("pk"):
        pool[question.topic_id].append(question)
    if any(len(pool[t.pk]) < 2 or not t.category.typed_bank_id for t in topics):
        raise ValidationError("This subject needs at least two typed questions per topic before a session can start. Choose another subject.")
    session = StudySession.objects.create(user=user, request_key=request_key, subcategory=sub,
                                         subcategory_label=sub.payload.get("label", sub.pk), category_label=sub.category_id)
    for position, topic in enumerate(topics):
        pinned = StudySessionTopic.objects.create(session=session, topic=topic, position=position, content=reading_snapshot(topic))
        StudyQuestion.objects.bulk_create([StudyQuestion(session_topic=pinned, revision=q.current_revision,
                                                        answer_bank_id=topic.category.typed_bank_id) for q in pool[topic.pk]])
    return session


def reading_topics(session):
    topics = list(session.topics.all())
    if session.phase == StudySession.Phase.REVIEW:
        topics = [t for t in topics if t.topic_id in session.review_topic_ids]
    return topics


def question_groups(session):
    """Treat matching prompts OR answers as one question, across topic records.

    Connected groups also handle malformed duplicates with conflicting answers.
    All inputs are pinned revisions, so imports cannot change quiz identity.
    """
    questions = list(StudyQuestion.objects.filter(session_topic__session=session)
                     .select_related("revision").order_by("pk"))
    parents = list(range(len(questions)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    keys = {}
    for i, question in enumerate(questions):
        payload = question.revision.payload
        for kind, text in [("prompt", payload["question"]), ("answer", payload["correct_answer"])]:
            key = (kind, search_key(text))
            if key in keys:
                parents[root(i)] = root(keys[key])
            else:
                keys[key] = i
    groups = defaultdict(list)
    for i, question in enumerate(questions):
        groups[root(i)].append(question)
    return list(groups.values())


def initial_question_ids(session):
    groups = question_groups(session)
    topics = list(session.topics.values_list("pk", flat=True))
    rng.shuffle(topics)
    # Match two slots per topic to distinct groups where possible. An augmenting
    # path avoids randomly using a shared question needed by a smaller topic pool.
    edges = {topic: [i for i, group in enumerate(groups) if any(q.session_topic_id == topic for q in group)]
             for topic in topics}
    for options in edges.values():
        rng.shuffle(options)
    assigned = {}

    def match(slot, visited):
        for group_id in edges[slot[0]]:
            if group_id in visited:
                continue
            visited.add(group_id)
            if group_id not in assigned or match(assigned[group_id], visited):
                assigned[group_id] = slot
                return True
        return False

    for number in range(2):
        for topic in topics:
            match((topic, number), set())
    selected = [rng.choice([q for q in groups[group_id] if q.session_topic_id == slot[0]]).pk
                for group_id, slot in assigned.items()]
    # If two per topic is impossible, fill from other unique pinned questions.
    extra = [group for i, group in enumerate(groups) if i not in assigned]
    rng.shuffle(extra)
    selected += [rng.choice(group).pk for group in extra[:max(0, 2 * len(topics) - len(selected))]]
    return selected


def retry_pool(session):
    """Correct or seen duplicate variants cannot reenter as unseen questions."""
    groups = question_groups(session)
    group_for = {q.pk: i for i, group in enumerate(groups) for q in group}
    previous = session.attempts.order_by("-number").first()
    history = list(StudyAnswer.objects.filter(attempt__session=session, answered_at__isnull=False)
                   .values_list("question_id", "is_correct"))
    correct = {group_for[qid] for qid, passed in history if passed}
    seen = {group_for[qid] for qid, _ in history}
    misses, included = [], set()
    for qid in previous.answers.filter(is_correct=False).values_list("question_id", flat=True):
        group = group_for[qid]
        if group not in correct and group not in included:
            misses.append(qid)
            included.add(group)
    unused = [rng.choice(group).pk for i, group in enumerate(groups) if i not in seen]
    return misses, unused


def _complete_session(session, now):
    session.phase = StudySession.Phase.PASSED
    session.completed_at = now
    TopicCompletion.objects.bulk_create([
        TopicCompletion(user=session.user, topic_id=t.topic_id, session=session, completed_at=now)
        for t in session.topics.all()], ignore_conflicts=True)
    StudyActivity.objects.create(session=session, kind="passed", created_at=now)


def _new_attempt(session):
    total = session.topics.count() * 2
    previous = session.attempts.order_by("-number").first()
    if previous is None:
        selected = initial_question_ids(session)
    else:
        misses, unused = retry_pool(session)
        rng.shuffle(unused)
        selected = (misses + unused)[:total]
    if not selected:
        # A pre-fix quiz may have missed a duplicate of an already-correct answer.
        # Keep its historical score, but don't create an empty retry or ask again.
        _complete_session(session, timezone.now())
        session.review_topic_ids = []
        return
    rng.shuffle(selected)
    attempt = StudyAttempt.objects.create(session=session, number=previous.number + 1 if previous else 1)
    StudyAnswer.objects.bulk_create([StudyAnswer(attempt=attempt, question_id=qid, position=i)
                                    for i, qid in enumerate(selected, 1)])
    session.phase = StudySession.Phase.QUIZ
    session.reading_position = 0
    session.review_topic_ids = []


@transaction.atomic
def move_reading(user, session_id, version, direction):
    lock_active_account(user)
    session = StudySession.objects.select_for_update().get(pk=session_id, user=user)
    if not session.active:
        raise ValidationError("This session is no longer active.")
    if session.version != version:
        raise ValidationError("This page is out of date. Continue from your saved position.")
    if session.phase not in {StudySession.Phase.READING, StudySession.Phase.REVIEW} or direction not in {"back", "next"}:
        raise ValidationError("Use the current reading controls.")
    topics = reading_topics(session)
    if direction == "back":
        if session.reading_position == 0:
            raise ValidationError("You are at the first topic.")
        session.reading_position -= 1
    elif session.reading_position + 1 < len(topics):
        session.reading_position += 1
    else:
        _new_attempt(session)
    session.version += 1
    session.save(update_fields=["phase", "completed_at", "reading_position", "review_topic_ids", "version"])
    StudyActivity.objects.create(session=session, kind="reading")
    return session


@transaction.atomic
def abandon_study(user, session_id):
    lock_active_account(user)
    session = StudySession.objects.select_for_update().get(pk=session_id, user=user)
    if session.active:
        session.phase = StudySession.Phase.ABANDONED
        session.abandoned_at = timezone.now()
        session.version += 1
        session.save(update_fields=["phase", "abandoned_at", "version"])
    return session


@transaction.atomic
def submit_answer(user, session_id, answer_id, typed_answer=None, skip=False):
    lock_active_account(user)
    session = StudySession.objects.select_for_update().get(pk=session_id, user=user)
    if session.phase == StudySession.Phase.ABANDONED:
        raise ValidationError("This session was abandoned. Return to Study.")
    answer = StudyAnswer.objects.select_related("attempt", "question__revision", "question__answer_bank").get(
        pk=answer_id, attempt__session=session)
    if answer.answered_at:
        return session, False  # First submitted response wins; duplicate final posts cannot award again.
    if session.phase != StudySession.Phase.QUIZ or answer.attempt.completed_at:
        raise ValidationError("This quiz is no longer active. Continue from your saved position.")
    if answer.attempt.answers.filter(position__lt=answer.position, answered_at__isnull=True).exists():
        raise ValidationError("Answer the current question first.")
    if type(skip) is not bool or (not skip and (not isinstance(typed_answer, str) or not typed_answer.strip() or len(typed_answer) > 240)):
        raise ValidationError("Enter an answer of 1–240 characters, or skip.")
    outcome = grade(None if skip else typed_answer, answer.question.revision.payload["correct_answer"],
                    suppressed_answers=for_item(answer.question)["suppressedAnswers"])
    if outcome == "prompt":
        return session, True
    now = timezone.now()
    answer.typed_answer = None if skip else typed_answer
    answer.skipped = skip
    answer.is_correct = outcome == "correct"
    answer.answered_at = now
    answer.save(update_fields=["typed_answer", "skipped", "is_correct", "answered_at"])
    StudyActivity.objects.create(session=session, kind="quiz", created_at=now)
    attempt = answer.attempt
    if not attempt.answers.filter(answered_at__isnull=True).exists():
        attempt.score = attempt.answers.filter(is_correct=True).count()
        attempt.completed_at = now
        attempt.save(update_fields=["score", "completed_at"])
        if attempt.score >= ceil(attempt.answers.count() * .9):
            _complete_session(session, now)
        else:
            session.phase = StudySession.Phase.REVIEW
            session.reading_position = 0
            missed = set(attempt.answers.filter(is_correct=False).values_list("question__session_topic__topic_id", flat=True))
            session.review_topic_ids = [t.topic_id for t in session.topics.all() if t.topic_id in missed]
    session.version += 1
    session.save(update_fields=["phase", "completed_at", "reading_position", "review_topic_ids", "version"])
    return session, False
