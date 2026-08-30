"""
Celery application (README: "Celery + Redis handle scheduled auction
closing and asynchronous notification delivery so these never block a web
request"). Two kinds of work run through this:

  - Periodic tasks (Celery beat, via django-celery-beat) driving
    apps.auctions.services.activate_if_due / apps.bidding.services.close_auction
    on a schedule configured in Django Admin — the management commands in
    apps/bidding/management/commands remain the cron-friendly alternative
    for deployments that don't run Celery beat.
  - On-demand async tasks, currently just
    apps.notifications.tasks.deliver_notification.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("mbarara_auction")

# Read CELERY_* settings from Django settings (see CELERY_BROKER_URL etc.
# in config/settings/base.py) rather than a separate celeryconfig module.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Pick up a tasks.py from every installed app automatically.
app.autodiscover_tasks()
