import uuid
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.views import administrator_required
from . import live
from .models import LiveQuiz, LiveQuizQuestion, LiveParticipant, SavedQuiz
from .typed_answers import for_item
from .live_scoring import grace_seconds, leaderboard


def api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except PermissionDenied as exc:
            return JsonResponse({'error': str(exc)}, status=403)
        except Http404:
            return JsonResponse({'error': 'This quiz or player is unavailable.'}, status=404)
        except ValidationError as exc:
            return JsonResponse({'error': ' '.join(exc.messages)}, status=409 if isinstance(exc, live.LiveConflict) else 400)
    return wrapped


def integer(request, name):
    try:
        return int(request.POST.get(name, ''))
    except (ValueError, TypeError) as exc:
        raise ValidationError('Invalid quiz control. Refresh the page.') from exc


def invitation(user):
    game = LiveQuiz.objects.filter(phase__in=live.OPEN_PHASES).first()
    if not game:
        return None
    if game.host_id == user.pk:
        label = 'Hosting Live Quiz'
    elif user.is_admin:
        return None
    elif game.phase == 'waiting':
        label = 'Join the Live Quiz!'
    elif game.participants.filter(user=user, roster_at__isnull=False).exists():
        label = 'Return to your live quiz'
    else:
        label = 'Join the Live Quiz!'
    return {'title': game.title, 'label': label, 'url': reverse('scholars:live_page', args=[game.pk]), 'id': str(game.pk)}


@administrator_required
@require_http_methods(['GET', 'POST'])
def host(request):
    current = invitation(request.user)
    if current:
        return redirect(current['url'])
    error = None
    if request.method == 'POST':
        try:
            game = live.host(request.user, live.token(request.POST.get('quiz')), integer(request, 'version'), request.POST.get('request_key'))
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            return redirect('scholars:live_page', pk=game.pk)
    quizzes = SavedQuiz.objects.filter(owner=request.user, archived=False).annotate(question_count=Count('items')).order_by('-updated_at', '-pk')
    return render(request, 'scholars/live/host.html', {'teacher_tools': True, 'error': error,
        'quizzes': Paginator(quizzes, 20).get_page(request.GET.get('page')), 'request_key': uuid.uuid4()}, status=400 if error else 200)


@login_required
@require_GET
@api
def discover(request):
    return JsonResponse({'invitation': invitation(request.user)})


@login_required
@require_GET
def page(request, pk):
    game = get_object_or_404(LiveQuiz, pk=pk)
    live.can_view(request.user, game)
    if game.phase == 'finished':
        return redirect('scholars:live_report', pk=game.pk)
    return render(request, 'scholars/live/page.html', {'game': game, 'hosting': game.host_id == request.user.pk,
        'teacher_tools': request.user.is_admin})


