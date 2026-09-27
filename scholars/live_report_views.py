from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from accounts.views import administrator_required
from .live_reports import report, run_history
from .models import LiveQuiz, SavedQuiz


@login_required
@require_GET
def results(request, pk):
    game = get_object_or_404(LiveQuiz, pk=pk, phase='finished')
    hosting = request.user.is_admin and game.host_id == request.user.pk
    participant = None if hosting else get_object_or_404(game.participants, user=request.user, roster_at__isnull=False)
    return render(request, 'scholars/live/report.html', {'game': game, 'hosting': hosting,
        'teacher_tools': hosting, **report(game, participant, include_students=hosting)})


@administrator_required
@require_GET
def student_results(request, pk, student_id):
    game = get_object_or_404(LiveQuiz, pk=pk, phase='finished', host=request.user)
    participant = get_object_or_404(game.participants.select_related('user'), user_id=student_id, roster_at__isnull=False)
    return render(request, 'scholars/live/report.html', {'game': game, 'hosting': True, 'teacher_tools': True,
        'student': participant.user, **report(game, participant)})


@administrator_required
@require_GET
def history(request, quiz_id=None):
    quiz = get_object_or_404(SavedQuiz, pk=quiz_id, owner=request.user) if quiz_id else None
    games = run_history(request.user)
    if quiz:
        games = games.filter(quiz=quiz)
    return render(request, 'scholars/live/history.html', {'teacher_tools': True, 'quiz': quiz,
        'games': Paginator(games, 20).get_page(request.GET.get('page'))})
