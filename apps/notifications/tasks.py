"""
Async delivery for notifications already persisted by
apps.notifications.services.notify(). The in-app row exists the instant
notify() returns — this task is only responsible for any *additional*
outbound channel (email/SMS), so it deliberately does nothing observable
yet: no email/SMS gateway is wired up in this phase (see README: Payments
and further integrations are later phases too). Keeping the task in place
now means a future phase adds a gateway call here without touching any of
the calling code in bidding/auctions/accounts.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def deliver_notification(self, notification_id):
    from .models import Notification

    try:
        notification = Notification.objects.select_related("recipient").get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.warning("deliver_notification: Notification #%s no longer exists.", notification_id)
        return

    if notification.channel == Notification.Channel.IN_APP:
        # Already fully "delivered" by virtue of existing in the DB — the
        # inbox view and unread-count context processor read it directly.
        logger.info("Notification #%s delivered in-app to %s.", notification.pk, notification.recipient.username)
        return

    # EMAIL / SMS: no provider is configured yet in this phase. Log rather
    # than silently drop, so a future gateway integration has an obvious
    # spot to replace this branch.
    logger.info(
        "Notification #%s (%s) queued for %s delivery to %s — no gateway configured yet.",
        notification.pk, notification.event, notification.channel, notification.recipient.username,
    )
