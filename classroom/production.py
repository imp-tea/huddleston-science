"""Production profile for the loopback-only Gunicorn + Caddy deployment."""
from .settings import *  # noqa: F403

if DEBUG:
    raise ImproperlyConfigured("Production requires DJANGO_DEBUG=0.")
if SECRET_KEY.startswith("replace-") or len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
    raise ImproperlyConfigured("Production requires a strong random secret of at least 50 characters.")
if not os.environ.get("DJANGO_ALLOWED_HOSTS") or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS for production.")
if not DATABASES["default"]["PASSWORD"] or DATABASES["default"]["PASSWORD"].startswith("replace-"):
    raise ImproperlyConfigured("Set a database password for production.")

# Only enable with the supplied loopback listener and a proxy that overwrites headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
MIDDLEWARE = ["classroom.proxy.LoopbackProxyMiddleware", *MIDDLEWARE]
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
# Do not preload or include other subdomains until their HTTPS is separately verified.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", "/srv/huddleston/static"))
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Counts/severity only: never log request URLs, query strings, users, or tracebacks.
LOGGING = {"version": 1, "disable_existing_loggers": False,
    "formatters": {"private": {"()": "classroom.proxy.PrivateFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "private"}},
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}}}
