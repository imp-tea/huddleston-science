"""Current library coverage and calendar progress, separate from legacy practice."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Category, StudyActivity, StudySession, Subcategory

CENTRAL = ZoneInfo('America/Chicago')
WEEKLY_GOAL = 5


def coverage_rows(user):
    active = Q(topic__active=True)
    completed = active & Q(topic__topiccompletion__user=user)
    categories = list(Category.objects.filter(active=True).annotate(
        total=Count('topic', filter=active, distinct=True),
        done=Count('topic', filter=completed, distinct=True)).order_by('id'))
    subs = Subcategory.objects.filter(active=True, category__active=True).annotate(
        total=Count('topic', filter=active & Q(topic__category__active=True), distinct=True),
        done=Count('topic', filter=completed & Q(topic__category__active=True), distinct=True)
    ).order_by('payload__label', 'pk')
    by_category = {cat.pk: cat for cat in categories}
    for cat in categories:
        cat.subs = []
        cat.percent = cat.done * 100 // cat.total if cat.total else 0
    for sub in subs:
        sub.percent = sub.done * 100 // sub.total if sub.total else 0
        by_category[sub.category_id].subs.append(sub)
    total = sum(cat.total for cat in categories)
    done = sum(cat.done for cat in categories)
    return {'categories': categories, 'total': total, 'done': done,
            'percent': done * 100 // total if total else 0}


def calendar_progress(user, now=None):
    now = now or timezone.now()
    today = now.astimezone(CENTRAL).date()
    monday = today - timedelta(days=today.weekday())
    grid_start = monday - timedelta(weeks=4)
    next_monday = monday + timedelta(days=7)
    start = datetime.combine(grid_start, time.min, CENTRAL)
    end = datetime.combine(next_monday, time.min, CENTRAL)
    week_start = datetime.combine(monday, time.min, CENTRAL)
    passes = StudySession.objects.filter(user=user, phase='passed', completed_at__gte=start,
                                         completed_at__lt=end, completed_at__lte=now)
    count = passes.filter(completed_at__gte=week_start).count()
    pass_days = {row['day']: row['count'] for row in passes.annotate(
        day=TruncDate('completed_at', tzinfo=CENTRAL)).values('day').annotate(count=Count('pk'))}
    activities = StudyActivity.objects.filter(session__user=user, created_at__gte=start,
        created_at__lt=end, created_at__lte=now, kind__in=['reading', 'quiz'])
    activity_days = {row['day']: row for row in activities.annotate(day=TruncDate('created_at', tzinfo=CENTRAL))
        .values('day').annotate(reading=Count('pk', filter=Q(kind='reading')), quiz=Count('pk', filter=Q(kind='quiz')))}
    days = []
    for offset in range(35):
        date = grid_start + timedelta(days=offset)
        events = activity_days.get(date, {})
        reading, quiz, passed = events.get('reading', 0), events.get('quiz', 0), pass_days.get(date, 0)
        future = date > today
        level = 3 if passed else 2 if quiz else 1 if reading else 0
        description = ('Future date' if future else
            f'{reading} reading actions, {quiz} quiz answers, {passed} completed sessions' if level else 'No activity')
        days.append({'date': date, 'future': future, 'level': level, 'passed': passed,
                     'label': f'{date:%A, %B %d, %Y}: {description}'})
    return {'count': count, 'goal': WEEKLY_GOAL, 'percent': count * 100 // WEEKLY_GOAL,
            'fill': min(100, count * 100 // WEEKLY_GOAL), 'remaining': max(0, WEEKLY_GOAL - count),
            'week_start': monday, 'week_end': next_monday - timedelta(days=1), 'days': days}