@login_required
@require_GET
@api
def state(request, pk):
    game = get_object_or_404(LiveQuiz, pk=pk)
    live.can_view(request.user, game)
    hosting = game.host_id == request.user.pk
    active_ids = set(live.live_connections(game).values_list('user_id', flat=True))
    # A non-ended expired lease means connection loss; all ended leases mean a
    # deliberate exit. Another live tab always keeps that student's presence.
    unended_ids = set(game.connections.filter(ended_at__isnull=True).values_list('user_id', flat=True))
    players = game.participants.select_related('user').filter(user__is_active=True, user__must_change_password=False)
    if game.phase != 'waiting':
        players = players.filter(roster_at__isnull=False)
    participants = []
    for player in players.order_by('user__username'):
        presence = 'connected' if player.user_id in active_ids else ('away' if player.user_id in unended_ids else 'left')
        if game.phase == 'waiting' and presence != 'connected':
            continue
        participants.append({'id': player.pk, 'name': player.user.username, 'presence': presence})
    own = game.participants.filter(user=request.user, roster_at__isnull=False).first()
    now = timezone.now()
    data = {'server_now': now.isoformat(), 'timed_scoring': game.timed_scoring, 'id': str(game.pk), 'title': game.title, 'phase': game.phase, 'version': game.version,
        'position': game.position, 'total': game.question_count, 'hosting': hosting,
        'host_present': game.host_id in active_ids, 'players': participants,
        'connected': sum(p['presence'] == 'connected' for p in participants),
        'roster_count': game.participants.filter(roster_at__isnull=False).count()}
    if game.phase in {'running', 'finished'}:
        data['leaderboard'] = leaderboard(game)
    if game.phase == 'running':
        question = game.questions.select_related('revision').defer('revision__context').get(position=game.position)
        revealing = question.opened_at > now
        data['revealing'] = revealing
        if revealing:
            previous = game.questions.select_related('revision').get(position=game.position - 1)
            data['reveal'] = {'position': previous.position, 'prompt': previous.revision.payload['question'],
                'answer': previous.revision.payload['correct_answer'], 'until': question.opened_at.isoformat()}
        else:
            data['question'] = {'position': question.position,
                'grace_seconds': grace_seconds(question.revision.payload['question'])}
            # Reveal the prompt only once the student's persisted clock has begun.
            if hosting or not game.timed_scoring or (own and own.timer_position == game.position):
                data['question']['prompt'] = question.revision.payload['question']
        data['started_at'] = (own.question_started_at.isoformat()
            if own and own.timer_position == game.position and own.question_started_at else None)
        if hosting:
            statuses = dict(question.responses.values_list('participant_id', 'status'))
            data['answered'] = len(statuses)
            for player in participants:
                player['answered'] = player['id'] in statuses
        elif own:
            response = question.responses.filter(participant=own).first()
            data['response'] = {'status': response.status, 'answer': response.typed_answer, 'points': response.points} if response else None
    elif game.phase == 'finished':
        data['report_url'] = reverse('scholars:live_report', args=[game.pk])
        if game.roster_size_at_start is None:
            data['cohort_note'] = 'Original roster size was not recorded for this older quiz. Results use retained player records.'
        elif game.roster_size_at_start + game.late_joiners > data['roster_count']:
            data['cohort_note'] = 'Some player accounts have been deleted. Results have been recalculated from retained records.'
        presented = game.position
        covered = game.questions.filter(position__lte=presented, responses__status='correct').distinct().count()
        data['summary'] = {'presented': presented, 'covered': covered,
            'coverage_percent': round(100 * covered / presented) if presented else 0, 'partial': game.ended_early,
            'score': own.responses.filter(status='correct').count() if own else None,
            'points': next((p['points'] for p in data['leaderboard'] if own and p['id'] == own.pk), None)}
    return JsonResponse(data)


@login_required
@require_GET
@api
def suggestions(request, pk, position):
    game = get_object_or_404(LiveQuiz, pk=pk)
    get_object_or_404(LiveParticipant, game=game, user=request.user, roster_at__isnull=False)
    if game.phase != 'running' or position != game.position:
        raise live.LiveConflict('That question has closed.')
    question = game.questions.select_related('revision', 'answer_bank').get(position=position)
    if question.opened_at is None or question.opened_at > timezone.now():
        raise live.LiveConflict('Wait for this question to open.')
    bank = for_item(question)
    return JsonResponse({'position': position, 'version': game.version,
        'index': [{k: row[k] for k in ('text', 'key', 'parts')} for row in bank['index']]})


@login_required
@require_POST
@api
def connect(request, pk):
    live.join(request.user, pk, request.POST.get('connection'))
    return JsonResponse({'ok': True})


@login_required
@require_POST
@api
def heartbeat(request, pk):
    live.heartbeat(request.user, pk, request.POST.get('connection'))
    return JsonResponse({'ok': True})


@login_required
@require_POST
@api
def leave(request, pk):
    live.leave(request.user, pk, request.POST.get('connection'))
    return JsonResponse({'ok': True})


@login_required
@require_POST
@api
def control(request, pk):
    game = live.transition(request.user, pk, request.POST.get('action'), integer(request, 'version'),
                           integer(request, 'position'), request.POST.get('request_key'))
    return JsonResponse({'version': game.version})


@login_required
@require_POST
@api
def answer(request, pk):
    action = request.POST.get('action')
    if action not in {'answer', 'skip'}:
        raise ValidationError('Choose Submit or Skip.')
    position = integer(request, 'position')
    result = live.answer(request.user, pk, position, request.POST.get('typed_answer', ''), action == 'skip')
    response = LiveParticipant.objects.get(game_id=pk, user=request.user).responses.filter(question__position=position).first()
    return JsonResponse({'position': position, 'outcome': result, 'points': response.points if response else None})


@login_required
@require_POST
@api
def ready(request, pk):
    position = integer(request, 'position')
    started_at = live.ready(request.user, pk, position)
    question = get_object_or_404(LiveQuizQuestion.objects.select_related('revision'), game_id=pk, position=position)
    return JsonResponse({'started_at': started_at.isoformat(), 'server_now': timezone.now().isoformat(),
        'question': {'position': position, 'prompt': question.revision.payload['question'],
            'grace_seconds': grace_seconds(question.revision.payload['question'])}})
