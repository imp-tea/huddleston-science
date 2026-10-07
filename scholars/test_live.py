import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections, IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import set_student_active
from . import live
from .models import (LiveConnection, LiveParticipant, LiveQuiz, LiveQuizQuestion,
                     LiveResponse, Question, StudyActivity, TopicCompletion)
from .question_authoring import edit_question
from .quiz_lists import add_question, create_quiz, update_quiz
from .test_study import seed_study


def setup_game():
    student = seed_study()
    teacher = User.objects.create_user('live-teacher', 'Teacher-password!', is_admin=True, must_change_password=False)
    quiz = create_quiz(teacher, 'Friday quiz', uuid.uuid4())
    for i in range(3):
        q = Question.objects.get(pk=f'q-0-{i}')
        quiz, _ = add_question(teacher, quiz.pk, quiz.edit_version, q.pk, q.current_revision_id)
    game = live.host(teacher, quiz.pk, quiz.edit_version, uuid.uuid4())
    return teacher, student, quiz, game


class LiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher, cls.student, cls.quiz, cls.game = setup_game()
        cls.other = User.objects.create_user('other-player', must_change_password=False)

    def setUp(self):
        self.client.force_login(self.teacher)

    def connect(self, user=None):
        key = uuid.uuid4()
        live.join(user or self.student, self.game.pk, key)
        return key

    @patch('scholars.live.REVEAL_SECONDS', 0)
    def control(self, action, key=None):
        self.game.refresh_from_db()
        self.game = live.transition(self.teacher, self.game.pk, action, self.game.version, self.game.position, key or uuid.uuid4())
        return self.game

    def start(self):
        self.connect()
        return self.control('start')

    def url(self, name, *args):
        return reverse('scholars:live_' + name, args=[self.game.pk, *args])

    def state(self, user=None):
        self.client.force_login(user or self.student)
        response = self.client.get(self.url('state'))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_timed_curve_grace_rounding_and_floor(self):
        from .live_scoring import grace_seconds, points_available
        for prompt, grace in [('', 5), ('x' * 100, 11.5), ('x' * 200, 18), ('A 🐈?', 5.26)]:
            with self.subTest(prompt=prompt):
                self.assertAlmostEqual(grace_seconds(prompt), grace)
                self.assertEqual(points_available(0, prompt), 100)
                self.assertEqual(points_available(grace - .1, prompt), 100)
                for after_grace, expected in [(0, 100), (1, 90), (3, 73), (7.5, 44),
                                               (10, 33), (15, 25), (100, 25)]:
                    self.assertEqual(points_available(grace + after_grace, prompt), expected)
                scores = [points_available(t / 10, prompt) for t in range(1000)]
                self.assertEqual(scores, sorted(scores, reverse=True))

    def test_correct_answer_keeps_full_points_through_reading_grace(self):
        from .live_scoring import grace_seconds
        self.start()
        start = live.ready(self.student, self.game.pk, 1)
        prompt = self.game.questions.get(position=1).revision.payload['question']
        with patch('scholars.live.timezone.now', return_value=start + timedelta(seconds=grace_seconds(prompt))):
            live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0')
            self.assertEqual(self.state()['response']['points'], 100)

    def test_reveal_blocks_next_prompt_answers_and_controls_until_deadline(self):
        self.start()
        self.game = live.transition(self.teacher, self.game.pk, 'next', 1, 1, uuid.uuid4())
        state = self.state()
        self.assertTrue(state['revealing'])
        self.assertEqual(state['reveal']['answer'], 'Canonical 0 number 0')
        self.assertNotIn('question', state)
        self.assertNotIn('Prompt 0 / 1?', json.dumps(state))
        self.assertEqual(self.client.get(self.url('suggestions', 2)).status_code, 409)
        with self.assertRaises(live.LiveConflict):
            live.answer(self.student, self.game.pk, 2, 'Canonical 0 number 1')
        with self.assertRaises(live.LiveConflict):
            live.ready(self.student, self.game.pk, 2)
        with self.assertRaises(live.LiveConflict):
            live.transition(self.teacher, self.game.pk, 'next', 2, 2, uuid.uuid4())
        opens = self.game.questions.get(position=2).opened_at
        closes = self.game.questions.get(position=1).closed_at
        self.assertEqual((opens - closes).total_seconds(), 4)
        with patch('scholars.live.timezone.now', return_value=opens):
            state = self.state()
            self.assertFalse(state['revealing'])
            self.assertNotIn('reveal', state)
            self.assertNotIn('prompt', state['question'])
            self.assertEqual(live.ready(self.student, self.game.pk, 2), opens)
            self.assertEqual(self.state()['question']['prompt'], 'Prompt 0 / 1?')
            self.assertEqual(live.answer(self.student, self.game.pk, 2, 'Canonical 0 number 1'), 'correct')
            self.assertEqual(self.state()['response']['points'], 100)

    def test_clock_persists_across_tabs_refresh_and_prompt_with_server_scoring(self):
        self.start()
        start = live.ready(self.student, self.game.pk, 1)
        from .live_scoring import grace_seconds
        grace = grace_seconds(self.game.questions.get(position=1).revision.payload['question'])
        with patch('scholars.live.timezone.now', return_value=start + timedelta(seconds=grace + 3)):
            self.connect()
            self.assertEqual(live.ready(self.student, self.game.pk, 1), start)
            self.assertEqual(self.state()['started_at'], start.isoformat())
            with patch('scholars.live.grade', return_value='prompt'):
                self.assertEqual(live.answer(self.student, self.game.pk, 1, 'partial'), 'prompt')
            self.assertEqual(live.ready(self.student, self.game.pk, 1), start)
            response = self.client.post(self.url('answer'), {'position': 1, 'action': 'answer',
                'typed_answer': 'Canonical 0 number 0', 'points': 100, 'elapsed': 0, 'grace_seconds': 9999})
            self.assertEqual(response.json()['points'], 73)
        with patch('scholars.live.timezone.now', return_value=start + timedelta(seconds=15)):
            self.assertEqual(live.answer(self.student, self.game.pk, 1, 'wrong'), 'correct')
            state = self.state()
            self.assertEqual(state['response']['points'], 73)
            self.assertEqual(state['leaderboard'][0]['points'], 73)
            self.assertEqual(LiveResponse.objects.count(), 1)

    def test_late_arrival_during_reveal_joins_current_question_with_fresh_clock(self):
        self.start()
        self.game = live.transition(self.teacher, self.game.pk, 'next', 1, 1, uuid.uuid4())
        self.connect(self.other)
        player = self.game.participants.get(user=self.other)
        self.assertFalse(player.responses.exists())
        self.assertTrue(self.state(self.other)['revealing'])
        opens = self.game.questions.get(position=2).opened_at
        with patch('scholars.live.timezone.now', return_value=opens + timedelta(seconds=5)):
            start = live.ready(self.other, self.game.pk, 2)
            self.assertEqual(start, opens + timedelta(seconds=5))
            live.answer(self.other, self.game.pk, 2, 'Canonical 0 number 1')
            self.control('end')
        from .live_reports import report
        result = report(self.game, player)
        self.assertEqual(result['personal_points'], 100)
        self.assertEqual(result['summary']['late_joiners'], 1)
        self.assertEqual(result['summary']['removed_players'], 0)
        self.assertEqual(result['leaderboard'][0]['name'], self.other.username)
        self.assertEqual(self.state(self.other)['summary']['points'], 100)

    def test_ready_endpoint_requires_connected_player_post_and_open_question(self):
        self.start()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('ready')).status_code, 405)
        self.assertNotIn('prompt', self.state()['question'])
        response = self.client.post(self.url('ready'), {'position': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['question']['prompt'], 'Prompt 0 / 0?')
        self.assertEqual(response.json()['started_at'], self.state()['started_at'])
        self.assertAlmostEqual(response.json()['question']['grace_seconds'], 5 + .065 * len('Prompt 0 / 0?'))
        self.assertEqual(response.json()['question']['grace_seconds'], self.state()['question']['grace_seconds'])
        self.assertEqual(self.client.post(self.url('ready'), {'position': 2}).status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url('ready'), {'position': 1}).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url('ready'), {'position': 1}).status_code, 404)

    def test_wrong_skipped_unanswered_and_legacy_quizzes_do_not_earn_points(self):
        self.connect(self.other)
        self.start()
        live.ready(self.student, self.game.pk, 1)
        live.answer(self.student, self.game.pk, 1, 'Totally wrong')
        live.answer(self.other, self.game.pk, 1, skip=True)
        self.control('next')
        self.control('end')
        self.assertEqual(set(LiveResponse.objects.values_list('points', flat=True)), {0})
        self.assertTrue(all(p['points'] == 0 for p in self.state()['leaderboard']))
        self.game = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        LiveQuiz.objects.filter(pk=self.game.pk).update(timed_scoring=False)
        self.start()
        live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0')
        self.assertIsNone(self.state()['response']['points'])

    def test_host_snapshots_title_order_bank_and_revision(self):
        question = self.game.questions.first()
        before = (question.revision_id, question.answer_bank_id)
        q = Question.objects.get(pk='q-0-0')
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'Future prompt', 'correct_answer': 'Future answer'})
        update_quiz(self.teacher, self.quiz.pk, self.quiz.edit_version, 'rename', name='Future title')
        question.refresh_from_db()
        self.assertEqual(before, (question.revision_id, question.answer_bank_id))
        self.assertEqual(self.game.title, 'Friday quiz')
        self.assertEqual(list(self.game.questions.values_list('position', flat=True)), [1, 2, 3])
        self.assertNotEqual(question.revision_id, Question.objects.get(pk=q.pk).current_revision_id)
        with self.assertRaises(live.LiveConflict):
            live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        self.assertEqual(live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, self.game.request_key).pk, self.game.pk)

    def test_one_open_game_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LiveQuiz.objects.create(host=self.teacher, request_key=uuid.uuid4(), title='Other', question_count=1, grading_version='typed-v1')

    def test_host_requires_reviewed_active_nonempty_list_and_admin(self):
        self.control('cancel')
        q = Question.objects.get(pk='q-0-0')
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'Unreviewed', 'correct_answer': 'New'})
        with self.assertRaises(ValidationError):
            live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        with self.assertRaises(PermissionDenied):
            live.host(self.student, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())

    def test_get_is_read_only_and_csrf_required_for_join(self):
        self.client.force_login(self.student)
        for name in ['page', 'state']:
            self.assertEqual(self.client.get(self.url(name)).status_code, 200)
        self.assertEqual(LiveParticipant.objects.count(), 0)
        self.assertEqual(LiveConnection.objects.count(), 0)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        self.assertEqual(client.post(self.url('connect'), {'connection': uuid.uuid4()}).status_code, 403)
        self.assertEqual(self.client.get(self.url('connect')).status_code, 405)

    def test_roster_captures_present_players_and_admits_late_join(self):
        with self.assertRaises(ValidationError):
            self.control('start')
        self.connect()
        expired = self.connect(self.other)
        LiveConnection.objects.filter(pk=expired).update(last_seen=timezone.now() - timedelta(seconds=21))
        self.control('start')
        self.assertTrue(self.game.participants.get(user=self.student).roster_at)
        self.assertIsNone(self.game.participants.get(user=self.other).roster_at)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('state')).status_code, 200)
        self.assertEqual(self.client.get(reverse('scholars:live_discover')).json()['invitation']['label'], 'Join the Live Quiz!')
        self.connect(self.other)
        self.assertIsNotNone(self.game.participants.get(user=self.other).roster_at)
        self.game.refresh_from_db()
        self.assertEqual(self.game.late_joiners, 1)
        self.connect(self.other)
        self.game.refresh_from_db()
        self.assertEqual(self.game.late_joiners, 1)

    def test_multiple_tabs_departure_expiry_and_reconnection(self):
        a, b = self.connect(), self.connect()
        self.assertEqual(self.game.participants.count(), 1)
        live.leave(self.student, self.game.pk, a)
        self.assertEqual(self.state()['connected'], 1)
        self.control('start')
        live.leave(self.student, self.game.pk, b)
        self.assertEqual(self.state()['players'][0]['presence'], 'left')
        with self.assertRaises(live.LiveConflict):
            live.heartbeat(self.student, self.game.pk, b)
        c = self.connect()
        LiveConnection.objects.filter(pk=c).update(last_seen=timezone.now() - timedelta(seconds=21))
        self.assertEqual(self.state()['players'][0]['presence'], 'away')
        live.heartbeat(self.student, self.game.pk, c)
        self.assertEqual(self.state()['connected'], 1)
        with self.assertRaises(live.LiveConflict):
            live.join(self.other, self.game.pk, c)

    def test_presence_tokens_are_scoped_and_cannot_be_resurrected(self):
        key = self.connect()
        live.leave(self.other, self.game.pk, key)
        self.assertEqual(self.state()['connected'], 1)
        with self.assertRaises(live.LiveConflict):
            live.heartbeat(self.other, self.game.pk, key)
        with self.assertRaises(live.LiveConflict):
            live.join(self.other, self.game.pk, key)
        live.leave(self.student, self.game.pk, key)
        with self.assertRaises(live.LiveConflict):
            live.join(self.student, self.game.pk, key)

    def test_teacher_absence_does_not_advance_and_answers_survive_refresh(self):
        teacher_connection = self.connect(self.teacher)
        self.start()
        live.leave(self.teacher, self.game.pk, teacher_connection)
        self.assertFalse(self.state()['host_present'])
        self.assertEqual(live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0'), 'correct')
        self.connect()
        state = self.state()
        self.assertEqual(state['position'], 1)
        self.assertEqual(state['response']['status'], 'correct')
        self.assertEqual(live.answer(self.student, self.game.pk, 1, 'wrong'), 'correct')
        self.assertEqual(LiveResponse.objects.count(), 1)

    def test_next_closes_unanswered_and_first_final_response_wins(self):
        self.connect(self.other)
        self.start()
        live.answer(self.student, self.game.pk, 1, skip=True)
        self.control('next')
        first = self.game.questions.get(position=1)
        self.assertEqual(set(first.responses.values_list('status', flat=True)), {'skipped', 'unanswered'})
        self.assertIsNotNone(first.closed_at)
        with self.assertRaises(live.LiveConflict):
            live.answer(self.other, self.game.pk, 1, 'Canonical 0 number 0')
        self.assertEqual(live.answer(self.student, self.game.pk, 2, 'Totally wrong'), 'incorrect')
        self.assertEqual(live.answer(self.student, self.game.pk, 2, 'Canonical 0 number 1'), 'incorrect')
        self.assertEqual(StudyActivity.objects.count(), 0)
        self.assertEqual(TopicCompletion.objects.count(), 0)

    def test_grading_prompt_does_not_finalize_and_input_is_validated(self):
        from unittest.mock import patch
        self.start()
        with patch('scholars.live.grade', return_value='prompt'):
            self.assertEqual(live.answer(self.student, self.game.pk, 1, 'partial'), 'prompt')
        self.assertEqual(LiveResponse.objects.count(), 0)
        for value in ['', ' ', 'x' * 241]:
            with self.assertRaises(ValidationError):
                live.answer(self.student, self.game.pk, 1, value)
        self.assertEqual(live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0'), 'correct')

    def test_controls_require_host_expected_position_version_and_request_identity(self):
        self.start()
        with self.assertRaises(PermissionDenied):
            live.transition(self.student, self.game.pk, 'next', 1, 1, uuid.uuid4())
        key = uuid.uuid4()
        live.transition(self.teacher, self.game.pk, 'next', 1, 1, key)
        live.transition(self.teacher, self.game.pk, 'next', 1, 1, key)
        self.game.refresh_from_db()
        self.assertEqual(self.game.position, 2)
        with self.assertRaises(live.LiveConflict):
            live.transition(self.teacher, self.game.pk, 'next', 1, 1, uuid.uuid4())
        with self.assertRaises(live.LiveConflict):
            live.transition(self.teacher, self.game.pk, 'end', 2, 2, key)

    def test_student_state_privacy_and_current_only_suggestions(self):
        self.connect(self.other)
        self.start()
        live.answer(self.other, self.game.pk, 1, 'Other private response')
        live.ready(self.student, self.game.pk, 1)
        state = self.state()
        text = json.dumps(state)
        for secret in ['Canonical 0 number 0', 'correct_answer', 'Other private response', 'Prompt 0 / 1?', 'suppressedAnswers', 'revision']:
            self.assertNotIn(secret, text)
        self.assertNotIn('answered', state)
        self.assertTrue(all('answered' not in p for p in state['players']))
        self.assertEqual(state['question']['prompt'], 'Prompt 0 / 0?')
        suggestion = self.client.get(self.url('suggestions', 1)).json()
        self.assertEqual(set(suggestion), {'position', 'version', 'index'})
        self.assertTrue(all(set(row) == {'text', 'key', 'parts'} for row in suggestion['index']))
        self.assertEqual(self.client.get(self.url('suggestions', 2)).status_code, 409)
        self.assertNotContains(self.client.get(self.url('page')), 'Canonical 0 number 0')
        host_state = self.state(self.teacher)
        self.assertEqual(host_state['answered'], 1)
        self.assertNotIn('Other private response', json.dumps(host_state))

    def test_finish_and_partial_summary_use_presented_denominator(self):
        self.connect(self.other)
        self.start()
        live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0')
        self.control('next')
        live.answer(self.other, self.game.pk, 2, 'Canonical 0 number 1')
        self.control('end')
        summary = self.state()['summary']
        self.assertEqual(summary, {'presented': 2, 'covered': 2, 'coverage_percent': 100, 'partial': True, 'score': 1, 'points': 100})
        self.assertFalse(self.game.questions.filter(position=3, opened_at__isnull=False).exists())
        with self.assertRaises(live.LiveConflict):
            live.answer(self.student, self.game.pk, 2, 'Canonical 0 number 1')
        self.assertIsNone(self.client.get(reverse('scholars:live_discover')).json()['invitation'])

    def test_normal_finish_cancel_and_new_game(self):
        self.connect()
        self.control('cancel')
        self.assertEqual(self.state()['phase'], 'cancelled')
        self.assertEqual(LiveResponse.objects.count(), 0)
        self.game = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        self.start()
        for _ in range(3):
            self.control('next')
        self.assertEqual(self.game.phase, 'finished')
        self.assertFalse(self.game.ended_early)
        self.assertEqual(self.state()['summary']['presented'], 3)

    def test_disabled_or_reset_accounts_cannot_keep_presence_or_answer(self):
        self.start()
        set_student_active(self.student.pk, False)
        with self.assertRaises(PermissionDenied):
            live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0')
        self.assertFalse(live.live_connections(self.game).filter(user=self.student).exists())
        User.objects.filter(pk=self.student.pk).update(is_active=True, must_change_password=True)
        with self.assertRaises(PermissionDenied):
            self.connect()

    def test_home_discovery_and_teacher_link(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('scholars:dashboard'))
        self.assertContains(response, 'Join the Live Quiz!')
        self.assertContains(response, 'Choose your interests')
        self.assertEqual(self.client.get(reverse('scholars:live_discover')).json()['invitation']['label'], 'Join the Live Quiz!')
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('scholars:teacher_home')), 'Hosting Live Quiz')
        self.assertRedirects(self.client.get(reverse('scholars:live_host')), self.url('page'))
        self.start()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('scholars:live_discover')).json()['invitation']['label'], 'Return to your live quiz')


