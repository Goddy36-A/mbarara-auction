from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.permissions import StaffOrOfficerRequiredMixin
from apps.auctions.models import Auction

from .forms import DisputeForm
from .models import Dispute
from .services import (
    active_disputes, can_raise_dispute, can_view_dispute, open_dispute, resolve_dispute, take_for_review,
)


class DisputeCreateView(LoginRequiredMixin, View):
    template_name = "disputes/form.html"

    def _auction_or_403(self, request, auction_id):
        auction = get_object_or_404(Auction, pk=auction_id)
        if not can_raise_dispute(request.user, auction):
            raise PermissionDenied("You cannot raise a dispute on this auction.")
        return auction

    def get(self, request, auction_id):
        auction = self._auction_or_403(request, auction_id)
        return render(request, self.template_name, {"form": DisputeForm(), "auction": auction})

    def post(self, request, auction_id):
        auction = self._auction_or_403(request, auction_id)
        form = DisputeForm(request.POST)
        if form.is_valid():
            try:
                dispute = open_dispute(
                    auction, raised_by=request.user,
                    category=form.cleaned_data["category"], description=form.cleaned_data["description"],
                )
            except PermissionError as exc:
                raise PermissionDenied(str(exc))
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Your dispute has been submitted. Staff will review it.")
                return redirect("disputes:detail", pk=dispute.pk)
        return render(request, self.template_name, {"form": form, "auction": auction})


class MyDisputesView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        disputes = Dispute.objects.filter(
            Q(raised_by=user) | Q(auction__seller__user=user) | Q(auction__winner=user)
        ).select_related("auction", "raised_by").distinct()
        return render(request, "disputes/my_disputes.html", {"disputes": disputes})


class DisputeDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        dispute = get_object_or_404(Dispute.objects.select_related("auction__seller__user", "raised_by"), pk=pk)
        if not can_view_dispute(request.user, dispute):
            raise PermissionDenied("You do not have access to this dispute.")
        payment = getattr(dispute.auction, "payment", None)
        return render(request, "disputes/detail.html", {
            "dispute": dispute, "payment": payment,
            "is_staff": request.user.is_officer_or_admin,
            "outcomes": Dispute.Outcome.choices,
        })


class DisputeQueueView(StaffOrOfficerRequiredMixin, View):
    def get(self, request):
        return render(request, "disputes/queue.html", {"disputes": active_disputes()})


class TakeDisputeView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        dispute = get_object_or_404(Dispute, pk=pk)
        try:
            take_for_review(dispute, actor=request.user)
            messages.success(request, f"Dispute #{dispute.pk} assigned to you.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("disputes:detail", pk=dispute.pk)


class ResolveDisputeView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        dispute = get_object_or_404(Dispute, pk=pk)
        try:
            resolve_dispute(
                dispute, actor=request.user,
                outcome=request.POST.get("outcome", ""),
                notes=request.POST.get("notes", ""),
                refund=request.POST.get("refund") == "on",
            )
            messages.success(request, f"Dispute #{dispute.pk} resolved.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("disputes:detail", pk=dispute.pk)
