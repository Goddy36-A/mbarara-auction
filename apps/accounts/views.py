from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView

from .forms import RegistrationForm
from .models import BidderProfile, SellerProfile
from .permissions import StaffOrOfficerRequiredMixin
from .services import pending_profiles, reject_profile, verify_profile


class RegisterView(CreateView):
    """
    Public self-registration for Sellers and Bidders (Section 10-13).
    Logs the new user in immediately after successful registration so they
    land straight on their dashboard, matching common auction-site UX.
    The matching SellerProfile/BidderProfile is created automatically by
    apps.accounts.signals.create_role_profile.
    """

    form_class = RegistrationForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("core:dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class VerificationQueueView(StaffOrOfficerRequiredMixin, View):
    """Administrator/officer screen listing every seller and bidder profile
    still awaiting verification (Section 11)."""

    template_name = "accounts/verification_queue.html"

    def get(self, request):
        return render(request, self.template_name, pending_profiles())


class VerifySellerView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        profile = get_object_or_404(SellerProfile, pk=pk)
        decision = request.POST.get("decision")
        reason = request.POST.get("reason", "")
        if decision == "approve":
            verify_profile(profile, actor=request.user, reason=reason)
            messages.success(request, f"Seller {profile.user.username} verified.")
        elif decision == "reject":
            if not reason:
                messages.error(request, "A reason is required to reject a seller.")
                return redirect("accounts:verification_queue")
            reject_profile(profile, actor=request.user, reason=reason)
            messages.warning(request, f"Seller {profile.user.username} rejected.")
        return redirect("accounts:verification_queue")


class VerifyBidderView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        profile = get_object_or_404(BidderProfile, pk=pk)
        decision = request.POST.get("decision")
        reason = request.POST.get("reason", "")
        if decision == "approve":
            verify_profile(profile, actor=request.user, reason=reason)
            messages.success(request, f"Bidder {profile.user.username} verified.")
        elif decision == "reject":
            if not reason:
                messages.error(request, "A reason is required to reject a bidder.")
                return redirect("accounts:verification_queue")
            reject_profile(profile, actor=request.user, reason=reason)
            messages.warning(request, f"Bidder {profile.user.username} rejected.")
        return redirect("accounts:verification_queue")
