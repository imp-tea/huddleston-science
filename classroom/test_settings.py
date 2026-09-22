"""Isolated test configuration; always PostgreSQL, never a SQLite substitute."""
import os
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-key-never-use-for-a-running-site")
from .settings import *  # noqa: F403

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
