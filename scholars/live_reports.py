"""Read-only reports over presented, frozen questions and the retained players."""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Count, F, OuterRef, Q, Subquery

from .live_scoring import leaderboard
from .models import LiveParticipant, LiveQuiz, Topic, TopicRedirect


def percentage(numerator, denominator):
    return round(100 * numerator / denominator) if denominator else 0


def presented_questions(game):
    return game.questions.filter(position__lte=game.position, opened_at__isnull=False, closed_at__isnull=False)


def student_history(student):
    return student.live_participations.filter(roster_at__isnull=False, game__phase='finished').select_related('game').annotate(
        score=Count('responses', filter=Q(responses__status='correct', responses__question__game_id=F('game_id'),
            responses__question__opened_at__isnull=False, responses__question__closed_at__isnull=False,
            responses__question__position__lte=F('game__position')))
    ).order_by('-game__ended_at', '-game_id')


def run_history(host):
    roster = LiveParticipant.objects.filter(game_id=OuterRef('pk'), roster_at__isnull=False).order_by().values('game_id').annotate(total=Count('pk'))
    return LiveQuiz.objects.filter(host=host).annotate(retained_players=Subquery(roster.values('total')[:1])).order_by('-created_at', '-pk')


def report(game, participant=None, *, include_students=False):
    # Keep this boundary in addition to HTTP gating: no caller can accidentally
    # use this helper to reveal answers during play or from a cancelled lobby.
    if game.phase != 'finished':
        raise ValidationError('Results are available only after the quiz finishes.')
    if participant and (participant.game_id != game.pk or participant.roster_at is None):
        raise ValidationError('This student did not join this game.')
    roster = game.participants.filter(roster_at__isnull=False)
    retained = roster.count()
    eligible = Q(responses__participant__roster_at__isnull=False, responses__participant__game_id=game.pk)
    questions = list(presented_questions(game).select_related('revision').defer('revision__context').annotate(
        correct_count=Count('responses', filter=eligible & Q(responses__status='correct')),
        answered_count=Count('responses', filter=eligible & Q(responses__status__in=['correct', 'incorrect', 'skipped'])),
    ).order_by('position'))
    topic_ids = {q.topic_id_snapshot for q in questions}
    available = set(Topic.objects.filter(pk__in=topic_ids, active=True, category__active=True).values_list('pk', flat=True))
    available.update(TopicRedirect.objects.filter(pk__in=topic_ids, active=True, topic__active=True,
        topic__category__active=True).values_list('pk', flat=True))
    responses = ({r.question_id: r for r in participant.responses.filter(question__in=questions)} if participant else {})
    outcomes = {'correct': 0, 'incorrect': 0, 'skipped': 0, 'unanswered': 0}
    categories = defaultdict(lambda: {'presented': 0, 'covered': 0})
    rows = []
    for question in questions:
        category = categories[question.category]
        category['presented'] += 1
        category['covered'] += int(question.correct_count > 0)
        response = responses.get(question.pk)
        # Normal games finalize all roster responses at closure. Missing historical
        # rows still count toward personal accuracy, rather than shrinking its denominator.
        status = response.status if response else 'unanswered'
        if participant:
            outcomes[status] += 1
        rows.append({'position': question.position, 'prompt': question.revision.payload['question'],
            'correct_answer': question.revision.payload['correct_answer'], 'topic_id': question.topic_id_snapshot,
            'topic_title': question.topic_title, 'topic_available': question.topic_id_snapshot in available,
            'category': question.category, 'correct_count': question.correct_count,
            'answered_count': question.answered_count, 'no_correct': question.correct_count == 0,
            'status': status if participant else None, 'typed_answer': response.typed_answer if response else '',
            'points': response.points if response else 0})
    presented = len(questions)
    covered = sum(row['correct_count'] > 0 for row in rows)
    original = game.roster_size_at_start
    summary = {'presented': presented, 'total': game.question_count, 'covered': covered,
        'coverage_percent': percentage(covered, presented), 'retained_players': retained,
        'original_players': original, 'late_joiners': game.late_joiners, 'removed_players': max(0, original + game.late_joiners - retained) if original is not None else None,
        'cohort_unknown': original is None, 'no_correct': presented - covered,
        'no_responses': sum(row['answered_count'] == 0 for row in rows), 'partial': game.ended_early}
    personal = ({**outcomes, 'percent': percentage(outcomes['correct'], presented)} if participant else None)
    students = None
    if include_students:
        students = list(roster.select_related('user').annotate(score=Count('responses', filter=Q(
            responses__question__in=[q.pk for q in questions], responses__status='correct'))).order_by('user__username', 'pk'))
        for student in students:
            student.percent = percentage(student.score, presented)
    return {'leaderboard': leaderboard(game), 'personal_points': sum(r.points or 0 for r in responses.values()), 'summary': summary, 'personal': personal, 'rows': rows, 'report_students': students,
        'categories': [{'name': name, **values, 'percent': percentage(values['covered'], values['presented'])}
                       for name, values in sorted(categories.items())]}
