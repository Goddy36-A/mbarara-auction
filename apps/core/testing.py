"""Shared factories for tests. Everything is driven through the real service
layer / state machine rather than writing status fields directly."""
from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import verify_profile
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import Status, approve, submit_for_review, transition

_n = count(1)


def make_user(role, *, verified=True, **kw):
    n = next(_n)
    user = User.objects.create_user(
        username=kw.pop("username", f"{role.lower()}{n}"), password="pw12345!", role=role,
        email=f"{role.lower()}{n}@example.com", **kw,
    )
    if verified and role in (User.Role.SELLER, User.Role.BIDDER):
        officer = User.objects.filter(role=User.Role.OFFICER).first() or User.objects.create_user(
            username=f"autoofficer{n}", password="pw12345!", role=User.Role.OFFICER)
        verify_profile(user.seller_profile if role == User.Role.SELLER else user.bidder_profile, actor=officer)
    return user


def make_officer():
    return make_user(User.Role.OFFICER)


def make_category(name="General"):
    return AuctionCategory.objects.get_or_create(name=name)[0]


def make_auction(seller_user, *, to=Status.LIVE, category=None, officer=None, **overrides):
    """Create an auction and move it to `to` (DRAFT, SUBMITTED, SCHEDULED or LIVE)."""
    now = timezone.now()
    defaults = dict(
        seller=seller_user.seller_profile, category=category or make_category(), title="Item",
        description="Description", starting_price=Decimal("10000"), min_increment=Decimal("1000"),
        start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
    )
    defaults.update(overrides)
    auction = Auction.objects.create(**defaults)
    officer = officer or make_officer()
    order = [Status.DRAFT, Status.SUBMITTED, Status.SCHEDULED, Status.LIVE]
    target = order.index(to)
    if target >= 1:
        submit_for_review(auction, actor=seller_user)
    if target >= 2:
        approve(auction, actor=officer)
    if target >= 3:
        auction.refresh_from_db()
        transition(auction, Status.LIVE, actor=officer, reason="test setup")
    auction.refresh_from_db()
    return auction
