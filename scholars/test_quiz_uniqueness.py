import json
import uuid
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import Question, StudyActivity, StudyAnswer, Topic
from .study import initial_question_ids, start_study
from .test_study import seed_study, finish_reading, answer_attempt
from .typed_answers import search_key


class UniqueQuizTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = seed_study()

    def setUp(self):
        self.client.force_login(self.user)

    def start(self):
        # Select five known topics; question selection is still randomized.
        with patch('scholars.study.rng.sample', side_effect=lambda pool, count: pool[:count]):
            return start_study(self.user, uuid.uuid4(), 'sub-00')

    def tokenization_duplicates(self):
        duplicates = [q for q in json.loads((Path(settings.BASE_DIR) / 'data/typed-questions.json').read_text())
                      if q['answer'] == 'Tokenization']
        self.assertEqual(len(duplicates), 2)
        for i, payload in enumerate(duplicates):
            revision = Question.objects.get(pk=f'q-{i}-1').current_revision
            revision.payload.update(question=payload['question'], correct_answer=payload['answer'])
            revision.save()
            Question.objects.filter(pk=f'q-{i}-2').update(active=False)

    def assert_unique(self, answers):
        payloads = [item.question.revision.payload for item in answers]
        for key in ['question', 'correct_answer']:
            values = [search_key(p[key]) for p in payloads]
            self.assertEqual(len(values), len(set(values)))

    def test_real_tokenization_duplicates_get_one_slot_and_ten_unique_questions(self):
        self.tokenization_duplicates()
        session = self.start()
        for _ in range(20):
            ids = initial_question_ids(session)
            from .models import StudyQuestion
            selected = list(StudyQuestion.objects.filter(pk__in=ids).select_related('revision'))
            self.assertEqual(len(selected), 10)
            self.assertEqual(sum(q.revision.payload['correct_answer'] == 'Tokenization' for q in selected), 1)
            self.assertEqual(len({q.session_topic_id for q in selected}), 5)
            for key in ['question', 'correct_answer']:
                self.assertEqual(len({search_key(q.revision.payload[key]) for q in selected}), 10)
        session = finish_reading(self.user, session)
        self.assert_unique(session.attempts.get().answers.select_related('question__revision'))

    def test_identical_prompt_with_different_answer_is_also_deduplicated(self):
        first = Question.objects.get(pk='q-0-1').current_revision
        second = Question.objects.get(pk='q-1-1').current_revision
        second.payload['question'] = '  ' + first.payload['question'].upper() + '  '
        second.save()
        session = finish_reading(self.user, self.start())
        self.assertEqual(session.attempts.get().answers.count(), 10)
        self.assert_unique(session.attempts.get().answers.select_related('question__revision'))

    def test_too_small_unique_pool_is_shortened_instead_of_repeating(self):
        self.tokenization_duplicates()
        Question.objects.filter(pk__endswith='-2').update(active=False)
        session = self.start()
        page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertEqual(page.context['quiz_size'], 9)
        from .study import move_reading
        for _ in range(4):
            session = move_reading(self.user, session.pk, session.version, 'next')
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), 'Take 9-question quiz')
        session = finish_reading(self.user, session)
        self.assertEqual(session.attempts.get().answers.count(), 9)
        self.assert_unique(session.attempts.get().answers.select_related('question__revision'))
        page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertContains(page, 'Question 1 of 9')
        self.assertEqual(page.context['passing_score'], 9)

    def test_correct_duplicate_variant_cannot_return_as_unseen_on_retry(self):
        self.tokenization_duplicates()
        session = finish_reading(self.user, self.start())
        from .study import submit_answer
        remaining_misses = 2
        for item in session.attempts.get().answers.select_related('question__revision'):
            expected = item.question.revision.payload['correct_answer']
            miss = remaining_misses > 0 and expected != 'Tokenization'
            if miss:
                remaining_misses -= 1
            session, _ = submit_answer(self.user, session.pk, item.pk, 'Unrelated wrong response' if miss else expected)
        self.assertEqual(session.phase, 'review')
        correct_answers = {search_key(item.question.revision.payload['correct_answer'])
            for item in StudyAnswer.objects.filter(attempt__session=session, is_correct=True).select_related('question__revision')}
        session = finish_reading(self.user, session)
        retry = session.attempts.last().answers.select_related('question__revision')
        self.assert_unique(retry)
        self.assertFalse({search_key(item.question.revision.payload['correct_answer']) for item in retry} & correct_answers)

    def test_nine_of_ten_has_optional_pinned_review_without_reopening_quiz(self):
        session = answer_attempt(self.user, finish_reading(self.user, self.start()), misses=1)
        missed = session.attempts.last().answers.get(is_correct=False).question.session_topic
        result_url = reverse('scholars:study_session', args=[session.pk])
        review_url = reverse('scholars:study_passed_review', args=[session.pk, missed.topic_id])
        page = self.client.get(result_url)
        self.assertContains(page, '9/10')
        self.assertContains(page, 'Topic to review')
        self.assertContains(page, review_url)
        self.assertEqual(page.context['optional_review'], [{'id': missed.topic_id, 'title': missed.content['title']}])
        Topic.objects.filter(pk=missed.topic_id).update(active=False, payload={'description': 'Changed live content'})
        events = StudyActivity.objects.count()
        page = self.client.get(review_url)
        self.assertContains(page, missed.content['description'])
        self.assertContains(page, 'No further quiz is required')
        self.assertNotContains(page, 'correct_answer')
        self.assertNotContains(page, 'typed-bank')
        self.assertEqual(StudyActivity.objects.count(), events)
        session.refresh_from_db()
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(session.attempts.count(), 1)
        self.assertEqual(self.user.topic_completions.count(), 5)
        other_topic = session.topics.exclude(pk=missed.pk).first()
        self.assertEqual(self.client.get(reverse('scholars:study_passed_review', args=[session.pk, other_topic.topic_id])).status_code, 404)
        other = User.objects.create_user('review-other', 'Password-123!', must_change_password=False)
        self.client.force_login(other)
        self.assertEqual(self.client.get(review_url).status_code, 404)

    def test_old_duplicate_only_misses_finish_without_empty_retry(self):
        from django.utils import timezone
        from .models import StudyAttempt, StudyQuestion
        session = self.start()
        # Emulate saved pre-fix history: each remaining miss is a duplicate of
        # another already-correct answer. Original scores must remain unchanged.
        first, second = list(StudyQuestion.objects.filter(session_topic__session=session)
                             .select_related('revision')[:2])
        second.revision.payload = first.revision.payload
        second.revision.save()
        attempt = StudyAttempt.objects.create(session=session, number=1, score=1, completed_at=timezone.now())
        StudyAnswer.objects.create(attempt=attempt, question=first, position=1,
            typed_answer=first.revision.payload['correct_answer'], is_correct=True, answered_at=timezone.now())
        StudyAnswer.objects.create(attempt=attempt, question=second, position=2,
            typed_answer='Wrong', is_correct=False, answered_at=timezone.now())
        # Other pinned questions were already mastered in a prior attempt.
        prior = StudyAttempt.objects.create(session=session, number=0, score=13, completed_at=timezone.now())
        for position, question in enumerate(StudyQuestion.objects.filter(session_topic__session=session).exclude(pk__in=[first.pk, second.pk]).select_related('revision'), 1):
            StudyAnswer.objects.create(attempt=prior, question=question, position=position,
                typed_answer=question.revision.payload['correct_answer'], is_correct=True, answered_at=timezone.now())
        session.phase = 'review'
        session.review_topic_ids = [second.session_topic.topic_id]
        session.save()
        page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertContains(page, 'Finish this review')
        self.assertNotContains(page, '0/0')
        session = finish_reading(self.user, session)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(session.attempts.count(), 2)
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 1)
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), 'All remaining questions were answered correctly earlier')
