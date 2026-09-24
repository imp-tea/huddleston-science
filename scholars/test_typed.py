import copy
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections, IntegrityError, transaction
from django.test import TestCase, SimpleTestCase, TransactionTestCase
from django.urls import reverse
from accounts.models import User
from .importer import import_content
from .models import AnswerBank, Category, PracticeSession, Question, RewardEvent, ReviewState, SessionQuestion, Topic
from .progress import coverage, participation, personal_bests, missed_topics
from .reviews import review_summary
from .services import answer_question, start_session
from .test_helpers import small_dataset
from .typed_answers import answer_key, answer_index, question_bank, grade, for_item

FIXTURES = json.loads((settings.BASE_DIR / 'tests/fixtures/typed-answers.json').read_text())


class MatchingTests(SimpleTestCase):
    def test_shared_fixtures(self):
        for given, correct, expected in FIXTURES['grades']:
            self.assertEqual(grade(given, correct), expected, (given, correct))
        for correct, other in FIXTURES['distinct']:
            self.assertFalse(question_bank(answer_index([correct, other]), correct)['suppressedAnswers'], (correct, other))
        for correct, other in FIXTURES['variants']:
            self.assertEqual(len(question_bank(answer_index([correct, other]), correct)['suppressedAnswers']), 1)

    def test_saturn_search_and_isolation(self):
        index = answer_index(FIXTURES['saturn'])
        before = copy.deepcopy(index)
        bank = question_bank(index, "Saturn's rings")
        labels = [r['text'] for r in bank['index']]
        self.assertNotIn('Rings of Saturn', labels)
        self.assertNotIn('The rings of Saturn', labels)
        self.assertEqual(next(r['text'] for r in bank['index'] if r['key'] == 'rings of saturn'), "Saturn's rings")
        self.assertEqual(grade('Rings of Saturn', "Saturn's rings", suppressed_answers=bank['suppressedAnswers']), 'prompt')
        self.assertEqual(index, before)
        self.assertIn('Rings of Saturn', [r['text'] for r in question_bank(index, 'Moons of Saturn')['index']])
        self.assertEqual(question_bank([], 'Missing answer')['index'][0]['text'], 'Missing answer')


def typed_dataset(directory):
    data = small_dataset(directory)
    questions = data['practice/01.json']
    single = next(q for q in questions if sum(x['study_topic_id'] == q['study_topic_id'] for x in questions) == 1)
    single['correct_answer'] = 'Magnetic Levitation'
    single['distractors'] = ["Saturn's rings", 'Rings of Saturn', 'The rings of Saturn']
    other = next(q for q in questions if q != single)
    other['distractors'] = ['Antonín Dvořák', 'ANTONIN DVORAK', 'Moons of Saturn']
    Path(directory, 'practice/01.json').write_text(json.dumps(questions))
    import_content(directory)
    return single['question_id'], data


class TypedPracticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with tempfile.TemporaryDirectory() as directory:
            cls.qid, cls.data = typed_dataset(directory)
        cls.user = User.objects.create_user('typed-student', 'Typed-test-password!', must_change_password=False)
        cls.other = User.objects.create_user('other-typed', 'Typed-test-password!', must_change_password=False)
        cls.topic = Question.objects.get(pk=cls.qid).topic

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, mode='typed'):
        return start_session(self.user, uuid.uuid4(), {'topic': self.topic.pk}, mode=mode)

    def post(self, session, **data):
        return self.client.post(reverse('scholars:answer', args=[session.pk, 1]), data)

    def test_default_and_full_category_bank(self):
        response = self.client.post(reverse('scholars:start'), {'request_key': uuid.uuid4(), 'topic': self.topic.pk})
        session = PracticeSession.objects.get()
        self.assertEqual(session.mode, 'typed')
        self.assertEqual(response.status_code, 302)
        item = session.items.get()
        bank = item.answer_bank.answers
        expected = {answer_key(a) for payload in Question.objects.filter(topic__category=self.topic.category, active=True).values_list('current_revision__payload', flat=True) for a in [payload['correct_answer'], *payload['distractors']]}
        self.assertEqual(set(map(answer_key, bank)), expected)
        self.assertEqual(len(bank), len(expected))
        self.assertGreater(len(bank), 4)
        self.assertEqual(sum(answer_key(a) == 'antonin dvorak' for a in bank), 1)
        for scope in [{'topic': self.topic.pk}, {'subcategory': self.topic.payload['subcategory_ids'][0]}, {'q': self.topic.title}]:
            session = start_session(self.user, uuid.uuid4(), scope)
            self.assertTrue(all(i.answer_bank.category == i.revision.context['topic']['primary_category'] for i in session.items.select_related('answer_bank', 'revision')))

    def test_repeated_prompts_are_read_only_then_credit_once(self):
        session = self.start()
        for _ in range(3):
            response = self.post(session, typed_answer='Magnet', is_correct='true', score=999)
            self.assertContains(response, 'Not quite, but close — try again!')
            self.assertContains(response, 'value="Magnet"')
            self.assertNotContains(response, 'Correct answer:')
            self.assertEqual(session.answered, 0)
            self.assertFalse(RewardEvent.objects.exists())
            self.assertFalse(ReviewState.objects.exists())
            self.assertEqual(participation(self.user)['weekly_count'], 0)
            session.refresh_from_db()
            self.assertIsNone(session.completed_at)
        self.assertEqual(self.post(session, typed_answer='  MAGNETIC Levitation ').status_code, 302)
        item = session.items.get()
        self.assertEqual(item.typed_answer, '  MAGNETIC Levitation ')
        self.assertIsNone(item.selected)
        self.assertTrue(item.is_correct)
        self.post(session, typed_answer='wrong')
        self.post(session, typed_answer='')
        item.refresh_from_db()
        self.assertTrue(item.is_correct)
        self.assertEqual(session.score, 1)
        self.assertEqual(RewardEvent.objects.count(), 1)
        self.assertEqual(ReviewState.objects.get().mode, 'typed')
        self.assertEqual(participation(self.user)['weekly_count'], 1)

    def test_blank_length_wrong_skip_and_constraints(self):
        session = self.start()
        self.assertEqual(self.post(session, typed_answer=' ').status_code, 400)
        self.assertEqual(self.post(session, typed_answer='x' * 241).status_code, 400)
        self.assertEqual(session.answered, 0)
        self.assertEqual(self.post(session, action='skip').status_code, 302)
        item = session.items.get()
        self.assertTrue(item.skipped)
        self.assertFalse(item.is_correct)
        self.assertIsNone(item.typed_answer)
        self.assertContains(self.client.get(reverse('scholars:feedback', args=[session.pk, 1])), 'Skipped')
        self.assertEqual(participation(self.user)['xp'], 2)
        self.assertEqual(ReviewState.objects.get().successes, 0)
        second = self.start()
        self.post(second, typed_answer='Gravity')
        self.assertFalse(second.items.get().is_correct)
        self.assertEqual(participation(self.user)['xp'], 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SessionQuestion.objects.filter(pk=item.pk).update(skipped=False)

    def test_saturn_direct_variant_and_pinned_answer_after_import(self):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            data = copy.deepcopy(self.data)
            q = next(q for q in data['practice/01.json'] if q['question_id'] == self.qid)
            q['correct_answer'] = "Saturn's rings"
            q['distractors'] = ['Rings of Saturn', 'The rings of Saturn', 'Moons of Saturn']
            Path(directory, 'practice/01.json').write_text(json.dumps(data['practice/01.json']))
            import_content(directory)
            session = self.start()
            item = session.items.select_related('revision', 'answer_bank').get()
            old_bank = item.answer_bank_id
            response = self.post(session, typed_answer='Rings of Saturn')
            self.assertContains(response, 'Not quite, but close — try again!')
            entries = response.context['suggestion_data']['index']
            self.assertNotIn('Rings of Saturn', [x['text'] for x in entries])
            self.assertEqual(next(r['text'] for r in entries if r['key'] == 'rings of saturn'), "Saturn's rings")
            self.assertEqual(set(entries[0]), {'text', 'key', 'parts'})
            q['correct_answer'] = 'New answer'
            q['distractors'] = ['New one', 'New two', 'New three']
            Path(directory, 'practice/01.json').write_text(json.dumps(data['practice/01.json']))
            import_content(directory)
            self.assertNotEqual(Category.objects.get(pk=self.topic.category_id).typed_bank_id, old_bank)
            item.refresh_from_db()
            self.assertEqual(item.answer_bank_id, old_bank)
            self.assertEqual(self.post(session, typed_answer='The rings of Saturn').status_code, 200)
            self.post(session, typed_answer="Saturn's rings")
            item.refresh_from_db()
            self.assertTrue(item.is_correct)
            self.assertEqual(item.attempt_kind, 'historical')
            self.assertFalse(ReviewState.objects.exists())
            self.assertTrue(AnswerBank.objects.filter(pk=old_bank).exists())
            self.assertEqual(for_item(self.start().items.select_related('revision', 'answer_bank').get())['suppressedAnswers'], set())

    def test_mode_progress_rewards_bests_and_corrected_misses(self):
        recognition = self.start('recognition')
        choice = recognition.items.get().choices.index('Magnetic Levitation')
        answer_question(self.user, recognition.pk, 1, choice)
        wrong = self.start()
        self.post(wrong, typed_answer='Gravity')
        correct = self.start()
        self.post(correct, typed_answer='Magnetic Levitation')
        self.assertTrue(correct.items.get().corrected_previous_miss)
        correct.refresh_from_db()
        self.assertTrue(correct.is_personal_best)
        self.assertEqual(set(personal_bests(self.user).values_list('mode', flat=True)), {'recognition', 'typed'})
        self.assertEqual(participation(self.user)['xp'], 2)
        self.assertEqual(participation(self.user)['weekly_count'], 1)
        self.assertEqual(coverage(self.user)['total']['answers'], 1)
        summary = {r['mode']: r for r in review_summary(self.user)}
        self.assertEqual(summary['typed']['recent_answers'], 2)
        self.assertEqual(summary['typed']['recent_successes'], 1)
        self.assertEqual(summary['recognition']['recent_answers'], 1)
        self.assertEqual(summary['recall']['recent_answers'], 0)
        self.assertEqual(ReviewState.objects.count(), 2)
        # Success in recognition cannot mask the latest typed miss.
        miss = self.start()
        self.post(miss, typed_answer='Gravity')
        self.assertIn(self.topic, missed_topics(self.user))
        due = start_session(self.user, uuid.uuid4(), {'topic': self.topic.pk}, mode='typed', selection='personalized')
        self.assertEqual(due.total, 1)
        with self.assertRaises(ValidationError):
            start_session(self.user, uuid.uuid4(), {'topic': self.topic.pk}, mode='typed', selection='review')

    def test_ownership_resume_feedback_history_and_atomic_rollback(self):
        session = self.start()
        self.client.force_login(self.other)
        self.assertEqual(self.post(session, typed_answer='Magnetic Levitation').status_code, 404)
        self.client.force_login(self.user)
        with patch('scholars.services.record_review', side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError):
                answer_question(self.user, session.pk, 1, typed_answer='Magnetic Levitation')
        self.assertEqual(session.answered, 0)
        self.assertFalse(RewardEvent.objects.exists())
        self.assertContains(self.client.get(reverse('scholars:session', args=[session.pk])), 'Your answer')
        self.post(session, typed_answer='Magnetic Levitation')
        self.assertContains(self.client.get(reverse('scholars:feedback', args=[session.pk, 1])), 'Your answer:')
        self.assertContains(self.client.get(reverse('scholars:results', args=[session.pk])), 'Magnetic Levitation')
        self.assertContains(self.client.get(reverse('scholars:history')), 'Typed answers')
        self.assertEqual(self.client.get(reverse('scholars:session', args=[session.pk])).status_code, 302)

    def test_private_csrf_and_admin_feedback(self):
        from django.test import Client
        session = self.start()
        page = self.client.get(reverse('scholars:session', args=[session.pk]))
        self.assertIn('no-store', page['Cache-Control'])
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('scholars:answer', args=[session.pk, 1]), {'typed_answer': 'Magnetic Levitation'}).status_code, 403)
        self.post(session, typed_answer='Gravity', canonical_answer='Magnetic Levitation', is_correct='true', suppressed_answers=['Gravity'])
        self.assertFalse(session.items.get().is_correct)
        admin = User.objects.create_superuser('typed-admin', 'Typed-admin-password!')
        self.client.force_login(admin)
        page = self.client.get(reverse('scholars:results', args=[session.pk]))
        self.assertContains(page, 'Gravity')
        self.assertContains(page, 'Typed answers')
        self.assertEqual(self.post(session, typed_answer='Magnetic Levitation').status_code, 404)


