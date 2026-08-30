from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.permissions import SellerRequiredMixin, StaffOrOfficerRequiredMixin, check_owner
from apps.auctions.models import Auction
from apps.auctions.services import InvalidTransition, approve, reject, submit_for_review

from .forms import AuctionForm, AuctionImageFormSet


def _own_draft_or_403(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    check_owner(request.user, auction.seller.user)
    if auction.status != Auction.Status.DRAFT:
        raise PermissionDenied("This listing can no longer be edited (it has left DRAFT status).")
    return auction


class MyListingsView(SellerRequiredMixin, View):
    def get(self, request):
        auctions = Auction.objects.filter(seller=request.user.seller_profile).order_by("-created_at")
        return render(request, "listings/my_listings.html", {"auctions": auctions})


class AuctionCreateView(SellerRequiredMixin, View):
    template_name = "listings/auction_form.html"

    def get(self, request):
        form = AuctionForm()
        return render(request, self.template_name, {"form": form, "formset": None})

    def post(self, request):
        form = AuctionForm(request.POST)
        if form.is_valid():
            auction = form.save(commit=False)
            auction.seller = request.user.seller_profile
            auction.status = Auction.Status.DRAFT
            auction.save()
            formset = AuctionImageFormSet(request.POST, request.FILES, instance=auction)
            if formset.is_valid():
                formset.save()
            else:
                messages.warning(request, "Auction saved, but some images were rejected: check file type/size.")
            messages.success(request, "Draft listing created. Submit it for review when you're ready.")
            return redirect("listings:my_listings")
        return render(request, self.template_name, {"form": form, "formset": None})


class AuctionEditView(SellerRequiredMixin, View):
    template_name = "listings/auction_form.html"

    def get(self, request, pk):
        auction = _own_draft_or_403(request, pk)
        form = AuctionForm(instance=auction)
        formset = AuctionImageFormSet(instance=auction)
        return render(request, self.template_name, {"form": form, "formset": formset, "auction": auction})

    def post(self, request, pk):
        auction = _own_draft_or_403(request, pk)
        form = AuctionForm(request.POST, instance=auction)
        formset = AuctionImageFormSet(request.POST, request.FILES, instance=auction)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Listing updated.")
            return redirect("listings:my_listings")
        return render(request, self.template_name, {"form": form, "formset": formset, "auction": auction})


class SubmitListingView(SellerRequiredMixin, View):
    def post(self, request, pk):
        auction = get_object_or_404(Auction, pk=pk)
        check_owner(request.user, auction.seller.user)
        try:
            submit_for_review(auction, actor=request.user)
            messages.success(request, "Listing submitted for review.")
        except InvalidTransition as exc:
            messages.error(request, str(exc))
        return redirect("listings:my_listings")


class ApprovalQueueView(StaffOrOfficerRequiredMixin, View):
    def get(self, request):
        pending = Auction.objects.filter(status=Auction.Status.SUBMITTED).select_related("seller__user", "category")
        return render(request, "listings/approval_queue.html", {"auctions": pending})


class ApproveListingView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        auction = get_object_or_404(Auction, pk=pk)
        try:
            approve(auction, actor=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, f"'{auction.title}' approved and scheduled.")
        except InvalidTransition as exc:
            messages.error(request, str(exc))
        return redirect("listings:approval_queue")


class RejectListingView(StaffOrOfficerRequiredMixin, View):
    def post(self, request, pk):
        auction = get_object_or_404(Auction, pk=pk)
        reason = request.POST.get("reason", "")
        if not reason:
            messages.error(request, "A reason is required to reject a listing.")
            return redirect("listings:approval_queue")
        try:
            reject(auction, actor=request.user, reason=reason)
            messages.warning(request, f"'{auction.title}' rejected.")
        except InvalidTransition as exc:
            messages.error(request, str(exc))
        return redirect("listings:approval_queue")
