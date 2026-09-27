import json
from pathlib import Path
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from accounts.models import User
from scholars.question_bank import apply_updates


class Command(BaseCommand):
    help = 'Preview versioned question patches from local analysis. Use --apply to write atomically.'

    def add_arguments(self, parser):
        parser.add_argument('input', type=Path)
        parser.add_argument('--author', required=True, help='Existing active administrator username.')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            author = User.objects.get(username=options['author'])
            report = apply_updates(author, json.loads(options['input'].read_text()), apply=options['apply'])
        except (User.DoesNotExist, PermissionDenied, ValidationError, ValueError, TypeError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2))
