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
