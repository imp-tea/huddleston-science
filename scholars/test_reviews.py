import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from .importer import import_content
from .models import PracticeSession, Question, QuestionRevision, ReviewState, RewardEvent, SessionQuestion, Topic
from .progress import coverage, personal_bests
from .reviews import current_reviews, review_summary, select_questions
from .services import abandon_session, answer_question, reveal_question, start_session, rng
from .test_helpers import small_dataset


class ReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        cls.user = User.objects.create_user('reviews', 'Review-test-password!', must_change_password=False)
        cls.other = User.objects.create_user('other-review', 'Review-test-password!', must_change_password=False)
        cls.admin = User.objects.create_superuser('review-teacher', 'Admin-test-password!')
        cls.topic = next(t for t in Topic.objects.all() if Question.objects.filter(topic=t).count() == 1)
        cls.day = timezone.make_aware(datetime(2026, 9, 21, 12))

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, mode='recognition', selection='random', scope=None):
        return start_session(self.user, uuid.uuid4(), {'topic': self.topic.pk} if scope is None else scope, mode, selection)

    def answer(self, successful=True, day=0, mode='recognition', session=None):
        with patch('django.utils.timezone.now', return_value=self.day + timedelta(days=day)):
            session = session or self.start(mode)
            item = session.items.select_related('revision').get(position=1)
            if mode == 'recall':
                reveal_question(self.user, session.pk, 1)
                return answer_question(self.user, session.pk, 1, self_assessment=successful)
            correct = item.choices.index(item.revision.payload['correct_answer'])
            return answer_question(self.user, session.pk, 1, correct if successful else (correct + 1) % 4)

    def test_exact_intervals_and_readiness(self):
        for day, streak, interval in [(0, 1, 1), (1, 2, 3), (4, 3, 7), (11, 4, 14), (25, 5, 30), (55, 5, 30)]:
            item = self.answer(day=day)
            state = ReviewState.objects.get(user=self.user)
            self.assertEqual(state.successes, streak)
            self.assertEqual(state.due_on, (self.day + timedelta(days=day + interval)).date())
            self.assertEqual(item.attempt_kind, 'first' if day == 0 else 'review')
            self.assertEqual(item.review_due_on, state.due_on)
        summary = review_summary(self.user)[0]
        self.assertEqual(summary['total']['remembered'], 1)

    def test_same_day_retry_and_early_success_do_not_extend(self):
        first = self.answer()
        retry = self.answer()
        self.assertEqual(retry.attempt_kind, 'same_day')
        self.assertEqual(retry.review_due_on, first.review_due_on)
        due = self.answer(day=1)
        early = self.answer(day=2)
        self.assertEqual(early.attempt_kind, 'early')
        self.assertEqual(early.review_successes, 2)
        self.assertEqual(early.review_due_on, due.review_due_on)

    def test_failure_resets_and_retry_cannot_erase_failure(self):
        self.answer()
        self.answer(day=1)
        failure = self.answer(False, day=2)
        retry = self.answer(day=2)
        self.assertEqual(failure.review_successes, 0)
        self.assertEqual(retry.review_successes, 0)
        self.assertEqual(retry.review_due_on, (self.day + timedelta(days=3)).date())
        self.assertEqual(self.answer(day=3).review_successes, 1)

    def test_calendar_boundary_and_dst(self):
        before = timezone.make_aware(datetime(2026, 10, 31, 23, 59))
        self.day = before
        self.answer()
        self.day = timezone.make_aware(datetime(2026, 11, 1, 0, 1))
        item = self.answer()
        self.assertEqual(item.review_successes, 2)
        self.assertEqual(item.review_due_on.isoformat(), '2026-11-04')

    def test_reveal_is_persistent_idempotent_and_awards_nothing(self):
        session = self.start('recall')
        item = session.items.get()
        first = reveal_question(self.user, session.pk, 1)
        second = reveal_question(self.user, session.pk, 1)
        self.assertEqual(first.revealed_at, second.revealed_at)
        self.assertEqual(session.answered, 0)
        self.assertFalse(RewardEvent.objects.exists())
        self.assertFalse(ReviewState.objects.exists())
        device = Client()
        device.force_login(self.user)
        response = device.get(reverse('scholars:session', args=[session.pk]))
        self.assertContains(response, 'Save assessment')
        self.assertContains(response, item.revision.payload['correct_answer'])

    def test_recall_hides_choices_and_answer_until_reveal(self):
        session = self.start('recall')
        response = self.client.get(reverse('scholars:session', args=[session.pk]))
        self.assertContains(response, 'Reveal answer')
        self.assertNotContains(response, 'name="selected"')
        self.assertNotContains(response, 'Save assessment')
        self.assertNotContains(response, session.items.get().revision.payload['explanation'])
        self.assertEqual(self.client.get(reverse('scholars:feedback', args=[session.pk, 1])).status_code, 404)
        self.assertEqual(self.client.get(reverse('scholars:evidence', args=[session.pk, 1])).status_code, 404)

    def test_assessment_requires_reveal_and_cannot_score_objective_answer(self):
        session = self.start('recall')
        with self.assertRaises(ValidationError):
            answer_question(self.user, session.pk, 1, self_assessment=True)
        reveal_question(self.user, session.pk, 1)
        with self.assertRaises(ValidationError):
            answer_question(self.user, session.pk, 1, selected=0)
        with self.assertRaises(ValidationError):
            answer_question(self.user, session.pk, 1, self_assessment='yes')
        answer = answer_question(self.user, session.pk, 1, self_assessment=True)
        self.assertIsNone(answer.is_correct)
        self.assertIsNone(answer.selected)
        self.assertTrue(answer.self_assessment)
        self.assertEqual(session.score, 0)

    def test_recall_never_counts_as_accuracy_or_personal_best(self):
        self.answer(False)
        self.answer(mode='recall')
        report = coverage(self.user)['total']
        self.assertEqual((report['answers'], report['correct']), (1, 0))
        self.assertEqual(personal_bests(self.user).count(), 1)
        self.assertEqual(personal_bests(self.user).get().mode, 'recognition')
        session = PracticeSession.objects.get(mode='recall')
        self.assertFalse(session.is_personal_best)
        self.assertEqual(session.comparison_key, '')
        response = self.client.get(reverse('scholars:results', args=[session.pk]))
        self.assertContains(response, '1 / 1 self-assessed remembered')
        self.assertNotContains(response, 'Personal best:')
        self.assertNotContains(response, 'Your answer:')

    def test_modes_have_independent_evidence_but_share_xp_limit(self):
        self.answer()
        self.answer(mode='recall')
        self.assertEqual(ReviewState.objects.count(), 2)
        self.assertEqual(RewardEvent.objects.count(), 1)
        self.assertEqual(set(ReviewState.objects.values_list('successes', flat=True)), {1})
        self.answer(day=1, mode='recall')
        self.assertEqual(ReviewState.objects.get(mode='recognition').successes, 1)
        self.assertEqual(ReviewState.objects.get(mode='recall').successes, 2)

    def test_duplicate_assessment_does_not_change_history_or_rewards(self):
        answer = self.answer(mode='recall')
        second = answer_question(self.user, answer.session_id, 1, self_assessment=False)
        self.assertEqual(answer.pk, second.pk)
        self.assertTrue(second.self_assessment)
        self.assertEqual(ReviewState.objects.get().successes, 1)
        self.assertEqual(RewardEvent.objects.count(), 1)

    def test_due_selection_is_scoped_and_empty_is_actionable(self):
        self.answer()
        with patch('django.utils.timezone.now', return_value=self.day):
            with self.assertRaisesMessage(ValidationError, 'No reviews are due'):
                self.start(selection='review')
        with patch('django.utils.timezone.now', return_value=self.day + timedelta(days=1)):
            session = self.start(selection='review')
            self.assertEqual(session.total, 1)
            self.assertEqual(session.items.get().revision.question.topic_id, self.topic.pk)
            self.assertEqual(session.comparison_key, '')
            with self.assertRaises(ValidationError):
                self.start('recall', 'review')

    def test_personalized_selection_has_due_weak_new_and_unique_questions(self):
        bank = list(Question.objects.order_by('id').values_list('id', 'current_revision_id'))
        today = timezone.localdate()
        for i, (qid, rid) in enumerate(bank[:7]):
            ReviewState.objects.create(user=self.user, revision_id=rid, mode='recognition', successes=0,
                last_evidence_on=today, last_attempt_at=timezone.now(), due_on=today + timedelta(days=-1 if i < 4 else 1))
        chosen = select_questions(bank, self.user, 'recognition', 'personalized', rng)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(len(set(chosen)), 10)
        self.assertTrue({qid for qid, _ in bank[:7]}.issubset(chosen))
        self.assertEqual(len(set(chosen) & {qid for qid, _ in bank[7:]}), 3)
        session = self.start(selection='personalized', scope={})
        self.assertEqual(session.comparison_key, '')

    def test_changed_revision_starts_fresh_and_old_session_keeps_evidence(self):
        first = self.answer()
        waiting = self.start()
        question = Question.objects.get(topic=self.topic)
        payload = copy.deepcopy(question.current_revision.payload)
        payload['explanation'] += ' Updated context.'
        revision = QuestionRevision.objects.create(question=question, digest='a' * 64, payload=payload, context=question.current_revision.context)
        question.current_revision = revision
        question.save(update_fields=['current_revision'])
        old = self.answer(day=1, session=waiting)
        self.assertEqual(old.attempt_kind, 'historical')
        self.assertIsNone(old.review_due_on)
        self.assertFalse(current_reviews(self.user).exists())
        current = self.answer(day=1)
        self.assertEqual(current.review_successes, 1)
        self.assertEqual(ReviewState.objects.count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.review_successes, 1)

    def test_retirement_and_overlap_do_not_inflate_readiness(self):
        topic = next(t for t in Topic.objects.all() if len(t.payload['subcategory_ids']) > 1)
        self.topic = topic
        self.answer()
        with patch('django.utils.timezone.now', return_value=self.day + timedelta(days=1)):
            summary = review_summary(self.user)[0]
            self.assertEqual(summary['total']['due'], 1)
            self.assertEqual(summary['rows'][topic.category_id]['due'], 1)
            subs = review_summary(self.user, topic.category_id)[0]
            for sub in topic.payload['subcategory_ids']:
                self.assertEqual(subs['rows'][sub]['due'], 1)
            Topic.objects.filter(pk=topic.pk).update(active=False)
            self.assertEqual(review_summary(self.user)[0]['total']['due'], 0)
        self.assertEqual(ReviewState.objects.count(), 1)

    def test_repeat_import_preserves_review_evidence(self):
        self.answer()
        state = ReviewState.objects.get()
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        self.assertEqual(current_reviews(self.user).get().pk, state.pk)
        self.assertEqual(current_reviews(self.user).get().due_on, state.due_on)

    def test_abandoned_sessions_keep_answers_and_cannot_resume_or_score(self):
        session = self.start(scope={})
        self.answer(session=session)
        ended = abandon_session(self.user, session.pk)
        again = abandon_session(self.user, session.pk)
        self.assertEqual(ended.abandoned_at, again.abandoned_at)
        with self.assertRaises(ValidationError):
            answer_question(self.user, session.pk, 2, 0)
        self.assertIsNone(ended.completed_at)
        self.assertEqual(ended.answered, 1)
        self.assertEqual(personal_bests(self.user).count(), 0)
        self.assertRedirects(self.client.get(reverse('scholars:session', args=[session.pk])), reverse('scholars:results', args=[session.pk]))
        self.assertContains(self.client.get(reverse('scholars:results', args=[session.pk])), 'Session ended')

    def test_reveal_rejects_out_of_order_and_wrong_mode(self):
        session = self.start('recall', scope={})
        with self.assertRaises(ValidationError):
            reveal_question(self.user, session.pk, 2)
        with self.assertRaises(ValidationError):
            reveal_question(self.user, self.start().pk, 1)

    def test_new_writes_require_owner_csrf_post_and_ignore_client_totals(self):
        session = self.start('recall')
        urls = [reverse('scholars:reveal', args=[session.pk, 1]), reverse('scholars:abandon', args=[session.pk])]
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(csrf.post(url).status_code, 403)
            self.client.force_login(self.other)
            self.assertEqual(self.client.post(url).status_code, 404)
            self.client.force_login(self.user)
        self.client.post(urls[0])
        response = self.client.post(reverse('scholars:answer', args=[session.pk, 1]), {
            'self_assessment': 'remembered', 'selected': 0, 'is_correct': True, 'xp': 1000, 'user': self.other.pk})
        self.assertEqual(response.status_code, 302)
        item = session.items.get()
        self.assertIsNone(item.is_correct)
        self.assertTrue(item.self_assessment)
        self.assertFalse(ReviewState.objects.filter(user=self.other).exists())
        self.assertEqual(RewardEvent.objects.get().points, 2)

    def test_review_progress_is_private_and_admin_read_only(self):
        self.answer(mode='recall')
        self.client.force_login(self.other)
        response = self.client.get(reverse('scholars:progress'), {'user': self.user.pk})
        self.assertEqual(response.context['reviews'][1]['total']['practicing'], 0)
        admin_url = reverse('scholars:student_progress', args=[self.user.pk])
        self.assertEqual(self.client.get(admin_url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(admin_url)
        self.assertEqual(response.context['reviews'][1]['total']['practicing'], 1)
        self.assertNotContains(response, 'name="weekly_goal"')

    def test_answer_review_and_xp_roll_back_together(self):
        session = self.start()
        with patch('scholars.services.RewardEvent.objects.create', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.answer(session=session)
        self.assertFalse(ReviewState.objects.exists())
        self.assertEqual(session.answered, 0)

    def test_database_rejects_mixed_scoring_fields(self):
        item = self.answer(mode='recall')
        with self.assertRaises(IntegrityError), transaction.atomic():
            SessionQuestion.objects.filter(pk=item.pk).update(is_correct=True)

    def test_invalid_mode_and_selection_rejected_without_session(self):
        for mode, selection in [('typed', 'random'), ('recognition', 'untrusted')]:
            with self.assertRaises(ValidationError):
                self.start(mode, selection)
        self.assertFalse(PracticeSession.objects.exists())


class ConcurrentRecallTests(TransactionTestCase):
    def test_two_devices_cannot_advance_review_or_reward_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        user = User.objects.create_user('concurrent-recall', 'Recall-password!', must_change_password=False)
        topic = next(t for t in Topic.objects.all() if Question.objects.filter(topic=t).count() == 1)
        sessions = [start_session(user, uuid.uuid4(), {'topic': topic.pk}, 'recall') for _ in range(2)]
        for session in sessions:
            reveal_question(user, session.pk, 1)
        barrier = Barrier(2)
        def work(session):
            close_old_connections()
            try:
                actor = User.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                return answer_question(actor, session.pk, 1, self_assessment=True).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(work, sessions))
        self.assertEqual(len(set(answers)), 2)
        self.assertEqual(ReviewState.objects.get(user=user).successes, 1)
        self.assertEqual(RewardEvent.objects.filter(user=user).count(), 1)
        self.assertEqual(PracticeSession.objects.filter(user=user, completed_at__isnull=False).count(), 2)
        self.assertEqual(set(SessionQuestion.objects.values_list('attempt_kind', flat=True)), {'first', 'same_day'})
