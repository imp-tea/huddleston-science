import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

username_validator = RegexValidator(r"\A[a-z0-9][a-z0-9_-]{2,31}\Z", "Use 3–32 lowercase letters, digits, underscores or hyphens.")


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra):
        user = self.model(username=username.strip().lower(), **extra)
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        return self.create_user(username, password, is_admin=True, must_change_password=False)


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=32, unique=True, validators=[username_validator])
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=True)
    session_version = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = UserManager()
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["is_admin"], condition=models.Q(is_admin=True), name="one_administrator"),
            models.UniqueConstraint(Lower("username"), name="unique_username_casefold"),
            models.CheckConstraint(condition=models.Q(is_admin=False) | models.Q(is_active=True), name="administrator_stays_active"),
            models.CheckConstraint(condition=models.Q(username__regex=r"^[a-z0-9][a-z0-9_-]{2,31}$"), name="username_format"),
        ]

    @property
    def account_code(self):
        return str(self.id)

    @property
    def is_staff(self):
        return self.is_admin

    @property
    def is_superuser(self):
        return self.is_admin

    def _get_session_auth_hash(self, secret=None):
        from django.utils.crypto import salted_hmac
        return salted_hmac("accounts.session", self.password + str(self.session_version), secret=secret, algorithm="sha256").hexdigest()

    def __str__(self):
        return self.username


class TemporaryCredential(models.Model):
    # One-way keyed fingerprints prevent reissuing a temporary password to anyone.
    digest = models.CharField(max_length=64, primary_key=True)


class LoginBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    started_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
