import uuid
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.views import administrator_required
from . import live
from .models import LiveQuiz, LiveParticipant, SavedQuiz
from .typed_answers import for_item


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
        return None
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
    data = {'id': str(game.pk), 'title': game.title, 'phase': game.phase, 'version': game.version,
        'position': game.position, 'total': game.question_count, 'hosting': hosting,
        'host_present': game.host_id in active_ids, 'players': participants,
        'connected': sum(p['presence'] == 'connected' for p in participants),
        'roster_count': game.participants.filter(roster_at__isnull=False).count()}
    if game.phase == 'running':
        question = game.questions.select_related('revision').defer('revision__context').get(position=game.position)
        data['question'] = {'position': question.position, 'prompt': question.revision.payload['question']}
        if hosting:
            statuses = dict(question.responses.values_list('participant_id', 'status'))
            data['answered'] = len(statuses)
            for player in participants:
                player['answered'] = player['id'] in statuses
        elif own:
            response = question.responses.filter(participant=own).first()
            data['response'] = {'status': response.status, 'answer': response.typed_answer} if response else None
    elif game.phase == 'finished':
        presented = game.position
        covered = game.questions.filter(position__lte=presented, responses__status='correct').distinct().count()
        data['summary'] = {'presented': presented, 'covered': covered,
            'coverage_percent': round(100 * covered / presented) if presented else 0, 'partial': game.ended_early,
            'score': own.responses.filter(status='correct').count() if own else None}
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
    return JsonResponse({'position': position, 'outcome': result})
