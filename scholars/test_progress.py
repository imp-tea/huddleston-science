import copy
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from django.db import close_old_connections, connections
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from .catalog import topic_pool
from .importer import import_content
from .models import Category, PracticeSession, Question, QuestionRevision, RewardEvent, StudyPreferences, StudyState, Topic
from .progress import coverage, missed_topics, participation, personal_bests
from .services import answer_question, mark_studied, reveal_question, start_session
from .test_helpers import small_dataset

PASSWORD = 'Milestone-two-test-password!'


class ProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        cls.user = User.objects.create_user('learner', PASSWORD, must_change_password=False)
        cls.other = User.objects.create_user('other', PASSWORD, must_change_password=False)
        cls.admin = User.objects.create_superuser('teacher', PASSWORD)
        cls.single = next(t for t in Topic.objects.all() if Question.objects.filter(topic=t).count() == 1)

    def setUp(self):
        self.client.force_login(self.user)

    def session(self, scope=None, user=None):
        return start_session(user or self.user, uuid.uuid4(), scope if scope is not None else {'topic': self.single.pk})

    def answer(self, session, position=1, correct=True):
        item = session.items.select_related('revision').get(position=position)
        index = item.choices.index(item.revision.payload['correct_answer'])
        return answer_question(session.user, session.pk, position, index if correct else (index + 1) % 4)

    def test_opening_records_visit_without_studied_or_xp(self):
        url = reverse('scholars:topic', args=[self.single.pk])
        self.client.get(url)
        first = StudyState.objects.get(user=self.user, topic=self.single)
        self.assertIsNone(first.studied_at)
        self.client.get(url)
        state = StudyState.objects.get(user=self.user, topic=self.single)
        self.assertEqual(state.first_opened_at, first.first_opened_at)
        self.assertGreaterEqual(state.last_opened_at, first.last_opened_at)
        self.assertEqual(StudyState.objects.count(), 1)
        self.assertEqual(RewardEvent.objects.count(), 0)

    def test_explicit_study_marker_is_idempotent_and_can_be_undone(self):
        url = reverse('scholars:studied', args=[self.single.pk])
        self.client.post(url, {'studied': 'yes', 'user_id': str(self.other.pk), 'xp': 999})
        first = StudyState.objects.get(user=self.user, topic=self.single).studied_at
        self.client.post(url, {'studied': 'yes'})
        self.assertEqual(StudyState.objects.get(user=self.user, topic=self.single).studied_at, first)
        self.assertFalse(StudyState.objects.filter(user=self.other).exists())
        self.client.post(url, {'studied': 'no'})
        self.assertIsNone(StudyState.objects.get(user=self.user, topic=self.single).studied_at)
        self.assertEqual(RewardEvent.objects.count(), 0)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'studied': 'anything'}).status_code, 400)

    def test_marker_and_goal_require_csrf_authentication_and_password_change(self):
        paths = [reverse('scholars:studied', args=[self.single.pk]), reverse('scholars:goal')]
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        for path in paths:
            self.assertEqual(browser.post(path, {'studied': 'yes', 'weekly_goal': 20}).status_code, 403)
            self.assertEqual(Client().post(path).status_code, 302)
        self.user.must_change_password = True
        self.user.save(update_fields=['must_change_password'])
        for path in paths + [reverse('scholars:progress')]:
            self.assertRedirects(self.client.get(path), reverse('password_change'), fetch_redirect_response=False)

    def test_study_and_preferences_persist_across_rename_and_new_browser(self):
        mark_studied(self.user, self.single, True)
        self.client.post(reverse('scholars:goal'), {'weekly_goal': '20', 'user_id': self.other.pk})
        self.client.post(reverse('account'), {'username': 'renamed-learner'})
        self.client.post(reverse('logout'))
        device = Client()
        self.assertTrue(device.login(username='renamed-learner', password=PASSWORD))
        response = device.get(reverse('scholars:progress'))
        self.assertEqual(response.context['coverage']['total']['studied'], 1)
        self.assertEqual(response.context['participation']['weekly_goal'], 20)
        self.assertFalse(StudyPreferences.objects.filter(user=self.other).exists())

    def test_progress_is_private_and_admin_can_read_student_progress(self):
        mark_studied(self.other, self.single, True)
        self.answer(self.session(user=self.other))
        response = self.client.get(reverse('scholars:progress'), {'user': self.other.pk})
        self.assertEqual(response.context['coverage']['total']['studied'], 0)
        self.assertEqual(response.context['participation']['xp'], 0)
        url = reverse('scholars:student_progress', args=[self.other.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.context['coverage']['total']['studied'], 1)
        self.assertEqual(response.context['participation']['xp'], 2)
        self.assertNotContains(response, 'name="weekly_goal"')

    def test_library_filters_and_practice_pool_match_including_alias_search(self):
        data = copy.deepcopy(self.single.payload)
        data['aliases'].append('unique-library-alias')
        self.single.payload = data
        self.single.save(update_fields=['payload'])
        mark_studied(self.user, self.single, True)
        scope = {'q': 'unique-library-alias', 'status': 'studied', 'category': self.single.category_id}
        response = self.client.get(reverse('scholars:library'), scope)
        self.assertEqual([t.pk for t in response.context['topics']], [self.single.pk])
        session = self.session(scope)
        self.assertEqual(session.total, 1)
        self.assertEqual(session.items.get().revision.question.topic_id, self.single.pk)
        self.assertFalse(topic_pool(self.other, scope).exists())
        self.assertFalse(topic_pool(self.user, {**scope, 'status': 'practiced'}).exists())
        self.answer(session)
        self.assertTrue(topic_pool(self.user, {**scope, 'status': 'practiced'}).exists())

    def test_shared_subjects_do_not_share_study_or_practice_credit(self):
        other_topic = Topic.objects.exclude(pk=self.single.pk).first()
        other_topic.subject_id = self.single.subject_id
        other_topic.save(update_fields=['subject_id'])
        mark_studied(self.user, self.single, True)
        self.answer(self.session())
        topics = {t.pk: t for t in topic_pool(self.user, {})}
        self.assertTrue(topics[self.single.pk].studied)
        self.assertTrue(topics[self.single.pk].practiced)
        self.assertFalse(topics[other_topic.pk].studied)
        self.assertFalse(topics[other_topic.pk].practiced)

    def test_overlapping_subcategories_do_not_duplicate_category_accuracy(self):
        topic = next(t for t in Topic.objects.all() if len(t.payload['subcategory_ids']) > 1)
        self.answer(self.session({'topic': topic.pk}))
        overall = coverage(self.user)
        category = next(row for row in overall['rows'] if row['id'] == topic.category_id)
        self.assertEqual(overall['total']['answers'], 1)
        self.assertEqual(category['answers'], 1)
        self.assertEqual(category['practiced'], 1)
        subs = coverage(self.user, topic.category_id)
        self.assertEqual(subs['total']['answers'], 1)
        for row in subs['rows']:
            if row['id'] in topic.payload['subcategory_ids']:
                self.assertEqual(row['answers'], 1)

    def test_studied_practiced_and_accuracy_are_independent(self):
        self.client.get(reverse('scholars:topic', args=[self.single.pk]))
        self.answer(self.session(), correct=False)
        report = coverage(self.user)['total']
        self.assertEqual((report['studied'], report['practiced'], report['correct'], report['answers']), (0, 1, 0, 1))
        mark_studied(self.user, self.single, True)
        self.assertEqual(coverage(self.user)['total']['studied'], 1)
        self.assertEqual(participation(self.user)['xp'], 2)

    def test_accuracy_window_and_retired_coverage_are_honest(self):
        item = self.answer(self.session())
        type(item).objects.filter(pk=item.pk).update(answered_at=timezone.now() - timedelta(days=31))
        report = coverage(self.user)['total']
        self.assertEqual(report['answers'], 0)
        self.assertEqual(report['practiced'], 1)
        before = report['total']
        self.single.active = False
        self.single.save(update_fields=['active'])
        report = coverage(self.user)['total']
        self.assertEqual(report['total'], before - 1)
        self.assertEqual(report['practiced'], 0)

    def test_historical_accuracy_and_practice_do_not_move_to_a_new_category(self):
        self.answer(self.session())
        original_category = self.single.category_id
        new_category = Category.objects.exclude(pk=original_category).first()
        self.single.category = new_category
        self.single.save(update_fields=['category'])
        self.assertEqual(coverage(self.user, original_category)['total']['answers'], 1)
        moved = coverage(self.user, new_category.pk)['total']
        self.assertEqual(moved['answers'], 0)
        self.assertEqual(moved['practiced'], 0)

    def test_personal_bests_exclude_incomplete_and_compare_matching_sessions(self):
        unfinished = self.session()
        self.assertEqual(len(personal_bests(self.user)), 0)
        first = self.session()
        self.answer(first, correct=False)
        first.refresh_from_db()
        self.assertFalse(first.is_personal_best)
        second = self.session()
        self.answer(second, correct=True)
        second.refresh_from_db()
        self.assertTrue(second.is_personal_best)
        tied = self.session()
        self.answer(tied, correct=True)
        tied.refresh_from_db()
        self.assertFalse(tied.is_personal_best)
        self.assertEqual([s.pk for s in personal_bests(self.user)], [second.pk])
        self.assertIsNone(PracticeSession.objects.get(pk=unfinished.pk).completed_at)

    def test_smaller_quizzes_and_different_modes_keep_separate_bests(self):
        small = self.session()
        self.answer(small)
        large = self.session({})
        for position in range(1, 11):
            self.answer(large, position, correct=position != 10)
        mode = self.session()
        # Recall never enters scored records, even with a reused comparison key.
        mode.mode = 'recall'
        mode.save(update_fields=['mode'])
        reveal_question(self.user, mode.pk, 1)
        answer_question(self.user, mode.pk, 1, self_assessment=True)
        self.assertEqual({(s.mode, s.score, s.total) for s in personal_bests(self.user)},
                         {('recognition', 1, 1), ('recognition', 9, 10)})
        large.refresh_from_db()
        self.assertFalse(large.is_personal_best)

    def test_changed_content_bank_starts_a_separate_record(self):
        first = self.session()
        self.answer(first, correct=False)
        question = Question.objects.get(topic=self.single)
        revision = question.current_revision
        payload = copy.deepcopy(revision.payload)
        payload['explanation'] = 'A revised explanation.'
        question.current_revision = QuestionRevision.objects.create(question=question, payload=payload, context=revision.context, digest='f' * 64)
        question.save(update_fields=['current_revision'])
        second = self.session()
        self.answer(second)
        second.refresh_from_db()
        self.assertNotEqual(first.comparison_key, second.comparison_key)
        self.assertFalse(second.is_personal_best)
        self.assertFalse(second.items.get().corrected_previous_miss)
        self.assertEqual(len(personal_bests(self.user)), 2)

    def test_legacy_results_remain_readable_without_inventing_a_comparison_bank(self):
        session = self.session()
        self.answer(session)
        PracticeSession.objects.filter(pk=session.pk).update(comparison_key='', scope_label='')
        response = self.client.get(reverse('scholars:results', args=[session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['best'])
        self.assertEqual(len(personal_bests(self.user)), 0)

    def test_previous_miss_feedback_and_revisit_list_use_latest_revision_answer(self):
        self.answer(self.session(), correct=False)
        self.assertIn(self.single, list(missed_topics(self.user)))
        corrected = self.answer(self.session())
        self.assertTrue(corrected.corrected_previous_miss)
        self.assertNotIn(self.single, list(missed_topics(self.user)))
        self.assertFalse(self.answer(self.session()).corrected_previous_miss)

    def test_rewards_ignore_correctness_and_same_day_retries(self):
        first = self.session()
        item = self.answer(first, correct=False)
        self.assertEqual(RewardEvent.objects.get(answer=item).points, 2)
        self.answer(first)
        self.answer(self.session())
        self.assertEqual(RewardEvent.objects.count(), 1)
        self.assertEqual(participation(self.user)['xp'], 2)
        self.assertEqual(participation(self.user)['weekly_count'], 1)

    def test_later_day_reward_is_reduced_and_week_boundary_is_local(self):
        tz = timezone.get_current_timezone()
        sunday = timezone.make_aware(datetime(2026, 9, 20, 23, 55), tz)
        monday = sunday + timedelta(minutes=10)
        first, second, third = self.session(), self.session(), self.session()
        with patch('django.utils.timezone.now', return_value=sunday):
            self.answer(first)
            self.assertEqual(participation(self.user)['weekly_count'], 1)
        with patch('django.utils.timezone.now', return_value=monday):
            self.assertEqual(participation(self.user)['weekly_count'], 0)
            self.answer(second)
            self.answer(third)
            self.assertEqual(participation(self.user)['weekly_count'], 1)
            self.assertEqual(participation(self.user)['xp'], 3)
        self.assertCountEqual(RewardEvent.objects.values_list('points', flat=True), [2, 1])

    def test_reward_failure_rolls_back_answer_and_completion(self):
        session = self.session()
        with patch('scholars.services.RewardEvent.objects.create', side_effect=RuntimeError('write failure')):
            with self.assertRaises(RuntimeError):
                self.answer(session)
        item = session.items.get()
        session.refresh_from_db()
        self.assertIsNone(item.selected)
        self.assertIsNone(item.answered_at)
        self.assertIsNone(session.completed_at)
        self.assertEqual(RewardEvent.objects.count(), 0)

    def test_goal_validation_off_setting_and_no_client_supplied_rewards(self):
        self.assertEqual(participation(self.user)['weekly_goal'], 0)
        for value in ['-1', '101', '999', 'words']:
            self.assertEqual(self.client.post(reverse('scholars:goal'), {'weekly_goal': value}).status_code, 400)
        self.client.post(reverse('scholars:goal'), {'weekly_goal': '30', 'xp': '999'})
        self.assertEqual(participation(self.user)['weekly_goal'], 30)
        self.assertEqual(participation(self.user)['xp'], 0)
        self.client.post(reverse('scholars:goal'), {'weekly_goal': '0'})
        self.assertEqual(participation(self.user)['weekly_goal'], 0)

    def test_progress_with_records_and_pagination_renders(self):
        mark_studied(self.user, self.single, True)
        self.answer(self.session())
        response = self.client.get(reverse('scholars:progress'))
        self.assertContains(response, 'Personal bests')
        self.assertContains(response, 'Recently opened')
        self.assertContains(response, self.single.title)
        response = self.client.get(reverse('scholars:progress'), {'category': self.single.category_id, 'page': 99})
        self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse('scholars:dashboard')), '2 XP')

    def test_repeat_import_preserves_study_markers_rewards_and_personal_bests(self):
        mark_studied(self.user, self.single, True)
        session = self.session()
        answer = self.answer(session)
        before = StudyState.objects.get(user=self.user, topic=self.single).studied_at
        key = session.comparison_key
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        session.refresh_from_db()
        self.assertEqual(StudyState.objects.get(user=self.user, topic=self.single).studied_at, before)
        self.assertEqual(RewardEvent.objects.get(answer=answer).points, 2)
        self.assertEqual(personal_bests(self.user).get().pk, session.pk)
        self.assertEqual(self.session().comparison_key, key)

    def test_inflight_disabled_account_cannot_record_answer_or_reward(self):
        session = self.session()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.answer(session)
        self.assertEqual(session.answered, 0)
        self.assertEqual(RewardEvent.objects.count(), 0)


class ConcurrentRewardsTests(TransactionTestCase):
    def test_simultaneous_answers_in_different_sessions_award_once(self):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        user = User.objects.create_user('parallel-learner', PASSWORD, must_change_password=False)
        topic = next(t for t in Topic.objects.all() if Question.objects.filter(topic=t).count() == 1)
        sessions = [start_session(user, uuid.uuid4(), {'topic': topic.pk}) for _ in range(2)]
        barrier = Barrier(2)
        def work(session):
            close_old_connections()
            try:
                actor = User.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                return answer_question(actor, session.pk, 1, 0).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(work, sessions))
        self.assertEqual(len(set(answers)), 2)
        self.assertEqual(RewardEvent.objects.filter(user=user).count(), 1)
        self.assertEqual(participation(user)['xp'], 2)
        self.assertEqual(PracticeSession.objects.filter(user=user, completed_at__isnull=False).count(), 2)