class LiveRaceTests(TransactionTestCase):
    def setUp(self):
        self.teacher, self.student, self.quiz, self.game = setup_game()

    def race(self, functions):
        barrier = Barrier(len(functions))
        def worker(fn):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return fn()
                except (ValidationError, PermissionDenied) as exc:
                    return type(exc).__name__
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(worker, fn) for fn in functions]
            return [f.result(timeout=20) for f in futures]

    def test_answer_racing_advance_is_final_once(self):
        live.join(self.student, self.game.pk, uuid.uuid4())
        live.transition(self.teacher, self.game.pk, 'start', 0, 0, uuid.uuid4())
        self.race([lambda: live.answer(self.student, self.game.pk, 1, 'Canonical 0 number 0'),
                   lambda: live.transition(self.teacher, self.game.pk, 'next', 1, 1, uuid.uuid4())])
        response = LiveResponse.objects.get(question__game=self.game, question__position=1)
        self.assertIn(response.status, ['correct', 'unanswered'])
        self.assertEqual(LiveResponse.objects.count(), 1)
        self.assertEqual(LiveQuiz.objects.get(pk=self.game.pk).position, 2)

    def test_join_racing_start_always_admits_player(self):
        live.join(self.student, self.game.pk, uuid.uuid4())
        other = User.objects.create_user('late-player', must_change_password=False)
        self.race([lambda: live.join(other, self.game.pk, uuid.uuid4()),
                   lambda: live.transition(self.teacher, self.game.pk, 'start', 0, 0, uuid.uuid4())])
        self.game.refresh_from_db()
        participant = self.game.participants.filter(user=other).first()
        self.assertIsNotNone(participant)
        self.assertIsNotNone(participant.roster_at)

    def test_duplicate_host_and_next_are_idempotent(self):
        live.transition(self.teacher, self.game.pk, 'cancel', 0, 0, uuid.uuid4())
        key = uuid.uuid4()
        self.race([lambda: live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, key)] * 2)
        self.game = LiveQuiz.objects.get(request_key=key)
        live.join(self.student, self.game.pk, uuid.uuid4())
        live.transition(self.teacher, self.game.pk, 'start', 0, 0, uuid.uuid4())
        key = uuid.uuid4()
        self.race([lambda: live.transition(self.teacher, self.game.pk, 'next', 1, 1, key)] * 2)
        self.assertEqual(LiveQuiz.objects.get(pk=self.game.pk).position, 2)
