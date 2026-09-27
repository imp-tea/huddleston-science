"""Complete local-analysis snapshot; no student data. Database backups remain authoritative."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from scholars.importer import CONTENT_LOCK
from scholars.question_bank import bank_queryset, fingerprint


class Command(BaseCommand):
    help = 'Export the entire question bank with conflict tokens; optionally include revision/change history.'

    def add_arguments(self, parser):
        parser.add_argument('output', type=Path)
        parser.add_argument('--history', action='store_true')

    def handle(self, *args, **options):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock_shared(%s)', [CONTENT_LOCK])
            questions = bank_queryset()
            if options['history']:
                questions = questions.prefetch_related('revisions', 'changes')
            rows = []
            for q in questions:
                if not q.current_revision_id:
                    raise CommandError(f'{q.pk} has no current revision; repair before exporting.')
                row = {'question_id': q.pk, 'study_topic_id': q.topic_id, 'category': q.topic.category_id,
                       'format': q.format, 'origin': q.origin, 'active': q.active, 'difficulty': q.difficulty,
                       'difficulty_metadata': q.difficulty_metadata, 'edit_version': q.edit_version,
                       'current_revision_id': q.current_revision_id, 'source_sha256': fingerprint(q),
                       'question': q.current_revision.payload['question'], 'answer': q.current_revision.payload['correct_answer'],
                       'payload': q.current_revision.payload}
                if options['history']:
                    row['revisions'] = [{'id': r.pk, 'digest': r.digest, 'payload': r.payload, 'context': r.context,
                        'author_id': str(r.author_id) if r.author_id else None, 'created_at': r.created_at.isoformat()}
                        for r in q.revisions.all()]
                    row['changes'] = [{'kind': c.kind, 'before': c.before, 'after': c.after,
                        'author_id': str(c.author_id) if c.author_id else None, 'created_at': c.created_at.isoformat()}
                        for c in q.changes.all()]
                rows.append(row)
            result = {'schema_version': 1, 'exported_at': timezone.now().isoformat(), 'questions': rows}
        try:
            descriptor = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        except OSError as exc:
            raise CommandError('Choose a new file in an existing writable directory.') from exc
        self.stdout.write(f'Exported {len(rows)} questions to {options["output"]}')
