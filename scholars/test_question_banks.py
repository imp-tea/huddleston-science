import json
from pathlib import Path
import tempfile
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from .importer import import_content
from .models import Question, QuestionRevision, ReviewState
from .reviews import current_reviews, review_summary
from .services import start_session, answer_question, reveal_question
from .test_helpers import small_dataset


class SeparateQuestionBankTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        data = small_dataset(self.path)
        self.ids = {t['study_topic_id'] for t in data['topics.json']}
        self.typed = [q for q in json.loads((settings.BASE_DIR/'data/typed-questions.json').read_text()) if q['study_topic_id'] in self.ids]
        import_content(self.path)
        self.user = User.objects.create_user('bank-student', 'Bank-test-password!', must_change_password=False)
        self.client.force_login(self.user)

    def install(self):
        (self.path/'typed-questions.json').write_text(json.dumps(self.typed))
        return import_content(self.path)

    def test_new_sessions_and_progress_use_the_correct_bank(self):
        before = dict(Question.objects.values_list('pk', 'current_revision_id'))
        counts = self.install()
        for mode, expected in [('typed','typed'), ('recall','typed'), ('recognition','multiple_choice')]:
            session = start_session(self.user, uuid.uuid4(), {}, mode)
            for item in session.items.select_related('revision__question', 'answer_bank'):
                self.assertEqual(item.revision.question.format, expected)
                self.assertEqual(len(item.choices), 4 if mode == 'recognition' else 0)
                if mode == 'typed':
                    self.assertIn(item.revision.payload['correct_answer'], item.answer_bank.answers)
            summary = next(s for s in review_summary(self.user) if s['mode'] == mode)
            self.assertEqual(summary['total']['questions'], counts['typed_questions' if expected == 'typed' else 'multiple_choice_questions'])
        for qid,rid in before.items():self.assertEqual(Question.objects.get(pk=qid).current_revision_id,rid)
        count = QuestionRevision.objects.count()
        self.assertEqual(import_content(self.path),counts)
        self.assertEqual(QuestionRevision.objects.count(),count)

    def test_old_typed_session_and_pinned_bank_survive_import(self):
        session = start_session(self.user,uuid.uuid4(),{},'typed')
        item = session.items.select_related('revision','answer_bank').get(position=1)
        rid, bank = item.revision_id, item.answer_bank_id
        self.install()
        result = answer_question(self.user,session.pk,1,typed_answer=item.revision.payload['correct_answer'])
        self.assertTrue(result.is_correct)
        self.assertEqual((result.revision_id,result.answer_bank_id),(rid,bank))
        self.assertEqual(result.attempt_kind,'historical')
        self.assertFalse(ReviewState.objects.filter(revision_id=rid).exists())
        self.assertEqual(self.client.get(reverse('scholars:results',args=[session.pk])).status_code,200)

    def test_new_typed_and_recall_scoring_without_choices_or_explanations(self):
        self.install()
        for mode in ('typed','recall'):
            session = start_session(self.user,uuid.uuid4(),{},mode)
            item = session.items.select_related('revision').get(position=1)
            self.assertEqual(self.client.get(reverse('scholars:session',args=[session.pk])).status_code,200)
            if mode == 'typed':
                result = answer_question(self.user,session.pk,1,typed_answer=item.revision.payload['correct_answer'])
                self.assertTrue(result.is_correct)
            else:
                reveal_question(self.user,session.pk,1)
                result = answer_question(self.user,session.pk,1,self_assessment=True)
                self.assertTrue(result.self_assessment)
            self.assertEqual(result.attempt_kind,'first')

    def test_old_due_reviews_no_longer_pollute_new_bank(self):
        session = start_session(self.user,uuid.uuid4(),{},'typed')
        item = session.items.select_related('revision').get(position=1)
        answer_question(self.user,session.pk,1,typed_answer=item.revision.payload['correct_answer'])
        self.assertTrue(current_reviews(self.user,'typed').exists())
        self.install()
        self.assertFalse(current_reviews(self.user,'typed').exists())
        self.assertTrue(ReviewState.objects.filter(revision=item.revision).exists())

    def test_omitted_bank_is_not_silently_retired(self):
        self.install(); (self.path/'typed-questions.json').unlink()
        with self.assertRaises(ValidationError):import_content(self.path)
        self.assertEqual(Question.objects.filter(format='typed',active=True).count(),len(self.typed))
        import_content(self.path,allow_retire=True)
        self.assertFalse(Question.objects.filter(format='typed',active=True).exists())
        self.assertTrue(start_session(self.user,uuid.uuid4(),{},'typed').items.exists())

    def test_bad_typed_payload_fails_before_writes(self):
        count = Question.objects.count()
        for mutate in (lambda rows: rows.pop(), lambda rows: rows[0].update(answer='x'*241),
                       lambda rows: rows[0].update(question_id=rows[1]['question_id'])):
            rows = json.loads(json.dumps(self.typed)); mutate(rows)
            (self.path/'typed-questions.json').write_text(json.dumps(rows))
            with self.assertRaises(ValueError):import_content(self.path)
            self.assertEqual(Question.objects.count(),count)
