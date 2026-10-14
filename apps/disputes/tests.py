from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import verify_profile
from apps.audit.models import AuditLog
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import Status, approve, submit_for_review, transition
from apps.bidding.services import close_auction, place_bid
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.payments.services import mark_paid

from .models import Dispute
from .services import can_raise_dispute, open_dispute, resolve_dispute, take_for_review


class DisputeBase(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="dofficer", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="dseller", password="x", role=User.Role.SELLER)
        self.winner = User.objects.create_user(username="dwinner", password="x", role=User.Role.BIDDER)
        self.loser = User.objects.create_user(username="dloser", password="x", role=User.Role.BIDDER)
        self.stranger = User.objects.create_user(username="dstranger", password="x", role=User.Role.BIDDER)
        for u in (self.winner, self.loser, self.stranger):
            verify_profile(u.bidder_profile, actor=self.officer)
        self.category = AuctionCategory.objects.create(name="Phones")

    def closed_auction(self):
        now = timezone.now()
        auction = Auction.objects.create(
            seller=self.seller.seller_profile, category=self.category, title="Phone", description="d",
            starting_price=Decimal("10000"), min_increment=Decimal("1000"),
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
        )
        submit_for_review(auction, actor=self.seller)
        approve(auction, actor=self.officer)
        auction.refresh_from_db()
        transition(auction, Status.LIVE, actor=self.officer, reason="setup")
        auction.refresh_from_db()
        place_bid(auction, bidder_user=self.loser, amount=Decimal("10000"))
        place_bid(auction, bidder_user=self.winner, amount=Decimal("12000"))
        auction.refresh_from_db()
        close_auction(auction, actor=self.officer)
        auction.refresh_from_db()
        return auction


class OpenDisputeTests(DisputeBase):
    def test_participants_can_raise_others_cannot(self):
        auction = self.closed_auction()
        self.assertTrue(can_raise_dispute(self.seller, auction))
        self.assertTrue(can_raise_dispute(self.winner, auction))
        self.assertTrue(can_raise_dispute(self.loser, auction))
        self.assertFalse(can_raise_dispute(self.stranger, auction))

    def test_open_moves_auction_to_disputed_and_logs(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="NOT_AS_DESCRIBED", description="Screen cracked")
        auction.refresh_from_db()
        self.assertEqual(auction.status, Status.DISPUTED)
        self.assertEqual(d.status, Dispute.Status.OPEN)
        self.assertEqual(d.auction_status_before, "CLOSED")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DISPUTE_CREATED).exists())

    def test_notifies_staff_and_seller_but_not_raiser(self):
        auction = self.closed_auction()
        open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        events = Notification.objects.filter(event=Notification.Event.DISPUTE_OPENED)
        recipients = set(events.values_list("recipient__username", flat=True))
        self.assertEqual(recipients, {"dofficer", "dseller"})

    def test_stranger_cannot_open(self):
        auction = self.closed_auction()
        with self.assertRaises(PermissionError):
            open_dispute(auction, raised_by=self.stranger, category="OTHER", description="x")

    def test_live_auction_cannot_be_disputed(self):
        auction = self.closed_auction()
        Auction.objects.filter(pk=auction.pk).update(status=Status.LIVE)
        auction.refresh_from_db()
        with self.assertRaises(ValueError):
            open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")

    def test_description_required_and_one_active_at_a_time(self):
        auction = self.closed_auction()
        with self.assertRaises(ValueError):
            open_dispute(auction, raised_by=self.winner, category="OTHER", description="   ")
        open_dispute(auction, raised_by=self.winner, category="OTHER", description="first")
        auction.refresh_from_db()
        with self.assertRaises(ValueError):
            open_dispute(auction, raised_by=self.seller, category="OTHER", description="second")


