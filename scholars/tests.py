import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from accounts.models import User
from .importer import import_content
from .models import Category, ContentImport, PracticeSession, Question, QuestionRevision, Source, Subcategory, Topic, TopicRedirect
from .services import answer_question, start_session
from .test_helpers import small_dataset

def recognition_session(*args, **kwargs):
    return start_session(*args, mode="recognition", **kwargs)


PASSWORD = "Cedar-scholars-practice-682!"


class PracticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        cls.user = User.objects.create_user("learner", PASSWORD, must_change_password=False)
        cls.other = User.objects.create_user("other-learner", PASSWORD, must_change_password=False)
        cls.admin = User.objects.create_superuser("administrator", PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, **scope):
        response = self.client.post(reverse("scholars:start"), {"mode": "recognition", "request_key": uuid.uuid4(), **scope})
        self.assertEqual(response.status_code, 302)
        return PracticeSession.objects.filter(user=self.user).latest("started_at")

    def answer(self, session, position, correct=True):
        item = session.items.select_related("revision").get(position=position)
        correct_index = item.choices.index(item.revision.payload["correct_answer"])
        value = correct_index if correct else (correct_index + 1) % 4
        response = self.client.post(reverse("scholars:answer", args=[session.pk, position]),
                                    {"selected": value, "is_correct": "true", "score": "999", "user": str(self.other.pk)})
        self.assertEqual(response.status_code, 302)
        return item

    def test_ten_question_selection_is_distinct_and_server_scored(self):
        session = self.start()
        self.assertEqual(session.total, 10)
        self.assertEqual(session.items.values("revision").distinct().count(), 10)
        for position in range(1, 11):
            self.answer(session, position, correct=position % 2 == 0)
        session.refresh_from_db()
        self.assertEqual(session.score, 5)
        self.assertEqual(session.answered, 10)
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(self.other.practice_sessions.count(), 0)
        self.assertContains(self.client.get(reverse("scholars:results", args=[session.pk])), "Session complete")

    def test_small_scope_uses_actual_denominator_and_preserves_choice_permutation(self):
        topic = Topic.objects.first()
        session = self.start(topic=topic.pk)
        self.assertEqual(session.total, Question.objects.filter(topic=topic).count())
        self.assertLess(session.total, 10)
        for item in session.items.select_related("revision"):
            self.assertEqual(item.revision.question.topic_id, topic.pk)
            self.assertCountEqual(item.choices, [item.revision.payload["correct_answer"], *item.revision.payload["distractors"]])

    def test_category_and_overlapping_subcategory_selection(self):
        topic = Topic.objects.first()
        session = self.start(category=topic.category_id, subcategory=topic.payload["subcategory_ids"][0])
        self.assertTrue(session.total > 0)
        for item in session.items.select_related("revision"):
            self.assertEqual(item.revision.context["topic"]["primary_category"], topic.category_id)
            self.assertIn(topic.payload["subcategory_ids"][0], item.revision.context["topic"]["subcategory_ids"])

    def test_empty_scope_has_message_and_creates_no_session(self):
        response = self.client.post(reverse("scholars:start"), {"mode": "recognition", "request_key": uuid.uuid4(), "topic": "does-not-exist"}, follow=True)
        self.assertContains(response, "No practice questions")
        self.assertEqual(PracticeSession.objects.count(), 0)

    def test_duplicate_start_and_answers_are_idempotent(self):
        key = uuid.uuid4()
        for _ in range(2):
            self.client.post(reverse("scholars:start"), {"mode": "recognition", "request_key": key})
        self.assertEqual(PracticeSession.objects.count(), 1)
        session = PracticeSession.objects.get()
        self.answer(session, 1, correct=False)
        first = session.items.get(position=1)
        self.answer(session, 1, correct=True)
        repeated = session.items.get(position=1)
        self.assertEqual(first.selected, repeated.selected)
        self.assertEqual(first.answered_at, repeated.answered_at)
        self.assertEqual(session.answered, 1)
        self.assertEqual(session.score, 0)

    def test_invalid_and_out_of_order_answers_cannot_change_results(self):
        session = self.start()
        for choice in ["-1", "4", "999", "not-a-number", ""]:
            self.assertEqual(self.client.post(reverse("scholars:answer", args=[session.pk, 1]), {"selected": choice}).status_code, 400)
        self.assertEqual(self.client.post(reverse("scholars:answer", args=[session.pk, 2]), {"selected": 0}).status_code, 400)
        self.assertEqual(session.answered, 0)
        self.assertEqual(self.client.get(reverse("scholars:answer", args=[session.pk, 1])).status_code, 405)

    def test_cross_account_access_and_admin_write_are_denied(self):
        session = self.start()
        self.answer(session, 1)
        paths = [reverse("scholars:session", args=[session.pk]), reverse("scholars:results", args=[session.pk]),
                 reverse("scholars:feedback", args=[session.pk, 1]), reverse("scholars:evidence", args=[session.pk, 1])]
        self.client.force_login(self.other)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(reverse("scholars:answer", args=[session.pk, 2]), {"selected": 0}).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("scholars:results", args=[session.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("scholars:evidence", args=[session.pk, 1])).status_code, 200)
        self.assertEqual(self.client.post(reverse("scholars:answer", args=[session.pk, 2]), {"selected": 0}).status_code, 404)

    def test_unanswered_question_feedback_and_answer_key_are_not_exposed(self):
        session = self.start()
        item = session.items.select_related("revision").first()
        response = self.client.get(reverse("scholars:session", args=[session.pk]))
        self.assertNotContains(response, item.revision.payload["explanation"])
        for route in ["scholars:feedback", "scholars:evidence"]:
            self.assertEqual(self.client.get(reverse(route, args=[session.pk, 1])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("scholars:results", args=[session.pk])), item.revision.payload["question"])

    def test_interrupted_session_resumes_after_logout_and_on_new_device(self):
        session = self.start()
        self.answer(session, 1)
        self.client.post(reverse("logout"))
        browser = Client()
        self.assertTrue(browser.login(username=self.user.username, password=PASSWORD))
        response = browser.get(reverse("scholars:session", args=[session.pk]))
        self.assertEqual(response.context["item"].position, 2)
        self.assertEqual(session.answered, 1)
        self.assertIsNone(PracticeSession.objects.get(pk=session.pk).completed_at)
        self.assertContains(browser.get(reverse("scholars:history")), "1 / 10 answered")

    def test_complete_vertical_journey_including_rename_and_second_device(self):
        browser = Client()
        browser.force_login(self.admin)
        browser.post(reverse("students"), {"username": "new-scholar", "password": "Temporary-journey-839!"})
        browser.post(reverse("logout"))
        response = browser.post(reverse("login"), {"username": "new-scholar", "password": "Temporary-journey-839!"}, follow=True)
        self.assertContains(response, "Change temporary password")
        browser.post(reverse("password_change"), {"old_password": "Temporary-journey-839!", "new_password1": PASSWORD, "new_password2": PASSWORD})
        original_id = User.objects.get(username="new-scholar").pk
        browser.post(reverse("scholars:start"), {"mode": "recognition", "request_key": uuid.uuid4(), "topic": Topic.objects.first().pk})
        session = PracticeSession.objects.get(user_id=original_id)
        for item in session.items.select_related("revision"):
            browser.post(reverse("scholars:answer", args=[session.pk, item.position]),
                         {"selected": item.choices.index(item.revision.payload["correct_answer"])})
        browser.post(reverse("account"), {"username": "renamed-scholar"})
        browser.post(reverse("logout"))
        device = Client()
        device.post(reverse("login"), {"username": "renamed-scholar", "password": PASSWORD})
        response = device.get(reverse("scholars:results", args=[session.pk]))
        self.assertContains(response, "Session complete")
        self.assertEqual(User.objects.get(username="renamed-scholar").pk, original_id)
        self.assertEqual(session.score, session.total)
        self.assertEqual(session.answered, session.total)

    def test_library_topics_attribution_and_redirects_render(self):
        for route in ["home", "scholars:dashboard", "scholars:library", "scholars:history", "scholars:attribution"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        topic = Topic.objects.exclude(study_content={}).first()
        response = self.client.get(reverse("scholars:topic", args=[topic.pk]))
        self.assertContains(response, "Study-note attribution")
        self.assertContains(response, topic.study_content["source"]["title"])
        self.assertEqual(self.client.get(reverse("scholars:topic", args=["legacy-topic"])).status_code, 301)

    def test_category_change_clears_incompatible_subcategory(self):
        response = self.client.get(reverse("scholars:library"), {"category": "Science and Technology", "subcategory": "arts-001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["subcategory"], "")

    def test_deleted_student_removes_history_but_not_content(self):
        session = self.start()
        self.answer(session, 1)
        self.user.delete()
        self.assertFalse(PracticeSession.objects.filter(pk=session.pk).exists())
        self.assertGreater(QuestionRevision.objects.count(), 0)


class ImportTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.data = small_dataset(self.path)
        import_content(self.path)
        self.user = User.objects.create_user("import-learner", PASSWORD, must_change_password=False)

    def write(self, name, value):
        (self.path / name).write_text(json.dumps(value))

    def test_repeat_import_preserves_ids_counts_history_and_revisions(self):
        session = recognition_session(self.user, uuid.uuid4(), {})
        answer_question(self.user, session.pk, 1, 0)
        before = list(Question.objects.order_by("id").values_list("id", "current_revision_id"))
        import_content(self.path)
        self.assertEqual(before, list(Question.objects.order_by("id").values_list("id", "current_revision_id")))
        self.assertEqual(QuestionRevision.objects.count(), Question.objects.count())
        self.assertEqual(session.answered, 1)

    def test_content_edit_creates_revision_without_changing_inflight_or_saved_results(self):
        q = Question.objects.first()
        session = recognition_session(self.user, uuid.uuid4(), {"topic": q.topic_id})
        old = session.items.select_related("revision").first()
        answer_question(self.user, session.pk, 1, old.choices.index(old.revision.payload["correct_answer"]))
        questions = self.data["practice/01.json"]
        target = next(q for q in questions if q["question_id"] == old.revision.question_id)
        target["correct_answer"] = "Revised answer text"
        target["explanation"] = "Revised explanation."
        self.write("practice/01.json", questions)
        import_content(self.path)
        current = Question.objects.get(pk=target["question_id"])
        self.assertNotEqual(current.current_revision_id, old.revision_id)
        old.refresh_from_db()
        self.assertNotEqual(old.revision.payload["explanation"], "Revised explanation.")
        self.assertTrue(old.is_correct)
        self.assertEqual(session.score, 1)

    def test_source_attribution_changes_are_versioned(self):
        question = Question.objects.first()
        revision = question.current_revision
        sid = next(iter(revision.context["sources"]))
        self.data["sources.json"][sid]["source"] = "Updated source attribution"
        self.write("sources.json", self.data["sources.json"])
        import_content(self.path)
        question.refresh_from_db()
        self.assertNotEqual(question.current_revision_id, revision.pk)
        self.assertNotEqual(revision.context["sources"][sid]["source"], "Updated source attribution")

    def test_enriched_notes_preserve_inflight_revision_and_render_unlicensed_citation(self):
        question = Question.objects.first()
        session = recognition_session(self.user, uuid.uuid4(), {"topic": question.topic_id})
        item = session.items.select_related("revision").first()
        original_context = item.revision.context
        study = {
            "overview": [{"id": "o1", "text": "An original researched overview.", "source_urls": ["https://example.org/study"]}],
            "key_facts": [{"id": "f1", "text": "A supported study fact.", "source_urls": ["https://example.org/study"]}],
            "source": {"references": [{"title": "Research source", "publisher": "Source publisher", "url": "https://example.org/study"}]},
        }
        self.data["content.json"][question.topic_id] = study
        self.write("content.json", self.data["content.json"])
        import_content(self.path)
        question.refresh_from_db()
        item.refresh_from_db()
        self.assertNotEqual(question.current_revision_id, item.revision_id)
        self.assertEqual(item.revision.context, original_context)
        self.assertEqual(question.current_revision.context["study_content"], study)
        self.client.force_login(self.user)
        response = self.client.get(reverse("scholars:topic", args=[question.topic_id]))
        self.assertContains(response, "An original researched overview.")
        self.assertContains(response, "A supported study fact.")
        self.assertContains(response, 'href="https://example.org/study"')
        self.assertNotContains(response, 'href=""')
        import_content(self.path)
        self.assertEqual(Question.objects.get(pk=question.pk).current_revision_id, question.current_revision_id)

    def test_invalid_import_does_not_modify_database(self):
        self.data["practice/01.json"][0]["evidence_ids"] = ["missing-evidence"]
        self.write("practice/01.json", self.data["practice/01.json"])
        with self.assertRaises(ValueError):
            import_content(self.path)
        self.assertEqual(ContentImport.objects.count(), 1)
        self.assertEqual(Question.objects.count(), len(self.data["practice/01.json"]))

    def test_failed_write_rolls_back_entire_import(self):
        old = Category.objects.first().payload
        self.data["taxonomy.json"]["categories"][0]["test_metadata"] = "This change must roll back."
        self.write("taxonomy.json", self.data["taxonomy.json"])
        with patch("scholars.importer.QuestionRevision.objects.bulk_create", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                import_content(self.path)
        self.assertEqual(Category.objects.first().payload, old)
        self.assertEqual(ContentImport.objects.count(), 1)

    def test_inflight_answer_uses_original_revision_after_content_change(self):
        session = recognition_session(self.user, uuid.uuid4(), {})
        item = session.items.select_related("revision").first()
        original_correct = item.choices.index(item.revision.payload["correct_answer"])
        questions = self.data["practice/01.json"]
        target = next(q for q in questions if q["question_id"] == item.revision.question_id)
        target["correct_answer"] = "A changed answer after the session began"
        self.write("practice/01.json", questions)
        import_content(self.path)
        answer_question(self.user, session.pk, item.position, original_correct)
        item.refresh_from_db()
        self.assertTrue(item.is_correct)
        self.assertEqual(session.score, 1)

    def test_removals_require_explicit_retirement_and_preserve_quiz(self):
        topic = Topic.objects.exclude(pk="legacy-topic").last()
        session = recognition_session(self.user, uuid.uuid4(), {"topic": topic.pk})
        self.write("topics.json", [t for t in self.data["topics.json"] if t["study_topic_id"] != topic.pk])
        self.write("content.json", {k: v for k, v in self.data["content.json"].items() if k != topic.pk})
        self.write("practice/01.json", [q for q in self.data["practice/01.json"] if q["study_topic_id"] != topic.pk])
        self.write("topic-redirects.json", {})
        with self.assertRaises(ValidationError):
            import_content(self.path)
        self.assertTrue(Topic.objects.get(pk=topic.pk).active)
        import_content(self.path, allow_retire=True)
        self.assertFalse(Topic.objects.get(pk=topic.pk).active)
        self.assertFalse(Question.objects.filter(topic=topic, active=True).exists())
        answer_question(self.user, session.pk, 1, 0)
        self.assertEqual(session.answered, 1)

    def test_reusing_topic_identity_for_other_subject_is_rejected(self):
        self.data["topics.json"][0]["subject_id"] = "a-different-subject"
        self.write("topics.json", self.data["topics.json"])
        with self.assertRaises(ValidationError):
            import_content(self.path)
        self.assertEqual(ContentImport.objects.count(), 1)

    def test_duplicate_question_ids_are_rejected_before_writes(self):
        questions = self.data["practice/01.json"]
        questions[1]["question_id"] = questions[0]["question_id"]
        self.write("practice/01.json", questions)
        with self.assertRaises(ValueError):
            import_content(self.path)
        self.assertEqual(ContentImport.objects.count(), 1)


class FullContentTests(TestCase):
    def test_complete_real_dataset_matches_authoritative_payloads_twice(self):
        root = settings.BASE_DIR / "data"
        counts = import_content(root)
        expected = json.loads((root / "import-manifest.json").read_text())["counts"]
        self.assertGreaterEqual(counts["detailed_pages"], expected["detailed_pages"])
        self.assertEqual({key: counts[key] for key in expected if key != "detailed_pages"},
                         {key: value for key, value in expected.items() if key != "detailed_pages"})
        self.assertEqual(counts["subjects"], 6906)
        self.assertEqual(import_content(root), counts)
        self.assertEqual(QuestionRevision.objects.count(), 10976)
        self.assertEqual({t.pk: t.payload for t in Topic.objects.all()},
                         {t["study_topic_id"]: t for t in json.loads((root / "topics.json").read_text())})
        self.assertEqual({s.pk: s.payload for s in Source.objects.all()}, json.loads((root / "sources.json").read_text()))
        self.assertEqual({t.pk: t.study_content for t in Topic.objects.exclude(study_content={})}, json.loads((root / "content.json").read_text()))
        self.assertEqual({r.pk: r.topic_id for r in TopicRedirect.objects.all()}, json.loads((root / "topic-redirects.json").read_text()))
        taxonomy = json.loads((root / "taxonomy.json").read_text())
        self.assertEqual({c.pk: c.payload for c in Category.objects.all()}, {c["primary_category"]: c for c in taxonomy["categories"]})
        self.assertEqual({s.pk: s.payload for s in Subcategory.objects.all()}, {s["subcategory_id"]: s for s in taxonomy["subcategories"]})
        for topic in Topic.objects.prefetch_related("subcategories"):
            self.assertEqual({s.pk for s in topic.subcategories.all()}, set(topic.payload["subcategory_ids"]))
        self.assertEqual({q.pk: q.current_revision.payload for q in Question.objects.select_related("current_revision")},
                         {q["question_id"]: q for p in (root / "practice").glob("*.json") for q in json.loads(p.read_text())})


class ConcurrentPracticeTests(TransactionTestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as directory:
            small_dataset(directory)
            import_content(directory)
        self.user = User.objects.create_user("concurrent-learner", PASSWORD, must_change_password=False)

    def parallel(self, fn):
        barrier = Barrier(2)
        def work():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                return fn(user)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _: work(), range(2)))

    def test_concurrent_duplicate_starts_create_one_session(self):
        key = uuid.uuid4()
        ids = self.parallel(lambda user: recognition_session(user, key, {}).pk)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(PracticeSession.objects.count(), 1)
        self.assertEqual(PracticeSession.objects.get().total, 10)

    def test_concurrent_final_answers_complete_once(self):
        single = next(t for t in Topic.objects.all() if Question.objects.filter(topic=t).count() == 1)
        session = recognition_session(self.user, uuid.uuid4(), {"topic": single.pk})
        ids = self.parallel(lambda user: answer_question(user, session.pk, 1, 0).pk)
        self.assertEqual(ids[0], ids[1])
        session.refresh_from_db()
        self.assertEqual(session.answered, 1)
        self.assertIsNotNone(session.completed_at)
