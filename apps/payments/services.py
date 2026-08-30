"""
Payment status tracking (Phase 8). There is no gateway here — every state
change is a human (officer/admin) recording that something happened
out-of-band, which is why every transition below requires an `actor` and
the failure/refund paths require a `reason`, mirroring the same
accountability pattern used for listing rejection and bid invalidation.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.services import notify_payment_failed, notify_payment_received

from .models import Payment


def create_pending_payment(auction):
    """
    Called from apps.bidding.services.close_auction once a winner is
    determined. Idempotent (returns the existing row rather than raising)
    so it's safe even if something ever calls it twice for the same
    auction. Returns None if the auction has no winner — there is nothing
    to collect payment for.
    """
    existing = getattr(auction, "payment", None)
    if existing is not None:
        return existing

    if auction.winner_id is None or auction.final_price is None:
        return None

    payment = Payment.objects.create(auction=auction, amount=auction.final_price)
    AuditLog.record(actor=None, action=AuditLog.Action.PAYMENT_PENDING, obj=payment, auction_id=auction.pk)
    return payment


@transaction.atomic
def mark_paid(payment: Payment, *, actor, method="", reference="", notes=""):
    if payment.status != Payment.Status.PENDING:
        raise ValueError(f"Cannot mark payment #{payment.pk} paid: current status is {payment.status}, not PENDING.")

    payment.status = Payment.Status.PAID
    payment.method = method
    payment.reference = reference
    payment.notes = notes
    payment.recorded_by = actor
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "method", "reference", "notes", "recorded_by", "paid_at", "updated_at"])

    AuditLog.record(actor=actor, action=AuditLog.Action.PAYMENT_RECEIVED, obj=payment, method=method, reference=reference)

    # Advance the auction lifecycle: CLOSED -> SETTLED once payment is
    # confirmed (Auction.Status: SETTLED sits between CLOSED and COMPLETED
    # in apps.auctions.services.ALLOWED_TRANSITIONS specifically to mark
    # "paid, not yet handed over"). A local import avoids a hard
    # module-level dependency cycle between payments and auctions.
    from apps.auctions.services import transition, Status as AuctionStatus

    auction = payment.auction
    if auction.status == AuctionStatus.CLOSED:
        transition(auction, AuctionStatus.SETTLED, actor=actor, reason="Payment recorded as received")

    notify_payment_received(payment)

    return payment


def mark_failed(payment: Payment, *, actor, reason):
    if not reason:
        raise ValueError("A reason is required to mark a payment failed.")
    if payment.status != Payment.Status.PENDING:
        raise ValueError(f"Cannot mark payment #{payment.pk} failed: current status is {payment.status}, not PENDING.")

    payment.status = Payment.Status.FAILED
    payment.notes = reason
    payment.recorded_by = actor
    payment.save(update_fields=["status", "notes", "recorded_by", "updated_at"])

    AuditLog.record(actor=actor, action=AuditLog.Action.PAYMENT_FAILED, obj=payment, reason=reason)
    notify_payment_failed(payment, reason=reason)

    return payment


def mark_refunded(payment: Payment, *, actor, reason):
    if not reason:
        raise ValueError("A reason is required to mark a payment refunded.")
    if payment.status != Payment.Status.PAID:
        raise ValueError(f"Cannot refund payment #{payment.pk}: current status is {payment.status}, not PAID.")

    payment.status = Payment.Status.REFUNDED
    payment.notes = f"{payment.notes}\nRefunded: {reason}".strip()
    payment.recorded_by = actor
    payment.save(update_fields=["status", "notes", "recorded_by", "updated_at"])

    AuditLog.record(actor=actor, action=AuditLog.Action.PAYMENT_REFUNDED, obj=payment, reason=reason)

    return payment


def pending_payments():
    """Queue for the officer/admin payment-recording screen, mirroring
    apps.accounts.services.pending_profiles and
    apps.listings.views.ApprovalQueueView's pending-work pattern."""
    return Payment.objects.filter(status=Payment.Status.PENDING).select_related(
        "auction__seller__user", "auction__winner"
    )
