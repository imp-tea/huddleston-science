import uuid

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import PracticeSession, Question, SessionQuestion, StudyActivity, StudyAnswer, StudySession, Topic, TopicCompletion
from .study import start_study, submit_answer
from .test_study import answer_attempt, finish_reading, seed_study


class TeacherProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = seed_study()
        # Legacy coverage reads imported membership metadata, which the small
        # Study-only fixture omits.
        for topic in Topic.objects.all():
            topic.payload['subcategory_ids'] = list(topic.subcategories.values_list('pk', flat=True))
            topic.save(update_fields=['payload'])
        cls.teacher = User.objects.create_user('report-teacher', 'Teacher-password!', is_admin=True, must_change_password=False)
        cls.other = User.objects.create_user('report-other', 'Other-password!', must_change_password=False)
        cls.disabled = User.objects.create_user('report-disabled', 'Disabled-password!', is_active=False)
        cls.passed = answer_attempt(cls.student, finish_reading(cls.student,
            start_study(cls.student, uuid.uuid4(), 'small')), misses=1)
        cls.passed = answer_attempt(cls.student, finish_reading(cls.student, cls.passed))
        cls.active = finish_reading(cls.student, start_study(cls.student, uuid.uuid4(), 'sub-00'))
        answers = list(cls.active.attempts.last().answers.select_related('question__revision'))
        submit_answer(cls.student, cls.active.pk, answers[0].pk, answers[0].question.revision.payload['correct_answer'])
        submit_answer(cls.student, cls.active.pk, answers[1].pk, skip=True)
        submit_answer(cls.student, cls.active.pk, answers[2].pk, 'Entirely unrelated answer')
        q = Question.objects.select_related('current_revision', 'topic__category').first()
        q.current_revision.context['topic'].update(primary_category=q.topic.category_id,
            subcategory_ids=q.topic.payload['subcategory_ids'])
        q.current_revision.save(update_fields=['context'])
        cls.legacy = PracticeSession.objects.create(user=cls.student, request_key=uuid.uuid4(),
            scope_label='Older practice sample', mode='typed', completed_at=timezone.now())
        SessionQuestion.objects.create(session=cls.legacy, position=1, revision=q.current_revision,
            choices=[], answer_bank=q.topic.category.typed_bank, typed_answer='Saved historic response',
            is_correct=False, answered_at=timezone.now())

    def setUp(self):
        self.client.force_login(self.teacher)

    def report_url(self, student=None):
        return reverse('scholars:student_progress', args=[(student or self.student).pk])

    def urls(self):
        return [reverse('scholars:teacher_home'), reverse('scholars:teacher_students'), self.report_url(),
                reverse('scholars:teacher_student_history', args=[self.student.pk]),
                reverse('scholars:teacher_study_detail', args=[self.student.pk, self.active.pk]),
                reverse('scholars:teacher_practice_detail', args=[self.student.pk, self.legacy.pk])]

    def test_home_card_and_tools_work_without_teacher_interests(self):
        response = self.client.get(reverse('scholars:dashboard'))
        self.assertContains(response, 'Teacher Tools')
        self.assertContains(response, 'destination-teacher')
        response = self.client.get(reverse('scholars:teacher_home'))
        self.assertContains(response, 'View Student Progress')
        self.assertContains(response, 'Quiz Creator')
        self.assertContains(response, reverse('scholars:quiz_list'))
        self.assertNotContains(response, 'href="#"')
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(reverse('scholars:dashboard')), 'Teacher Tools')

    def test_current_progress_matches_students_own_progress(self):
        teacher = self.client.get(self.report_url())
        self.client.force_login(self.student)
        own = self.client.get(reverse('scholars:progress'))
        self.assertEqual(teacher.context['weekly'], own.context['weekly'])
        for key in ['total', 'done', 'percent']:
            self.assertEqual(teacher.context['coverage'][key], own.context['coverage'][key])
        self.assertEqual(teacher.context['weekly']['count'], 1)
        self.assertEqual(teacher.context['coverage']['done'], 1)
        self.assertContains(teacher, 'Viewing study-student')
        self.assertContains(teacher, 'Read only')
        self.assertContains(teacher, 'Older practice sample')

    def test_students_and_anonymous_cannot_access_teacher_routes(self):
        self.client.force_login(self.student)
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 403)
        self.client.logout()
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_reporting_gets_do_not_mutate_and_posts_are_rejected(self):
        before = {model: list(model.objects.order_by('pk').values()) for model in
                  [StudySession, StudyAnswer, StudyActivity, TopicCompletion, PracticeSession, SessionQuestion]}
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.post(url, {'action': 'skip', 'direction': 'next'}).status_code, 405)
        for model, rows in before.items():
            self.assertEqual(rows, list(model.objects.order_by('pk').values()))
        self.assertEqual(self.client.session['_auth_user_id'], str(self.teacher.pk))

    def test_session_detail_is_scoped_to_selected_student(self):
        for name, session in [('teacher_study_detail', self.active), ('teacher_practice_detail', self.legacy)]:
            self.assertEqual(self.client.get(reverse('scholars:' + name, args=[self.other.pk, session.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse('scholars:' + name, args=[self.student.pk, uuid.uuid4()])).status_code, 404)
        self.assertEqual(self.client.get(self.report_url(self.teacher)).status_code, 404)
        self.assertEqual(self.client.get(reverse('scholars:student_progress', args=[uuid.uuid4()])).status_code, 404)
        response = self.client.get(self.report_url(self.other), {'user': self.student.pk})
        self.assertEqual(response.context['weekly']['count'], 0)
        self.assertNotContains(response, 'Older practice sample')

    def test_admin_inspection_does_not_grant_student_mutation_access(self):
        answer = self.active.attempts.last().answers.filter(answered_at__isnull=True).first()
        for name, args, data in [
            ('study_answer', [self.active.pk, answer.pk], {'action': 'skip'}),
            ('study_read', [self.active.pk], {'direction': 'next', 'version': self.active.version}),
            ('study_restart', [self.active.pk], {})]:
            self.assertEqual(self.client.post(reverse('scholars:' + name, args=args), data).status_code, 404)
        self.assertEqual(self.client.get(reverse('scholars:study_session', args=[self.active.pk])).status_code, 404)

    def test_details_show_saved_outcomes_attempts_and_never_student_controls(self):
        response = self.client.get(reverse('scholars:teacher_study_detail', args=[self.student.pk, self.active.pk]))
        for text in ['Not answered', 'Skipped', 'Correct', 'Incorrect', 'Student’s answer:', 'Correct answer:']:
            self.assertContains(response, text)
        for text in ['typed-bank', 'study_read', 'Take quiz', 'name="typed_answer"', 'Retry quiz']:
            self.assertNotContains(response, text)
        self.assertNotContains(response, reverse('scholars:study_restart', args=[self.active.pk]))
        passed = self.client.get(reverse('scholars:teacher_study_detail', args=[self.student.pk, self.passed.pk]))
        self.assertContains(passed, 'Quiz 1')
        self.assertContains(passed, 'Quiz 2')
        legacy = self.client.get(reverse('scholars:teacher_practice_detail', args=[self.student.pk, self.legacy.pk]))
        self.assertContains(legacy, 'Saved historic response')
        self.assertNotContains(legacy, 'Continue practice')

    def test_history_has_zero_scores_pending_counts_and_empty_states(self):
        history = self.client.get(reverse('scholars:teacher_student_history', args=[self.student.pk]))
        self.assertContains(history, '3/10 answered')
        self.assertContains(history, '2/2 correct')
        self.assertContains(history, '0/1 correct')
        empty = self.client.get(self.report_url(self.other))
        self.assertContains(empty, 'No Study sessions yet.')
        self.assertContains(empty, 'No previous practice results.')
        disabled = self.client.get(self.report_url(self.disabled))
        self.assertContains(disabled, 'Disabled account')

    def test_roster_search_pagination_and_disabled_students(self):
        for i in range(31):
            User.objects.create_user(f'roster-{i:02}', must_change_password=False)
        url = reverse('scholars:teacher_students')
        response = self.client.get(url, {'q': 'roster-', 'page': '2'})
        self.assertEqual(len(response.context['students']), 1)
        self.assertEqual(response.context['students'].paginator.count, 31)
        self.assertContains(response, 'q=roster-')
        result = self.client.get(url, {'q': 'REPORT-DISABLED'})
        self.assertContains(result, 'Disabled')
        self.assertEqual(list(result.context['students'])[0], self.disabled)
        self.assertEqual(self.client.get(url, {'q': 'no-such-student'}).context['students'].paginator.count, 0)
        self.assertEqual(self.client.get(url, {'q': 'report-teacher'}).context['students'].paginator.count, 0)

    def test_history_pages_and_database_queries_are_bounded(self):
        for _ in range(21):
            StudySession.objects.create(user=self.student, request_key=uuid.uuid4(), subcategory_id='small',
                subcategory_label='Archived reading', category_label='Geography', phase='abandoned', abandoned_at=timezone.now())
        url = reverse('scholars:teacher_student_history', args=[self.student.pk])
        with CaptureQueriesContext(connection) as queries:
            first = self.client.get(url)
        self.assertLess(len(queries), 12)
        self.assertEqual(len(first.context['study_sessions']), 20)
        second = self.client.get(url, {'study_page': 2})
        self.assertEqual(len(second.context['study_sessions']), 3)
        self.assertContains(second, 'study_page=1')
        self.assertEqual(self.client.get(url, {'study_page': 'bad'}).status_code, 200)

    def test_existing_admin_link_opens_current_progress_and_legacy_is_labeled(self):
        self.assertContains(self.client.get(reverse('student', args=[self.student.pk])), self.report_url())
        response = self.client.get(reverse('scholars:legacy_student_progress', args=[self.student.pk]))
        self.assertContains(response, 'current Study progress')
        self.assertContains(response, self.report_url())
