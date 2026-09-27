"""Portable authoring evidence; full database backups remain the restore mechanism."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from scholars.importer import CONTENT_LOCK
from scholars.models import Question


class Command(BaseCommand):
    help = 'Export teacher questions and edited-question histories to a new JSON file (no student data).'

    def add_arguments(self, parser):
        parser.add_argument('output', type=Path)

    def handle(self, *args, **options):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock_shared(%s)', [CONTENT_LOCK])
            questions = Question.objects.filter(Q(origin='teacher') | Q(override_revision__isnull=False) |
                                                Q(revisions__author__isnull=False)).distinct().order_by('pk').prefetch_related('revisions')
            rows = []
            for question in questions:
                rows.append({'question_id': question.pk, 'topic_id': question.topic_id,
                    'format': question.format, 'origin': question.origin, 'active': question.active,
                    'edit_version': question.edit_version, 'current_revision_id': question.current_revision_id,
                    'imported_revision_id': question.imported_revision_id,
                    'override_revision_id': question.override_revision_id,
                    'override_base_revision_id': question.override_base_revision_id,
                    'revisions': [{'id': r.pk, 'digest': r.digest, 'payload': r.payload, 'context': r.context,
                        'author_id': str(r.author_id) if r.author_id else None,
                        'created_at': r.created_at.isoformat()} for r in question.revisions.all()]})
        data = {'schema_version': 1, 'exported_at': timezone.now().isoformat(), 'questions': rows}
        try:
            descriptor = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write('\n')
        except OSError as exc:
            raise CommandError('Could not create export. Choose a new file in an existing writable directory.') from exc
        self.stdout.write(self.style.SUCCESS(f'Exported {len(rows)} questions to {options["output"]}'))
