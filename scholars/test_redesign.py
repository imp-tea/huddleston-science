"""Release-boundary checks spanning Study, Explore, and Progress."""
import uuid

from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, StudyActivity, StudyAnswer, StudySession, TopicCompletion
from .study import save_interests, start_study
from .test_study import seed_study


class RedesignJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = seed_study()

    def setUp(self):
        self.client.force_login(self.user)

    def device(self):
        device = Client()
        device.force_login(self.user)
        return device

    def test_plain_forms_resume_every_phase_and_count_short_pass_once(self):
        session = start_study(self.user, uuid.uuid4(), 'small')
        page_url = reverse('scholars:study_session', args=[session.pk])
        read_url = reverse('scholars:study_read', args=[session.pk])
        for attempt in range(1, 3):
            browser = self.device()
            self.assertContains(browser.get(reverse('scholars:study')), 'Resume Previous Session')
            page = browser.get(page_url)
            self.assertEqual(page.context['session'].phase, 'reading' if attempt == 1 else 'review')
            response = browser.post(read_url, {'version': page.context['session'].version, 'direction': 'next'}, follow=True)
            self.assertContains(response, 'Question 1 of 2')
            answers = list(session.attempts.get(number=attempt).answers.select_related('question__revision'))
            for i, answer in enumerate(answers):
                # A new device sees exactly the saved next question each time.
                browser = self.device()
                page = browser.get(page_url)
                self.assertEqual(page.context['answer_id'], answer.pk)
                url = reverse('scholars:study_answer', args=[session.pk, answer.pk])
                response = browser.post(url, {'action': 'skip'} if attempt == 1 else {
                    'action': 'answer', 'typed_answer': answer.question.revision.payload['correct_answer']}, follow=True)
                self.assertEqual(response.status_code, 200)
                for question in answers:
                    self.assertNotContains(response, question.question.revision.payload['correct_answer'])
        self.assertContains(self.device().get(page_url), 'Session complete')
        last = answers[-1]
        self.client.post(reverse('scholars:study_answer', args=[session.pk, last.pk]), {'action': 'skip'})
        progress = self.device().get(reverse('scholars:progress'))
        self.assertEqual(progress.context['weekly']['count'], 1)
        self.assertEqual(progress.context['coverage']['done'], 1)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)
        completion = TopicCompletion.objects.get()
        self.assertContains(self.device().get(reverse('scholars:topic', args=[completion.topic_id])), 'View study session')
        self.assertContains(self.device().get(reverse('scholars:history')), 'Passed')

    def test_retired_interests_do_not_block_resuming_pinned_session(self):
        session = start_study(self.user, uuid.uuid4(), 'small')
        Category.objects.filter(pk='Geography').update(active=False)
        self.assertContains(self.client.get(reverse('scholars:study')), 'Resume Previous Session')
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), 'Short description 0')
        self.client.post(reverse('scholars:study_restart', args=[session.pk]))
        self.assertRedirects(self.client.get(reverse('scholars:study')), reverse('scholars:interests'))

    def test_empty_interests_are_not_reported_as_completed(self):
        save_interests(self.user, ['Literature'])
        response = self.client.get(reverse('scholars:study'))
        self.assertContains(response, 'No study topics available')
        self.assertNotContains(response, 'All selected topics complete')

    def test_study_mutations_require_csrf_and_private_gets_never_cache(self):
        session = start_study(self.user, uuid.uuid4(), 'small')
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        for route, args, data in [
            ('interests', [], {'categories': ['Literature']}),
            ('study_start', [], {'request_key': uuid.uuid4(), 'subcategory': 'small'}),
            ('study_read', [session.pk], {'version': 0, 'direction': 'next'}),
            ('study_restart', [session.pk], {}),
        ]:
            self.assertEqual(secure.post(reverse('scholars:' + route, args=args), data).status_code, 403)
        self.assertEqual(StudySession.objects.get().phase, 'reading')
        self.assertFalse(StudyAnswer.objects.exists())
        for route, args in [('study', []), ('progress', []), ('library', []), ('study_session', [session.pk])]:
            response = secure.get(reverse('scholars:' + route, args=args))
            self.assertIn('no-store', response['Cache-Control'])
