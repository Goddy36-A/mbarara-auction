from django.conf import settings
from django.db import models

from apps.auctions.models import Auction
from apps.core.models import TimeStampedModel


class Payment(TimeStampedModel):
    """
    Payment status tracking (Phase 8; Phase 1 Project Assumption: "No real
    money moves through the MVP; payments are tracked as a status separate
    from the winning bid amount"). This is deliberately a record-keeping
    scaffold, not a gateway integration — `method`/`reference` are free-text
    fields an officer/admin fills in after confirming payment happened by
    some out-of-band means (mobile money, bank transfer, cash), not fields
    a gateway populated automatically.

    One row per won auction, created automatically the moment a winner is
    determined (see apps.payments.services.create_pending_payment, called
    from apps.bidding.services.close_auction) so there is always exactly
    one payment record to track against a sale — never created ad hoc by
    a view.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    auction = models.OneToOneField(Auction, on_delete=models.PROTECT, related_name="payment")

    # Snapshot of Auction.final_price at creation time — the auction's own
    # price fields could in principle change meaning over time (they won't,
    # since Auction is closed by this point, but a payment record should
    # never depend on a live read of another table to know what was owed).
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    method = models.CharField(max_length=50, blank=True, help_text="e.g. Mobile Money, Bank Transfer, Cash — free text, no gateway.")
    reference = models.CharField(max_length=100, blank=True, help_text="Manual transaction reference, if any.")
    notes = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"Payment for auction #{self.auction_id} ({self.status})"

    @property
    def buyer(self):
        return self.auction.winner

    @property
    def seller_user(self):
        return self.auction.seller.user
