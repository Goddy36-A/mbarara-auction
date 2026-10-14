from django.conf import settings
from django.db import models

from apps.auctions.models import Auction
from apps.core.models import TimeStampedModel


class Dispute(TimeStampedModel):
    """
    A complaint raised about a finished auction (Phase 9). Only auctions in
    CLOSED or SETTLED status can be disputed. Raising a dispute moves the
    auction to DISPUTED through the normal state machine; resolving it moves
    the auction back (to CLOSED, or SETTLED if it had already been paid and
    no refund was issued).

    At most one dispute per auction may be active (OPEN / UNDER_REVIEW) at a
    time, enforced by a database constraint, not just by view logic.
    """

    class Category(models.TextChoices):
        NON_PAYMENT = "NON_PAYMENT", "Payment not made or not received"
        NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED", "Item not as described"
        NOT_DELIVERED = "NOT_DELIVERED", "Item not handed over"
        BID_IRREGULARITY = "BID_IRREGULARITY", "Suspicious or incorrect bidding"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        RESOLVED = "RESOLVED", "Resolved"

    class Outcome(models.TextChoices):
        UPHELD = "UPHELD", "Complaint upheld"
        DISMISSED = "DISMISSED", "Complaint dismissed"

    ACTIVE_STATUSES = (Status.OPEN, Status.UNDER_REVIEW)

    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="disputes")
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="disputes_raised")
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.TextField()
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)

    # Auction status at the moment the dispute was raised (CLOSED or SETTLED),
    # used to decide where the auction goes back to on resolution.
    auction_status_before = models.CharField(max_length=12)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    resolution_notes = models.TextField(blank=True)
    refunded = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["auction"],
                condition=models.Q(status__in=["OPEN", "UNDER_REVIEW"]),
                name="one_active_dispute_per_auction",
            )
        ]

    def __str__(self):
        return f"Dispute #{self.pk} on auction #{self.auction_id} ({self.status})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES
