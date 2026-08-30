from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    In-app notification (Phase 7 / README: "In-app notification model &
    delivery"). Rows are created once by apps.notifications.services.notify()
    and afterwards only ever have read_at set — never edited otherwise, so
    a notification always reflects exactly what the triggering event said
    at the time it happened (consistent with the audit trail it's usually
    raised alongside).

    Delivery is deliberately channel-agnostic at the model level: `channel`
    records where (if anywhere, beyond in-app) this was sent, so email/SMS
    backends can be added in a later phase without a schema change. For
    this MVP only IN_APP is ever produced.
    """

    class Event(models.TextChoices):
        OUTBID = "OUTBID", "You've been outbid"
        AUCTION_WON = "AUCTION_WON", "You won an auction"
        AUCTION_LIVE = "AUCTION_LIVE", "Your auction is now live"
        AUCTION_CLOSED_NO_WINNER = "AUCTION_CLOSED_NO_WINNER", "Auction closed with no winner"
        LISTING_APPROVED = "LISTING_APPROVED", "Listing approved"
        LISTING_REJECTED = "LISTING_REJECTED", "Listing rejected"
        ACCOUNT_VERIFIED = "ACCOUNT_VERIFIED", "Account verified"
        ACCOUNT_REJECTED = "ACCOUNT_REJECTED", "Account verification rejected"
        ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED", "Account suspended"
        ACCOUNT_REACTIVATED = "ACCOUNT_REACTIVATED", "Account reactivated"
        PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment received"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment marked failed"

    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-app"
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.CharField(max_length=32, choices=Event.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)

    title = models.CharField(max_length=150)
    message = models.TextField()

    # Loosely-coupled reference to whatever triggered this notification
    # (an Auction, a Bid, a SellerProfile, ...), mirroring the pattern in
    # apps.audit.models.AuditLog: a plain string pair rather than a
    # GenericForeignKey, so this app never has to import the models of
    # every app that might raise a notification.
    related_object_type = models.CharField(max_length=64, blank=True)
    related_object_id = models.CharField(max_length=64, blank=True)
    # Where the "view" link (if any) on the notification should point —
    # populated by the caller since only it knows the right named URL.
    link = models.CharField(max_length=200, blank=True)

    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]

    def __str__(self):
        return f"{self.get_event_display()} -> {self.recipient.username}"

    @property
    def is_read(self):
        return self.read_at is not None
