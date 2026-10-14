"""
Dispute workflow (Phase 9). Same accountability pattern as the rest of the
project: every state change goes through a service function, requires an
actor, is audit-logged, and notifies the people affected.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.auctions.models import Auction
from apps.auctions.services import Status as AuctionStatus, transition
from apps.notifications.services import notify_dispute_opened, notify_dispute_resolved

from .models import Dispute

DISPUTABLE_STATUSES = (AuctionStatus.CLOSED, AuctionStatus.SETTLED)


def auction_participants(auction):
    """Users with a direct stake in an auction: its seller, its winner and
    anyone who placed a bid on it."""
    users = {auction.seller.user_id: auction.seller.user}
    if auction.winner_id:
        users[auction.winner_id] = auction.winner
    for bid in auction.bids.select_related("bidder__user"):
        users[bid.bidder.user_id] = bid.bidder.user
    return users


def can_raise_dispute(user, auction):
    """True if `user` may raise a dispute on `auction` right now."""
    if not getattr(user, "is_authenticated", False):
        return False
    if auction.status not in DISPUTABLE_STATUSES:
        return False
    if auction.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists():
        return False
    return user.pk in auction_participants(auction)


def can_view_dispute(user, dispute):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_officer_or_admin:
        return True
    return user.pk in (dispute.raised_by_id, dispute.auction.seller.user_id, dispute.auction.winner_id)


def _staff_users():
    User = get_user_model()
    return User.objects.filter(Q(role__in=[User.Role.ADMIN, User.Role.OFFICER]) | Q(is_staff=True), is_active=True)


def _other_party(dispute):
    """The seller or winner who did NOT raise the dispute (None if the raiser
    was a losing bidder, in which case the seller is the affected party)."""
    seller_user = dispute.auction.seller.user
    if dispute.raised_by_id == seller_user.pk:
        return dispute.auction.winner
    return seller_user


@transaction.atomic
def open_dispute(auction: Auction, *, raised_by, category, description):
    if not description or not description.strip():
        raise ValueError("Please describe the problem.")
    if category not in Dispute.Category.values:
        raise ValueError("Choose a valid dispute category.")

    auction = Auction.objects.select_for_update().get(pk=auction.pk)
    if auction.status not in DISPUTABLE_STATUSES:
        raise ValueError("Only closed or settled auctions can be disputed.")
    if raised_by.pk not in auction_participants(auction):
        raise PermissionError("Only the seller, the winner or a bidder on this auction can raise a dispute.")
    if auction.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists():
        raise ValueError("This auction already has an active dispute.")

    before = auction.status
    try:
        dispute = Dispute.objects.create(
            auction=auction, raised_by=raised_by, category=category,
            description=description.strip(), auction_status_before=before,
        )
    except IntegrityError:
        raise ValueError("This auction already has an active dispute.")

    transition(auction, AuctionStatus.DISPUTED, actor=raised_by, reason=f"Dispute #{dispute.pk} raised")
    AuditLog.record(
        actor=raised_by, action=AuditLog.Action.DISPUTE_CREATED, obj=dispute,
        reason=description.strip()[:500], auction_id=auction.pk, category=category,
    )

    recipients = {u.pk: u for u in _staff_users()}
    other = _other_party(dispute)
    if other is not None:
        recipients[other.pk] = other
    recipients.pop(raised_by.pk, None)
    for user in recipients.values():
        notify_dispute_opened(dispute, user)
    return dispute


@transaction.atomic
def take_for_review(dispute: Dispute, *, actor):
    dispute = Dispute.objects.select_for_update().get(pk=dispute.pk)
    if dispute.status != Dispute.Status.OPEN:
        raise ValueError(f"Dispute #{dispute.pk} is {dispute.get_status_display().lower()}, not open.")
    dispute.status = Dispute.Status.UNDER_REVIEW
    dispute.assigned_to = actor
    dispute.save(update_fields=["status", "assigned_to", "updated_at"])
    return dispute


@transaction.atomic
def resolve_dispute(dispute: Dispute, *, actor, outcome, notes, refund=False):
    """
    Close a dispute. `notes` (the reasoning) is mandatory. If `refund` is
    set, the auction's payment must be PAID and is marked REFUNDED. The
    auction returns to CLOSED, or to SETTLED when it was settled before the
    dispute and no refund was issued.
    """
    from apps.payments.services import mark_refunded

    if outcome not in Dispute.Outcome.values:
        raise ValueError("Choose an outcome for the dispute.")
    if not notes or not notes.strip():
        raise ValueError("Resolution notes are required.")

    dispute = Dispute.objects.select_for_update().get(pk=dispute.pk)
    if not dispute.is_active:
        raise ValueError(f"Dispute #{dispute.pk} is already resolved.")

    auction = dispute.auction
    refunded = False
    if refund:
        payment = getattr(auction, "payment", None)
        if payment is None or payment.status != payment.Status.PAID:
            raise ValueError("A refund can only be recorded for a payment that has been marked paid.")
        mark_refunded(payment, actor=actor, reason=f"Dispute #{dispute.pk}: {notes.strip()}")
        refunded = True

    auction = transition(auction, AuctionStatus.CLOSED, actor=actor, reason=f"Dispute #{dispute.pk} resolved")
    if dispute.auction_status_before == AuctionStatus.SETTLED and not refunded:
        transition(auction, AuctionStatus.SETTLED, actor=actor, reason=f"Restored after dispute #{dispute.pk}")

    dispute.status = Dispute.Status.RESOLVED
    dispute.outcome = outcome
    dispute.resolution_notes = notes.strip()
    dispute.refunded = refunded
    dispute.resolved_by = actor
    dispute.resolved_at = timezone.now()
    dispute.save(update_fields=[
        "status", "outcome", "resolution_notes", "refunded", "resolved_by", "resolved_at", "updated_at",
    ])

    AuditLog.record(
        actor=actor, action=AuditLog.Action.DISPUTE_RESOLVED, obj=dispute,
        reason=notes.strip()[:500], outcome=outcome, refunded=refunded, auction_id=auction.pk,
    )

    recipients = {dispute.raised_by_id: dispute.raised_by}
    other = _other_party(dispute)
    if other is not None:
        recipients[other.pk] = other
    for user in recipients.values():
        notify_dispute_resolved(dispute, user)
    return dispute


def active_disputes():
    return Dispute.objects.filter(status__in=Dispute.ACTIVE_STATUSES).select_related(
        "auction__seller__user", "auction__winner", "raised_by"
    ).order_by("created_at")
