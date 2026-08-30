from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.bidding.services import get_bid_history

from .models import Auction, AuctionCategory


def browse(request):
    """Public auction search/browse (Section 30). Only publicly-visible
    statuses are shown — a DRAFT or SUBMITTED listing is never exposed."""
    qs = Auction.objects.filter(status__in=Auction.PUBLICLY_VISIBLE_STATUSES).select_related("category", "seller__user")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    category_slug = request.GET.get("category", "").strip()
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    status = request.GET.get("status", "").strip()
    if status in dict(Auction.Status.choices):
        qs = qs.filter(status=status)

    return render(
        request,
        "auctions/browse.html",
        {
            "auctions": qs.order_by("-status", "end_time")[:100],
            "categories": AuctionCategory.objects.all(),
            "query": q,
            "selected_category": category_slug,
        },
    )


def detail(request, pk):
    auction = get_object_or_404(
        Auction.objects.select_related("category", "seller__user").prefetch_related("images"),
        pk=pk,
    )
    # A seller can preview their own non-public listing; anyone else can
    # only see it once it's publicly visible (object-level check, Section 42).
    is_owner = request.user.is_authenticated and getattr(request.user, "seller_profile", None) == auction.seller
    is_staff = request.user.is_authenticated and request.user.is_officer_or_admin
    if auction.status not in Auction.PUBLICLY_VISIBLE_STATUSES and not (is_owner or is_staff):
        raise Http404("Auction not found.")

    minimum_permitted = (
        (auction.current_highest_bid + auction.min_increment)
        if auction.current_highest_bid is not None
        else auction.starting_price
    )

    can_bid = (
        request.user.is_authenticated
        and request.user.is_bidder
        and auction.is_biddable
        and getattr(request.user.bidder_profile, "is_eligible_to_bid", False)
        and request.user.pk != auction.seller.user_id
    )

    return render(
        request,
        "auctions/detail.html",
        {
            "auction": auction,
            "server_time": timezone.now(),
            "is_owner": is_owner,
            "bid_history": get_bid_history(auction, viewer=request.user),
            "minimum_permitted": minimum_permitted,
            "can_bid": can_bid,
        },
    )
