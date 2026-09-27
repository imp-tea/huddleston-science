"""Durable teacher-paced games. Lock order: active account, content (hosting), game.

Routine state reads and connection heartbeats never lock the game. Admission,
explicit leave, answers, and host transitions serialize against its row.
"""
from datetime import timedelta
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (LiveConnection, LiveParticipant, LiveQuiz, LiveQuizQuestion,
                     LiveResponse, LiveTransition, SavedQuiz)
from .question_authoring import lock_author
from .quiz_lists import ready_items
from .services import lock_active_account
from .typed_answers import VERSION, for_item, grade

OPEN_PHASES = ['waiting', 'running']
LEASE_SECONDS = 20


class LiveConflict(ValidationError):
    pass


def token(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError('Invalid request. Reload the live quiz.') from exc


def live_connections(game, now=None):
    now = now or timezone.now()
    return game.connections.filter(ended_at__isnull=True, last_seen__gte=now - timedelta(seconds=LEASE_SECONDS),
        user__is_active=True, user__must_change_password=False)


def can_view(user, game):
    if game.host_id == user.pk:
        return
    if user.is_admin:
        raise PermissionDenied('Only the host can manage this game.')
    if game.phase == 'waiting' or (game.phase == 'cancelled' and game.participants.filter(user=user).exists()):
        return
    if not game.participants.filter(user=user, roster_at__isnull=False).exists():
        raise PermissionDenied('This quiz has already started. Only its original players can return.')


def locked_game(game_id):
    return get_object_or_404(LiveQuiz.objects.select_for_update(), pk=game_id)


@transaction.atomic
def host(user, quiz_id, version, request_key):
    lock_author(user)
    key = token(request_key)
    previous = LiveQuiz.objects.filter(host=user, request_key=key).first()
    if previous:
        return previous
    if LiveQuiz.objects.filter(phase__in=OPEN_PHASES).exists():
        raise LiveConflict('A live quiz is already open. Return to it or close it before hosting another.')
    quiz = get_object_or_404(SavedQuiz.objects.select_for_update(), pk=quiz_id, owner=user)
    if type(version) is not int or quiz.edit_version != version:
        raise LiveConflict('This quiz changed. Reload and review it before hosting.')
    items = ready_items(quiz)
    if any(not i.question.topic.category.typed_bank_id for i in items):
        raise ValidationError('An autocomplete bank is unavailable. Rebuild the question bank before hosting.')
    game = LiveQuiz.objects.create(host=user, quiz=quiz, request_key=key, title=quiz.name,
                                  question_count=len(items), grading_version=VERSION)
    LiveQuizQuestion.objects.bulk_create([LiveQuizQuestion(game=game, position=i.position,
        revision=i.question.current_revision, answer_bank_id=i.question.topic.category.typed_bank_id,
        topic_id_snapshot=i.question.topic_id, topic_title=i.question.topic.title,
        category=i.question.topic.category_id) for i in items])
    return game


@transaction.atomic
def join(user, game_id, connection_id):
    lock_active_account(user)
    game = locked_game(game_id)
    can_view(user, game)
    if game.phase not in OPEN_PHASES:
        raise LiveConflict('This live quiz has ended.')
    key = token(connection_id)
    existing = LiveConnection.objects.filter(pk=key).first()
    if existing and (existing.game_id != game.pk or existing.user_id != user.pk or existing.ended_at):
        raise LiveConflict('This page connection has closed. Reload to reconnect.')
    if user.pk != game.host_id:
        if game.phase == 'running' and not game.participants.filter(user=user, roster_at__isnull=False).exists():
            raise LiveConflict('This quiz has already started.')
        LiveParticipant.objects.get_or_create(game=game, user=user)
    LiveConnection.objects.update_or_create(pk=key, defaults={'game': game, 'user': user, 'last_seen': timezone.now()})
    return game


@transaction.atomic
def heartbeat(user, game_id, connection_id):
    lock_active_account(user)
    updated = LiveConnection.objects.filter(pk=token(connection_id), game_id=game_id, user=user,
        ended_at__isnull=True, game__phase__in=OPEN_PHASES).update(last_seen=timezone.now())
    if not updated:
        raise LiveConflict('This page connection has closed. Reload to reconnect.')


@transaction.atomic
def leave(user, game_id, connection_id):
    lock_active_account(user)
    locked_game(game_id)  # Serialize deliberate departure with roster capture.
    LiveConnection.objects.filter(pk=token(connection_id), game_id=game_id, user=user,
                                  ended_at__isnull=True).update(ended_at=timezone.now())


def close_question(game, now):
    question = game.questions.get(position=game.position)
    answered = question.responses.values_list('participant_id', flat=True)
    missing = game.participants.filter(roster_at__isnull=False).exclude(pk__in=answered)
    LiveResponse.objects.bulk_create([LiveResponse(participant=p, question=question, status='unanswered',
                                                   finalized_at=now) for p in missing])
    question.closed_at = now
    question.save(update_fields=['closed_at'])


@transaction.atomic
def transition(user, game_id, action, version, position, request_key):
    lock_active_account(user)
    game = locked_game(game_id)
    if not user.is_admin or game.host_id != user.pk:
        raise PermissionDenied('Only the host can advance this quiz.')
    key = token(request_key)
    previous = game.transitions.filter(request_key=key).first()
    if previous:
        if (previous.action, previous.expected_version, previous.expected_position) != (action, version, position):
            raise LiveConflict('This request was already used for a different action.')
        return game
    if (type(version), type(position)) != (int, int) or (game.version, game.position) != (version, position):
        raise LiveConflict('The quiz moved on. Refresh its current state before trying again.')
    now = timezone.now()
    if action == 'start' and game.phase == 'waiting':
        players = game.participants.filter(user_id__in=live_connections(game, now).values('user_id'))
        if not players.exists():
            raise ValidationError('Wait for at least one student to join before starting.')
        players.update(roster_at=now)
        game.phase, game.started_at, game.position = 'running', now, 1
        game.questions.filter(position=1).update(opened_at=now)
    elif action == 'cancel' and game.phase == 'waiting':
        game.phase, game.ended_at = 'cancelled', now
    elif action in {'next', 'end'} and game.phase == 'running':
        close_question(game, now)
        if action == 'end' or game.position == game.question_count:
            game.phase, game.ended_at = 'finished', now
            game.ended_early = game.position < game.question_count
        else:
            game.position += 1
            game.questions.filter(position=game.position).update(opened_at=now)
    else:
        raise LiveConflict('This action is not available in the current quiz state.')
    game.version += 1
    game.save(update_fields=['phase', 'started_at', 'position', 'ended_at', 'ended_early', 'version'])
    LiveTransition.objects.create(game=game, request_key=key, action=action,
                                  expected_version=version, expected_position=position)
    return game


@transaction.atomic
def answer(user, game_id, position, typed_answer='', skip=False):
    lock_active_account(user)
    game = locked_game(game_id)
    participant = get_object_or_404(LiveParticipant, game=game, user=user, roster_at__isnull=False)
    if game.phase != 'running' or type(position) is not int or position != game.position:
        raise LiveConflict('That question has closed. Continue with the current question.')
    question = game.questions.select_related('revision', 'answer_bank').get(position=position)
    previous = LiveResponse.objects.filter(participant=participant, question=question).first()
    if previous:
        return previous.status
    if not live_connections(game).filter(user=user).exists():
        raise LiveConflict('Reconnect to this quiz before answering.')
    if type(skip) is not bool or (not skip and (not isinstance(typed_answer, str) or not typed_answer.strip() or len(typed_answer) > 240)):
        raise ValidationError('Enter 1–240 characters, or skip the question.')
    if game.grading_version != VERSION:
        raise LiveConflict('This game uses an unsupported grading version. Ask the host to end it.')
    result = grade(None if skip else typed_answer, question.revision.payload['correct_answer'],
                   suppressed_answers=for_item(question)['suppressedAnswers'])
    if result == 'prompt':
        return result
    status = 'skipped' if skip else result
    LiveResponse.objects.create(participant=participant, question=question, status=status,
                                typed_answer='' if skip else typed_answer)
    return status
