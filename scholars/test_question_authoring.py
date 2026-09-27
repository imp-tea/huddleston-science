import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connections
from django.db.models import F
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from .test_helpers import import_content
from .models import Category, Question, QuestionRevision, Source, StudyQuestion
from .question_authoring import (StaleQuestion, change_question_status, create_question,
                                 edit_question)
from .study import abandon_study, start_study
from .test_helpers import small_dataset
from .test_study import seed_study


def admin():
    return User.objects.create_user('author-admin', 'Author-password!', is_admin=True, must_change_password=False)


class AuthoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = seed_study()
        cls.teacher = admin()
        source = Source.objects.create(pk='original', payload={'source': 'Original Tournament', 'round': '3',
            'number': '7', 'question_type': 'bonuses', 'parts': [{'label': 'A',
                'question': 'Original source secret <script>alert(1)</script>', 'answer': 'Original answer'}]})
        topic = Question.objects.get(pk='q-0-0').topic
        topic.payload['source_ids'] = [source.pk]
        topic.save()

    def setUp(self):
        self.client.force_login(self.teacher)

    def create(self, **data):
        return create_question(self.teacher, 'topic-0', uuid.uuid4(),
            {'question': 'Name this mineral.', 'correct_answer': 'Zircon', **data})

    def test_create_validates_identity_payload_and_repeated_request(self):
        key = uuid.uuid4()
        q = create_question(self.teacher, 'topic-0', key, {'question': '  Mineral? ', 'correct_answer': ' Zircon '})
        self.assertEqual(q.pk, f'teacher-{key}')
        self.assertEqual(q.origin, 'teacher')
        self.assertEqual(q.current_revision.payload['question'], 'Mineral?')
        self.assertEqual(q.current_revision.author, self.teacher)
        self.assertEqual(q.current_revision.context['sources']['original']['source'], 'Original Tournament')
        again = create_question(self.teacher, 'topic-0', key, {'question': 'Mineral?', 'correct_answer': 'Zircon'})
        self.assertEqual(again.pk, q.pk)
        self.assertEqual(q.revisions.count(), 1)
        self.assertIn('Zircon', Category.objects.get(pk='Geography').typed_bank.answers)
        for data in [{'question': '', 'correct_answer': 'x'}, {'question': 'Q', 'correct_answer': ' '},
                     {'question': 'Q', 'correct_answer': 'a' * 241}]:
            with self.assertRaises(ValidationError):
                self.create(**data)

    def test_new_study_uses_edit_and_authored_question_old_session_keeps_evidence(self):
        old = start_study(self.student, uuid.uuid4(), 'small')
        item = StudyQuestion.objects.get(session_topic__session=old, revision__question_id='q-0-0')
        original = item.revision
        old_bank = item.answer_bank
        edited = edit_question(self.teacher, 'q-0-0', 0,
            {'question': 'Rewritten question?', 'correct_answer': 'Brand new canonical'})
        created = self.create()
        item.refresh_from_db()
        self.assertEqual(item.revision_id, original.pk)
        self.assertEqual(item.answer_bank_id, old_bank.pk)
        self.assertNotIn('Brand new canonical', old_bank.answers)
        abandon_study(self.student, old.pk)
        new = start_study(self.student, uuid.uuid4(), 'small')
        items = StudyQuestion.objects.filter(session_topic__session=new)
        self.assertTrue(items.filter(revision=edited.current_revision).exists())
        self.assertTrue(items.filter(revision=created.current_revision).exists())
        self.assertIn('Brand new canonical', items.first().answer_bank.answers)

    def test_stale_edit_archive_and_restore_are_rejected_without_overwrite(self):
        q = self.create()
        before = q.edit_version
        q = edit_question(self.teacher, q.pk, before, {'question': 'Updated?', 'correct_answer': 'Corundum'})
        with self.assertRaises(StaleQuestion):
            edit_question(self.teacher, q.pk, before, {'question': 'Stale?', 'correct_answer': 'Quartz'})
        with self.assertRaises(StaleQuestion):
            change_question_status(self.teacher, q.pk, before, 'archive')
        archived = change_question_status(self.teacher, q.pk, q.edit_version, 'archive')
        self.assertFalse(archived.active)
        self.assertNotIn('Corundum', Category.objects.get(pk='Geography').typed_bank.answers)
        restored = change_question_status(self.teacher, q.pk, archived.edit_version, 'reactivate')
        self.assertTrue(restored.active)
        self.assertEqual(restored.current_revision_id, q.current_revision_id)
        self.assertFalse(change_question_status(self.teacher, 'q-0-0', 0, 'archive').active)

    def test_imported_restore_action_is_removed_history_is_preserved(self):
        baseline = Question.objects.get(pk='q-0-0').current_revision
        edited = edit_question(self.teacher, 'q-0-0', 0, {'question': 'Replacement?', 'correct_answer': 'Zircon'})
        with self.assertRaises(ValidationError):
            change_question_status(self.teacher, edited.pk, edited.edit_version, 'restore_imported')
        self.assertTrue(QuestionRevision.objects.filter(pk=baseline.pk).exists())

    def test_source_panel_is_admin_only_and_escaped(self):
        url = reverse('scholars:topic', args=['topic-0'])
        response = self.client.get(url)
        self.assertContains(response, 'Quiz Questions')
        self.assertContains(response, 'Original Tournament')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.client.force_login(self.student)
        response = self.client.get(url)
        self.assertNotContains(response, 'Original source secret')
        self.assertNotContains(response, 'Canonical 0 number 0')
        self.assertNotIn('teacher_questions', response.context)
        self.assertNotIn('teacher_sources', response.context)

    def test_admin_study_reading_has_tools_but_student_reading_does_not(self):
        from .study import save_interests
        save_interests(self.teacher, ['Geography'])
        teacher_session = start_study(self.teacher, uuid.uuid4(), 'small')
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[teacher_session.pk])), 'Quiz Questions')
        student_session = start_study(self.student, uuid.uuid4(), 'small')
        self.client.force_login(self.student)
        response = self.client.get(reverse('scholars:study_session', args=[student_session.pk]))
        self.assertNotContains(response, 'Original source secret')
        self.assertNotIn('teacher_questions', response.context)

    def test_authoring_requires_admin_in_views_and_services_and_csrf(self):
        urls = [reverse('scholars:question_create', args=['topic-0']),
                reverse('scholars:question_edit', args=['q-0-0'])]
        self.client.force_login(self.student)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            create_question(self.student, 'topic-0', uuid.uuid4(), {'question': 'Q', 'correct_answer': 'A'})
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.teacher)
        self.assertEqual(secure.post(urls[0], {}).status_code, 403)
        User.objects.filter(pk=self.teacher.pk).update(must_change_password=True)
        with self.assertRaises(PermissionDenied):
            self.create()

    def test_forms_create_edit_stale_and_archive_confirmation(self):
        url = reverse('scholars:question_create', args=['topic-0'])
        response = self.client.get(url)
        key = response.context['form'].initial['request_key']
        response = self.client.post(url, {'request_key': key, 'question': 'Mineral?', 'correct_answer': 'Zircon',
                                         'format': 'multiple_choice', 'topic_id': 'topic-1'})
        self.assertEqual(response.status_code, 302)
        q = Question.objects.get(pk=f'teacher-{key}')
        self.assertEqual((q.topic_id, q.format), ('topic-0', 'typed'))
        edit_url = reverse('scholars:question_edit', args=[q.pk])
        payload = {'version': q.edit_version, 'question': 'New mineral?', 'correct_answer': 'Quartz'}
        self.assertEqual(self.client.post(edit_url, payload).status_code, 302)
        self.assertContains(self.client.post(edit_url, payload), 'another tab', status_code=409)
        q.refresh_from_db()
        action_url = reverse('scholars:question_action', args=[q.pk, 'archive'])
        self.assertEqual(self.client.get(action_url).status_code, 200)
        q.refresh_from_db()
        self.assertTrue(q.active)
        self.assertEqual(self.client.post(action_url, {'version': q.edit_version, 'action': 'archive'}).status_code, 302)
        q.refresh_from_db()
        self.assertFalse(q.active)

    def test_transaction_rolls_back_question_when_bank_update_fails(self):
        before = Question.objects.count()
        with patch('scholars.question_authoring.rebuild_banks', side_effect=RuntimeError('bank failure')):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(Question.objects.count(), before)

    def test_export_includes_archived_restored_history_and_refuses_overwrite(self):
        q = self.create()
        change_question_status(self.teacher, q.pk, q.edit_version, 'archive')
        edited = edit_question(self.teacher, 'q-0-0', 0, {'question': 'Edited', 'correct_answer': 'Zircon'})
        change_question_status(self.teacher, edited.pk, edited.edit_version, 'archive')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'teacher.json'
            call_command('export_teacher_questions', str(output), stdout=StringIO())
            data = json.loads(output.read_text())
            self.assertEqual(len(data['questions']), Question.objects.count())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertTrue({q.pk, edited.pk} <= {r['question_id'] for r in data['questions']})
            self.assertNotIn('study-student', output.read_text())
            with self.assertRaises(CommandError):
                call_command('export_teacher_questions', str(output), stdout=StringIO())


class AuthoringImportTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.data = small_dataset(self.path)
        import_content(self.path)
        self.teacher = admin()
        self.q = Question.objects.select_related('current_revision').first()

    def edit(self):
        return edit_question(self.teacher, self.q.pk, self.q.edit_version, {
            'question': 'Edited multiple choice?', 'correct_answer': 'Teacher answer',
            'distractors': 'First distractor\nSecond distractor\nThird distractor', 'explanation': 'Teacher explanation.'})

    def test_reimport_keeps_override_new_and_archived_questions(self):
        q = self.edit()
        created = create_question(self.teacher, q.topic_id, uuid.uuid4(), {'question': 'New?', 'correct_answer': 'New answer'})
        change_question_status(self.teacher, created.pk, created.edit_version, 'archive')
        import_content(self.path)
        q.refresh_from_db()
        created.refresh_from_db()
        self.assertEqual(q.current_revision.payload['correct_answer'], 'Teacher answer')
        self.assertEqual(q.current_revision.payload['canonical_correct_answer'], 'Teacher answer')
        self.assertFalse(created.active)

    def test_changed_repo_question_is_ignored_without_invalidating_editor(self):
        q = self.edit()
        version, revision = q.edit_version, q.current_revision_id
        questions = self.data['practice/01.json']
        next(row for row in questions if row['question_id'] == q.pk)['question'] = 'New imported wording?'
        (self.path / 'practice/01.json').write_text(json.dumps(questions))
        import_content(self.path)
        q.refresh_from_db()
        self.assertEqual((q.edit_version, q.current_revision_id), (version, revision))
        self.assertEqual(q.current_revision.payload['question'], 'Edited multiple choice?')

    def test_import_retirement_preserves_authored_question_and_evidence(self):
        q = self.edit()
        created = create_question(self.teacher, q.topic_id, uuid.uuid4(), {'question': 'New?', 'correct_answer': 'New answer'})
        # Use another valid real subset so all references and legacy question quotas remain valid.
        data = self.data
        tid = q.topic_id
        data['topics.json'] = [t for t in data['topics.json'] if t['study_topic_id'] != tid]
        data['practice/01.json'] = [row for row in data['practice/01.json'] if row['study_topic_id'] != tid]
        data['content.json'].pop(tid, None)
        data['topic-redirects.json'] = {}
        for name, value in data.items():
            (self.path / name).write_text(json.dumps(value))
        with self.assertRaises(ValidationError):
            import_content(self.path)
        with self.assertRaises(ValidationError):
            import_content(self.path, allow_retire=True)
        Question.objects.filter(topic_id=tid).update(active=False)
        import_content(self.path, allow_retire=True)
        q.refresh_from_db()
        created.refresh_from_db()
        self.assertFalse(q.active)
        self.assertFalse(created.active)
        self.assertFalse(created.topic.active)
        with self.assertRaises(ValidationError):
            edit_question(self.teacher, created.pk, created.edit_version, {'question': 'Q', 'correct_answer': 'A'})

    def test_multiple_choice_validation_rejects_duplicates_and_wrong_count(self):
        for choices in ['A\nB', 'Answer\nB\nC', 'B\nb\nC']:
            with self.assertRaises(ValidationError):
                edit_question(self.teacher, self.q.pk, self.q.edit_version, {'question': 'Question?',
                    'correct_answer': 'Answer', 'distractors': choices, 'explanation': 'Explanation'})


