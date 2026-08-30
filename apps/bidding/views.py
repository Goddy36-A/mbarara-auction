from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.permissions import BidderRequiredMixin
from apps.auctions.models import Auction

from .models import Bid
from .services import BidRejected, place_bid


class PlaceBidView(BidderRequiredMixin, View):
    """
    Handles the bid-confirmation submit (Section 32). All real validation
    happens server-side in apps.bidding.services.place_bid — this view's
    only job is translating between the HTTP form and that service, and
    turning a BidRejected into a user-facing message rather than a 500.
    """

    def post(self, request, auction_id):
        auction = get_object_or_404(Auction, pk=auction_id)
        raw_amount = request.POST.get("amount", "")
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, TypeError):
            messages.error(request, "Enter a valid bid amount.")
            return redirect("auctions:detail", pk=auction.pk)

        try:
            bid = place_bid(auction, bidder_user=request.user, amount=amount)
            messages.success(request, f"Bid of {bid.amount} placed successfully.")
        except BidRejected as exc:
            messages.error(request, str(exc))

        return redirect("auctions:detail", pk=auction.pk)


class MyBidsView(BidderRequiredMixin, View):
    """Bidder dashboard data (Section 29): active bids, auctions won/lost,
    full personal bid history."""

    def get(self, request):
        my_bids = (
            Bid.objects.filter(bidder=request.user.bidder_profile)
            .select_related("auction")
            .order_by("-created_at")
        )
        won = Auction.objects.filter(winner=request.user)
        return render(request, "bidding/my_bids.html", {"my_bids": my_bids, "won_auctions": won})
