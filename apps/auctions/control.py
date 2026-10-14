"""Auction Control dashboard (staff only): see everything that is scheduled or
running, with live countdowns, and act on it."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from datetime import timedelta

from django.utils import timezone
from django.views import View

from apps.accounts.permissions import StaffOrOfficerRequiredMixin

from . import scheduling
from .models import Auction, AuctionStatusLog
from .scheduling import SchedulingError
from .services import InvalidTransition, Status

DT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"]


class RescheduleForm(forms.Form):
    start_time = forms.DateTimeField(required=False, input_formats=DT_FORMATS)
    end_time = forms.DateTimeField(required=False, input_formats=DT_FORMATS)
    reason = forms.CharField(max_length=500)


def _message(exc):
    if isinstance(exc, ValidationError):
        return "; ".join(exc.messages)
    return str(exc)


def _with_bid_counts(qs):
    return qs.select_related("seller__user", "category").annotate(
        bid_total=Count("bids", filter=Q(bids__status="ACCEPTED"))
    )


class ControlDashboardView(StaffOrOfficerRequiredMixin, View):
    def get(self, request):
        now = timezone.now()
        scheduled = _with_bid_counts(Auction.objects.filter(status=Status.SCHEDULED)).order_by("start_time")
        live = _with_bid_counts(Auction.objects.filter(status=Status.LIVE)).order_by("end_time")
        paused = _with_bid_counts(Auction.objects.filter(status=Status.PAUSED)).order_by("end_time")
        return render(request, "control/dashboard.html", {
            "scheduled": scheduled, "live": live, "paused": paused,
            "overdue_start": scheduled.filter(start_time__lte=now).count(),
            "overdue_close": live.filter(end_time__lte=now).count(),
            "ending_soon": live.filter(end_time__lte=now + timedelta(hours=1), end_time__gt=now).count(),
            "total_bids": sum(a.bid_total for a in live),
        })


class AuctionControlView(StaffOrOfficerRequiredMixin, View):
    def get(self, request, pk):
        auction = get_object_or_404(_with_bid_counts(Auction.objects.all()), pk=pk)
        history = AuctionStatusLog.objects.filter(auction=auction).select_related("changed_by")[:15]
        return render(request, "control/auction.html", {
            "auction": auction, "history": history,
            "can_start": auction.status == Status.SCHEDULED,
            "can_pause": auction.status == Status.LIVE,
            "can_resume": auction.status == Status.PAUSED,
            "can_end": auction.status == Status.LIVE,
            "can_cancel": auction.status in (Status.SCHEDULED, Status.LIVE, Status.PAUSED),
            "can_reschedule": auction.status in (Status.SCHEDULED, Status.LIVE, Status.PAUSED),
            "can_edit_start": auction.status == Status.SCHEDULED,
            "local_start": timezone.localtime(auction.start_time).strftime("%Y-%m-%dT%H:%M"),
            "local_end": timezone.localtime(auction.end_time).strftime("%Y-%m-%dT%H:%M"),
        })


class _ActionView(StaffOrOfficerRequiredMixin, View):
    success = "Done."

    def run(self, request, auction):
        raise NotImplementedError

    def post(self, request, pk):
        auction = get_object_or_404(Auction, pk=pk)
        try:
            self.run(request, auction)
            messages.success(request, self.success)
        except (SchedulingError, InvalidTransition, ValidationError, ValueError) as exc:
            messages.error(request, _message(exc))
        return redirect("control:auction", pk=pk)


class StartNowView(_ActionView):
    success = "Auction is now live."

    def run(self, request, auction):
        scheduling.start_now(auction, actor=request.user)


class PauseView(_ActionView):
    success = "Auction paused."

    def run(self, request, auction):
        scheduling.pause(auction, actor=request.user, reason=request.POST.get("reason", ""))


class ResumeView(_ActionView):
    success = "Auction resumed."

    def run(self, request, auction):
        scheduling.resume(auction, actor=request.user)


class CancelView(_ActionView):
    success = "Auction cancelled."

    def run(self, request, auction):
        scheduling.cancel_auction(auction, actor=request.user, reason=request.POST.get("reason", ""))


class EndNowView(_ActionView):
    success = "Auction closed and the winner (if any) has been determined."

    def run(self, request, auction):
        scheduling.end_now(auction, actor=request.user, reason=request.POST.get("reason", ""))


class RescheduleView(_ActionView):
    success = "Schedule updated. The seller and bidders have been notified."

    def run(self, request, auction):
        form = RescheduleForm(request.POST)
        if not form.is_valid():
            raise SchedulingError("Enter valid dates (and a reason). " + " ".join(
                f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
        scheduling.reschedule(
            auction, actor=request.user, reason=form.cleaned_data["reason"],
            start_time=form.cleaned_data["start_time"], end_time=form.cleaned_data["end_time"],
        )


class SweepView(StaffOrOfficerRequiredMixin, View):
    def post(self, request):
        started, closed = scheduling.sweep_due(actor=request.user)
        messages.success(request, f"Sweep complete: {started} auction(s) started, {closed} closed.")
        return redirect("control:dashboard")
