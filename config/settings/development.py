from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Verbose SQL logging (opt-in via SQL_DEBUG_LEVEL=DEBUG) helps while building
# the bidding service's transactions — kept off by default even in dev.
LOGGING["loggers"]["django.db.backends"] = {  # noqa: F405
    "handlers": ["console"],
    "level": env("SQL_DEBUG_LEVEL", default="WARNING"),  # noqa: F405
    "propagate": False,
}

# Run background tasks (notifications) immediately inside the web process, so
# local development works without Redis. Set CELERY_TASK_ALWAYS_EAGER=False in
# .env if you do run Redis and a Celery worker.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=True)  # noqa: F405
CELERY_TASK_EAGER_PROPAGATES = env.bool("CELERY_TASK_EAGER_PROPAGATES", default=True)  # noqa: F405
