"""Read-only reporting queries; never enter the student's Study state machine."""
from django.db.models import Count, OuterRef, Q, Subquery

from .models import StudyAttempt
from .progress import session_totals


def study_history(student):
    latest = StudyAttempt.objects.filter(session_id=OuterRef('pk')).order_by('-number').annotate(
        total_answers=Count('answers'),
        saved_answers=Count('answers', filter=Q(answers__answered_at__isnull=False)))
    return student.study_sessions.annotate(
        latest_attempt_number=Subquery(latest.values('number')[:1]),
        latest_score=Subquery(latest.values('score')[:1]),
        latest_total=Subquery(latest.values('total_answers')[:1]),
        latest_answered=Subquery(latest.values('saved_answers')[:1]),
    ).order_by('-started_at', '-pk')


def practice_history(student):
    return session_totals(student.practice_sessions).annotate(
        recalled_count=Count('items', filter=Q(items__self_assessment=True))
    ).order_by('-started_at', '-pk')
