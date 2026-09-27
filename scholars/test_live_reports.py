import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from . import live
from .live_reports import report, student_history
from .models import (LiveConnection, LiveParticipant, LiveQuiz, LiveResponse, Question,
                     SavedQuiz, StudyActivity, Topic, TopicCompletion)
from .question_authoring import edit_question
from .quiz_lists import create_quiz, add_question, update_quiz
from .test_study import seed_study


class LiveReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = seed_study()
        cls.alice.username = 'alice'
        cls.alice.save(update_fields=['username'])
        cls.bob = User.objects.create_user('bob', must_change_password=False)
        cls.outsider = User.objects.create_user('outside', must_change_password=False)
        cls.teacher = User.objects.create_user('report-host', is_admin=True, must_change_password=False)
        cls.quiz = create_quiz(cls.teacher, 'Original game title', uuid.uuid4())
        # Four questions with different topics and categories; reports must use
        # frozen category labels, not the current topic/category bank.
        Topic.objects.filter(pk='topic-1').update(category_id='Literature')
        for qid in ['q-0-0', 'q-0-1', 'q-1-0', 'q-1-1']:
            q = Question.objects.get(pk=qid)
            cls.quiz, _ = add_question(cls.teacher, cls.quiz.pk, cls.quiz.edit_version, q.pk, q.current_revision_id)
        cls.game = live.host(cls.teacher, cls.quiz.pk, cls.quiz.edit_version, uuid.uuid4())
        cls.alice_connection, cls.bob_connection = uuid.uuid4(), uuid.uuid4()
        live.join(cls.alice, cls.game.pk, cls.alice_connection)
        live.join(cls.bob, cls.game.pk, cls.bob_connection)
        live.join(cls.outsider, cls.game.pk, uuid.uuid4())
        # A lobby visitor who leaves before Start never becomes part of reports.
        LiveConnection.objects.filter(user=cls.outsider).update(ended_at=timezone.now())
        cls.game = live.transition(cls.teacher, cls.game.pk, 'start', 0, 0, uuid.uuid4())
        # Q1 both correct; Q2 only Bob correct; Q3 nobody correct; Q4 no responses.
        live.answer(cls.alice, cls.game.pk, 1, 'Canonical 0 number 0')
        live.answer(cls.bob, cls.game.pk, 1, 'Canonical 0 number 0')
        cls.game = live.transition(cls.teacher, cls.game.pk, 'next', 1, 1, uuid.uuid4())
        live.answer(cls.alice, cls.game.pk, 2, 'Alice private wrong response')
        live.answer(cls.bob, cls.game.pk, 2, 'Canonical 0 number 1')
        cls.game = live.transition(cls.teacher, cls.game.pk, 'next', 2, 2, uuid.uuid4())
        live.answer(cls.alice, cls.game.pk, 3, skip=True)
        live.answer(cls.bob, cls.game.pk, 3, 'Bob private wrong response')
        # Bob deliberately leaves, but his accepted answers remain in the cohort.
        live.leave(cls.bob, cls.game.pk, cls.bob_connection)
        cls.game = live.transition(cls.teacher, cls.game.pk, 'next', 3, 3, uuid.uuid4())
        cls.game = live.transition(cls.teacher, cls.game.pk, 'next', 4, 4, uuid.uuid4())

    def setUp(self):
        self.client.force_login(self.alice)

    def url(self, game=None):
        return reverse('scholars:live_report', args=[(game or self.game).pk])

    def personal_url(self, user=None, game=None):
        return reverse('scholars:live_student_report', args=[(game or self.game).pk, (user or self.alice).pk])

    def test_exact_team_and_individual_denominators_outcomes_and_categories(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        summary, personal = response.context['summary'], response.context['personal']
        self.assertEqual((summary['covered'], summary['presented'], summary['coverage_percent']), (2, 4, 50))
        self.assertEqual((summary['no_correct'], summary['no_responses']), (2, 1))
        self.assertEqual((summary['retained_players'], summary['original_players']), (2, 2))
        self.assertEqual(personal, {'correct': 1, 'incorrect': 1, 'skipped': 1, 'unanswered': 1, 'percent': 25})
        self.assertEqual([r['correct_count'] for r in response.context['rows']], [2, 1, 0, 0])
        self.assertEqual(response.context['categories'], [
            {'name': 'Geography', 'presented': 2, 'covered': 2, 'percent': 100},
            {'name': 'Literature', 'presented': 2, 'covered': 0, 'percent': 0}])
        for text in ['Team coverage', 'Your accuracy', 'Incorrect', 'Skipped', 'No answer before advance', 'Canonical 0 number 1', 'Alice private wrong response']:
            self.assertContains(response, text)
        self.assertEqual(StudyActivity.objects.count(), 0)
        self.assertEqual(TopicCompletion.objects.count(), 0)

    def test_student_only_gets_own_responses_no_rankings_or_student_table(self):
        response = self.client.get(self.url(), {'student_id': self.bob.pk, 'user': self.bob.pk})
        self.assertNotContains(response, 'Bob private wrong response')
        self.assertNotContains(response, 'Student reports')
        self.assertNotContains(response, self.personal_url(self.bob))
        self.assertIsNone(response.context['report_students'])
        self.assertEqual(self.client.get(self.personal_url(self.bob)).status_code, 403)
        self.client.force_login(self.bob)
        response = self.client.get(self.url())
        self.assertContains(response, 'Bob private wrong response')
        self.assertNotContains(response, 'Alice private wrong response')
        self.assertEqual(response.context['personal']['correct'], 2)

    def test_teacher_roster_is_alphabetical_and_individual_is_game_scoped(self):
        self.client.force_login(self.teacher)
        response = self.client.get(self.url())
        self.assertIsNone(response.context['personal'])
        self.assertEqual([p.user.username for p in response.context['report_students']], ['alice', 'bob'])
        self.assertNotContains(response, 'Bob private wrong response')
        self.assertContains(response, self.personal_url(self.bob))
        response = self.client.get(self.personal_url(self.bob))
        self.assertContains(response, 'Viewing bob')
        self.assertContains(response, 'Read only')
        self.assertContains(response, 'Bob private wrong response')
        self.assertNotContains(response, 'Alice private wrong response')
        self.assertEqual(self.client.get(self.personal_url(self.outsider)).status_code, 404)
        other = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        live.join(self.alice, other.pk, uuid.uuid4())
        live.transition(self.teacher, other.pk, 'start', 0, 0, uuid.uuid4())
        live.transition(self.teacher, other.pk, 'end', 1, 1, uuid.uuid4())
        self.assertEqual(self.client.get(self.personal_url(self.bob, other)).status_code, 404)

    def test_reports_deny_anonymous_non_roster_and_non_finished_games(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.teacher)
        game = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        for phase in ['waiting', 'running', 'cancelled']:
            LiveQuiz.objects.filter(pk=game.pk).update(phase=phase)
            game.refresh_from_db()
            for user in [self.teacher, self.alice]:
                self.client.force_login(user)
                response = self.client.get(self.url(game))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, 'Canonical', status_code=404)
            with self.assertRaises(ValidationError):
                report(game)

    def test_partial_report_never_reveals_unpresented_prompts_or_answers(self):
        game = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        live.join(self.alice, game.pk, uuid.uuid4())
        live.transition(self.teacher, game.pk, 'start', 0, 0, uuid.uuid4())
        live.answer(self.alice, game.pk, 1, 'Canonical 0 number 0')
        live.transition(self.teacher, game.pk, 'next', 1, 1, uuid.uuid4())
        live.transition(self.teacher, game.pk, 'end', 2, 2, uuid.uuid4())
        response = self.client.get(self.url(game))
        self.assertEqual(response.context['personal']['percent'], 50)
        self.assertEqual(response.context['summary']['coverage_percent'], 50)
        self.assertEqual(len(response.context['rows']), 2)
        self.assertContains(response, 'Partial quiz: 2 of 4 questions presented')
        for text in ['Prompt 1 / 0?', 'Canonical 1 number 0', 'Prompt 1 / 1?', 'Canonical 1 number 1']:
            self.assertNotContains(response, text)
        self.client.force_login(self.teacher)
        self.assertNotContains(self.client.get(self.url(game)), 'Canonical 1 number 0')
        self.assertNotContains(self.client.get(self.personal_url(self.alice, game)), 'Canonical 1 number 1')

    def test_frozen_report_survives_question_edits_quiz_rename_archive_and_topic_retirement(self):
        q = Question.objects.get(pk='q-0-0')
        edit_question(self.teacher, q.pk, q.edit_version, {'question': 'Future secret prompt', 'correct_answer': 'Future secret answer'})
        quiz = update_quiz(self.teacher, self.quiz.pk, self.quiz.edit_version, 'rename', name='Renamed source quiz')
        update_quiz(self.teacher, quiz.pk, quiz.edit_version, 'archive')
        Topic.objects.filter(pk='topic-0').update(active=False, title='New topic name', category_id='Literature')
        response = self.client.get(self.url())
        for text in ['Original game title', 'Prompt 0 / 0?', 'Canonical 0 number 0', 'Topic 0', 'Geography', 'no longer available']:
            self.assertContains(response, text)
        for text in ['Future secret prompt', 'Future secret answer', 'Renamed source quiz', 'New topic name']:
            self.assertNotContains(response, text)
        self.assertNotContains(response, 'href="' + reverse('scholars:topic', args=['topic-0']) + '"')

    def test_deleted_accounts_recalculate_coverage_and_remove_personal_records(self):
        original = self.game.roster_size_at_start
        bob_id = self.bob.pk
        self.bob.delete()
        response = self.client.get(self.url())
        summary = response.context['summary']
        self.assertEqual((summary['covered'], summary['coverage_percent']), (1, 25))
        self.assertEqual((summary['original_players'], summary['retained_players'], summary['removed_players']), (2, 1, 1))
        self.assertContains(response, 'have been deleted')
        self.assertNotContains(response, 'Bob')
        self.assertFalse(LiveParticipant.objects.filter(user_id=bob_id).exists())
        self.assertFalse(LiveConnection.objects.filter(user_id=bob_id).exists())
        self.assertFalse(LiveResponse.objects.filter(typed_answer='Bob private wrong response').exists())
        self.game.refresh_from_db()
        self.assertEqual(self.game.roster_size_at_start, original)

    def test_all_accounts_deleted_keeps_questions_and_zero_safe_coverage(self):
        self.alice.delete()
        self.bob.delete()
        self.client.force_login(self.teacher)
        response = self.client.get(self.url())
        self.assertEqual(response.context['summary']['coverage_percent'], 0)
        self.assertEqual(response.context['summary']['retained_players'], 0)
        self.assertContains(response, 'No player records remain')
        self.assertContains(response, 'Canonical 0 number 0')

    def test_older_roster_baseline_is_explicitly_unknown_not_fabricated(self):
        LiveQuiz.objects.filter(pk=self.game.pk).update(roster_size_at_start=None)
        response = self.client.get(self.url())
        self.assertContains(response, 'Original roster size was not recorded')
        self.assertTrue(response.context['summary']['cohort_unknown'])
        self.assertIsNone(response.context['summary']['removed_players'])

    def test_disabled_players_remain_in_results_and_missing_response_does_not_shrink_total(self):
        User.objects.filter(pk=self.bob.pk).update(is_active=False)
        participant = self.game.participants.get(user=self.alice)
        participant.responses.filter(question__position=4).delete()
        response = self.client.get(self.url())
        self.assertEqual(response.context['summary']['retained_players'], 2)
        self.assertEqual(response.context['summary']['coverage_percent'], 50)
        self.assertEqual(response.context['personal']['percent'], 25)
        self.assertEqual(response.context['personal']['unanswered'], 1)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(self.url()), 'Disabled account')
        self.assertEqual(self.client.get(self.personal_url(self.bob)).status_code, 200)

    def test_history_links_scoping_and_read_only_requests(self):
        self.assertContains(self.client.get(reverse('scholars:history')), self.url())
        self.assertContains(self.client.get(reverse('scholars:history')), '1/4 correct')
        self.client.force_login(self.outsider)
        self.assertNotContains(self.client.get(reverse('scholars:history')), self.url())
        self.assertEqual(self.client.get(reverse('scholars:live_history')).status_code, 403)
        self.assertEqual(self.client.get(reverse('scholars:quiz_runs', args=[self.quiz.pk])).status_code, 403)
        self.client.force_login(self.teacher)
        urls = [self.url(), self.personal_url(), reverse('scholars:live_history'), reverse('scholars:quiz_runs', args=[self.quiz.pk])]
        before = {model: list(model.objects.order_by('pk').values()) for model in [LiveQuiz, LiveParticipant, LiveResponse, StudyActivity, TopicCompletion]}
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.post(url, {'action': 'next'}).status_code, 405)
        for model, rows in before.items():
            self.assertEqual(rows, list(model.objects.order_by('pk').values()))
        self.assertContains(self.client.get(reverse('scholars:student_progress', args=[self.bob.pk])), self.personal_url(self.bob))
        self.assertContains(self.client.get(reverse('scholars:teacher_student_history', args=[self.bob.pk])), '2/4 correct')
        self.assertContains(self.client.get(reverse('scholars:live_history')), self.url())
        self.assertContains(self.client.get(reverse('scholars:quiz_detail', args=[self.quiz.pk])), reverse('scholars:quiz_runs', args=[self.quiz.pk]))

    def test_report_queries_are_bounded_and_personal_history_scores_are_exact(self):
        self.client.force_login(self.teacher)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url())
        self.assertLessEqual(len(queries), 10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(student_history(self.alice).get().score, 1)
        self.assertEqual(student_history(self.bob).get().score, 2)

    def test_teacher_run_history_pagination_cancelled_and_quiz_filter(self):
        now = timezone.now()
        for i in range(21):
            LiveQuiz.objects.create(host=self.teacher, quiz=self.quiz, title=f'Cancelled lobby {i}',
                request_key=uuid.uuid4(), phase='cancelled', question_count=4, grading_version='typed-v1', ended_at=now)
        other_quiz = create_quiz(self.teacher, 'Other source', uuid.uuid4())
        other = LiveQuiz.objects.create(host=self.teacher, quiz=other_quiz, title='Other source run',
            request_key=uuid.uuid4(), phase='cancelled', question_count=1, grading_version='typed-v1', ended_at=now)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('scholars:quiz_runs', args=[self.quiz.pk]), {'page': 2})
        self.assertEqual(response.context['games'].paginator.count, 22)
        self.assertEqual(len(response.context['games']), 2)
        self.assertNotContains(response, 'Other source run')
        self.assertContains(response, 'No scored report')
        self.assertEqual(self.client.get(self.url(other)).status_code, 404)
        self.assertEqual(self.client.get(reverse('scholars:live_history'), {'page': 'bad'}).status_code, 200)

    def test_student_history_pagination_preserves_other_sections(self):
        for i in range(21):
            game = LiveQuiz.objects.create(host=self.teacher, quiz=self.quiz, title=f'Finished quiz {i}',
                request_key=uuid.uuid4(), phase='finished', position=1, question_count=1, grading_version='typed-v1',
                ended_at=timezone.now() + timedelta(seconds=i), roster_size_at_start=1)
            LiveParticipant.objects.create(game=game, user=self.alice, roster_at=timezone.now())
        response = self.client.get(reverse('scholars:history'), {'live_page': 2})
        self.assertEqual(response.context['live_sessions'].paginator.count, 22)
        self.assertEqual(len(response.context['live_sessions']), 2)
        self.assertContains(response, 'live_page=1&amp;study_page=1&amp;page=1')
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('scholars:teacher_student_history', args=[self.alice.pk]), {'live_page': 2})
        self.assertContains(response, 'live_page=1&amp;study_page=1&amp;practice_page=1')

    def test_finish_exposes_report_link_but_running_state_does_not(self):
        response = self.client.get(reverse('scholars:live_state', args=[self.game.pk]))
        self.assertEqual(response.json()['report_url'], self.url())
        self.assertRedirects(self.client.get(reverse('scholars:live_page', args=[self.game.pk])), self.url())
        game = live.host(self.teacher, self.quiz.pk, self.quiz.edit_version, uuid.uuid4())
        live.join(self.alice, game.pk, uuid.uuid4())
        live.transition(self.teacher, game.pk, 'start', 0, 0, uuid.uuid4())
        self.assertNotIn('report_url', self.client.get(reverse('scholars:live_state', args=[game.pk])).json())
