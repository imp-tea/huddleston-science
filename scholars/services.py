import random
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from accounts.models import User
from .importer import CONTENT_LOCK
from .models import PracticeSession, Question, SessionQuestion

rng = random.SystemRandom()


@transaction.atomic
def start_session(user, request_key, scope):
    # Account lock serializes duplicate starts, including simultaneous requests on separate workers.
    User.objects.select_for_update().get(pk=user.pk, is_active=True, must_change_password=False)
    previous = PracticeSession.objects.filter(user=user, request_key=request_key).first()
    if previous:
        return previous
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [CONTENT_LOCK])
    pool = Question.objects.filter(active=True, topic__active=True, current_revision__isnull=False)
    if scope.get("category"):
        pool = pool.filter(topic__category_id=scope["category"])
    if scope.get("subcategory"):
        pool = pool.filter(topic__subcategories=scope["subcategory"])
    if scope.get("topic"):
        pool = pool.filter(topic_id=scope["topic"])
    ids = list(pool.values_list("id", flat=True).distinct())
    if not ids:
        raise ValidationError("No practice questions are available in this scope yet. Choose another scope.")
    selected_ids = rng.sample(ids, min(10, len(ids)))
    questions = {q.pk: q for q in pool.filter(pk__in=selected_ids).select_related("current_revision")}
    session = PracticeSession.objects.create(user=user, request_key=request_key, scope=scope)
    items = []
    for position, qid in enumerate(selected_ids, 1):
        revision = questions[qid].current_revision
        choices = [revision.payload["correct_answer"], *revision.payload["distractors"]]
        rng.shuffle(choices)
        items.append(SessionQuestion(session=session, position=position, revision=revision, choices=choices))
    SessionQuestion.objects.bulk_create(items)
    return session


@transaction.atomic
def answer_question(user, session_id, position, selected):
    # One session row lock serializes scoring/completion; saved choices are immutable.
    session = PracticeSession.objects.select_for_update().get(pk=session_id, user=user)
    item = SessionQuestion.objects.select_related("revision").get(session=session, position=position)
    if item.answered_at:
        return item  # Retry never changes the first recorded answer, even with another choice.
    if session.items.filter(position__lt=position, answered_at__isnull=True).exists():
        raise ValidationError("Answer the current question first.")
    if selected not in range(len(item.choices)):
        raise ValidationError("Choose one of the displayed answers.")
    item.selected = selected
    item.is_correct = item.choices[selected] == item.revision.payload["correct_answer"]
    item.answered_at = timezone.now()
    item.save(update_fields=["selected", "is_correct", "answered_at"])
    if not session.items.filter(answered_at__isnull=True).exists():
        session.completed_at = item.answered_at
        session.save(update_fields=["completed_at"])
    return item
