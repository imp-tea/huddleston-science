"""Server-owned scoring and public totals; never expose classmates' answers."""
import math

from django.db.models import Q, Sum


def points_available(elapsed):
    seconds = min(15, max(0, elapsed - 3))
    return math.floor(max(25, 100 - 10 * seconds + seconds ** 2 / 3) + .5)


def leaderboard(game):
    players = game.participants.filter(roster_at__isnull=False).select_related('user').annotate(
        total_points=Sum('responses__points', filter=Q(responses__question__game=game,
            responses__question__opened_at__isnull=False, responses__question__position__lte=game.position), default=0)).order_by('-total_points', 'user__username', 'pk')
    rows = [{'id': player.pk, 'name': player.user.username, 'points': player.total_points} for player in players]
    maximum = max((row['points'] for row in rows), default=0)
    for row in rows:
        row['percent'] = round(100 * row['points'] / maximum, 2) if maximum else 0
    return rows
