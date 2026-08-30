"""
The bidding engine (Sections 18-20, 22-27, 40 of the design specification).

place_bid() is the single entry point for submitting a bid. It is
server-authoritative end to end: every rule (auction is live, bidder is
eligible, seller isn't bidding on their own item, amount clears the
current highest bid by at least the minimum increment) is re-checked here,
inside a single atomic transaction against a row-locked Auction, regardless
of what a client believed was true when it rendered the page. This closes
the race-condition window described in Section 19/40: two simultaneous
requests for the same auction are serialized by PostgreSQL's row lock, not
by application-level luck.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.auctions.models import Auction
from apps.auctions.services import transition, Status as AuctionStatus
from apps.notifications.services import notify_auction_closed_no_winner, notify_auction_won, notify_outbid
from apps.payments.services import create_pending_payment

from .models import Bid


class BidRejected(Exception):
    """Raised for any bid that fails validation. The message is safe to
    show directly to the bidder (Section 32: bid confirmation should state
    plainly what the minimum permitted bid is)."""


@transaction.atomic
def place_bid(auction: Auction, *, bidder_user, amount: Decimal) -> Bid:
    # Lock the auction row first — every other check reads from this locked
    # copy, not the possibly-stale `auction` argument the caller passed in.
    locked = Auction.objects.select_for_update().get(pk=auction.pk)

    now = timezone.now()

    if locked.status != AuctionStatus.LIVE or not (locked.start_time <= now < locked.end_time):
        raise BidRejected("This auction is not currently open for bidding.")

    bidder_profile = getattr(bidder_user, "bidder_profile", None)
    if bidder_profile is None:
        raise BidRejected("Only registered bidders can place bids.")
    if not bidder_profile.is_eligible_to_bid:
        raise BidRejected("Your bidder account is not currently eligible to bid (verification or suspension).")

    if bidder_user.pk == locked.seller.user_id:
        raise BidRejected("Sellers cannot bid on their own auction.")  # Business Rule BR-04

    current_highest = locked.current_highest_bid
    minimum_permitted = (current_highest + locked.min_increment) if current_highest is not None else locked.starting_price

    if amount < minimum_permitted:
        raise BidRejected(f"Your bid must be at least {minimum_permitted}.")

    next_sequence = (locked.bids.order_by("-sequence_no").values_list("sequence_no", flat=True).first() or 0) + 1

    bid = Bid.objects.create(
        auction=locked,
        bidder=bidder_profile,
        amount=amount,
        sequence_no=next_sequence,
    )

    locked.current_highest_bid = amount

    # Optional anti-sniping extension (Section 26): a bid arriving inside
    # the configured final window pushes end_time back by that same window.
    if locked.extension_minutes:
        window = timezone.timedelta(minutes=locked.extension_minutes)
        if locked.end_time - now <= window:
            locked.end_time = now + window
            AuditLog.record(
                actor=bidder_user, action=AuditLog.Action.AUCTION_EXTENDED, obj=locked,
                reason="Bid received inside anti-sniping window", new_end_time=str(locked.end_time),
            )

    locked.save(update_fields=["current_highest_bid", "end_time", "updated_at"])

    AuditLog.record(actor=bidder_user, action=AuditLog.Action.BID_PLACED, obj=bid, amount=str(amount))

    notify_outbid(bid)

    return bid


def invalidate_bid(bid: Bid, *, actor, reason: str):
    """Administrative invalidation (Section 22): the row is kept forever,
    only its status changes. If the invalidated bid was the current
    highest, the auction's current_highest_bid is recomputed from the
    remaining valid bids."""
    if not reason:
        raise ValueError("A reason is required to invalidate a bid (Section 20).")

    with transaction.atomic():
        locked_auction = Auction.objects.select_for_update().get(pk=bid.auction_id)
        bid.status = Bid.Status.INVALIDATED
        bid.invalidated_reason = reason
        bid.invalidated_by = actor
        bid.invalidated_at = timezone.now()
        bid.save(update_fields=["status", "invalidated_reason", "invalidated_by", "invalidated_at"])

        highest_valid = locked_auction.bids.filter(status=Bid.Status.ACCEPTED).order_by("-amount", "sequence_no").first()
        locked_auction.current_highest_bid = highest_valid.amount if highest_valid else None
        locked_auction.save(update_fields=["current_highest_bid", "updated_at"])

        AuditLog.record(actor=actor, action=AuditLog.Action.BID_INVALIDATED, obj=bid, reason=reason)

    return bid


@transaction.atomic
def close_auction(auction: Auction, *, actor=None):
    """
    Automated closing (Section 25). Intended to be called by a scheduled
    task (see apps/bidding/management/commands/close_ended_auctions.py),
    never by a browser request (Section 25: 'Do not rely exclusively on a
    browser page to close an auction').
    """
    locked = Auction.objects.select_for_update().get(pk=auction.pk)

    if locked.status != AuctionStatus.LIVE:
        raise ValueError(f"Cannot close auction #{locked.pk}: status is {locked.status}, not LIVE.")

    highest = locked.bids.filter(status=Bid.Status.ACCEPTED).order_by("-amount", "sequence_no").first()

    reserve_met = None
    winner_user = None
    final_price = None

    if highest:
        if locked.reserve_price is not None:
            reserve_met = highest.amount >= locked.reserve_price
        else:
            reserve_met = True  # no reserve configured — any valid highest bid wins

        if reserve_met:
            winner_user = highest.bidder.user
            final_price = highest.amount

    locked.winner = winner_user
    locked.final_price = final_price
    locked.reserve_met = reserve_met
    locked.save(update_fields=["winner", "final_price", "reserve_met", "updated_at"])

    locked = transition(locked, AuctionStatus.CLOSED, actor=actor, reason="Automated closing at end_time")

    if winner_user:
        AuditLog.record(
            actor=actor, action=AuditLog.Action.WINNER_DETERMINED, obj=locked,
            winner_id=winner_user.pk, final_price=str(final_price),
        )
        notify_auction_won(locked)
        create_pending_payment(locked)
    else:
        notify_auction_closed_no_winner(locked)

    return locked


def get_bid_history(auction: Auction, viewer=None):
    """
    Privacy-preserving bid history (Section 21, 43, and the Phase 2
    Transparency & Privacy Model): the public and other bidders see
    anonymized labels ('Bidder A', 'Bidder B', ...) assigned in order of
    each bidder's first bid on this auction; a bidder always recognizes
    their own bids as 'You'; staff see real usernames.
    """
    bids = list(auction.bids.select_related("bidder__user").order_by("sequence_no"))

    is_staff = bool(viewer and getattr(viewer, "is_authenticated", False) and viewer.is_officer_or_admin)

    labels = {}
    history = []
    for bid in bids:
        bidder_user_id = bid.bidder.user_id
        if bidder_user_id not in labels:
            labels[bidder_user_id] = f"Bidder {chr(ord('A') + len(labels))}"

        if is_staff:
            label = bid.bidder.user.username
        elif viewer and getattr(viewer, "is_authenticated", False) and viewer.pk == bidder_user_id:
            label = "You"
        else:
            label = labels[bidder_user_id]

        history.append({
            "sequence_no": bid.sequence_no,
            "amount": bid.amount,
            "created_at": bid.created_at,
            "label": label,
            "status": bid.status,
            "is_mine": bool(viewer and getattr(viewer, "is_authenticated", False) and viewer.pk == bidder_user_id),
        })

    return history
