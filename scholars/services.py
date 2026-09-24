import random
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone
from accounts.models import User
from .importer import CONTENT_LOCK, digest
from .catalog import describe_scope, topic_pool
from .reviews import record_review, select_questions
from .typed_answers import for_item, grade
from .models import PracticeSession, Question, RewardEvent, SessionQuestion, StudyState

rng = random.SystemRandom()


def lock_active_account(user):
    try:
        return User.objects.select_for_update().get(pk=user.pk, is_active=True, must_change_password=False)
    except User.DoesNotExist as exc:
        raise PermissionDenied("Sign in again before continuing.") from exc


@transaction.atomic
def start_session(user, request_key, scope, mode="typed", selection="random"):
    # Account lock serializes duplicate starts, including simultaneous requests on separate workers.
    lock_active_account(user)
    previous = PracticeSession.objects.filter(user=user, request_key=request_key).first()
    if previous:
        return previous
    if mode not in {"typed", "recognition", "recall"} or selection not in {"random", "personalized", "review"}:
        raise ValidationError("Choose a valid practice mode and selection.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [CONTENT_LOCK])
    pool = Question.objects.filter(active=True, current_revision__isnull=False, topic__in=topic_pool(user, scope))
    bank = list(pool.order_by("id").values_list("id", "current_revision_id"))
    ids = [qid for qid, revision_id in bank]
    if not ids:
        raise ValidationError("No practice questions are available in this scope yet. Choose another scope.")
    selected_ids = select_questions(bank, user, mode, selection, rng)
    if not selected_ids:
        raise ValidationError("No reviews are due in this scope and mode. Try personalized practice or browse topics.")
    questions = {q.pk: q for q in pool.filter(pk__in=selected_ids).select_related("current_revision", "topic__category")}
    comparison_key = digest([f"{mode}-v1", scope, min(10, len(ids)), bank]) if mode in {"typed", "recognition"} and selection == "random" else ""
    if mode == "typed" and comparison_key:
        versions = sorted(set(pool.values_list("topic__category__typed_bank_id", flat=True)))
        comparison_key = digest([comparison_key, versions])
    session = PracticeSession.objects.create(user=user, request_key=request_key, scope=scope,
                                             scope_label=describe_scope(scope), comparison_key=comparison_key, mode=mode, selection=selection)
    items = []
    for position, qid in enumerate(selected_ids, 1):
        revision = questions[qid].current_revision
        choices = [revision.payload["correct_answer"], *revision.payload["distractors"]]
        rng.shuffle(choices)
        items.append(SessionQuestion(session=session, position=position, revision=revision, choices=choices,
                                     answer_bank_id=questions[qid].topic.category.typed_bank_id if mode == "typed" else None))
    SessionQuestion.objects.bulk_create(items)
    return session


@transaction.atomic
def answer_question(user, session_id, position, selected=None, *, self_assessment=None, typed_answer=None, skip=False):
    # Account then session: one lock order for starts, answers, and rewards across tabs.
    lock_active_account(user)
    session = PracticeSession.objects.select_for_update().get(pk=session_id, user=user)
    item = SessionQuestion.objects.select_related("revision__question__topic", "answer_bank").get(session=session, position=position)
    if item.answered_at:
        return item  # Retry never changes the first recorded answer, even with another choice.
    ensure_current(session, item)
    if session.mode == "typed":
        if selected is not None or self_assessment is not None or type(skip) is not bool:
            raise ValidationError("Submit a typed answer or skip.")
        if not skip and (not isinstance(typed_answer, str) or not typed_answer.strip() or len(typed_answer) > 240):
            raise ValidationError("Enter an answer of 1–240 characters, or skip.")
        outcome = grade(None if skip else typed_answer, item.revision.payload["correct_answer"],
                        suppressed_answers=for_item(item)["suppressedAnswers"])
        if outcome == "prompt":
            # No writes, rewards, or review evidence. Final requests still serialize above.
            return item
        item.typed_answer = None if skip else typed_answer
        item.skipped = skip
        item.is_correct = outcome == "correct"
    elif session.mode == "recall":
        if item.revealed_at is None or type(self_assessment) is not bool or selected is not None:
            raise ValidationError("Reveal the answer, then assess your recall.")
        item.self_assessment = self_assessment
    else:
        if type(selected) is not int or selected not in range(len(item.choices)) or self_assessment is not None:
            raise ValidationError("Choose one of the displayed answers.")
        item.selected = selected
        item.is_correct = item.choices[selected] == item.revision.payload["correct_answer"]
    item.answered_at = timezone.now()
    previous = SessionQuestion.objects.filter(session__user=user, revision__question_id=item.revision.question_id,
                                             answered_at__isnull=False).exclude(pk=item.pk)
    last = previous.filter(revision=item.revision, session__mode=session.mode).order_by("-answered_at", "-pk").first()
    item.corrected_previous_miss = bool(item.is_correct and last and not last.is_correct)
    # Hold the content read lock so an import cannot change the revision mid-answer.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [CONTENT_LOCK])
    item.revision.question.refresh_from_db()
    record_review(user, item, session.mode, item.self_assessment if session.mode == "recall" else item.is_correct)
    item.save(update_fields=["selected", "is_correct", "self_assessment", "typed_answer", "skipped", "answered_at", "corrected_previous_miss",
                             "attempt_kind", "review_due_on", "review_successes"])
    today = timezone.localdate(item.answered_at)
    if not previous.filter(answered_at__date=today).exists():
        RewardEvent.objects.create(user=user, question_id=item.revision.question_id, answer=item,
                                   earned_on=today, points=1 if previous.exists() else 2)
    if not session.items.filter(answered_at__isnull=True).exists():
        if session.mode in {"typed", "recognition"} and session.comparison_key:
            earlier = PracticeSession.objects.filter(user=user, mode=session.mode, completed_at__isnull=False, comparison_key=session.comparison_key).annotate(
                points=Count("items", filter=Q(items__is_correct=True)), size=Count("items")).filter(size=session.total).order_by("-points").first()
            session.is_personal_best = earlier is not None and session.score > earlier.points
        session.completed_at = item.answered_at
        session.save(update_fields=["completed_at", "is_personal_best"])
    return item


@transaction.atomic
def record_visit(user, topic):
    now = timezone.now()
    state, _ = StudyState.objects.update_or_create(user=user, topic=topic, defaults={"last_opened_at": now},
                                                 create_defaults={"first_opened_at": now, "last_opened_at": now})
    return state


@transaction.atomic
def mark_studied(user, topic, studied):
    lock_active_account(user)
    now = timezone.now()
    state, _ = StudyState.objects.get_or_create(user=user, topic=topic, defaults={"first_opened_at": now, "last_opened_at": now})
    # Explicit desired state makes repeated POSTs safe; opening never marks a topic.
    if studied and state.studied_at is None:
        state.studied_at = now
    elif not studied:
        state.studied_at = None
    state.save(update_fields=["studied_at"])
    return state


def ensure_current(session, item):
    if session.abandoned_at:
        raise ValidationError("This session has been ended. Start another practice session.")
    if session.items.filter(position__lt=item.position, answered_at__isnull=True).exists():
        raise ValidationError("Answer the current question first.")


@transaction.atomic
def reveal_question(user, session_id, position):
    lock_active_account(user)
    session = PracticeSession.objects.select_for_update().get(pk=session_id, user=user)
    item = session.items.select_related("revision").get(position=position)
    ensure_current(session, item)
    if session.mode != "recall":
        raise ValidationError("Only recall practice uses answer reveals.")
    if item.revealed_at is None:
        item.revealed_at = timezone.now()
        item.save(update_fields=["revealed_at"])
    return item


@transaction.atomic
def abandon_session(user, session_id):
    lock_active_account(user)
    session = PracticeSession.objects.select_for_update().get(pk=session_id, user=user)
    if session.completed_at is None and session.abandoned_at is None:
        session.abandoned_at = timezone.now()
        session.save(update_fields=["abandoned_at"])
    return session
