"""Portable list evidence; restore the full database backup for complete recovery."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from scholars.importer import CONTENT_LOCK
from scholars.models import SavedQuiz


class Command(BaseCommand):
    help = 'Export saved quizzes and reviewed/current question evidence to a new JSON file (no student data).'

    def add_arguments(self, parser):
        parser.add_argument('output', type=Path)

    def handle(self, *args, **options):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock_shared(%s)', [CONTENT_LOCK])
            rows = []
            for quiz in SavedQuiz.objects.order_by('pk').prefetch_related('items__question__current_revision', 'items__reviewed_revision'):
                rows.append({'id': str(quiz.pk), 'owner_id': str(quiz.owner_id), 'name': quiz.name,
                    'archived': quiz.archived, 'edit_version': quiz.edit_version,
                    'generation_settings': quiz.generation_settings,
                    'created_at': quiz.created_at.isoformat(), 'updated_at': quiz.updated_at.isoformat(),
                    'items': [{'position': item.position, 'question_id': item.question_id,
                        'reviewed_revision': self.revision(item.reviewed_revision),
                        'current_revision': self.revision(item.question.current_revision)} for item in quiz.items.all()]})
        data = {'schema_version': 1, 'exported_at': timezone.now().isoformat(), 'quizzes': rows}
        try:
            descriptor = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write('\n')
        except OSError as exc:
            raise CommandError('Could not create export. Choose a new file in an existing writable directory.') from exc
        self.stdout.write(self.style.SUCCESS(f'Exported {len(rows)} quizzes to {options["output"]}'))

    @staticmethod
    def revision(revision):
        if not revision:
            return None
        return {'id': revision.pk, 'digest': revision.digest, 'payload': revision.payload, 'context': revision.context}