class AuthoringConcurrencyTests(TransactionTestCase):
    def test_concurrent_edit_accepts_only_one_version(self):
        seed_study()
        teacher = admin()
        barrier = Barrier(2)

        def run(answer):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    edit_question(teacher, 'q-0-0', 0, {'question': 'Concurrent question?', 'correct_answer': answer})
                    return 'saved'
                except StaleQuestion:
                    return 'stale'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ['First answer', 'Second answer']))
        self.assertCountEqual(results, ['saved', 'stale'])
        self.assertEqual(Question.objects.get(pk='q-0-0').edit_version, 1)


class AuthoringMigrationTests(TransactionTestCase):
    def test_existing_question_gets_baseline_without_changing_current_revision(self):
        old = [('scholars', '0007_studypreferences_categories_and_more')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            category = apps.get_model('scholars', 'Category').objects.create(pk='Migration', payload={})
            topic = apps.get_model('scholars', 'Topic').objects.create(pk='migration-topic',
                subject_id='migration-subject', category=category, title='Migration topic', payload={})
            question = apps.get_model('scholars', 'Question').objects.create(pk='migration-question', topic=topic)
            revision = apps.get_model('scholars', 'QuestionRevision').objects.create(question=question,
                digest='migration-digest', payload={'question': 'Original?', 'correct_answer': 'Original'}, context={})
            question.current_revision = revision
            question.save()
        finally:
            MigrationExecutor(connection).migrate(latest)
        migrated = Question.objects.get(pk='migration-question')
        self.assertEqual(migrated.current_revision_id, revision.pk)
        self.assertEqual(migrated.difficulty, "")
        self.assertEqual(migrated.origin, 'imported')
