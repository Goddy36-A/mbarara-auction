"""
Reporting & analytics (Phase 10). Read-only queries over existing data; this
app owns no tables, so figures can never drift from the source records.
"""
import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import BidderProfile, SellerProfile, VerificationStatus
from apps.auctions.models import Auction
from apps.bidding.models import Bid
from apps.disputes.models import Dispute
from apps.payments.models import Payment

# Statuses after bidding has ended and a result exists.
FINISHED_STATUSES = (
    Auction.Status.CLOSED, Auction.Status.SETTLED, Auction.Status.COMPLETED, Auction.Status.DISPUTED,
)


def parse_date(value):
    """'YYYY-MM-DD' -> date, or None for blank/invalid input."""
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _bounds(date_from, date_to):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), tz) if date_from else None
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz) if date_to else None
    return start, end


def _in_range(qs, field, start, end):
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if end:
        qs = qs.filter(**{f"{field}__lt": end})
    return qs


def auctions_in_range(date_from=None, date_to=None):
    return _in_range(Auction.objects.all(), "created_at", *_bounds(date_from, date_to))


def payments_in_range(date_from=None, date_to=None):
    return _in_range(Payment.objects.all(), "created_at", *_bounds(date_from, date_to))


def build_summary(date_from=None, date_to=None):
    start, end = _bounds(date_from, date_to)
    auctions = auctions_in_range(date_from, date_to)

    by_status = {row["status"]: row["n"] for row in auctions.values("status").annotate(n=Count("id"))}
    status_rows = [(label, by_status.get(value, 0)) for value, label in Auction.Status.choices if by_status.get(value)]

    finished = auctions.filter(status__in=FINISHED_STATUSES)
    finished_count = finished.count()
    sold = finished.filter(winner__isnull=False)
    sold_count = sold.count()
    sales_value = sold.aggregate(t=Sum("final_price"))["t"] or Decimal("0")

    bids = _in_range(Bid.objects.filter(status=Bid.Status.ACCEPTED), "created_at", start, end)
    bid_count = bids.count()
    auctions_with_bids = bids.values("auction").distinct().count()

    payments = payments_in_range(date_from, date_to)
    payment_rows = []
    for value, label in Payment.Status.choices:
        agg = payments.filter(status=value).aggregate(n=Count("id"), t=Sum("amount"))
        payment_rows.append((label, agg["n"], agg["t"] or Decimal("0")))

    categories = (
        auctions.values("category__name")
        .annotate(
            total=Count("id"),
            sold=Count("id", filter=Q(status__in=FINISHED_STATUSES, winner__isnull=False)),
            value=Sum("final_price", filter=Q(status__in=FINISHED_STATUSES, winner__isnull=False)),
        )
        .order_by("-total", "category__name")
    )
    category_rows = [(c["category__name"], c["total"], c["sold"], c["value"] or Decimal("0")) for c in categories]

    disputes = Dispute.objects.all()
    disputes = _in_range(disputes, "created_at", start, end)

    return {
        "total_auctions": auctions.count(),
        "status_rows": status_rows,
        "finished_count": finished_count,
        "sold_count": sold_count,
        "unsold_count": finished_count - sold_count,
        "sell_through": round(100 * sold_count / finished_count, 1) if finished_count else None,
        "sales_value": sales_value,
        "average_sale": (sales_value / sold_count).quantize(Decimal("0.01")) if sold_count else None,
        "bid_count": bid_count,
        "avg_bids": round(bid_count / auctions_with_bids, 1) if auctions_with_bids else None,
        "payment_rows": payment_rows,
        "collected": payments.filter(status=Payment.Status.PAID).aggregate(t=Sum("amount"))["t"] or Decimal("0"),
        "outstanding": payments.filter(status=Payment.Status.PENDING).aggregate(t=Sum("amount"))["t"] or Decimal("0"),
        "category_rows": category_rows,
        "disputes_total": disputes.count(),
        "disputes_active": disputes.filter(status__in=Dispute.ACTIVE_STATUSES).count(),
        "verified_sellers": SellerProfile.objects.filter(verification_status=VerificationStatus.VERIFIED).count(),
        "verified_bidders": BidderProfile.objects.filter(verification_status=VerificationStatus.VERIFIED).count(),
        "pending_verifications": (
            SellerProfile.objects.filter(verification_status=VerificationStatus.PENDING).count()
            + BidderProfile.objects.filter(verification_status=VerificationStatus.PENDING).count()
        ),
    }


def csv_safe(value):
    """Neutralise spreadsheet formula injection: a cell starting with = + - @
    is prefixed with a quote so Excel/Sheets treat it as text."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def write_auctions_csv(fileobj, auctions):
    writer = csv.writer(fileobj)
    writer.writerow([
        "id", "title", "seller", "category", "status", "starting_price", "reserve_price",
        "final_price", "winner", "reserve_met", "bids", "start_time", "end_time",
    ])
    qs = auctions.select_related("seller__user", "category", "winner").annotate(
        bid_total=Count("bids", filter=Q(bids__status=Bid.Status.ACCEPTED))
    ).order_by("id")
    for a in qs:
        writer.writerow([csv_safe(v) for v in [
            a.pk, a.title, a.seller.user.username, a.category.name, a.status, a.starting_price,
            a.reserve_price, a.final_price, a.winner.username if a.winner else "", a.reserve_met,
            a.bid_total, a.start_time.isoformat(), a.end_time.isoformat(),
        ]])


def write_payments_csv(fileobj, payments):
    writer = csv.writer(fileobj)
    writer.writerow(["id", "auction_id", "auction_title", "buyer", "seller", "amount", "status", "method", "reference", "paid_at"])
    qs = payments.select_related("auction__seller__user", "auction__winner").order_by("id")
    for p in qs:
        writer.writerow([csv_safe(v) for v in [
            p.pk, p.auction_id, p.auction.title, p.auction.winner.username if p.auction.winner else "",
            p.auction.seller.user.username, p.amount, p.status, p.method, p.reference,
            p.paid_at.isoformat() if p.paid_at else "",
        ]])
