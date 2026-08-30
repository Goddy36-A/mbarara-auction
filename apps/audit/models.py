from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Immutable audit trail (Section 36). Rows are created only, never
    updated or deleted by application code. Generic enough to reference
    any object type without every domain app depending on this one.
    """

    class Action(models.TextChoices):
        USER_REGISTERED = "USER_REGISTERED", "User registered"
        USER_VERIFIED = "USER_VERIFIED", "User verified"
        USER_SUSPENDED = "USER_SUSPENDED", "User suspended"
        AUCTION_CREATED = "AUCTION_CREATED", "Auction created"
        AUCTION_APPROVED = "AUCTION_APPROVED", "Auction approved"
        AUCTION_REJECTED = "AUCTION_REJECTED", "Auction rejected"
        AUCTION_STARTED = "AUCTION_STARTED", "Auction started"
        BID_PLACED = "BID_PLACED", "Bid placed"
        BID_REJECTED = "BID_REJECTED", "Bid rejected"
        BID_INVALIDATED = "BID_INVALIDATED", "Bid invalidated"
        AUCTION_EXTENDED = "AUCTION_EXTENDED", "Auction extended"
        AUCTION_CLOSED = "AUCTION_CLOSED", "Auction closed"
        WINNER_DETERMINED = "WINNER_DETERMINED", "Winner determined"
        AUCTION_CANCELLED = "AUCTION_CANCELLED", "Auction cancelled"
        DISPUTE_CREATED = "DISPUTE_CREATED", "Dispute created"
        DISPUTE_RESOLVED = "DISPUTE_RESOLVED", "Dispute resolved"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Payment pending"
        PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment received"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment failed"
        PAYMENT_REFUNDED = "PAYMENT_REFUNDED", "Payment refunded"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.action} on {self.object_type}#{self.object_id} at {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def record(cls, *, actor, action, obj, reason="", **metadata):
        """Convenience helper so services don't repeat this boilerplate:
        AuditLog.record(actor=request.user, action=AuditLog.Action.BID_PLACED, obj=bid)"""
        return cls.objects.create(
            actor=actor,
            action=action,
            object_type=obj.__class__.__name__,
            object_id=str(obj.pk),
            reason=reason,
            metadata=metadata,
        )
