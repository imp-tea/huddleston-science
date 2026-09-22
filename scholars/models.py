import uuid
from django.conf import settings
from django.db import models


class Category(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    payload = models.JSONField()
    active = models.BooleanField(default=True)


class Subcategory(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    payload = models.JSONField()
    active = models.BooleanField(default=True)


class Source(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    payload = models.JSONField()
    active = models.BooleanField(default=True)


class Topic(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    subject_id = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=500)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    subcategories = models.ManyToManyField(Subcategory)
    payload = models.JSONField()
    study_content = models.JSONField(default=dict)
    active = models.BooleanField(default=True)


class TopicRedirect(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)


class Question(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT)
    current_revision = models.ForeignKey("QuestionRevision", on_delete=models.PROTECT, null=True, related_name="+")
    active = models.BooleanField(default=True)


class QuestionRevision(models.Model):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="revisions")
    digest = models.CharField(max_length=64)
    payload = models.JSONField()
    # Snapshot topic, study prose, and referenced source attribution as well as question text.
    context = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["question", "digest"], name="unique_question_revision")]


class ContentImport(models.Model):
    digest = models.CharField(max_length=64)
    counts = models.JSONField()
    imported_at = models.DateTimeField(auto_now_add=True)


class PracticeSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_sessions")
    request_key = models.UUIDField()
    scope = models.JSONField(default=dict)
    mode = models.CharField(max_length=20, default="recognition", editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "request_key"], name="unique_session_request")]

    @property
    def score(self):
        return self.items.filter(is_correct=True).count()

    @property
    def total(self):
        return self.items.count()

    @property
    def answered(self):
        return self.items.filter(answered_at__isnull=False).count()


class SessionQuestion(models.Model):
    session = models.ForeignKey(PracticeSession, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveSmallIntegerField()
    revision = models.ForeignKey(QuestionRevision, on_delete=models.PROTECT)
    choices = models.JSONField()
    selected = models.PositiveSmallIntegerField(null=True)
    is_correct = models.BooleanField(null=True)
    answered_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_session_position"),
            models.UniqueConstraint(fields=["session", "revision"], name="unique_session_question"),
            models.CheckConstraint(condition=models.Q(selected__isnull=True) | models.Q(selected__gte=0, selected__lte=3), name="valid_choice_index"),
            models.CheckConstraint(condition=(models.Q(selected__isnull=True, is_correct__isnull=True, answered_at__isnull=True) |
                                              models.Q(selected__isnull=False, is_correct__isnull=False, answered_at__isnull=False)), name="complete_answer_record"),
        ]

    @property
    def selected_text(self):
        return self.choices[self.selected] if self.selected is not None else ""
