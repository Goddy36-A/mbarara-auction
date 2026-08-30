from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import verify_profile

from .models import Auction, AuctionCategory
from .services import InvalidTransition, activate_if_due, approve, reject, submit_for_review, transition


def make_auction(seller_profile, category, **overrides):
    now = timezone.now()
    defaults = dict(
        seller=seller_profile,
        category=category,
        title="Test Item",
        description="A thing for sale",
        starting_price=Decimal("10000"),
        min_increment=Decimal("1000"),
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(days=1),
    )
    defaults.update(overrides)
    return Auction.objects.create(**defaults)


class AuctionLifecycleTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="officer", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="seller", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Electronics")
        self.auction = make_auction(self.seller.seller_profile, self.category)

    def test_new_auction_starts_as_draft(self):
        self.assertEqual(self.auction.status, Auction.Status.DRAFT)

    def test_valid_transition_sequence(self):
        submit_for_review(self.auction, actor=self.seller)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.SUBMITTED)

        approve(self.auction, actor=self.officer, reason="Looks good")
        self.auction.refresh_from_db()
        # approve() advances straight through APPROVED to SCHEDULED
        self.assertEqual(self.auction.status, Auction.Status.SCHEDULED)
        self.assertEqual(self.auction.status_logs.count(), 3)  # DRAFT->SUBMITTED, SUBMITTED->APPROVED, APPROVED->SCHEDULED

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(InvalidTransition):
            transition(self.auction, Auction.Status.LIVE, actor=self.officer)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.DRAFT)

    def test_rejecting_requires_a_reason(self):
        submit_for_review(self.auction, actor=self.seller)
        with self.assertRaises(InvalidTransition):
            reject(self.auction, actor=self.officer, reason="")

    def test_activate_if_due_moves_scheduled_to_live_once_start_time_passed(self):
        submit_for_review(self.auction, actor=self.seller)
        approve(self.auction, actor=self.officer)
        self.auction.refresh_from_db()
        self.auction.start_time = timezone.now() - timedelta(minutes=1)
        self.auction.save(update_fields=["start_time"])

        activate_if_due(self.auction)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.LIVE)

    def test_terminal_states_have_no_further_transitions(self):
        submit_for_review(self.auction, actor=self.seller)
        reject(self.auction, actor=self.officer, reason="Not eligible")
        with self.assertRaises(InvalidTransition):
            transition(self.auction, Auction.Status.SCHEDULED, actor=self.officer)


class PublicVisibilityTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="seller2", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Vehicles")
        self.draft = make_auction(self.seller.seller_profile, self.category, title="Draft item")

    def test_draft_auction_not_in_public_browse(self):
        response = self.client.get(reverse("auctions:browse"))
        self.assertNotContains(response, "Draft item")

    def test_draft_auction_detail_404s_for_stranger(self):
        response = self.client.get(reverse("auctions:detail", args=[self.draft.pk]))
        self.assertEqual(response.status_code, 404)

    def test_draft_auction_detail_visible_to_owner(self):
        self.client.login(username="seller2", password="x")
        response = self.client.get(reverse("auctions:detail", args=[self.draft.pk]))
        self.assertEqual(response.status_code, 200)
