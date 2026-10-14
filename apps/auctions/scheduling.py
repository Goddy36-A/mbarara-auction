"""
Staff scheduling controls (Auction Control dashboard).

Everything here is a deliberate action by a named staff member, so each
function takes an `actor`, writes to the audit log and tells the people
affected. Automatic starting/closing still happens through the two
management commands; `sweep_due` runs the very same logic on demand.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.notifications.services import notify_auction_update

from .models import Auction
from .services import InvalidTransition, Status, activate_if_due, cancel, transition


class SchedulingError(ValueError):
    pass


def _locked(auction):
    return Auction.objects.select_for_update().get(pk=auction.pk)


def _need_reason(reason):
    if not reason or not reason.strip():
        raise SchedulingError("A reason is required.")
    return reason.strip()


def _fmt(dt):
    return timezone.localtime(dt).strftime("%d %b %Y %H:%M")


@transaction.atomic
def start_now(auction, *, actor):
    """SCHEDULED -> LIVE immediately, even if start_time is still in the future."""
    locked = _locked(auction)
    if locked.status != Status.SCHEDULED:
        raise SchedulingError(f"Only a scheduled auction can be started (this one is {locked.get_status_display()}).")
    now = timezone.now()
    if locked.end_time <= now:
        raise SchedulingError("The end time has already passed. Reschedule the auction first.")
    if locked.start_time > now:
        old = locked.start_time
        locked.start_time = now
        locked.save(update_fields=["start_time", "updated_at"])
        AuditLog.record(
            actor=actor, action=AuditLog.Action.AUCTION_RESCHEDULED, obj=locked,
            reason="Started early by staff", old_start=old.isoformat(), new_start=now.isoformat(),
        )
    return transition(locked, Status.LIVE, actor=actor, reason="Started manually by staff")


@transaction.atomic
def reschedule(auction, *, actor, reason, start_time=None, end_time=None):
    """
    Change the schedule. What may change depends on status:
      SCHEDULED: start and end.
      LIVE:      end only, and only later (shortening a running auction is unfair to bidders).
      PAUSED:    end only.
    """
    reason = _need_reason(reason)
    locked = _locked(auction)
    now = timezone.now()

    if locked.status not in (Status.SCHEDULED, Status.LIVE, Status.PAUSED):
        raise SchedulingError(f"A {locked.get_status_display().lower()} auction cannot be rescheduled.")
    if start_time is None and end_time is None:
        raise SchedulingError("Enter a new start time or end time.")
    if start_time is not None and locked.status != Status.SCHEDULED:
        raise SchedulingError("The start time can only be changed before the auction starts.")

    new_start = start_time or locked.start_time
    new_end = end_time or locked.end_time
    if new_start >= new_end:
        raise SchedulingError("The start time must be before the end time.")
    if new_end <= now:
        raise SchedulingError("The end time must be in the future.")
    if locked.status == Status.SCHEDULED and start_time is not None and new_start <= now:
        raise SchedulingError("A scheduled start time must be in the future. Use Start now to open it immediately.")
    if locked.status == Status.LIVE and end_time is not None and end_time <= locked.end_time:
        raise SchedulingError("A live auction can only be extended, not shortened.")

    old_start, old_end = locked.start_time, locked.end_time
    locked.start_time, locked.end_time = new_start, new_end
    locked.save(update_fields=["start_time", "end_time", "updated_at"])
    AuditLog.record(
        actor=actor, action=AuditLog.Action.AUCTION_RESCHEDULED, obj=locked, reason=reason,
        old_start=old_start.isoformat(), new_start=new_start.isoformat(),
        old_end=old_end.isoformat(), new_end=new_end.isoformat(),
    )
    notify_auction_update(
        locked, Notification.Event.AUCTION_RESCHEDULED, "Auction rescheduled",
        f"'{locked.title}' now runs {_fmt(new_start)} to {_fmt(new_end)}. Reason: {reason}",
    )
    return locked


@transaction.atomic
def pause(auction, *, actor, reason):
    reason = _need_reason(reason)
    locked = _locked(auction)
    paused = transition(locked, Status.PAUSED, actor=actor, reason=reason)
    AuditLog.record(actor=actor, action=AuditLog.Action.AUCTION_PAUSED, obj=paused, reason=reason)
    notify_auction_update(
        paused, Notification.Event.AUCTION_PAUSED, "Auction paused",
        f"Bidding on '{paused.title}' is paused. Reason: {reason}",
    )
    return paused


@transaction.atomic
def resume(auction, *, actor):
    locked = _locked(auction)
    if locked.status != Status.PAUSED:
        raise SchedulingError(f"Only a paused auction can be resumed (this one is {locked.get_status_display()}).")
    if locked.end_time <= timezone.now():
        raise SchedulingError("The end time has passed while paused. Set a new end time before resuming.")
    live = transition(locked, Status.LIVE, actor=actor, reason="Resumed by staff")
    AuditLog.record(actor=actor, action=AuditLog.Action.AUCTION_RESUMED, obj=live)
    notify_auction_update(
        live, Notification.Event.AUCTION_RESUMED, "Auction resumed",
        f"Bidding on '{live.title}' has resumed. It closes {_fmt(live.end_time)}.",
    )
    return live


@transaction.atomic
def cancel_auction(auction, *, actor, reason):
    """Cancel a scheduled, live or paused auction. Bids already placed stay on record."""
    reason = _need_reason(reason)
    locked = _locked(auction)
    if locked.status not in (Status.SCHEDULED, Status.LIVE, Status.PAUSED):
        raise SchedulingError(f"A {locked.get_status_display().lower()} auction cannot be cancelled here.")
    cancelled = cancel(locked, actor=actor, reason=reason)
    notify_auction_update(
        cancelled, Notification.Event.AUCTION_CANCELLED, "Auction cancelled",
        f"'{cancelled.title}' was cancelled. Reason: {reason}",
    )
    return cancelled


def end_now(auction, *, actor, reason):
    """Close a live auction right now and pick the winner exactly as the automatic close does."""
    from apps.bidding.services import close_auction

    reason = _need_reason(reason)
    with transaction.atomic():
        locked = _locked(auction)
        if locked.status != Status.LIVE:
            raise SchedulingError(f"Only a live auction can be ended (this one is {locked.get_status_display()}).")
        return close_auction(locked, actor=actor, reason=f"Ended early by staff: {reason}")


def sweep_due(*, actor=None):
    """Start every scheduled auction whose time has come and close every live
    auction whose time has run out. Same rules as the two management
    commands; returns (started, closed)."""
    from apps.bidding.services import close_auction

    now = timezone.now()
    started = closed = 0
    for auction in Auction.objects.filter(status=Status.SCHEDULED, start_time__lte=now):
        try:
            activate_if_due(auction, actor=actor)
            started += 1
        except (InvalidTransition, ValidationError):
            pass  # someone else moved it first
    for auction in Auction.objects.filter(status=Status.LIVE, end_time__lte=now):
        try:
            close_auction(auction, actor=actor)
            closed += 1
        except (ValueError, InvalidTransition):
            pass
    return started, closed
