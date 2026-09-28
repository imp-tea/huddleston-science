import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse

from accounts.models import User
from .models import Category, Question, QuestionRevision, SavedQuiz, SavedQuizItem, Topic
from .question_authoring import edit_question
from .quiz_generation import Shortage, generate
from .quiz_lists import (StaleQuiz, add_question, create_quiz, quiz_items, ready_items, update_quiz)
from .quiz_views import PREVIEW_SALT
from .test_study import seed_study


class QuizListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = seed_study()
        cls.teacher = User.objects.create_user('quiz-teacher', 'Teacher-password!', is_admin=True, must_change_password=False)

    def setUp(self):
        self.client.force_login(self.teacher)
        self.quiz = create_quiz(self.teacher, 'Practice Night', uuid.uuid4())

    def add(self, qid='q-0-0', quiz=None):
        quiz = quiz or self.quiz
        quiz.refresh_from_db()
        q = Question.objects.get(pk=qid)
        return add_question(self.teacher, quiz.pk, quiz.edit_version, q.pk, q.current_revision_id)

    def change(self, action, **kwargs):
        self.quiz.refresh_from_db()
        return update_quiz(self.teacher, self.quiz.pk, self.quiz.edit_version, action, **kwargs)

    def test_create_validation_replay_and_permissions(self):
        key = uuid.uuid4()
        first = create_quiz(self.teacher, '  Test  ', key)
        self.assertEqual(first.name, 'Test')
        self.assertEqual(create_quiz(self.teacher, 'Other', key).pk, first.pk)
        for name in ['', '   ', 'x' * 161]:
            with self.assertRaises(ValidationError):
                create_quiz(self.teacher, name, uuid.uuid4())
        with self.assertRaises(PermissionDenied):
            create_quiz(self.student, 'No', uuid.uuid4())

    def test_add_is_unique_stale_safe_and_only_available_typed(self):
        self.add()
        quiz, added = self.add()
        self.assertFalse(added)
        self.assertEqual(quiz.items.count(), 1)
        with self.assertRaises(StaleQuiz):
            add_question(self.teacher, quiz.pk, 0, 'q-0-1', Question.objects.get(pk='q-0-1').current_revision_id)
        q = Question.objects.get(pk='q-0-1')
        for field, value in [('format', 'multiple_choice'), ('active', False)]:
            old = getattr(q, field)
            setattr(q, field, value)
            q.save()
            with self.assertRaises(StaleQuiz):
                self.add(q.pk)
            setattr(q, field, old)
            q.save()
        with self.assertRaises(StaleQuiz):
            add_question(self.teacher, quiz.pk, quiz.edit_version, q.pk, q.current_revision_id + 1000)
        Topic.objects.filter(pk=q.topic_id).update(active=False)
        with self.assertRaises(StaleQuiz):
            self.add(q.pk)

    def test_order_remove_duplicate_archive_restore_and_stale_tabs(self):
        for qid in ['q-0-0', 'q-0-1', 'q-0-2']:
            self.add(qid)
        items = list(self.quiz.items.all())
        self.change('up', item_id=items[2].pk)
        self.assertEqual(list(self.quiz.items.values_list('question_id', flat=True)), ['q-0-0', 'q-0-2', 'q-0-1'])
        self.change('down', item_id=items[0].pk)
        self.change('remove', item_id=items[2].pk)
        self.assertEqual(list(self.quiz.items.values_list('position', flat=True)), [1, 2])
        self.assertTrue(Question.objects.filter(pk='q-0-2').exists())
        with self.assertRaises(ValidationError):
            self.change('review', item_id=999999, revision_id=1)
        key = uuid.uuid4()
        copy = self.change('duplicate', name='Copy', request_key=key)
        self.assertEqual(list(copy.items.values_list('question_id', flat=True)), ['q-0-0', 'q-0-1'])
        self.assertEqual(self.change('duplicate', name='Copy again', request_key=key).pk, copy.pk)
        old_version = self.quiz.edit_version
        self.change('rename', name='Renamed')
        with self.assertRaises(StaleQuiz):
            update_quiz(self.teacher, self.quiz.pk, old_version, 'archive')
        self.change('archive')
        with self.assertRaises(ValidationError):
            self.add()
        self.change('restore')
        self.assertFalse(SavedQuiz.objects.get(pk=self.quiz.pk).archived)

    def test_review_tracks_exact_revision_and_duplicate_preserves_flags(self):
        self.add()
        item = self.quiz.items.get()
        q = Question.objects.get(pk=item.question_id)
        old = q.current_revision_id
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'A revised prompt?', 'correct_answer': 'New answer'})
        self.assertTrue(quiz_items(self.quiz)[0].changed)
        with self.assertRaises(ValidationError):
            ready_items(self.quiz)
        copy = self.change('duplicate', name='Unreviewed copy', request_key=uuid.uuid4())
        self.assertEqual(copy.items.get().reviewed_revision_id, old)
        with self.assertRaises(StaleQuiz):
            self.change('review', item_id=item.pk, revision_id=old)
        q.refresh_from_db()
        self.change('review', item_id=item.pk, revision_id=q.current_revision_id)
        self.assertFalse(quiz_items(self.quiz)[0].changed)
        self.assertEqual(len(ready_items(self.quiz)), 1)
        Category.objects.filter(pk=q.topic.category_id).update(active=False)
        self.assertFalse(quiz_items(self.quiz)[0].available)
        with self.assertRaises(ValidationError):
            ready_items(self.quiz)

    def test_duplicate_warning_uses_normalized_connected_groups(self):
        self.add('q-0-0')
        q = Question.objects.get(pk='q-1-0')
        payload = Question.objects.get(pk='q-0-0').current_revision.payload
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'Other prompt', 'correct_answer': payload['correct_answer']})
        self.add(q.pk)
        self.assertTrue(all(item.duplicate for item in quiz_items(self.quiz)))

    def test_database_constraints_and_bound(self):
        self.add()
        item = self.quiz.items.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedQuizItem.objects.create(quiz=self.quiz, question=item.question, reviewed_revision=item.reviewed_revision, position=2)
        with self.assertRaises(ValidationError):
            create_quiz(self.teacher, 'Too many', uuid.uuid4(), selected=[('same', item.reviewed_revision_id)] * 101)

    def test_routes_denied_to_students_and_anonymous_and_csrf_enforced(self):
        urls = [reverse('scholars:quiz_list'), reverse('scholars:quiz_random'), reverse('scholars:quiz_save_preview'),
                reverse('scholars:quiz_detail', args=[self.quiz.pk]), reverse('scholars:quiz_add', args=['q-0-0'])]
        self.client.force_login(self.student)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 403)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.teacher)
        self.assertEqual(csrf_client.post(urls[0], {'name': 'Bad', 'request_key': uuid.uuid4()}).status_code, 403)

    def test_ui_create_add_edit_return_and_archive(self):
        url = reverse('scholars:quiz_list')
        response = self.client.post(url, {'name': '<script>name</script>', 'request_key': uuid.uuid4()}, follow=True)
        self.assertContains(response, '&lt;script&gt;name&lt;/script&gt;')
        self.assertNotContains(response, '<script>name</script>')
        q = Question.objects.get(pk='q-0-0')
        response = self.client.post(reverse('scholars:quiz_add', args=[q.pk]),
            {'quiz_id': self.quiz.pk, 'version': 0, 'revision_id': q.current_revision_id}, follow=True)
        self.assertContains(response, 'Question added')
        response = self.client.post(reverse('scholars:question_edit', args=[q.pk]),
            {'question': 'Edited from quiz', 'correct_answer': 'New', 'version': q.edit_version, 'return_quiz': self.quiz.pk})
        self.assertRedirects(response, reverse('scholars:quiz_detail', args=[self.quiz.pk]))
        self.assertContains(self.client.get(response.url), 'Changed since you last reviewed it.')
        self.change('archive')
        self.assertNotContains(self.client.get(url), 'Practice Night')
        self.assertContains(self.client.get(url, {'archived': 1}), 'Practice Night')
        self.assertEqual(self.client.get(reverse('scholars:quiz_save_preview')).status_code, 405)

    def test_gets_leave_lists_unchanged_and_bad_actions_fail(self):
        self.add()
        before = list(SavedQuiz.objects.values()), list(SavedQuizItem.objects.values())
        for name, args in [('quiz_list', []), ('quiz_random', []), ('quiz_detail', [self.quiz.pk]), ('quiz_add', ['q-0-0'])]:
            self.assertEqual(self.client.get(reverse('scholars:' + name, args=args)).status_code, 200)
        self.assertEqual(before, (list(SavedQuiz.objects.values()), list(SavedQuizItem.objects.values())))
        self.assertEqual(self.client.post(reverse('scholars:quiz_detail', args=[self.quiz.pk]), {'action': 'unknown', 'version': 1}).status_code, 400)
        self.assertEqual(self.client.post(reverse('scholars:quiz_detail', args=[self.quiz.pk]), {'action': 'rename', 'version': 0, 'name': 'Oops'}).status_code, 409)

    def test_export_keeps_order_review_evidence_and_refuses_overwrite(self):
        import json
        import tempfile
        from io import StringIO
        from pathlib import Path
        from django.core.management import call_command
        from django.core.management.base import CommandError
        self.add()
        self.change('archive')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'quizzes.json'
            call_command('export_saved_quizzes', str(output), stdout=StringIO())
            row = json.loads(output.read_text())['quizzes'][0]
            self.assertTrue(row['archived'])
            self.assertEqual(row['items'][0]['question_id'], 'q-0-0')
            self.assertIn('payload', row['items'][0]['reviewed_revision'])
            self.assertNotIn('study-student', output.read_text())
            with self.assertRaises(CommandError):
                call_command('export_saved_quizzes', str(output), stdout=StringIO())

    def test_cross_list_items_and_student_owned_quiz_are_not_accessible(self):
        self.add()
        other = create_quiz(self.teacher, 'Other quiz', uuid.uuid4())
        with self.assertRaises(ValidationError):
            update_quiz(self.teacher, other.pk, 0, 'remove', item_id=self.quiz.items.get().pk)
        private = SavedQuiz.objects.create(owner=self.student, name='Wrong owner')
        url = reverse('scholars:quiz_detail', args=[private.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'version': 0, 'action': 'archive'}).status_code, 404)


class GenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = seed_study()
        cls.teacher = User.objects.create_user('generator', 'Teacher-password!', is_admin=True, must_change_password=False)
        Topic.objects.filter(pk__in=['topic-4', 'topic-5']).update(category_id='Literature')

    def setUp(self):
        self.client.force_login(self.teacher)

    def settings(self, **changes):
        return {'name': 'Generated practice', 'categories': ['Geography', 'Literature'], 'subcategories': [],
                'count': 8, 'max_per_topic': '', 'distribution': 'balanced', 'exclude_duplicates': True, **changes}

    def rate_questions(self):
        for index, level in enumerate(('easy', 'medium', 'hard')):
            Question.objects.filter(pk__endswith=f'-{index}').update(difficulty=level)

    def test_difficulty_center_edge_and_vertex(self):
        self.rate_questions()
        for weights, count, expected in [((1, 1, 1), 9, [3, 3, 3]),
                                          ((1, 1, 0), 8, [4, 4, 0]),
                                          ((0, 0, 1), 6, [0, 0, 6])]:
            for _ in range(5):
                preview = generate(self.settings(count=count, distribution='pool',
                    **dict(zip(('difficulty_easy', 'difficulty_medium', 'difficulty_hard'), weights))))
                self.assertEqual([row['actual'] for row in preview['difficulty_distribution']], expected)
                self.assertFalse(preview['difficulty_adjusted'])

    def test_difficulty_shortage_falls_back_without_changing_count_or_limits(self):
        self.rate_questions()
        preview = generate(self.settings(count=12, max_per_topic=2,
            difficulty_easy=0, difficulty_medium=0, difficulty_hard=100))
        self.assertEqual(len(preview['questions']), 12)
        self.assertTrue(preview['difficulty_adjusted'])
        self.assertEqual([row['actual'] for row in preview['distribution']], [8, 4])
        from collections import Counter
        self.assertLessEqual(max(Counter(q.topic_id for q in preview['questions']).values()), 2)
        self.assertEqual(len({q.pk for q in preview['questions']}), 12)
        Question.objects.update(difficulty='')
        preview = generate(self.settings())
        self.assertEqual(preview['difficulty_distribution'][-1], {'label': 'Not rated', 'target': 0, 'actual': 8})

    def test_difficulty_exchanges_preserve_duplicate_groups(self):
        self.rate_questions()
        a = Question.objects.get(pk='q-0-0')
        b = Question.objects.get(pk='q-1-2')
        edit_question(self.teacher, b.pk, b.edit_version,
                      {'question': 'Another prompt', 'correct_answer': a.current_revision.payload['correct_answer']})
        Question.objects.filter(pk=b.pk).update(difficulty='hard')
        from .question_selection import group_questions
        for _ in range(5):
            preview = generate(self.settings(count=10, distribution='pool', max_per_topic=2,
                difficulty_easy=0, difficulty_medium=0, difficulty_hard=1))
            selected = preview['questions']
            self.assertEqual(len(group_questions(selected, lambda q: q.current_revision.payload)), 10)

    def test_difficulty_rounding_validation_and_saved_settings(self):
        self.rate_questions()
        preview = generate(self.settings(count=1))
        self.assertEqual(sum(row['target'] for row in preview['difficulty_distribution']), 1)
        for values in [(0, 0, 0), (-1, 1, 1), (101, 1, 1), ('nan', 1, 1), ('inf', 1, 1), ('', 1, 1)]:
            with self.assertRaises(ValidationError):
                generate(self.settings(**dict(zip(('difficulty_easy', 'difficulty_medium', 'difficulty_hard'), values))))
        response = self.client.post(reverse('scholars:quiz_random'), self.settings(
            difficulty_easy=2, difficulty_medium=3, difficulty_hard=5))
        self.assertContains(response, 'Difficulty distribution')
        self.assertContains(response, 'subcategory-categories')
        self.assertEqual(response.context['form']['difficulty_hard'].value(), '5')
        data = signing.loads(response.context['token'], salt=PREVIEW_SALT)
        self.assertEqual(data['settings']['difficulty_hard'], 5)

    def test_balanced_exact_count_and_topic_limits(self):
        preview = generate(self.settings(max_per_topic=2))
        self.assertEqual(len(preview['questions']), 8)
        self.assertEqual([r['actual'] for r in preview['distribution']], [4, 4])
        self.assertFalse(preview['redistributed'])
        from collections import Counter
        self.assertLessEqual(max(Counter(q.topic_id for q in preview['questions']).values()), 2)

    def test_redistribution_and_precise_shortages(self):
        preview = generate(self.settings(count=12, max_per_topic=2))
        self.assertTrue(preview['redistributed'])
        self.assertEqual([r['actual'] for r in preview['distribution']], [8, 4])
        with self.assertRaises(Shortage) as caught:
            generate(self.settings(count=13, max_per_topic=2))
        self.assertEqual(caught.exception.available, 12)
        self.assertEqual(SavedQuiz.objects.count(), 0)

    def test_active_typed_filters_subcategories_and_validation(self):
        Question.objects.filter(pk='q-0-0').update(active=False)
        Question.objects.filter(pk='q-0-1').update(format='multiple_choice')
        result = generate(self.settings(categories=['Geography'], subcategories=['small'], count=1))
        self.assertEqual([q.pk for q in result['questions']], ['q-0-2'])
        for changes in [{'categories': []}, {'categories': ['missing']}, {'count': 101},
                        {'count': 0}, {'max_per_topic': 0}, {'categories': ['Literature'], 'subcategories': ['small']}]:
            with self.assertRaises(ValidationError):
                generate(self.settings(**changes))

    def test_duplicate_groups_and_matching_can_reassign_topics(self):
        # A shares an answer with B; only B's topic has another unique question.
        # Capacity is two with a one-per-topic cap, regardless of candidate order.
        Question.objects.exclude(pk__in=['q-0-0', 'q-1-0', 'q-1-1']).update(active=False)
        a = Question.objects.get(pk='q-0-0')
        b = Question.objects.get(pk='q-1-0')
        edit_question(self.teacher, b.pk, b.edit_version,
                      {'question': 'Different prompt', 'correct_answer': a.current_revision.payload['correct_answer']})
        for _ in range(8):
            result = generate(self.settings(categories=['Geography'], count=2, max_per_topic=1))
            self.assertEqual({q.pk for q in result['questions']}, {'q-0-0', 'q-1-1'})
        with self.assertRaises(Shortage) as caught:
            generate(self.settings(categories=['Geography'], count=3))
        self.assertEqual(caught.exception.available, 2)
        self.assertEqual(len(generate(self.settings(categories=['Geography'], count=3, exclude_duplicates=False))['questions']), 3)

    def preview(self):
        response = self.client.post(reverse('scholars:quiz_random'), self.settings())
        self.assertEqual(response.status_code, 200)
        return response.context['token'], response.context['preview']

    def test_explicit_preview_save_order_replay_and_tampering(self):
        token, preview = self.preview()
        self.assertEqual(SavedQuiz.objects.count(), 0)
        response = self.client.post(reverse('scholars:quiz_save_preview'), {'preview': token})
        self.assertEqual(response.status_code, 302)
        quiz = SavedQuiz.objects.get()
        self.assertEqual(list(quiz.items.values_list('question_id', flat=True)), [q.pk for q in preview['questions']])
        self.client.post(reverse('scholars:quiz_save_preview'), {'preview': token})
        self.assertEqual(SavedQuiz.objects.count(), 1)
        for bad in [token + 'bad', '', 'x' * 30001]:
            self.assertEqual(self.client.post(reverse('scholars:quiz_save_preview'), {'preview': bad}).status_code, 409)
        data = signing.loads(token, salt=PREVIEW_SALT)
        data['owner'] = str(self.student.pk)
        self.assertEqual(self.client.post(reverse('scholars:quiz_save_preview'),
            {'preview': signing.dumps(data, salt=PREVIEW_SALT)}).status_code, 409)

    def test_changed_preview_cannot_be_saved_or_silently_shortened(self):
        token, preview = self.preview()
        q = preview['questions'][0]
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'New prompt', 'correct_answer': 'New answer'})
        self.assertEqual(self.client.post(reverse('scholars:quiz_save_preview'), {'preview': token}).status_code, 409)
        self.assertEqual(SavedQuiz.objects.count(), 0)
        response = self.client.post(reverse('scholars:quiz_random'), self.settings(count=100))
        self.assertContains(response, 'Only 18 questions', status_code=400)

    def test_expired_preview_is_rejected(self):
        from unittest.mock import patch
        token, preview = self.preview()
        with patch('django.core.signing.time.time', return_value=9999999999):
            self.assertEqual(self.client.post(reverse('scholars:quiz_save_preview'), {'preview': token}).status_code, 409)
        self.assertEqual(SavedQuiz.objects.count(), 0)

    def test_pool_selection_and_duplicate_category_inputs(self):
        result = generate(self.settings(distribution='pool', categories=['Geography', 'Geography'], count=10))
        self.assertEqual(len(result['questions']), 10)
        self.assertEqual(len(result['distribution']), 1)
        self.assertEqual(len({q.pk for q in result['questions']}), 10)


class QuizConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_study()
        self.teacher = User.objects.create_user('concurrent-teacher', is_admin=True, must_change_password=False)
        self.quiz = create_quiz(self.teacher, 'Concurrent list', uuid.uuid4())

    def test_two_tabs_cannot_overwrite_order_or_add_twice(self):
        barrier = Barrier(2)
        def worker(qid):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.teacher.pk)
                q = Question.objects.get(pk=qid)
                barrier.wait(timeout=10)
                try:
                    add_question(user, self.quiz.pk, 0, q.pk, q.current_revision_id)
                    return 'saved'
                except StaleQuiz:
                    return 'stale'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, qid) for qid in ['q-0-0', 'q-0-1']]
            self.assertCountEqual([f.result(timeout=20) for f in futures], ['saved', 'stale'])
        self.assertEqual(self.quiz.items.count(), 1)
