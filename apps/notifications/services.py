"""
Notification service layer (Phase 7).

notify() is the single entry point every other app should call — never
`Notification.objects.create(...)` directly — so the row is always created
synchronously (the in-app inbox and unread badge must reflect it on the
very next page load) while any future outbound channel (email/SMS) is
handed off to Celery via apps.notifications.tasks.deliver_notification, in
line with the design doc's "Celery + Redis handle ... asynchronous
notification delivery so these never block a web request." Nothing in this
app blocks a request on network I/O to a mail/SMS provider.

The rest of this module is thin, event-specific wrappers so callers in
other apps (bidding, auctions, accounts) don't have to know Notification's
field names or compose title/message text themselves — they just say what
happened.
"""
from .models import Notification
from .tasks import deliver_notification


def notify(*, recipient, event, title, message, obj=None, link="", channel=Notification.Channel.IN_APP):
    """
    Create a notification for `recipient` and queue it for delivery.

    `recipient` must be a real, persisted User — silently no-ops on a None
    recipient (e.g. an auction with no winner) rather than making every
    call site guard against that itself.
    """
    if recipient is None:
        return None

    notification = Notification.objects.create(
        recipient=recipient,
        event=event,
        channel=channel,
        title=title,
        message=message,
        related_object_type=obj.__class__.__name__ if obj is not None else "",
        related_object_id=str(obj.pk) if obj is not None else "",
        link=link,
    )

    deliver_notification.delay(notification.pk)

    return notification


def mark_read(notification: Notification, *, user):
    if notification.recipient_id != user.pk:
        raise PermissionError("You cannot mark another user's notification as read.")
    if notification.read_at is None:
        from django.utils import timezone

        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification


def mark_all_read(user):
    from django.utils import timezone

    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(read_at=timezone.now())


def unread_count(user):
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


# ---------------------------------------------------------------------------
# Event-specific helpers — called from the other apps' service layers at the
# same point they already write an AuditLog entry for the same event.
# ---------------------------------------------------------------------------

def notify_outbid(bid):
    """A previously-highest bidder has just been overtaken (Section 21's
    real-time-awareness goal, delivered here as an in-app notification
    rather than a live socket push — see README's Django Channels note)."""
    auction = bid.auction
    previous_highest = (
        auction.bids.filter(status="ACCEPTED")
        .exclude(pk=bid.pk)
        .order_by("-amount", "-sequence_no")
        .first()
    )
    if previous_highest is None or previous_highest.bidder_id == bid.bidder_id:
        return None
    return notify(
        recipient=previous_highest.bidder.user,
        event=Notification.Event.OUTBID,
        title="You've been outbid",
        message=f"Someone placed a higher bid of {bid.amount} on '{auction.title}'.",
        obj=auction,
        link=f"/auctions/{auction.pk}/",
    )


def notify_auction_won(auction):
    if auction.winner_id is None:
        return None
    return notify(
        recipient=auction.winner,
        event=Notification.Event.AUCTION_WON,
        title="You won an auction!",
        message=f"You won '{auction.title}' with a final price of {auction.final_price}.",
        obj=auction,
        link=f"/auctions/{auction.pk}/",
    )


def notify_auction_closed_no_winner(auction):
    return notify(
        recipient=auction.seller.user,
        event=Notification.Event.AUCTION_CLOSED_NO_WINNER,
        title="Your auction closed with no winner",
        message=f"'{auction.title}' closed without a winning bid (no bids met the reserve, or none were placed).",
        obj=auction,
        link=f"/auctions/{auction.pk}/",
    )


def notify_auction_live(auction):
    return notify(
        recipient=auction.seller.user,
        event=Notification.Event.AUCTION_LIVE,
        title="Your auction is now live",
        message=f"'{auction.title}' is now live and open for bidding.",
        obj=auction,
        link=f"/auctions/{auction.pk}/",
    )


def notify_listing_approved(auction):
    return notify(
        recipient=auction.seller.user,
        event=Notification.Event.LISTING_APPROVED,
        title="Listing approved",
        message=f"Your listing '{auction.title}' was approved and scheduled.",
        obj=auction,
        link=f"/auctions/{auction.pk}/",
    )


def notify_listing_rejected(auction, *, reason=""):
    message = f"Your listing '{auction.title}' was rejected."
    if reason:
        message += f" Reason: {reason}"
    return notify(
        recipient=auction.seller.user,
        event=Notification.Event.LISTING_REJECTED,
        title="Listing rejected",
        message=message,
        obj=auction,
    )


def notify_account_verified(profile):
    return notify(
        recipient=profile.user,
        event=Notification.Event.ACCOUNT_VERIFIED,
        title="Account verified",
        message="Your account has been verified. You now have full access.",
        obj=profile,
    )


def notify_account_rejected(profile, *, reason=""):
    message = "Your account verification was rejected."
    if reason:
        message += f" Reason: {reason}"
    return notify(
        recipient=profile.user,
        event=Notification.Event.ACCOUNT_REJECTED,
        title="Account verification rejected",
        message=message,
        obj=profile,
    )


def notify_bidder_suspended(profile, *, reason=""):
    message = "Your bidder account has been suspended."
    if reason:
        message += f" Reason: {reason}"
    return notify(
        recipient=profile.user,
        event=Notification.Event.ACCOUNT_SUSPENDED,
        title="Account suspended",
        message=message,
        obj=profile,
    )


def notify_bidder_reactivated(profile):
    return notify(
        recipient=profile.user,
        event=Notification.Event.ACCOUNT_REACTIVATED,
        title="Account reactivated",
        message="Your bidder account has been reactivated.",
        obj=profile,
    )


def notify_payment_received(payment):
    """Both parties in the transaction care about this — the buyer gets a
    receipt-style confirmation, the seller learns it's safe to hand over
    the item (Phase 8 is status tracking only, so "safe" here means
    "recorded by staff", not gateway-verified)."""
    auction = payment.auction
    notify(
        recipient=payment.buyer,
        event=Notification.Event.PAYMENT_RECEIVED,
        title="Payment recorded",
        message=f"Your payment of {payment.amount} for '{auction.title}' has been recorded as received.",
        obj=payment,
        link=f"/auctions/{auction.pk}/",
    )
    return notify(
        recipient=payment.seller_user,
        event=Notification.Event.PAYMENT_RECEIVED,
        title="Payment received from buyer",
        message=f"Payment of {payment.amount} for '{auction.title}' has been recorded as received.",
        obj=payment,
        link=f"/auctions/{auction.pk}/",
    )


def notify_payment_failed(payment, *, reason=""):
    auction = payment.auction
    message = f"The payment for '{auction.title}' was marked as failed."
    if reason:
        message += f" Reason: {reason}"
    return notify(
        recipient=payment.buyer,
        event=Notification.Event.PAYMENT_FAILED,
        title="Payment issue on your winning bid",
        message=message,
        obj=payment,
        link=f"/auctions/{auction.pk}/",
    )
