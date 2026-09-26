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
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from .importer import import_content
from .models import (AnswerBank, Category, Question, QuestionRevision, StudyActivity, StudyAnswer,
                     StudyAttempt, StudyPreferences, StudyQuestion, StudySession, StudySessionTopic,
                     Subcategory, Topic, TopicCompletion)
from .study import (abandon_study, active_session, move_reading, picker, reading_topics,
                    save_interests, start_study, submit_answer)
from .test_helpers import small_dataset


def seed_study():
    user = User.objects.create_user('study-student', 'Study-password!', must_change_password=False)
    bank = AnswerBank.objects.create(pk='study-bank', category='Geography', answers=[f'Canonical {i} number {j}' for i in range(6) for j in range(3)])
    category = Category.objects.create(pk='Geography', payload={}, typed_bank=bank)
    other = Category.objects.create(pk='Literature', payload={}, typed_bank=bank)
    subs = [Subcategory.objects.create(pk=f'sub-{i:02}', category=category, payload={'label': f'Subject {i}'}) for i in range(25)]
    small = Subcategory.objects.create(pk='small', category=category, payload={'label': 'Small subject'})
    for i in range(6):
        topic = Topic.objects.create(pk=f'topic-{i}', subject_id=f'subject-{i}', category=category, title=f'Topic {i}',
                                    payload={'description': f'Short description {i}', 'source_ids': []})
        topic.subcategories.set(subs + ([small] if i == 0 else []))
        for j in range(3):
            q = Question.objects.create(pk=f'q-{i}-{j}', format='typed', topic=topic)
            revision = QuestionRevision.objects.create(question=q, digest=f'digest-{i}-{j}',
                payload={'question': f'Prompt {i} / {j}?', 'correct_answer': f'Canonical {i} number {j}', 'study_topic_id': topic.pk},
                context={'topic': {'topic': topic.title, 'description': f'Short description {i}'}, 'study_content': {}, 'sources': {}})
            q.current_revision = revision
            q.save()
    save_interests(user, ['Geography'])
    return user


def finish_reading(user, session):
    session.refresh_from_db()
    while session.phase in {'reading', 'review'}:
        session = move_reading(user, session.pk, session.version, 'next')
    return session


def answer_attempt(user, session, misses=0):
    attempt = session.attempts.order_by('-number').first()
    for i, item in enumerate(attempt.answers.select_related('question__revision')):
        session, prompted = submit_answer(user, session.pk, item.pk,
            'Entirely unrelated response' if i < misses else item.question.revision.payload['correct_answer'])
        assert not prompted
    return session


class StudyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = seed_study()
        cls.other = User.objects.create_user('study-other', 'Other-password!', must_change_password=False)

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, sub='sub-00'):
        return start_study(self.user, uuid.uuid4(), sub)

    def test_onboarding_account_validation_and_cross_device_interests(self):
        self.client.force_login(self.other)
        self.assertRedirects(self.client.get(reverse('scholars:dashboard')), reverse('scholars:interests'))
        for values in [[], ['missing'], ['Geography', 'missing']]:
            response = self.client.post(reverse('scholars:interests'), {'categories': values})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(StudyPreferences.objects.filter(user=self.other).exists())
        self.client.post(reverse('scholars:interests'), {'categories': ['Geography', 'Literature'], 'user': self.user.pk})
        device = Client()
        device.force_login(self.other)
        self.assertContains(device.get(reverse('scholars:dashboard')), 'Learn a few random topics and take a quiz!')
        account = device.get(reverse('account'))
        self.assertEqual(account.context['interests_form'].initial['categories'], ['Geography', 'Literature'])
        self.assertEqual(StudyPreferences.objects.get(user=self.user).categories.count(), 1)

    def test_picker_ten_distinct_reshuffle_filters_and_completed_exclusion(self):
        first = picker(self.user)
        second = picker(self.user, [s.pk for s in first])
        self.assertEqual(len(first), 10)
        self.assertEqual(len(set(s.pk for s in second)), 10)
        self.assertFalse(set(s.pk for s in first) & set(s.pk for s in second))
        self.assertTrue(all(s.category_id == 'Geography' for s in second))
        passed = answer_attempt(self.user, finish_reading(self.user, self.start()))
        self.assertEqual(passed.phase, 'passed')
        choices = picker(self.user)
        self.assertTrue(all(s.session_size == 1 for s in choices))
        remaining = self.start()
        self.assertEqual(remaining.topics.count(), 1)
        self.assertFalse(remaining.topics.filter(topic_id__in=passed.topics.values('topic_id')).exists())
        answer_attempt(self.user, finish_reading(self.user, remaining))
        self.assertEqual(picker(self.user), [])
        self.assertContains(self.client.get(reverse('scholars:study')), 'All selected topics complete')

    def test_start_scope_idempotency_pinned_pool_and_one_active(self):
        key = uuid.uuid4()
        session = start_study(self.user, key, 'sub-00')
        self.assertEqual(start_study(self.user, key, 'sub-01').pk, session.pk)
        self.assertEqual(session.topics.count(), 5)
        self.assertEqual(StudyQuestion.objects.count(), 15)
        with self.assertRaises(ValidationError):
            self.start()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudySession.objects.create(user=self.user, request_key=uuid.uuid4(), subcategory_id='sub-00', subcategory_label='X', category_label='Geography')
        save_interests(self.other, ['Literature'])
        with self.assertRaises(ValidationError):
            start_study(self.other, uuid.uuid4(), 'sub-00')
        self.assertFalse(self.other.study_sessions.exists())

    def test_read_position_back_duplicates_and_restart_invalidate_stale_tabs(self):
        session = self.start()
        first = session.topics.first().content
        session = move_reading(self.user, session.pk, 0, 'next')
        with self.assertRaises(ValidationError):
            move_reading(self.user, session.pk, 0, 'next')
        self.assertEqual(session.reading_position, 1)
        device = Client()
        device.force_login(self.user)
        page = device.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertContains(page, 'Topic 2 of 5')
        self.assertContains(device.get(reverse('scholars:study')), 'Resume Previous Session')
        session = move_reading(self.user, session.pk, session.version, 'back')
        self.assertEqual(reading_topics(session)[session.reading_position].content, first)
        abandon_study(self.user, session.pk)
        with self.assertRaises(ValidationError):
            move_reading(self.user, session.pk, session.version, 'next')
        newer = self.start()
        abandon_study(self.user, session.pk)
        self.assertEqual(active_session(self.user).pk, newer.pk)
        self.assertFalse(TopicCompletion.objects.exists())

    def test_interest_changes_preserve_session_and_completions(self):
        session = self.start()
        topics = list(session.topics.values_list('topic_id', flat=True))
        save_interests(self.user, ['Literature'])
        self.assertEqual(list(session.topics.values_list('topic_id', flat=True)), topics)
        passed = answer_attempt(self.user, finish_reading(self.user, session))
        self.assertEqual(passed.phase, 'passed')
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertEqual(picker(self.user), [])
        save_interests(self.user, ['Geography'])
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertTrue(picker(self.user))

    def test_failed_quiz_review_dedup_retry_priority_and_atomic_passing(self):
        session = finish_reading(self.user, self.start())
        attempt = session.attempts.get()
        initial = list(attempt.answers.values_list('question_id', flat=True))
        # Miss two questions from one topic to exercise deduplication.
        by_topic = {}
        for answer in attempt.answers.select_related('question'):
            by_topic.setdefault(answer.question.session_topic_id, []).append(answer.pk)
        misses = next(iter(by_topic.values()))
        for item in attempt.answers.select_related('question__revision'):
            session, _ = submit_answer(self.user, session.pk, item.pk,
                'Wrong response' if item.pk in misses else item.question.revision.payload['correct_answer'])
        self.assertEqual(session.phase, 'review')
        self.assertEqual(len(session.review_topic_ids), 1)
        self.assertFalse(TopicCompletion.objects.exists())
        page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertContains(page, '8/10')
        self.assertEqual(len(page.context['missed_topics']), 1)
        missed_qids = set(attempt.answers.filter(pk__in=misses).values_list('question_id', flat=True))
        session = finish_reading(self.user, session)
        retry = session.attempts.get(number=2)
        retried = set(retry.answers.values_list('question_id', flat=True))
        unused = set(StudyQuestion.objects.values_list('pk', flat=True)) - set(initial)
        self.assertEqual(len(retried), 7)
        self.assertFalse(retried & set(attempt.answers.filter(is_correct=True).values_list("question_id", flat=True)))
        self.assertTrue(missed_qids <= retried)
        self.assertTrue(unused <= retried)
        page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
        self.assertContains(page, 'Question 1 of 7')
        self.assertEqual(page.context['passing_score'], 7)
        session = answer_attempt(self.user, session)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)
        last = retry.answers.last()
        before = session.completed_at
        submit_answer(self.user, session.pk, last.pk, 'changed')
        session.refresh_from_db()
        self.assertEqual(session.completed_at, before)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertTrue(all(c.completed_at == before for c in self.user.topic_completions.all()))

    def test_short_session_threshold_and_unlimited_missed_only_retries(self):
        # Two available questions leave no unused pool on any retry.
        Question.objects.filter(topic_id='topic-0', pk='q-0-2').update(active=False)
        session = finish_reading(self.user, self.start('small'))
        for _ in range(4):
            session = answer_attempt(self.user, session, misses=1)
            self.assertEqual(session.phase, 'review')
            missed = set(session.attempts.last().answers.filter(is_correct=False).values_list('question_id', flat=True))
            page = self.client.get(reverse('scholars:study_session', args=[session.pk]))
            self.assertContains(page, 'The next quiz has 1 question:')
            self.assertEqual(page.context['passing_score'], 1)
            session = finish_reading(self.user, session)
            self.assertEqual(set(session.attempts.last().answers.values_list('question_id', flat=True)), missed)
            self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), 'Question 1 of 1')
        session = answer_attempt(self.user, session)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(self.user.topic_completions.count(), 1)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)

    def test_correct_questions_stay_out_of_every_later_retry(self):
        session = answer_attempt(self.user, finish_reading(self.user, self.start()), misses=3)
        correct_ids = set()
        for misses in [2, 1, 0]:
            correct_ids.update(StudyAnswer.objects.filter(attempt__session=session, is_correct=True).values_list('question_id', flat=True))
            prior_misses = set(session.attempts.last().answers.filter(is_correct=False).values_list('question_id', flat=True))
            session = finish_reading(self.user, session)
            current = set(session.attempts.last().answers.values_list('question_id', flat=True))
            self.assertTrue(prior_misses <= current)
            self.assertFalse(current & correct_ids)
            self.assertEqual(len(current), 8 if misses == 2 else 2 if misses == 1 else 1)
            session = answer_attempt(self.user, session, misses=misses)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(self.user.topic_completions.count(), 5)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)

    def test_original_nine_of_ten_still_passes_and_reroll_precedes_cards(self):
        page = self.client.get(reverse('scholars:study')).content.decode()
        self.assertLess(page.index('Reroll'), page.index('class="study-grid"'))
        self.assertNotIn('Reshuffle', page)
        session = answer_attempt(self.user, finish_reading(self.user, self.start()), misses=1)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(self.user.topic_completions.count(), 5)

    def test_snapshot_survives_content_revision_retirement_and_bank_change(self):
        session = self.start('small')
        original = copy.deepcopy(session.topics.get().content)
        Topic.objects.filter(pk='topic-0').update(title='Edited title', study_content={'overview': [{'text': 'Replaced content'}]}, active=False)
        Topic.objects.get(pk='topic-0').subcategories.clear()
        Subcategory.objects.filter(pk='small').update(active=False)
        for question in Question.objects.filter(topic_id='topic-0'):
            revision = QuestionRevision.objects.create(question=question, digest='new-'+question.pk,
                payload={'question': 'Changed prompt', 'correct_answer': 'Changed key'}, context={})
            question.current_revision = revision
            question.active = False
            question.save()
        new_bank = AnswerBank.objects.create(pk='new-bank', category='Geography', answers=['Changed key'])
        Category.objects.filter(pk='Geography').update(typed_bank=new_bank)
        self.assertEqual(session.topics.get().content, original)
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), 'Short description 0')
        session = finish_reading(self.user, session)
        session = answer_attempt(self.user, session)
        self.assertEqual(session.phase, 'passed')
        self.assertEqual(self.user.topic_completions.get().topic_id, 'topic-0')
        self.assertTrue(session.topics.get().questions.filter(answer_bank_id='study-bank').exists())

    def test_incomplete_question_pool_rolls_back_without_excluding_short_prose(self):
        Question.objects.filter(topic_id='topic-0').exclude(pk='q-0-0').update(active=False)
        with self.assertRaises(ValidationError):
            self.start('small')
        self.assertFalse(StudySession.objects.exists())
        self.assertFalse(StudySessionTopic.objects.exists())

    def test_question_pages_secrecy_validation_skip_prompt_and_ownership(self):
        session = finish_reading(self.user, self.start('small'))
        items = list(session.attempts.get().answers.select_related('question__revision'))
        first, second = items
        url = reverse('scholars:study_answer', args=[session.pk, first.pk])
        page_url = reverse('scholars:study_session', args=[session.pk])
        page = self.client.get(page_url)
        self.assertIn('no-store', page['Cache-Control'])
        self.assertNotContains(page, 'correct_answer')
        self.assertContains(page, 'typed-bank')
        self.assertIsNone(page.context.get('answer_bank'))
        self.assertEqual(set(page.context['suggestion_data']), {'index'})
        self.assertTrue(all(set(row) == {'text', 'key', 'parts'} for row in page.context['suggestion_data']['index']))
        self.assertGreater(len(page.context['suggestion_data']['index']), len(items))
        for text in ['', ' ', 'x'*241]:
            self.assertEqual(self.client.post(url, {'typed_answer': text, 'action': 'answer'}).status_code, 400)
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, second.pk, 'Wrong response')
        response = self.client.post(url, {'typed_answer': 'Canonical', 'action': 'answer'})
        self.assertContains(response, 'Please be more specific')
        self.assertFalse(StudyAnswer.objects.filter(answered_at__isnull=False).exists())
        self.assertFalse(StudyActivity.objects.filter(kind='quiz').exists())
        self.client.post(url, {'typed_answer': first.question.revision.payload['correct_answer'], 'action': 'skip', 'is_correct': True})
        first.refresh_from_db()
        self.assertFalse(first.is_correct)
        self.assertIsNone(first.typed_answer)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(page_url).status_code, 404)
        self.assertEqual(self.client.post(url, {'action': 'skip'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('scholars:study_restart', args=[session.pk])).status_code, 404)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(url, {'action': 'skip'}).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_feedback_uses_saved_correctness_without_revealing_answer(self):
        session = finish_reading(self.user, self.start('small'))
        answers = list(session.attempts.get().answers.select_related('question__revision'))
        for item, correct in zip(answers, [False, True]):
            url = reverse('scholars:study_answer', args=[session.pk, item.pk])
            feedback = reverse('scholars:study_feedback', args=[session.pk, item.pk])
            self.assertEqual(self.client.get(feedback).status_code, 404)
            text = item.question.revision.payload['correct_answer'] if correct else 'Unrelated incorrect response'
            response = self.client.post(url, {'action': 'answer', 'typed_answer': text}, follow=True)
            self.assertEqual(response.request['PATH_INFO'], feedback)
            self.assertContains(response, '<h1 id="feedback-heading" tabindex="-1">' + ('Correct' if correct else 'Incorrect') + '</h1>', html=True)
            self.assertContains(response, 'data-quiz-continue')
            for q in answers:
                self.assertNotContains(response, q.question.revision.payload['correct_answer'])
                self.assertNotContains(response, q.question.revision.payload['question'])
            self.assertNotContains(response, 'typed-bank')
            self.assertNotContains(response, 'correct_answer')
            # Reposting with a different answer displays the original saved result.
            repeated = self.client.post(url, {'action': 'skip'}, follow=True)
            self.assertEqual(repeated.context['correct'], correct)
            self.assertEqual(StudyActivity.objects.filter(kind='quiz').count(), item.position)
        session.refresh_from_db()
        self.assertEqual(session.phase, 'review')
        self.assertContains(self.client.get(reverse('scholars:study_session', args=[session.pk])), '1/2')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(feedback).status_code, 404)

    def test_autocomplete_uses_pinned_bank_on_retry_after_import_changes(self):
        from .typed_answers import for_item
        session = finish_reading(self.user, self.start('small'))
        first = session.attempts.get().answers.select_related('question__revision', 'question__answer_bank').first()
        expected = for_item(first.question)['index']
        page_url = reverse('scholars:study_session', args=[session.pk])
        page = self.client.get(page_url)
        self.assertEqual([r['text'] for r in page.context['suggestion_data']['index']], [r['text'] for r in expected])
        bank = AnswerBank.objects.create(pk='replacement-suggestions', category='Geography', answers=['New-bank candidate'])
        Category.objects.filter(pk='Geography').update(typed_bank=bank)
        session = answer_attempt(self.user, session, misses=2)
        session = finish_reading(self.user, session)
        page = self.client.get(page_url)
        self.assertNotContains(page, 'New-bank candidate')
        self.assertContains(page, 'Canonical')
        self.assertNotContains(page, 'suppressedAnswers')

    def test_legacy_endpoints_do_not_offer_answer_key_bypasses(self):
        from .services import answer_question, reveal_question, start_session
        legacy = start_session(self.user, uuid.uuid4(), {'topic': 'topic-0'})
        page = self.client.get(reverse('scholars:session', args=[legacy.pk]))
        self.assertNotContains(page, 'typed-bank')
        for item in legacy.items.select_related('revision'):
            self.assertNotContains(page, item.revision.payload['correct_answer'])
            answer_question(self.user, legacy.pk, item.position, skip=True)
            for route in ['scholars:feedback', 'scholars:evidence']:
                response = self.client.get(reverse(route, args=[legacy.pk, item.position]))
                self.assertNotContains(response, item.revision.payload['correct_answer'])
        result = self.client.get(reverse('scholars:results', args=[legacy.pk]))
        for item in legacy.items.select_related('revision'):
            self.assertNotContains(result, item.revision.payload['correct_answer'])
        recall = start_session(self.user, uuid.uuid4(), {'topic': 'topic-0'}, mode='recall')
        reveal_question(self.user, recall.pk, 1)
        hidden = self.client.get(reverse('scholars:session', args=[recall.pk]))
        self.assertContains(hidden, 'older quiz format')
        self.assertNotContains(hidden, recall.items.first().revision.payload['correct_answer'])
        self.assertEqual(self.client.post(reverse('scholars:reveal', args=[recall.pk, 1])).status_code, 400)

    def test_atomic_completion_failure_and_abandoned_quiz(self):
        session = finish_reading(self.user, self.start('small'))
        first, last = list(session.attempts.get().answers.select_related('question__revision'))
        submit_answer(self.user, session.pk, first.pk, first.question.revision.payload['correct_answer'])
        with patch('scholars.study.TopicCompletion.objects.bulk_create', side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError):
                submit_answer(self.user, session.pk, last.pk, last.question.revision.payload['correct_answer'])
        last.refresh_from_db()
        session.refresh_from_db()
        self.assertIsNone(last.answered_at)
        self.assertEqual(session.phase, 'quiz')
        self.assertFalse(TopicCompletion.objects.exists())
        abandon_study(self.user, session.pk)
        for item in [first, last]:
            with self.assertRaises(ValidationError):
                submit_answer(self.user, session.pk, item.pk, 'Wrong response')

    def test_completion_identity_shared_membership_and_no_manual_conversion(self):
        from .services import mark_studied
        topic = Topic.objects.get(pk='topic-0')
        mark_studied(self.user, topic, True)
        self.assertFalse(TopicCompletion.objects.exists())
        session = answer_attempt(self.user, finish_reading(self.user, self.start('small')))
        self.assertEqual(self.user.topic_completions.count(), 1)
        self.assertTrue(all(s.done == 1 for s in picker(self.user)))
        self.user.delete()
        self.assertFalse(StudySession.objects.filter(pk=session.pk).exists())
        self.assertFalse(TopicCompletion.objects.exists())
        self.assertTrue(Topic.objects.filter(pk=topic.pk).exists())


class StudyConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = seed_study()

    def race(self, functions):
        barrier = Barrier(len(functions))
        def call(fn):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    fn()
                    return 'ok'
                except ValidationError:
                    return 'stale'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(call, functions))

    def test_concurrent_start_and_final_submission_award_once(self):
        keys = [uuid.uuid4(), uuid.uuid4()]
        result = self.race([lambda: start_study(self.user, keys[0], 'small'), lambda: start_study(self.user, keys[1], 'small')])
        self.assertCountEqual(result, ['ok', 'stale'])
        session = finish_reading(self.user, StudySession.objects.get())
        first, last = list(session.attempts.get().answers.select_related('question__revision'))
        submit_answer(self.user, session.pk, first.pk, first.question.revision.payload['correct_answer'])
        answer = last.question.revision.payload['correct_answer']
        result = self.race([lambda: submit_answer(self.user, session.pk, last.pk, answer)]*2)
        self.assertEqual(result, ['ok', 'ok'])
        self.assertEqual(TopicCompletion.objects.count(), 1)
        self.assertEqual(StudyActivity.objects.filter(kind='passed').count(), 1)

    def test_concurrent_read_restart_and_last_answer_restart_are_atomic(self):
        session = start_study(self.user, uuid.uuid4(), 'small')
        self.race([lambda: move_reading(self.user, session.pk, 0, 'next'), lambda: abandon_study(self.user, session.pk)])
        session.refresh_from_db()
        self.assertEqual(session.phase, 'abandoned')
        session = finish_reading(self.user, start_study(self.user, uuid.uuid4(), 'small'))
        first, last = list(session.attempts.get().answers.select_related('question__revision'))
        submit_answer(self.user, session.pk, first.pk, first.question.revision.payload['correct_answer'])
        self.race([lambda: submit_answer(self.user, session.pk, last.pk, last.question.revision.payload['correct_answer']),
                   lambda: abandon_study(self.user, session.pk)])
        session.refresh_from_db()
        self.assertIn(session.phase, ['passed', 'abandoned'])
        self.assertEqual(TopicCompletion.objects.count(), int(session.phase == 'passed'))


