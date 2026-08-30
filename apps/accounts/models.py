from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TimeStampedModel


class User(AbstractUser):
    """
    Custom user model (Section 10-11 of the design spec: use Django's auth
    framework rather than a bespoke one; add only the fields this domain
    actually needs).

    Role is a coarse platform-level flag used for navigation/permissions
    defaults. It intentionally does NOT replace object-level authorization —
    every view must still check ownership/eligibility server-side
    (Section 42), a role of SELLER does not by itself grant access to a
    specific auction.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        OFFICER = "OFFICER", "Auction Officer / Moderator"
        SELLER = "SELLER", "Seller"
        BIDDER = "BIDDER", "Bidder"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BIDDER)
    phone_number = models.CharField(max_length=20, blank=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Set once identity/eligibility verification (configurable per Section 12-13) is complete.",
    )

    def __str__(self):
        return self.username

    @property
    def is_seller(self):
        return self.role == self.Role.SELLER

    @property
    def is_bidder(self):
        return self.role == self.Role.BIDDER

    @property
    def is_officer_or_admin(self):
        return self.role in (self.Role.ADMIN, self.Role.OFFICER) or self.is_staff


class VerificationStatus(models.TextChoices):
    """Shared by SellerProfile and BidderProfile (Section 12-13: seller and
    bidder verification should be configurable, not assumed mandatory —
    PENDING accounts can still browse; whether they can sell/bid while
    PENDING is a permissions-layer decision, not a model-layer one)."""

    PENDING = "PENDING", "Pending review"
    VERIFIED = "VERIFIED", "Verified"
    REJECTED = "REJECTED", "Rejected"


class SellerProfile(TimeStampedModel):
    """
    Seller-specific information (Section 12). Deliberately minimal — no
    sensitive identity information is assumed required unless a concrete
    verification requirement is supplied later (see Phase 1, Section 12
    note: 'Do not assume sensitive identity information is required unless
    justified').
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seller_profile")
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, default="Mbarara")
    verification_status = models.CharField(
        max_length=10, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Seller profile"

    def __str__(self):
        return f"Seller: {self.user.username} ({self.verification_status})"

    @property
    def is_verified(self):
        return self.verification_status == VerificationStatus.VERIFIED


class BidderProfile(TimeStampedModel):
    """Bidder-specific information (Section 13)."""

    class AccountStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bidder_profile")
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=100, blank=True)
    verification_status = models.CharField(
        max_length=10, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )
    account_status = models.CharField(max_length=10, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "Bidder profile"

    def __str__(self):
        return f"Bidder: {self.user.username} ({self.verification_status}/{self.account_status})"

    @property
    def is_verified(self):
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def is_eligible_to_bid(self):
        """Encodes Business Rule BR-05 at the profile level: a bidder must
        be verified, active, and not suspended. The bidding service (Phase 6)
        re-checks this server-side at bid time — this property is a
        convenience for UI/permission checks, not the sole enforcement
        point."""
        return self.is_verified and self.account_status == self.AccountStatus.ACTIVE and self.user.is_active