class ConcurrentTypedTests(TransactionTestCase):
    def test_final_posts_race_and_prompt_final_race(self):
        with tempfile.TemporaryDirectory() as directory:
            qid, _ = typed_dataset(directory)
        user = User.objects.create_user('concurrent-typed', 'Typed-password!', must_change_password=False)
        topic = Question.objects.get(pk=qid).topic_id
        for answers in [('Magnetic Levitation', 'Gravity'), ('Magnet', 'Magnetic Levitation')]:
            session = start_session(user, uuid.uuid4(), {'topic': topic})
            barrier = Barrier(2)
            def submit(text):
                close_old_connections()
                try:
                    from django.test import Client
                    client = Client()
                    client.force_login(User.objects.get(pk=user.pk))
                    barrier.wait(timeout=10)
                    return client.post(reverse('scholars:answer', args=[session.pk, 1]), {'typed_answer': text}).status_code
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, answers))
            self.assertTrue(all(code in (200, 302) for code in results))
            self.assertEqual(session.answered, 1)
            self.assertEqual(RewardEvent.objects.filter(user=user).count(), 1)
            self.assertEqual(ReviewState.objects.filter(user=user).count(), 1)
            session.refresh_from_db()
            self.assertIsNotNone(session.completed_at)


class TypedMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_legacy_modes_and_answers_and_builds_banks(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone
        executor = MigrationExecutor(connection)
        old_target = [('scholars', '0003_reviewstate_and_more')]
        new_target = [('scholars', '0005_alter_practicesession_mode')]
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            user = User.objects.create_user('legacy-migration', 'Migration-password!', must_change_password=False)
            category = apps.get_model('scholars', 'Category').objects.create(pk='Science', payload={})
            topic = apps.get_model('scholars', 'Topic').objects.create(pk='legacy-topic', subject_id='subject', title='Legacy', category=category, payload={})
            question = apps.get_model('scholars', 'Question').objects.create(pk='legacy-question', topic=topic)
            revision = apps.get_model('scholars', 'QuestionRevision').objects.create(question=question, digest='legacy',
                payload={'correct_answer': 'Saturn’s rings', 'distractors': ['Rings of Saturn', 'Carbon-12', 'Carbon-14']}, context={})
            question.current_revision = revision
            question.save()
            OldSession = apps.get_model('scholars', 'PracticeSession')
            OldItem = apps.get_model('scholars', 'SessionQuestion')
            recognition = OldSession.objects.create(user_id=user.pk, request_key=uuid.uuid4())
            saved = OldItem.objects.create(session=recognition, position=1, revision=revision, choices=['Saturn’s rings', 'Rings of Saturn', 'Carbon-12', 'Carbon-14'], selected=0, is_correct=True, answered_at=timezone.now())
            recall = OldSession.objects.create(user_id=user.pk, request_key=uuid.uuid4(), mode='recall')
            revealed = OldItem.objects.create(session=recall, position=1, revision=revision, choices=saved.choices, revealed_at=timezone.now())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
        self.assertEqual(PracticeSession.objects.get(pk=recognition.pk).mode, 'recognition')
        self.assertEqual(PracticeSession.objects.get(pk=recall.pk).mode, 'recall')
        self.assertTrue(SessionQuestion.objects.get(pk=saved.pk).is_correct)
        self.assertIsNone(SessionQuestion.objects.get(pk=saved.pk).typed_answer)
        self.assertIsNotNone(SessionQuestion.objects.get(pk=revealed.pk).revealed_at)
        self.assertIsNone(SessionQuestion.objects.get(pk=revealed.pk).answered_at)
        bank = Category.objects.get(pk=category.pk).typed_bank
        self.assertEqual(set(bank.answers), set(saved.choices))
        self.assertEqual(PracticeSession().mode, 'typed')