class StudyImportTests(TestCase):
    def test_real_import_preserves_pinned_reading_question_bank_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            data = small_dataset(directory)
            ids = {t['study_topic_id'] for t in data['topics.json']}
            typed = [q for q in json.loads((settings.BASE_DIR/'data/typed-questions.json').read_text()) if q['study_topic_id'] in ids]
            Path(directory, 'typed-questions.json').write_text(json.dumps(typed))
            import_content(directory)
            user = User.objects.create_user('import-study', 'Study-password!', must_change_password=False)
            category = Topic.objects.first().category_id
            save_interests(user, [category])
            sub = picker(user)[0]
            session = start_study(user, uuid.uuid4(), sub.pk)
            content = list(session.topics.values_list('content', flat=True))
            pinned = list(StudyQuestion.objects.values_list('revision_id', 'answer_bank_id'))
            # Import new study descriptions: live revisions change, snapshots don't.
            for topic in data['topics.json']:
                topic['description'] += ' Updated study description.'
            Path(directory, 'topics.json').write_text(json.dumps(data['topics.json']))
            import_content(directory)
            self.assertEqual(list(session.topics.values_list('content', flat=True)), content)
            self.assertEqual(list(StudyQuestion.objects.values_list('revision_id', 'answer_bank_id')), pinned)
            session = answer_attempt(user, finish_reading(user, session))
            self.assertEqual(session.phase, 'passed')
            import_content(directory)
            self.assertEqual(user.topic_completions.count(), len(content))
