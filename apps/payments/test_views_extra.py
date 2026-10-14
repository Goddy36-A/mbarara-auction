from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.auctions.models import Auction
from apps.auctions.services import Status
from apps.bidding.services import close_auction, place_bid
from apps.core.testing import make_auction, make_user

from .models import Payment


class PaymentActionViewTests(TestCase):
    def setUp(self):
        self.officer = make_user(User.Role.OFFICER)
        self.seller = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)
        a = make_auction(self.seller)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("20000"))
        Auction.objects.filter(pk=a.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        a.refresh_from_db()
        self.auction = close_auction(a)
        self.payment = Payment.objects.get(auction=self.auction)

    def test_mark_paid_records_method_reference_and_settles(self):
        self.client.force_login(self.officer)
        self.client.post(reverse("payments:mark_paid", args=[self.payment.pk]),
                         {"method": "Mobile Money", "reference": "TX123", "notes": "ok"})
        self.payment.refresh_from_db()
        self.auction.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.method, self.payment.reference), ("PAID", "Mobile Money", "TX123"))
        self.assertEqual(self.auction.status, Status.SETTLED)
        self.assertEqual(self.payment.recorded_by, self.officer)

    def test_mark_paid_twice_shows_error_and_changes_nothing(self):
        self.client.force_login(self.officer)
        url = reverse("payments:mark_paid", args=[self.payment.pk])
        self.client.post(url, {"method": "Cash"})
        resp = self.client.post(url, {"method": "Other"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.method, "Cash")

    def test_mark_failed_requires_reason(self):
        self.client.force_login(self.officer)
        url = reverse("payments:mark_failed", args=[self.payment.pk])
        self.client.post(url, {"reason": ""})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.client.post(url, {"reason": "Buyer unreachable"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.payment.notes, "Buyer unreachable")

    def test_failed_payment_cannot_then_be_marked_paid(self):
        self.client.force_login(self.officer)
        self.client.post(reverse("payments:mark_failed", args=[self.payment.pk]), {"reason": "x"})
        self.client.post(reverse("payments:mark_paid", args=[self.payment.pk]), {"method": "Cash"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)

    def test_non_staff_cannot_mark_paid_or_failed(self):
        for user in (self.bidder, self.seller):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("payments:mark_paid", args=[self.payment.pk]), {"method": "x"}).status_code, 403)
            self.assertEqual(self.client.post(reverse("payments:mark_failed", args=[self.payment.pk]), {"reason": "x"}).status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_unknown_payment_404(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.post(reverse("payments:mark_paid", args=[99999]), {}).status_code, 404)
