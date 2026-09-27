import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from .importer import import_content
from .models import Question, QuestionRevision, QuestionChange, StudyQuestion
from .question_bank import adopt_difficulty, apply_updates, fingerprint, PEI_ID, PEI_OLD, PEI_NEW
from .question_authoring import edit_question, change_question_status
from .test_helpers import small_dataset
from .test_question_authoring import admin
from .test_study import seed_study
from .study import start_study


class DatabaseQuestionBankTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = seed_study()
        cls.author = admin()

    def row(self, qid='q-0-0', **updates):
        q = Question.objects.select_related('current_revision').get(pk=qid)
        return {'question_id': q.pk, 'edit_version': q.edit_version,
                'source_sha256': fingerprint(q), **updates}

    def patch(self, rows, apply=False):
        return apply_updates(self.author, {'schema_version': 1, 'updates': rows}, apply=apply)

    def classification(self, q, label='medium'):
        return {'schema_version': 1, 'model': 'gpt-6-sol', 'reasoning_effort': 'low',
                'questions': {q.pk: {'difficulty': label, 'source_sha256': fingerprint(q)}}}

    def test_difficulty_import_preview_apply_and_idempotency_preserve_history(self):
        session = start_study(self.student, uuid.uuid4(), 'small')
        pinned = list(StudyQuestion.objects.filter(session_topic__session=session).values_list('pk', 'revision_id', 'answer_bank_id'))
        q = Question.objects.get(pk='q-0-0')
        revision = q.current_revision_id
        data = self.classification(q)
        self.assertEqual(adopt_difficulty(data)['changes'], 1)
        q.refresh_from_db(); self.assertEqual(q.difficulty, '')
        adopt_difficulty(data, apply=True)
        q.refresh_from_db()
        self.assertEqual((q.difficulty, q.edit_version, q.current_revision_id), ('medium', 1, revision))
        self.assertEqual(adopt_difficulty(data, apply=True)['changes'], 0)
        self.assertEqual(q.changes.count(), 1)
        self.assertEqual(pinned, list(StudyQuestion.objects.filter(session_topic__session=session).values_list('pk', 'revision_id', 'answer_bank_id')))

    def test_cutover_conflict_rolls_back_every_label(self):
        q = Question.objects.get(pk='q-0-0')
        data = self.classification(q)
        data['questions']['q-0-1'] = {'difficulty': 'hard', 'source_sha256': '0' * 64}
        with self.assertRaises(ValidationError): adopt_difficulty(data, apply=True)
        self.assertFalse(Question.objects.exclude(difficulty='').exists())
        self.assertFalse(QuestionChange.objects.exists())

    def test_exact_pei_correction_creates_revision_and_assesses_corrected_text(self):
        q = Question.objects.create(pk=PEI_ID, topic_id='topic-0', format='typed')
        old = QuestionRevision.objects.create(question=q, digest='pei-old', context={},
            payload={'question_id': q.pk, 'study_topic_id': q.topic_id, 'format': 'typed',
                     'question': PEI_OLD, 'correct_answer': 'I. M. Pei'})
        q.current_revision = old; q.save()
        data = self.classification(q)
        data['questions'][q.pk]['source_sha256'] = fingerprint(q, {**old.payload, 'question': PEI_NEW})
        self.assertEqual(adopt_difficulty(data)['pei_corrections'], 1)
        q.refresh_from_db(); self.assertEqual(q.current_revision_id, old.pk)
        adopt_difficulty(data, apply=True)
        q.refresh_from_db(); self.assertNotEqual(q.current_revision_id, old.pk)
        self.assertEqual(q.current_revision.payload['question'], PEI_NEW)
        old.refresh_from_db(); self.assertEqual(old.payload['question'], PEI_OLD)
        self.assertEqual(adopt_difficulty(data, apply=True)['changes'], 0)

    def test_bulk_preview_is_read_only_and_stale_rows_roll_back_all(self):
        rows = [self.row(difficulty='easy'), self.row('q-0-1', difficulty='hard')]
        self.assertEqual(self.patch(rows)['changes'], 2)
        self.assertFalse(Question.objects.exclude(difficulty='').exists())
        q = Question.objects.get(pk='q-0-1'); q.edit_version += 1; q.save()
        with self.assertRaises(ValidationError): self.patch(rows, apply=True)
        self.assertFalse(Question.objects.exclude(difficulty='').exists())
        rows[1] = self.row('q-0-1', difficulty='hard')
        self.patch(rows, apply=True)
        self.assertEqual(Question.objects.get(pk='q-0-0').difficulty, 'easy')
        with self.assertRaises(ValidationError): self.patch(rows, apply=True)

    def test_bulk_edit_archive_and_export_preserve_revision_evidence(self):
        q = Question.objects.get(pk='q-0-0'); old_id = q.current_revision_id
        rows = [self.row(question='A new stem?', answer='A new answer', difficulty='hard')]
        preview = self.patch(rows)['preview'][0]
        self.assertEqual(preview['before']['answer'], q.current_revision.payload['correct_answer'])
        self.assertEqual(preview['after']['answer'], 'A new answer')
        self.patch(rows, apply=True)
        q.refresh_from_db()
        self.assertEqual(q.difficulty, 'hard'); self.assertNotEqual(q.current_revision_id, old_id)
        self.assertTrue(QuestionRevision.objects.filter(pk=old_id).exists())
        self.patch([self.row(active=False)], apply=True)
        q.refresh_from_db(); self.assertFalse(q.active)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bank.json'
            call_command('export_question_bank', str(path), history=True, stdout=StringIO())
            data = json.loads(path.read_text())
            self.assertEqual(len(data['questions']), Question.objects.count())
            row = next(r for r in data['questions'] if r['question_id'] == q.pk)
            self.assertEqual(row['source_sha256'], fingerprint(q))
            self.assertFalse(row['active']); self.assertEqual(len(row['revisions']), 2)
            self.assertEqual(len(row['changes']), 2)
            self.assertNotIn('study-student', path.read_text())

    def test_editor_clears_stale_difficulty_and_allows_rating_and_archive(self):
        self.patch([self.row(difficulty='easy')], apply=True)
        q = Question.objects.get(pk='q-0-0')
        q = edit_question(self.author, q.pk, q.edit_version,
            {'question': 'Different stem?', 'correct_answer': q.current_revision.payload['correct_answer'], 'difficulty': 'easy'})
        self.assertEqual(q.difficulty, '')
        q = edit_question(self.author, q.pk, q.edit_version,
            {'question': 'Different stem?', 'correct_answer': q.current_revision.payload['correct_answer'], 'difficulty': 'hard'})
        self.assertEqual(q.difficulty, 'hard')
        self.assertFalse(change_question_status(self.author, q.pk, q.edit_version, 'archive').active)


