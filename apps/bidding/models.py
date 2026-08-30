from django.conf import settings
from django.db import models

from apps.auctions.models import Auction


class Bid(models.Model):
    """
    Immutable bid record (Section 20). Once created with status=ACCEPTED,
    `amount`, `auction`, `bidder`, and `sequence_no` are never modified —
    the only permitted change is marking a bid INVALIDATED (with a reason,
    an actor, and a timestamp), which apps.bidding.services.invalidate_bid
    handles. Nothing in this app ever does `bid.amount = ...; bid.save()`.
    """

    class Status(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        INVALIDATED = "INVALIDATED", "Invalidated"

    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="bids")
    bidder = models.ForeignKey("accounts.BidderProfile", on_delete=models.PROTECT, related_name="bids")

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Server-assigned, monotonically increasing per auction — the sole basis
    # for chronological ordering and tie-breaking (Business Rule BR-10).
    # Never derived from a client-supplied timestamp (Business Rule BR-07).
    sequence_no = models.PositiveIntegerField()

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACCEPTED)
    invalidated_reason = models.TextField(blank=True)
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    invalidated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)  # server timestamp — Business Rule BR-07

    class Meta:
        ordering = ["sequence_no"]
        constraints = [
            models.UniqueConstraint(fields=["auction", "sequence_no"], name="unique_sequence_per_auction"),
            models.CheckConstraint(check=models.Q(amount__gt=0), name="bid_amount_positive"),
        ]
        indexes = [models.Index(fields=["auction", "status"])]

    def __str__(self):
        return f"Bid #{self.sequence_no} on auction #{self.auction_id}: {self.amount} ({self.status})"

    @property
    def is_valid(self):
        return self.status == self.Status.ACCEPTED
