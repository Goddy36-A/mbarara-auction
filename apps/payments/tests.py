from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import verify_profile
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import approve, submit_for_review, transition, Status
from apps.bidding.services import close_auction, place_bid
from apps.notifications.models import Notification

from .models import Payment
from .services import create_pending_payment, mark_failed, mark_paid, mark_refunded, pending_payments


def make_live_auction(seller_profile, category, **overrides):
    from django.utils import timezone

    now = timezone.now()
    defaults = dict(
        seller=seller_profile,
        category=category,
        title="Live Item",
        description="On sale",
        starting_price=Decimal("10000"),
        min_increment=Decimal("1000"),
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(hours=1),
    )
    defaults.update(overrides)
    auction = Auction.objects.create(**defaults)
    officer = User.objects.create_user(username=f"paymentofficer_{auction.pk}", password="x", role=User.Role.OFFICER)
    submit_for_review(auction, actor=seller_profile.user)
    approve(auction, actor=officer)
    auction.refresh_from_db()
    transition(auction, Status.LIVE, actor=officer, reason="test setup")
    auction.refresh_from_db()
    return auction


class PendingPaymentCreationTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="payoff1", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="payseller1", password="x", role=User.Role.SELLER)
        self.bidder = User.objects.create_user(username="paybidder1", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder.bidder_profile, actor=self.officer)
        self.category = AuctionCategory.objects.create(name="Furniture")

    def test_winning_auction_creates_pending_payment(self):
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder, amount=Decimal("10000"))
        closed = close_auction(auction, actor=self.officer)
        payment = Payment.objects.get(auction=closed)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.amount, Decimal("10000"))

    def test_no_winner_creates_no_payment(self):
        auction = make_live_auction(self.seller.seller_profile, self.category, title="No bids")
        close_auction(auction, actor=self.officer)
        self.assertFalse(Payment.objects.filter(auction=auction).exists())

    def test_create_pending_payment_is_idempotent(self):
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder, amount=Decimal("10000"))
        closed = close_auction(auction, actor=self.officer)
        first = Payment.objects.get(auction=closed)
        second = create_pending_payment(closed)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Payment.objects.filter(auction=closed).count(), 1)


class PaymentStateTransitionTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="payoff2", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="payseller2", password="x", role=User.Role.SELLER)
        self.bidder = User.objects.create_user(username="paybidder2", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder.bidder_profile, actor=self.officer)
        self.category = AuctionCategory.objects.create(name="Appliances")
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder, amount=Decimal("10000"))
        self.auction = close_auction(auction, actor=self.officer)
        self.payment = Payment.objects.get(auction=self.auction)

    def test_mark_paid_updates_status_and_advances_auction_to_settled(self):
        mark_paid(self.payment, actor=self.officer, method="Mobile Money", reference="MM123")
        self.payment.refresh_from_db()
        self.auction.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.payment.method, "Mobile Money")
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(self.auction.status, Auction.Status.SETTLED)

    def test_mark_paid_notifies_buyer_and_seller(self):
        mark_paid(self.payment, actor=self.officer)
        self.assertTrue(
            Notification.objects.filter(recipient=self.bidder, event=Notification.Event.PAYMENT_RECEIVED).exists()
        )
        self.assertTrue(
            Notification.objects.filter(recipient=self.seller, event=Notification.Event.PAYMENT_RECEIVED).exists()
        )

    def test_cannot_mark_paid_twice(self):
        mark_paid(self.payment, actor=self.officer)
        with self.assertRaises(ValueError):
            mark_paid(self.payment, actor=self.officer)

    def test_mark_failed_requires_reason(self):
        with self.assertRaises(ValueError):
            mark_failed(self.payment, actor=self.officer, reason="")

    def test_mark_failed_sets_status_and_notifies_buyer(self):
        mark_failed(self.payment, actor=self.officer, reason="Mobile money transaction reversed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        note = Notification.objects.get(recipient=self.bidder, event=Notification.Event.PAYMENT_FAILED)
        self.assertIn("reversed", note.message)

    def test_mark_refunded_requires_paid_status_first(self):
        with self.assertRaises(ValueError):
            mark_refunded(self.payment, actor=self.officer, reason="Item not as described")
        mark_paid(self.payment, actor=self.officer)
        self.payment.refresh_from_db()
        mark_refunded(self.payment, actor=self.officer, reason="Item not as described")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)

    def test_pending_payments_queryset(self):
        self.assertEqual(list(pending_payments()), [self.payment])
        mark_paid(self.payment, actor=self.officer)
        self.assertEqual(list(pending_payments()), [])


class PaymentViewTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="payoff3", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="payseller3", password="x", role=User.Role.SELLER)
        self.bidder = User.objects.create_user(username="paybidder3", password="x", role=User.Role.BIDDER)
        self.other_bidder = User.objects.create_user(username="paybidder4", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder.bidder_profile, actor=self.officer)
        self.category = AuctionCategory.objects.create(name="Tools")
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder, amount=Decimal("10000"))
        self.auction = close_auction(auction, actor=self.officer)
        self.payment = Payment.objects.get(auction=self.auction)

    def test_queue_requires_officer_or_admin(self):
        self.client.login(username="paybidder3", password="x")
        response = self.client.get(reverse("payments:queue"))
        self.assertEqual(response.status_code, 403)

    def test_officer_can_view_queue(self):
        self.client.login(username="payoff3", password="x")
        response = self.client.get(reverse("payments:queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.auction.title)

    def test_officer_can_mark_paid_via_view(self):
        self.client.login(username="payoff3", password="x")
        self.client.post(reverse("payments:mark_paid", args=[self.payment.pk]), {"method": "Cash", "reference": ""})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)

    def test_bidder_sees_only_own_payments(self):
        self.client.login(username="paybidder3", password="x")
        response = self.client.get(reverse("payments:my_payments"))
        self.assertContains(response, self.auction.title)

        self.client.login(username="paybidder4", password="x")
        response = self.client.get(reverse("payments:my_payments"))
        self.assertNotContains(response, self.auction.title)

    def test_seller_sees_own_incoming_payments(self):
        self.client.login(username="payseller3", password="x")
        response = self.client.get(reverse("payments:seller_payments"))
        self.assertContains(response, self.auction.title)
