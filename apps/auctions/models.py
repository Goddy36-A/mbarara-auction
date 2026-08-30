from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class AuctionCategory(models.Model):
    """Configurable categories (Section 14). Administrators manage these
    via Django Admin — no dedicated app UI needed for an MVP."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "Auction categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Auction(TimeStampedModel):
    """
    The core listing/auction entity (Section 15). Status is only ever
    changed through apps.auctions.services.transition() — never assigned
    directly by a view — so every change is validated against the state
    machine and audit-logged (Section 16-17, Business Rule BR-11).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted for review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SCHEDULED = "SCHEDULED", "Scheduled"
        LIVE = "LIVE", "Live"
        PAUSED = "PAUSED", "Paused"
        CLOSED = "CLOSED", "Closed"
        SETTLED = "SETTLED", "Settled"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        DISPUTED = "DISPUTED", "Disputed"

    # Statuses visible to the public browse/search view (Section 30-31) —
    # a draft or a rejected listing should never be publicly discoverable.
    PUBLICLY_VISIBLE_STATUSES = (Status.SCHEDULED, Status.LIVE, Status.PAUSED, Status.CLOSED, Status.SETTLED, Status.COMPLETED)

    seller = models.ForeignKey("accounts.SellerProfile", on_delete=models.PROTECT, related_name="auctions")
    category = models.ForeignKey(AuctionCategory, on_delete=models.PROTECT, related_name="auctions")

    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=150, default="Mbarara")

    starting_price = models.DecimalField(max_digits=14, decimal_places=2)
    reserve_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    min_increment = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("1000.00"))

    # Denormalized for fast reads on the detail page; the bidding service
    # (Phase 6) is the only writer of this field once bidding starts.
    current_highest_bid = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    # Optional anti-sniping extension (Section 26) — 0 disables it.
    extension_minutes = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="won_auctions"
    )
    final_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    reserve_met = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "end_time"])]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("Auction start_time must be before end_time (Section 39).")
        if self.starting_price is not None and self.starting_price <= 0:
            raise ValidationError("starting_price must be positive (Section 39).")
        if self.min_increment is not None and self.min_increment <= 0:
            raise ValidationError("min_increment must be positive (Section 39).")

    @property
    def display_price(self):
        return self.current_highest_bid or self.starting_price

    @property
    def is_biddable(self):
        """Server-authoritative check (Section 18, 31, 55) — never trust a
        client-side countdown for this."""
        from django.utils import timezone

        now = timezone.now()
        return self.status == self.Status.LIVE and self.start_time <= now < self.end_time


class AuctionStatusLog(models.Model):
    """Every lifecycle transition, immutable (Section 17, 36)."""

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField(max_length=12)
    to_status = models.CharField(max_length=12)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"Auction #{self.auction_id}: {self.from_status} -> {self.to_status}"
