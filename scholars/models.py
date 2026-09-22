import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


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
    abandoned_at = models.DateTimeField(null=True)
    selection = models.CharField(max_length=20, default="random")
    scope_label = models.CharField(max_length=500, blank=True)
    comparison_key = models.CharField(max_length=64, blank=True, db_index=True)
    is_personal_best = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "request_key"], name="unique_session_request")]

    @property
    def score(self):
        if hasattr(self, "score_count"):
            return self.score_count
        return self.items.filter(is_correct=True).count()

    @property
    def total(self):
        if hasattr(self, "total_count"):
            return self.total_count
        return self.items.count()

    @property
    def answered(self):
        if hasattr(self, "answered_count"):
            return self.answered_count
        return self.items.filter(answered_at__isnull=False).count()

    @property
    def recalled(self):
        return self.items.filter(self_assessment=True).count()

    @property
    def display_scope(self):
        return self.scope_label or self.scope.get("category") or ("Topic practice" if self.scope.get("topic") else "Mixed practice")

    @property
    def display_selection(self):
        return {"random": "Random practice", "personalized": "Personalized mix", "review": "Due reviews"}.get(self.selection, "Practice")

    @property
    def display_mode(self):
        return "Multiple choice" if self.mode == "recognition" else "Recall · self-assessed"


class SessionQuestion(models.Model):
    session = models.ForeignKey(PracticeSession, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveSmallIntegerField()
    revision = models.ForeignKey(QuestionRevision, on_delete=models.PROTECT)
    choices = models.JSONField()
    selected = models.PositiveSmallIntegerField(null=True)
    is_correct = models.BooleanField(null=True)
    answered_at = models.DateTimeField(null=True)
    corrected_previous_miss = models.BooleanField(default=False)
    revealed_at = models.DateTimeField(null=True)
    self_assessment = models.BooleanField(null=True)
    attempt_kind = models.CharField(max_length=20, blank=True)
    review_due_on = models.DateField(null=True)
    review_successes = models.PositiveSmallIntegerField(null=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_session_position"),
            models.UniqueConstraint(fields=["session", "revision"], name="unique_session_question"),
            models.CheckConstraint(condition=models.Q(selected__isnull=True) | models.Q(selected__gte=0, selected__lte=3), name="valid_choice_index"),
            models.CheckConstraint(condition=(models.Q(selected__isnull=True, is_correct__isnull=True, self_assessment__isnull=True, answered_at__isnull=True) |
                                              models.Q(selected__isnull=False, is_correct__isnull=False, self_assessment__isnull=True, answered_at__isnull=False) |
                                              models.Q(selected__isnull=True, is_correct__isnull=True, self_assessment__isnull=False, revealed_at__isnull=False, answered_at__isnull=False)), name="complete_answer_record"),
        ]

    @property
    def selected_text(self):
        return self.choices[self.selected] if self.selected is not None else ""


class StudyState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT)
    first_opened_at = models.DateTimeField(default=timezone.now)
    last_opened_at = models.DateTimeField()
    studied_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "topic"], name="unique_student_topic_state")]


class StudyPreferences(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    weekly_goal = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(weekly_goal__lte=100), name="weekly_goal_at_most_100")]


class RewardEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    answer = models.OneToOneField(SessionQuestion, on_delete=models.CASCADE, related_name="reward")
    earned_on = models.DateField()
    points = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "question", "earned_on"], name="one_question_reward_per_day"),
            models.CheckConstraint(condition=models.Q(points__in=[1, 2]), name="valid_participation_points"),
        ]


class ReviewState(models.Model):
    # Mode and exact revision are independent evidence; reimports never rewrite it.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.ForeignKey(QuestionRevision, on_delete=models.PROTECT)
    mode = models.CharField(max_length=20)
    successes = models.PositiveSmallIntegerField(default=0)
    last_evidence_on = models.DateField()
    due_on = models.DateField(db_index=True)
    last_attempt_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "revision", "mode"], name="unique_review_evidence")]
