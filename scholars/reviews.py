"""Deterministic calendar-day reviews. Call record_review under the account lock."""
from datetime import timedelta
from django.db.models import Count, F, Q
from django.utils import timezone
from .models import ReviewState

INTERVALS = (1, 3, 7, 14, 30)
REMEMBERED_SUCCESSES = 3


def current_reviews(user, mode="recognition"):
    return ReviewState.objects.filter(user=user, mode=mode,
        revision_id=F("revision__question__current_revision_id"),
        revision__question__active=True, revision__question__topic__active=True)


def select_questions(bank, user, mode, selection, rng):
    ids = [qid for qid, _ in bank]
    if selection == "random":
        return rng.sample(ids, min(10, len(ids)))
    today = timezone.localdate()
    states = {r.revision_id: r for r in current_reviews(user, mode)}
    due, weak, new, other = [], [], [], []
    for qid, revision_id in bank:
        state = states.get(revision_id)
        if state is None:
            new.append(qid)
        elif state.due_on <= today:
            due.append((state.due_on, qid))
        elif state.successes == 0:
            weak.append(qid)
        else:
            other.append(qid)
    due = [qid for _, qid in sorted(due)]
    if selection == "review":
        return due[:10]
    for group in (weak, new, other):
        rng.shuffle(group)
    selected = due[:4] + weak[:3] + new[:3]
    # Fill short groups without duplicates; oldest due questions get first priority.
    for qid in due + weak + new + other:
        if len(selected) >= 10:
            break
        if qid not in selected:
            selected.append(qid)
    rng.shuffle(selected)
    return selected


def record_review(user, item, mode, successful):
    question = item.revision.question
    if not question.active or not question.topic.active or question.current_revision_id != item.revision_id:
        item.attempt_kind = "historical"
        return
    today = timezone.localdate(item.answered_at)
    state = ReviewState.objects.filter(user=user, revision=item.revision, mode=mode).first()
    if state is None:
        item.attempt_kind = "first"
        state = ReviewState(user=user, revision=item.revision, mode=mode,
                            successes=int(successful), last_evidence_on=today, due_on=today + timedelta(days=1))
    else:
        last_day = timezone.localdate(state.last_attempt_at)
        item.attempt_kind = "same_day" if today <= last_day else ("review" if today >= state.due_on else "early")
        if not successful:
            state.successes = 0
            state.last_evidence_on = today
            state.due_on = today + timedelta(days=1)
        elif item.attempt_kind == "review" and today > state.last_evidence_on:
            state.successes = min(state.successes + 1, len(INTERVALS))
            state.last_evidence_on = today
            state.due_on = today + timedelta(days=INTERVALS[state.successes - 1])
        # Early successes and same-day retries leave due dates and evidence unchanged.
    state.last_attempt_at = item.answered_at
    state.save()
    item.review_due_on = state.due_on
    item.review_successes = state.successes


def review_summary(user, category="", topic=""):
    """Current questions only; each question contributes once per category."""
    from .models import Question, SessionQuestion, Subcategory
    questions = Question.objects.filter(active=True, topic__active=True, current_revision__isnull=False)
    if category:
        questions = questions.filter(topic__category_id=category)
    if topic:
        questions = questions.filter(topic_id=topic)
    bank = list(questions.values_list("current_revision_id", "topic__category_id", "topic__payload__subcategory_ids"))
    today = timezone.localdate()
    labels = dict(Subcategory.objects.values_list("id", "payload__label")) if category else {}
    modes = []
    for mode, label in (("recognition", "Multiple choice"), ("recall", "Recall · self-assessed")):
        states = {r.revision_id: r for r in current_reviews(user, mode)}
        total = dict(questions=len(bank), due=0, remembered=0, practicing=0, new=0)
        rows = {}
        for rid, cat, subs in bank:
            state = states.get(rid)
            status = "new" if state is None else ("remembered" if state.successes >= REMEMBERED_SUCCESSES else "practicing")
            due = int(state is not None and state.due_on <= today)
            total[status] += 1
            total["due"] += due
            for key in set(subs if category else [cat]):
                row = rows.setdefault(key, dict(id=key, label=labels.get(key, key), questions=0, due=0, remembered=0, practicing=0, new=0))
                row["questions"] += 1
                row[status] += 1
                row["due"] += due
        upcoming = current_reviews(user, mode).filter(revision_id__in=[rid for rid, _, _ in bank]).select_related(
            "revision__question__topic").order_by("due_on", "pk")[:5]
        recent = SessionQuestion.objects.filter(session__user=user, session__mode=mode,
                                                answered_at__gte=timezone.now() - timedelta(days=30))
        if category:
            recent = recent.filter(revision__context__topic__primary_category=category)
        if topic:
            recent = recent.filter(revision__question__topic_id=topic)
        history = recent.aggregate(recent_answers=Count("pk"),
            recent_successes=Count("pk", filter=Q(**({"is_correct": True} if mode == "recognition" else {"self_assessment": True}))),
            scheduled_answers=Count("pk", filter=Q(attempt_kind="review")),
            repeat_answers=Count("pk", filter=Q(attempt_kind="same_day")))
        rows = dict(sorted(rows.items(), key=lambda pair: pair[1]["label"].casefold()))
        modes.append(dict(mode=mode, label=label, total=total, rows=rows, upcoming=upcoming, **history))
    return modes
