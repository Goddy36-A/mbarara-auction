from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.auctions.models import Auction
from apps.auctions.services import Status
from apps.core.testing import make_auction, make_user
from apps.notifications.models import Notification

from .models import Bid
from .services import BidRejected, close_auction, place_bid


class AntiSnipingTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)

    def test_bid_inside_window_extends_end_time(self):
        now = timezone.now()
        a = make_auction(self.seller, extension_minutes=5, end_time=now + timedelta(minutes=2))
        before = timezone.now()
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        self.assertGreaterEqual(a.end_time, before + timedelta(minutes=5))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.AUCTION_EXTENDED).exists())

    def test_bid_outside_window_does_not_extend(self):
        end = timezone.now() + timedelta(hours=1)
        a = make_auction(self.seller, extension_minutes=5, end_time=end)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        self.assertEqual(a.end_time, end)

    def test_zero_extension_disables_feature(self):
        end = timezone.now() + timedelta(minutes=1)
        a = make_auction(self.seller, extension_minutes=0, end_time=end)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        self.assertEqual(a.end_time, end)

    def test_extended_auction_still_accepts_bids_past_original_end(self):
        a = make_auction(self.seller, extension_minutes=5, end_time=timezone.now() + timedelta(minutes=1))
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        self.assertTrue(a.is_biddable)


class BidRuleEdgeTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)
        self.b1 = make_user(User.Role.BIDDER)
        self.b2 = make_user(User.Role.BIDDER)
        self.a = make_auction(self.seller)

    def test_exact_minimum_accepted_one_below_rejected(self):
        place_bid(self.a, bidder_user=self.b1, amount=Decimal("10000"))
        self.a.refresh_from_db()
        with self.assertRaises(BidRejected):
            place_bid(self.a, bidder_user=self.b2, amount=Decimal("10999.99"))
        place_bid(self.a, bidder_user=self.b2, amount=Decimal("11000"))
        self.a.refresh_from_db()
        self.assertEqual(self.a.current_highest_bid, Decimal("11000.00"))

    def test_rejected_bid_leaves_no_trace(self):
        with self.assertRaises(BidRejected):
            place_bid(self.a, bidder_user=self.b1, amount=Decimal("1"))
        self.assertEqual(Bid.objects.count(), 0)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.current_highest_bid)

    def test_non_bidder_user_cannot_bid(self):
        officer = make_user(User.Role.OFFICER)
        with self.assertRaises(BidRejected):
            place_bid(self.a, bidder_user=officer, amount=Decimal("10000"))

    def test_cannot_bid_on_non_live_states(self):
        for status in (Status.DRAFT, Status.SCHEDULED, Status.SUBMITTED):
            a = make_auction(self.seller, to=status)
            with self.assertRaises(BidRejected, msg=status):
                place_bid(a, bidder_user=self.b1, amount=Decimal("10000"))

    def test_outbid_notification_goes_to_previous_leader_only(self):
        place_bid(self.a, bidder_user=self.b1, amount=Decimal("10000"))
        self.a.refresh_from_db()
        place_bid(self.a, bidder_user=self.b2, amount=Decimal("12000"))
        outbid = Notification.objects.filter(event=Notification.Event.OUTBID)
        self.assertEqual([n.recipient for n in outbid], [self.b1])

    def test_raising_own_bid_does_not_notify_self(self):
        place_bid(self.a, bidder_user=self.b1, amount=Decimal("10000"))
        self.a.refresh_from_db()
        place_bid(self.a, bidder_user=self.b1, amount=Decimal("12000"))
        self.assertFalse(Notification.objects.filter(event=Notification.Event.OUTBID).exists())

    def test_close_requires_live_status(self):
        a = make_auction(self.seller, to=Status.SCHEDULED)
        with self.assertRaises(ValueError):
            close_auction(a)

    def test_reserve_exactly_met_wins(self):
        a = make_auction(self.seller, reserve_price=Decimal("15000"))
        place_bid(a, bidder_user=self.b1, amount=Decimal("15000"))
        a.refresh_from_db()
        closed = close_auction(a)
        self.assertEqual(closed.winner, self.b1)
        self.assertTrue(closed.reserve_met)


class BidViewEdgeTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)
        self.a = make_auction(self.seller)
        self.url = reverse("bidding:place_bid", args=[self.a.pk])

    def test_extreme_amounts_rejected_by_service(self):
        for bad in ("NaN", "Infinity", "-Infinity", "1E+20", "10000.123", "-5", "0"):
            with self.assertRaises(BidRejected, msg=bad):
                place_bid(self.a, bidder_user=make_user(User.Role.BIDDER), amount=Decimal(bad))
        self.assertEqual(Bid.objects.count(), 0)

    def test_non_numeric_amount_rejected_gracefully(self):
        self.client.force_login(self.bidder)
        for bad in ("abc", "", "1e500x", "NaN", "Infinity", "1E+30", "10000.999"):
            resp = self.client.post(self.url, {"amount": bad})
            self.assertEqual(resp.status_code, 302, bad)
        self.assertEqual(Bid.objects.count(), 0)

    def test_get_not_allowed(self):
        self.client.force_login(self.bidder)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonymous_cannot_bid(self):
        self.assertIn(self.client.post(self.url, {"amount": "10000"}).status_code, (302, 403))
        self.assertEqual(Bid.objects.count(), 0)

    def test_unknown_auction_404(self):
        self.client.force_login(self.bidder)
        self.assertEqual(self.client.post(reverse("bidding:place_bid", args=[99999]), {"amount": "10000"}).status_code, 404)

    def test_my_bids_page_lists_bids_and_wins(self):
        place_bid(self.a, bidder_user=self.bidder, amount=Decimal("10000"))
        Auction.objects.filter(pk=self.a.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        self.a.refresh_from_db()
        close_auction(self.a)
        self.client.force_login(self.bidder)
        resp = self.client.get(reverse("bidding:my_bids"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["my_bids"]), 1)
        self.assertEqual(len(resp.context["won_auctions"]), 1)

    def test_detail_page_bid_box_visibility(self):
        detail = reverse("auctions:detail", args=[self.a.pk])
        self.assertNotContains(self.client.get(detail), "Place bid")
        self.client.force_login(self.bidder)
        self.assertContains(self.client.get(detail), "Place bid")
        self.client.force_login(self.seller)
        self.assertNotContains(self.client.get(detail), "Place bid")
