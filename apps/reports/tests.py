import io
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import verify_profile
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import Status, approve, submit_for_review, transition
from apps.bidding.services import close_auction, place_bid
from apps.payments.models import Payment
from apps.payments.services import mark_paid

from .services import build_summary, csv_safe, parse_date, write_auctions_csv


class ReportsBase(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="rofficer", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="rseller", password="x", role=User.Role.SELLER)
        self.bidder = User.objects.create_user(username="rbidder", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder.bidder_profile, actor=self.officer)
        verify_profile(self.seller.seller_profile, actor=self.officer)
        self.cat = AuctionCategory.objects.create(name="Furniture")

    def make_auction(self, title, bid=None, close=True, reserve=None):
        now = timezone.now()
        a = Auction.objects.create(
            seller=self.seller.seller_profile, category=self.cat, title=title, description="d",
            starting_price=Decimal("10000"), reserve_price=reserve, min_increment=Decimal("1000"),
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
        )
        submit_for_review(a, actor=self.seller)
        approve(a, actor=self.officer)
        a.refresh_from_db()
        transition(a, Status.LIVE, actor=self.officer, reason="setup")
        a.refresh_from_db()
        if bid:
            place_bid(a, bidder_user=self.bidder, amount=Decimal(bid))
        if close:
            a.refresh_from_db()
            close_auction(a, actor=self.officer)
        a.refresh_from_db()
        return a


class SummaryTests(ReportsBase):
    def test_empty_summary_has_no_division_errors(self):
        s = build_summary()
        self.assertEqual(s["total_auctions"], 0)
        self.assertIsNone(s["sell_through"])
        self.assertIsNone(s["average_sale"])
        self.assertEqual(s["sales_value"], Decimal("0"))

    def test_sales_and_sell_through(self):
        self.make_auction("Sold one", bid="20000")
        self.make_auction("Sold two", bid="30000")
        self.make_auction("No bids")
        self.make_auction("Below reserve", bid="10000", reserve=Decimal("50000"))
        s = build_summary()
        self.assertEqual(s["total_auctions"], 4)
        self.assertEqual(s["finished_count"], 4)
        self.assertEqual(s["sold_count"], 2)
        self.assertEqual(s["unsold_count"], 2)
        self.assertEqual(s["sell_through"], 50.0)
        self.assertEqual(s["sales_value"], Decimal("50000"))
        self.assertEqual(s["average_sale"], Decimal("25000.00"))
        self.assertEqual(s["bid_count"], 3)

    def test_payment_totals(self):
        a = self.make_auction("Paid", bid="20000")
        self.make_auction("Owed", bid="15000")
        mark_paid(Payment.objects.get(auction=a), actor=self.officer, method="Cash")
        s = build_summary()
        self.assertEqual(s["collected"], Decimal("20000"))
        self.assertEqual(s["outstanding"], Decimal("15000"))

    def test_date_range_excludes_outside(self):
        self.make_auction("Today", bid="20000")
        tomorrow = date.today() + timedelta(days=2)
        s = build_summary(date_from=tomorrow, date_to=tomorrow + timedelta(days=1))
        self.assertEqual(s["total_auctions"], 0)
        s = build_summary(date_from=date.today() - timedelta(days=1), date_to=date.today() + timedelta(days=1))
        self.assertEqual(s["total_auctions"], 1)

    def test_category_rows(self):
        self.make_auction("A", bid="20000")
        s = build_summary()
        self.assertEqual(s["category_rows"], [("Furniture", 1, 1, Decimal("20000.00"))])


class HelperTests(TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("2026-10-13"), date(2026, 10, 13))
        self.assertIsNone(parse_date("13/10/2026"))
        self.assertIsNone(parse_date(""))

    def test_csv_safe_blocks_formulas(self):
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("@cmd"), "'@cmd")
        self.assertEqual(csv_safe("Plain"), "Plain")
        self.assertEqual(csv_safe(None), "")


class ReportViewTests(ReportsBase):
    def test_non_staff_and_anonymous_forbidden(self):
        # StaffOrOfficerRequiredMixin uses raise_exception=True, so anonymous
        # users also get 403 (consistent with the other staff-only screens).
        for url in ("reports:dashboard", "reports:auctions_csv", "reports:payments_csv"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 403)
        self.client.force_login(self.bidder)
        for url in ("reports:dashboard", "reports:auctions_csv", "reports:payments_csv"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 403)

    def test_dashboard_renders_for_officer(self):
        self.make_auction("Chair", bid="20000")
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sales value")

    def test_bad_dates_show_error_not_crash(self):
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("reports:dashboard"), {"from": "nonsense"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter valid dates")

    def test_csv_downloads(self):
        self.make_auction("=HYPERLINK(1)", bid="20000")
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("reports:auctions_csv"))
        self.assertEqual(resp["Content-Type"], "text/csv")
        body = resp.content.decode()
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertIn("rbidder", body)
        resp = self.client.get(reverse("reports:payments_csv"))
        self.assertIn("20000", resp.content.decode())