class DatabaseOwnedImportTests(TestCase):
    def test_default_import_ignores_question_files_and_seed_is_explicit_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); data = small_dataset(path)
            import_content(path)
            self.assertFalse(Question.objects.exists())
            import_content(path, seed_questions=True)
            q = Question.objects.first(); revision = q.current_revision_id
            q.active = False; q.save()
            (path / 'practice/01.json').write_text('not json')
            (path / 'typed-questions.json').write_text('not json')
            import_content(path, allow_retire=True)
            q.refresh_from_db(); self.assertFalse(q.active)
            self.assertEqual(q.current_revision_id, revision)
            (path / 'practice/01.json').write_text(json.dumps(data['practice/01.json']))
            (path / 'typed-questions.json').unlink()
            with self.assertRaises(ValidationError): import_content(path, seed_questions=True)

    def test_even_explicit_retirement_cannot_hide_active_questions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); data = small_dataset(path)
            import_content(path, seed_questions=True)
            q = Question.objects.first()
            for name in ('topics.json',):
                (path / name).write_text(json.dumps([t for t in data[name] if t['study_topic_id'] != q.topic_id]))
            (path / 'content.json').write_text(json.dumps({k:v for k,v in data['content.json'].items() if k != q.topic_id}))
            (path / 'topic-redirects.json').write_text('{}')
            with self.assertRaises(ValidationError): import_content(path, allow_retire=True)
            self.assertTrue(q.topic.active)


class OwnershipMigrationTests(TransactionTestCase):
    def test_cutover_preserves_edited_archived_question_and_baseline_evidence(self):
        old = [('scholars', '0011_live_roster_count')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            category = apps.get_model('scholars', 'Category').objects.create(pk='Migration', payload={})
            topic = apps.get_model('scholars', 'Topic').objects.create(pk='migration-topic',
                subject_id='migration-subject', category=category, title='Migration', payload={})
            q = apps.get_model('scholars', 'Question').objects.create(pk='migration-question', topic=topic, active=False, edit_version=9)
            Revision = apps.get_model('scholars', 'QuestionRevision')
            baseline = Revision.objects.create(question=q, digest='baseline', payload={'question': 'Before?', 'correct_answer': 'Before'}, context={})
            edited = Revision.objects.create(question=q, digest='edited', payload={'question': 'After?', 'correct_answer': 'After'}, context={})
            q.imported_revision = baseline; q.override_base_revision = baseline
            q.override_revision = edited; q.current_revision = edited; q.save()
        finally:
            MigrationExecutor(connection).migrate(latest)
        q = Question.objects.get(pk='migration-question')
        self.assertEqual((q.current_revision_id, q.active, q.edit_version), (edited.pk, False, 9))
        self.assertEqual(q.revisions.count(), 2)
        evidence = q.changes.get(kind='database_ownership')
        self.assertEqual(evidence.before['imported_revision_id'], baseline.pk)
        self.assertEqual(evidence.before['override_revision_id'], edited.pk)
        self.assertEqual(evidence.after['current_revision_id'], edited.pk)
