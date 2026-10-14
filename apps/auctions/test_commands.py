from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.auctions.models import Auction
from apps.auctions.services import Status
from apps.bidding.services import place_bid
from apps.core.testing import make_auction, make_user
from apps.payments.models import Payment


def run(name):
    out = StringIO()
    call_command(name, stdout=out)
    return out.getvalue()


class ActivateScheduledCommandTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)

    def test_activates_only_due_scheduled_auctions(self):
        now = timezone.now()
        due = make_auction(self.seller, to=Status.SCHEDULED, title="due", start_time=now - timedelta(minutes=1), end_time=now + timedelta(hours=1))
        future = make_auction(self.seller, to=Status.SCHEDULED, title="future", start_time=now + timedelta(hours=2), end_time=now + timedelta(hours=3))
        draft = make_auction(self.seller, to=Status.DRAFT, title="draft", start_time=now - timedelta(minutes=1))
        out = run("activate_scheduled_auctions")
        for a in (due, future, draft):
            a.refresh_from_db()
        self.assertEqual(due.status, Status.LIVE)
        self.assertEqual(future.status, Status.SCHEDULED)
        self.assertEqual(draft.status, Status.DRAFT)
        self.assertIn("1 auction(s) activated", out)

    def test_is_idempotent(self):
        make_auction(self.seller, to=Status.SCHEDULED)
        run("activate_scheduled_auctions")
        self.assertIn("0 auction(s) activated", run("activate_scheduled_auctions"))


class CloseEndedCommandTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)

    def _expire(self, auction):
        Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))

    def test_closes_ended_auction_declares_winner_and_creates_payment(self):
        a = make_auction(self.seller)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("15000"))
        self._expire(a)
        out = run("close_ended_auctions")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.CLOSED)
        self.assertEqual(a.winner, self.bidder)
        self.assertEqual(a.final_price, Decimal("15000"))
        self.assertTrue(Payment.objects.filter(auction=a).exists())
        self.assertIn("1 auction(s) closed", out)

    def test_leaves_running_auctions_alone(self):
        a = make_auction(self.seller)
        run("close_ended_auctions")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.LIVE)

    def test_no_bids_closes_without_winner_or_payment(self):
        a = make_auction(self.seller)
        self._expire(a)
        run("close_ended_auctions")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.CLOSED)
        self.assertIsNone(a.winner)
        self.assertFalse(Payment.objects.filter(auction=a).exists())

    def test_running_twice_does_not_close_again_or_duplicate_payment(self):
        a = make_auction(self.seller)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("12000"))
        self._expire(a)
        run("close_ended_auctions")
        self.assertIn("0 auction(s) closed", run("close_ended_auctions"))
        self.assertEqual(Payment.objects.filter(auction=a).count(), 1)


class CreateSuperuserEnvTests(TestCase):
    def test_skips_without_env(self):
        import os
        for k in ("DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD"):
            os.environ.pop(k, None)
        self.assertIn("skipping", run("create_superuser_env"))
        self.assertFalse(User.objects.filter(is_superuser=True).exists())

    def test_creates_then_updates_idempotently(self):
        import os
        os.environ.update(DJANGO_SUPERUSER_EMAIL="a@x.com", DJANGO_SUPERUSER_PASSWORD="S3cretpass!", DJANGO_SUPERUSER_USERNAME="boss")
        try:
            run("create_superuser_env")
            run("create_superuser_env")
        finally:
            for k in ("DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD", "DJANGO_SUPERUSER_USERNAME"):
                os.environ.pop(k, None)
        u = User.objects.get(username="boss")
        self.assertEqual(User.objects.filter(username="boss").count(), 1)
        self.assertTrue(u.is_superuser and u.is_staff)
        self.assertEqual(u.role, User.Role.ADMIN)
        self.assertTrue(u.check_password("S3cretpass!"))