class ResolveDisputeTests(DisputeBase):
    def test_resolve_returns_auction_to_closed(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        take_for_review(d, actor=self.officer)
        d.refresh_from_db()
        self.assertEqual(d.status, Dispute.Status.UNDER_REVIEW)
        resolve_dispute(d, actor=self.officer, outcome="DISMISSED", notes="No evidence")
        d.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(d.status, Dispute.Status.RESOLVED)
        self.assertEqual(auction.status, Status.CLOSED)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DISPUTE_RESOLVED).exists())
        self.assertTrue(Notification.objects.filter(event=Notification.Event.DISPUTE_RESOLVED, recipient=self.winner).exists())

    def test_notes_required(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        with self.assertRaises(ValueError):
            resolve_dispute(d, actor=self.officer, outcome="UPHELD", notes="")

    def test_cannot_resolve_twice(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        resolve_dispute(d, actor=self.officer, outcome="UPHELD", notes="ok")
        d.refresh_from_db()
        with self.assertRaises(ValueError):
            resolve_dispute(d, actor=self.officer, outcome="UPHELD", notes="again")

    def test_settled_auction_is_restored_to_settled(self):
        auction = self.closed_auction()
        mark_paid(Payment.objects.get(auction=auction), actor=self.officer, method="Cash")
        auction.refresh_from_db()
        self.assertEqual(auction.status, Status.SETTLED)
        d = open_dispute(auction, raised_by=self.seller, category="NON_PAYMENT", description="x")
        resolve_dispute(d, actor=self.officer, outcome="DISMISSED", notes="Paid in full")
        auction.refresh_from_db()
        self.assertEqual(auction.status, Status.SETTLED)

    def test_refund_marks_payment_refunded_and_leaves_auction_closed(self):
        auction = self.closed_auction()
        payment = Payment.objects.get(auction=auction)
        mark_paid(payment, actor=self.officer, method="Cash")
        auction.refresh_from_db()
        d = open_dispute(auction, raised_by=self.winner, category="NOT_DELIVERED", description="x")
        resolve_dispute(d, actor=self.officer, outcome="UPHELD", notes="Seller no-show", refund=True)
        payment.refresh_from_db()
        auction.refresh_from_db()
        d.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
        self.assertEqual(auction.status, Status.CLOSED)
        self.assertTrue(d.refunded)

    def test_refund_requires_paid_payment(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        with self.assertRaises(ValueError):
            resolve_dispute(d, actor=self.officer, outcome="UPHELD", notes="n", refund=True)
        d.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(d.status, Dispute.Status.OPEN)
        self.assertEqual(auction.status, Status.DISPUTED)


class DisputeViewTests(DisputeBase):
    def test_create_view_flow(self):
        auction = self.closed_auction()
        self.client.force_login(self.winner)
        url = reverse("disputes:create", args=[auction.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {"category": "OTHER", "description": "Problem"})
        d = Dispute.objects.get()
        self.assertRedirects(resp, reverse("disputes:detail", args=[d.pk]))

    def test_stranger_gets_403_on_create_and_detail(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse("disputes:create", args=[auction.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("disputes:detail", args=[d.pk])).status_code, 403)

    def test_losing_bidder_cannot_see_others_dispute(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.loser)
        self.assertEqual(self.client.get(reverse("disputes:detail", args=[d.pk])).status_code, 403)

    def test_queue_and_resolve_are_staff_only(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.winner)
        self.assertEqual(self.client.get(reverse("disputes:queue")).status_code, 403)
        self.assertEqual(self.client.post(reverse("disputes:resolve", args=[d.pk]), {"outcome": "UPHELD", "notes": "n"}).status_code, 403)
        d.refresh_from_db()
        self.assertTrue(d.is_active)

    def test_staff_resolve_via_view(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse("disputes:queue")).status_code, 200)
        self.assertEqual(self.client.get(reverse("disputes:detail", args=[d.pk])).status_code, 200)
        self.client.post(reverse("disputes:resolve", args=[d.pk]), {"outcome": "DISMISSED", "notes": "Nothing found"})
        d.refresh_from_db()
        self.assertEqual(d.status, Dispute.Status.RESOLVED)

    def test_my_disputes_lists_only_involved(self):
        auction = self.closed_auction()
        open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse("disputes:mine")), "Phone")
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("disputes:mine")), "Phone")

    def test_detail_page_shows_raise_button_only_when_eligible(self):
        auction = self.closed_auction()
        self.client.force_login(self.winner)
        self.assertContains(self.client.get(reverse("auctions:detail", args=[auction.pk])), "Raise a dispute")
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse("auctions:detail", args=[auction.pk])), "Raise a dispute")


class DisputeViewEdgeTests(DisputeBase):
    def test_invalid_form_rerenders_without_creating(self):
        auction = self.closed_auction()
        self.client.force_login(self.winner)
        resp = self.client.post(reverse("disputes:create", args=[auction.pk]), {"category": "BOGUS", "description": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Dispute.objects.count(), 0)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Status.CLOSED)

    def test_cannot_create_second_dispute_via_view(self):
        auction = self.closed_auction()
        open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("disputes:create", args=[auction.pk])).status_code, 403)

    def test_take_view_assigns_officer_and_is_staff_only(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.winner)
        self.assertEqual(self.client.post(reverse("disputes:take", args=[d.pk])).status_code, 403)
        self.client.force_login(self.officer)
        self.client.post(reverse("disputes:take", args=[d.pk]))
        d.refresh_from_db()
        self.assertEqual((d.status, d.assigned_to), (Dispute.Status.UNDER_REVIEW, self.officer))

    def test_take_twice_is_rejected_gracefully(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.officer)
        self.client.post(reverse("disputes:take", args=[d.pk]))
        resp = self.client.post(reverse("disputes:take", args=[d.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_resolve_without_notes_via_view_keeps_dispute_active(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        self.client.force_login(self.officer)
        self.client.post(reverse("disputes:resolve", args=[d.pk]), {"outcome": "UPHELD", "notes": ""})
        d.refresh_from_db()
        self.assertTrue(d.is_active)

    def test_refund_checkbox_via_view(self):
        auction = self.closed_auction()
        mark_paid(Payment.objects.get(auction=auction), actor=self.officer, method="Cash")
        auction.refresh_from_db()
        d = open_dispute(auction, raised_by=self.winner, category="NOT_DELIVERED", description="x")
        self.client.force_login(self.officer)
        self.client.post(reverse("disputes:resolve", args=[d.pk]), {"outcome": "UPHELD", "notes": "Refund due", "refund": "on"})
        self.assertEqual(Payment.objects.get(auction=auction).status, Payment.Status.REFUNDED)

    def test_resolved_dispute_detail_shows_outcome(self):
        auction = self.closed_auction()
        d = open_dispute(auction, raised_by=self.winner, category="OTHER", description="x")
        resolve_dispute(d, actor=self.officer, outcome="DISMISSED", notes="Checked the records")
        self.client.force_login(self.winner)
        resp = self.client.get(reverse("disputes:detail", args=[d.pk]))
        self.assertContains(resp, "Checked the records")
        self.assertContains(resp, "Complaint dismissed")
