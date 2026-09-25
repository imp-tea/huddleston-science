from collections import defaultdict
from datetime import datetime, time, timedelta
from django.db.models import Count, F, Q, Subquery, OuterRef, Sum, Window
from django.db.models.functions import RowNumber
from django.utils import timezone
from .models import Category, PracticeSession, Question, RewardEvent, SessionQuestion, StudyPreferences, StudyState, Subcategory, Topic
from .question_pools import current_questions


def session_totals(sessions):
    return sessions.annotate(
        score_count=Count("items", filter=Q(items__is_correct=True)),
        total_count=Count("items"),
        answered_count=Count("items", filter=Q(items__answered_at__isnull=False)),
    )


def personal_bests(user):
    # One record per scope/mode/count/bank fingerprint; never rank unlike denominators.
    return session_totals(PracticeSession.objects.filter(user=user, completed_at__isnull=False, mode__in=["recognition", "typed"]).exclude(comparison_key="")).annotate(
        best_rank=Window(expression=RowNumber(), partition_by=[F("comparison_key"), F("mode"), F("total_count")],
                         order_by=[F("score_count").desc(), F("completed_at").asc(), F("pk").asc()]),
    ).filter(best_rank=1).order_by("scope_label", "mode", "total_count", "-completed_at")


def participation(user):
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    start = timezone.make_aware(datetime.combine(monday, time.min))
    end = timezone.make_aware(datetime.combine(monday + timedelta(days=7), time.min))
    goal = StudyPreferences.objects.filter(user=user).values_list("weekly_goal", flat=True).first() or 0
    answered = SessionQuestion.objects.filter(session__user=user, answered_at__gte=start, answered_at__lt=end)
    count = answered.order_by().values("revision__question_id").distinct().count()
    return {"xp": RewardEvent.objects.filter(user=user).aggregate(total=Sum("points"))["total"] or 0,
            "weekly_goal": goal, "weekly_count": count, "week_start": monday}


def missed_topics(user, limit=5):
    # A success in one mode must not erase a miss in another mode.
    missed_ids = set()
    for mode in ("recognition", "typed"):
        questions = current_questions(mode)
        latest = SessionQuestion.objects.filter(session__user=user, session__mode=mode,
            revision_id=OuterRef("current_revision_id"), answered_at__isnull=False).order_by("-answered_at", "-pk")
        missed = questions.annotate(latest_correct=Subquery(latest.values("is_correct")[:1])).filter(latest_correct=False)
        missed_ids.update(missed.values_list("topic_id", flat=True))
    return Topic.objects.filter(active=True, pk__in=missed_ids).order_by("title")[:limit]


def coverage(user, category="", subcategory=""):
    """Coverage uses current active topic IDs; accuracy uses the recorded classifications.

    Each answer contributes once to its category/overall total, even when its topic
    belongs to several subcategories. Retired answers remain in historical accuracy.
    """
    active = Topic.objects.filter(active=True)
    if category:
        active = active.filter(category_id=category)
    if subcategory:
        active = active.filter(subcategories=subcategory)
    memberships = list(active.values_list("id", "category_id", "payload__subcategory_ids"))
    studied = set(StudyState.objects.filter(user=user, studied_at__isnull=False).values_list("topic_id", flat=True))
    practiced = set()
    practiced_categories, practiced_subcategories = defaultdict(set), defaultdict(set)
    history = SessionQuestion.objects.filter(session__user=user, answered_at__isnull=False).order_by().values_list(
        "revision__question__topic_id", "revision__context__topic__primary_category", "revision__context__topic__subcategory_ids").distinct()
    for tid, cat, subs in history:
        if (not category or cat == category) and (not subcategory or subcategory in subs):
            practiced.add(tid)
        practiced_categories[cat].add(tid)
        for sub in subs:
            practiced_subcategories[sub].add(tid)
    rows = {}
    if category:
        for sub in Subcategory.objects.filter(active=True, category_id=category).order_by("payload__label"):
            rows[sub.pk] = dict(id=sub.pk, label=sub.payload["label"], category=category, subcategory=sub.pk)
    else:
        for cat in Category.objects.filter(active=True).order_by("id"):
            rows[cat.pk] = dict(id=cat.pk, label=cat.pk, category=cat.pk, subcategory="")
    total = dict(total=0, studied=0, practiced=0, correct=0, answers=0)
    for row in rows.values():
        row.update(total)
    for tid, cat, subs in memberships:
        total["total"] += 1
        total["studied"] += tid in studied
        total["practiced"] += tid in practiced
        for key in (subs if category else [cat]):
            if key in rows:
                rows[key]["total"] += 1
                rows[key]["studied"] += tid in studied
                rows[key]["practiced"] += tid in (practiced_subcategories[key] if category else practiced_categories[key])
    recent = SessionQuestion.objects.filter(session__user=user, session__mode="recognition", answered_at__gte=timezone.now() - timedelta(days=30))
    for cat, subs, correct in recent.values_list("revision__context__topic__primary_category", "revision__context__topic__subcategory_ids", "is_correct"):
        if (category and cat != category) or (subcategory and subcategory not in subs):
            continue
        total["answers"] += 1
        total["correct"] += bool(correct)
        for key in (subs if category else [cat]):
            if key in rows:
                rows[key]["answers"] += 1
                rows[key]["correct"] += bool(correct)
    return {"total": total, "rows": list(rows.values())}
