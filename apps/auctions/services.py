"""
Auction lifecycle state machine (Section 16-17). This is the ONLY place
Auction.status should be assigned — views and admin actions call
transition(), never `auction.status = X; auction.save()` directly, so every
change is validated against ALLOWED_TRANSITIONS and audit-logged.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.services import notify_auction_live, notify_listing_approved, notify_listing_rejected

from .models import Auction, AuctionStatusLog

Status = Auction.Status

ALLOWED_TRANSITIONS = {
    Status.DRAFT: {Status.SUBMITTED, Status.CANCELLED},
    Status.SUBMITTED: {Status.APPROVED, Status.REJECTED},
    Status.APPROVED: {Status.SCHEDULED},
    Status.SCHEDULED: {Status.LIVE, Status.CANCELLED},
    Status.LIVE: {Status.PAUSED, Status.CLOSED, Status.CANCELLED, Status.DISPUTED},
    Status.PAUSED: {Status.LIVE, Status.CANCELLED},
    Status.CLOSED: {Status.SETTLED, Status.DISPUTED},
    Status.SETTLED: {Status.COMPLETED, Status.DISPUTED},
    Status.DISPUTED: {Status.CLOSED},
    Status.REJECTED: set(),
    Status.CANCELLED: set(),
    Status.COMPLETED: set(),
}

# Only transitions worth a dedicated AuditLog action get one; every
# transition regardless gets an AuctionStatusLog row (Section 36 lists the
# high-value events explicitly; SCHEDULED is an intermediate step that
# doesn't need its own audit action on top of the status log).
AUDIT_ACTION_FOR_TRANSITION = {
    Status.SUBMITTED: AuditLog.Action.AUCTION_CREATED,
    Status.APPROVED: AuditLog.Action.AUCTION_APPROVED,
    Status.REJECTED: AuditLog.Action.AUCTION_REJECTED,
    Status.LIVE: AuditLog.Action.AUCTION_STARTED,
    Status.CANCELLED: AuditLog.Action.AUCTION_CANCELLED,
    Status.CLOSED: AuditLog.Action.AUCTION_CLOSED,
}


class InvalidTransition(ValidationError):
    pass


@transaction.atomic
def transition(auction: Auction, to_status, *, actor, reason=""):
    """
    Move `auction` to `to_status` if allowed from its current status.
    Locks the row so a concurrent approval/rejection can't race.
    """
    locked = Auction.objects.select_for_update().get(pk=auction.pk)
    from_status = locked.status

    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise InvalidTransition(
            f"Cannot move auction #{locked.pk} from {from_status} to {to_status}."
        )

    if to_status == Status.REJECTED and not reason:
        raise InvalidTransition("A reason is required when rejecting an auction (Section 16).")

    locked.status = to_status
    locked.save(update_fields=["status", "updated_at"])

    AuctionStatusLog.objects.create(
        auction=locked, from_status=from_status, to_status=to_status, changed_by=actor, reason=reason
    )

    audit_action = AUDIT_ACTION_FOR_TRANSITION.get(to_status)
    if audit_action:
        AuditLog.record(actor=actor, action=audit_action, obj=locked, reason=reason)

    # Notify the seller of transitions that matter to them directly. Bid-
    # and closing-related notifications (outbid, won, closed-no-winner)
    # are raised from apps.bidding.services instead, at the point those
    # outcomes are actually determined.
    if to_status == Status.APPROVED:
        notify_listing_approved(locked)
    elif to_status == Status.REJECTED:
        notify_listing_rejected(locked, reason=reason)
    elif to_status == Status.LIVE:
        notify_auction_live(locked)

    return locked


def submit_for_review(auction, *, actor):
    return transition(auction, Status.SUBMITTED, actor=actor)


def approve(auction, *, actor, reason=""):
    """Approval immediately advances the auction to SCHEDULED too (Section
    16's diagram: Approved -> Scheduled), rather than leaving it in an
    intermediate APPROVED state a human has to remember to push forward."""
    approved = transition(auction, Status.APPROVED, actor=actor, reason=reason)
    return transition(approved, Status.SCHEDULED, actor=actor, reason="Auto-scheduled after approval")


def reject(auction, *, actor, reason):
    return transition(auction, Status.REJECTED, actor=actor, reason=reason)


def cancel(auction, *, actor, reason):
    return transition(auction, Status.CANCELLED, actor=actor, reason=reason)


def activate_if_due(auction, *, actor=None):
    """Move SCHEDULED -> LIVE once start_time has passed. Intended to be
    called by a periodic task (management command / Celery beat, wired up
    in Phase 6/11) — not by a browser request (Section 55)."""
    if auction.status == Status.SCHEDULED and auction.start_time <= timezone.now():
        return transition(auction, Status.LIVE, actor=actor, reason="Auto-activated: start_time reached")
    return auction
