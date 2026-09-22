import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import LoginBucket, TemporaryCredential, User


def consume_login_attempt(username, address):
    """Shared database counters: no raw network address or username in throttle rows."""
    now = timezone.now()
    allowed = True
    with transaction.atomic():
        for namespace, value, limit in [("account", username.lower(), settings.LOGIN_ACCOUNT_LIMIT),
                                         ("network", address, settings.LOGIN_NETWORK_LIMIT)]:
            key = salted_hmac("login." + namespace, value, algorithm="sha256").hexdigest()
            LoginBucket.objects.get_or_create(key=key, defaults={"started_at": now})
            bucket = LoginBucket.objects.select_for_update().get(pk=key)
            if now - bucket.started_at >= timedelta(seconds=settings.LOGIN_WINDOW_SECONDS):
                bucket.started_at, bucket.attempts = now, 0
            bucket.attempts += 1
            allowed = allowed and bucket.attempts <= limit
            bucket.save()
    return allowed


def reserve_temporary_password(password):
    digest = salted_hmac("temporary.password", password, algorithm="sha256").hexdigest()
    try:
        with transaction.atomic():
            TemporaryCredential.objects.create(digest=digest)
    except IntegrityError as exc:
        raise ValidationError("That temporary password has already been issued. Choose a unique one.") from exc


@transaction.atomic
def create_student(username, password):
    validate_password(password, User(username=username))
    reserve_temporary_password(password)
    return User.objects.create_user(username, password)


@transaction.atomic
def reset_student(student_id, password):
    student = User.objects.select_for_update().get(pk=student_id, is_admin=False)
    validate_password(password, student)
    if student.check_password(password):
        raise ValidationError("Choose a different temporary password.")
    reserve_temporary_password(password)
    student.set_password(password)
    student.must_change_password = True
    student.save(update_fields=["password", "must_change_password"])


@transaction.atomic
def set_student_active(student_id, active):
    student = User.objects.select_for_update().get(pk=student_id, is_admin=False)
    student.is_active = active
    student.session_version = uuid.uuid4()
    student.save(update_fields=["is_active", "session_version"])
