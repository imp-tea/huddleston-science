import json
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from scholars.question_bank import adopt_difficulty


class Command(BaseCommand):
    help = 'Preview database cutover: checked difficulty labels and the exact Pei correction. Use --apply to write.'

    def add_arguments(self, parser):
        parser.add_argument('--input', type=Path, default=settings.BASE_DIR / 'data/question-difficulty.json')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            report = adopt_difficulty(json.loads(options['input'].read_text()), apply=options['apply'])
        except (ValidationError, ValueError, TypeError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2))
