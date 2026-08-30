from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import suspend_bidder, verify_profile
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import approve, submit_for_review, transition, Status

from .models import Bid
from .services import BidRejected, close_auction, get_bid_history, invalidate_bid, place_bid


def make_live_auction(seller_profile, category, **overrides):
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
    # Drive it through the real state machine rather than poking .status directly.
    officer = User.objects.create_user(username=f"officer_{auction.pk}", password="x", role=User.Role.OFFICER)
    submit_for_review(auction, actor=seller_profile.user)
    approve(auction, actor=officer)
    auction.refresh_from_db()
    transition(auction, Status.LIVE, actor=officer, reason="test setup")
    auction.refresh_from_db()
    return auction


class PlaceBidValidationTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="off1", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="sellerB", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Livestock")
        self.auction = make_live_auction(self.seller.seller_profile, self.category)

        self.bidder1 = User.objects.create_user(username="bidderA", password="x", role=User.Role.BIDDER)
        self.bidder2 = User.objects.create_user(username="bidderB", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder1.bidder_profile, actor=self.officer)
        verify_profile(self.bidder2.bidder_profile, actor=self.officer)

    def test_first_bid_must_meet_starting_price(self):
        with self.assertRaises(BidRejected):
            place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("9000"))
        bid = place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        self.assertEqual(bid.sequence_no, 1)

    def test_subsequent_bid_must_clear_increment(self):
        place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        with self.assertRaises(BidRejected):
            place_bid(self.auction, bidder_user=self.bidder2, amount=Decimal("10500"))  # increment is 1000
        bid2 = place_bid(self.auction, bidder_user=self.bidder2, amount=Decimal("11000"))
        self.assertEqual(bid2.sequence_no, 2)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal("11000"))

    def test_seller_cannot_bid_on_own_auction(self):
        # In this model, SELLER and BIDDER are mutually exclusive roles, so
        # a seller has no bidder_profile at all — place_bid rejects them
        # for that reason. The explicit seller/bidder identity check in
        # place_bid (Business Rule BR-04) is defense-in-depth in case a
        # future change ever lets one user hold both roles.
        with self.assertRaises(BidRejected):
            place_bid(self.auction, bidder_user=self.seller, amount=Decimal("10000"))

    def test_unverified_bidder_cannot_bid(self):
        unverified = User.objects.create_user(username="unverified1", password="x", role=User.Role.BIDDER)
        with self.assertRaises(BidRejected):
            place_bid(self.auction, bidder_user=unverified, amount=Decimal("10000"))

    def test_suspended_bidder_cannot_bid(self):
        suspend_bidder(self.bidder1.bidder_profile, actor=self.officer, reason="test suspension")
        with self.assertRaises(BidRejected):
            place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))

    def test_cannot_bid_outside_time_window(self):
        expired = make_live_auction(
            self.seller.seller_profile, self.category, title="Expired",
            start_time=timezone.now() - timedelta(hours=2), end_time=timezone.now() - timedelta(hours=1),
        )
        with self.assertRaises(BidRejected):
            place_bid(expired, bidder_user=self.bidder1, amount=Decimal("10000"))

    def test_sequence_numbers_are_monotonic_and_unique(self):
        place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        place_bid(self.auction, bidder_user=self.bidder2, amount=Decimal("11000"))
        place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("12000"))
        sequences = list(self.auction.bids.order_by("sequence_no").values_list("sequence_no", flat=True))
        self.assertEqual(sequences, [1, 2, 3])


class BidHistoryPrivacyTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="off2", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="sellerC", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Motor Vehicles")
        self.auction = make_live_auction(self.seller.seller_profile, self.category)
        self.bidder1 = User.objects.create_user(username="alice", password="x", role=User.Role.BIDDER)
        self.bidder2 = User.objects.create_user(username="bob", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder1.bidder_profile, actor=self.officer)
        verify_profile(self.bidder2.bidder_profile, actor=self.officer)
        place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        place_bid(self.auction, bidder_user=self.bidder2, amount=Decimal("11000"))

    def test_public_sees_anonymized_labels(self):
        history = get_bid_history(self.auction, viewer=None)
        labels = {h["label"] for h in history}
        self.assertEqual(labels, {"Bidder A", "Bidder B"})
        self.assertNotIn("alice", labels)

    def test_bidder_sees_own_bids_as_you(self):
        history = get_bid_history(self.auction, viewer=self.bidder1)
        own = [h for h in history if h["is_mine"]]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]["label"], "You")
        other = [h for h in history if not h["is_mine"]][0]
        self.assertEqual(other["label"], "Bidder B")

    def test_staff_sees_real_usernames(self):
        history = get_bid_history(self.auction, viewer=self.officer)
        labels = {h["label"] for h in history}
        self.assertEqual(labels, {"alice", "bob"})


class InvalidateBidTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="off3", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="sellerD", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Property")
        self.auction = make_live_auction(self.seller.seller_profile, self.category)
        self.bidder1 = User.objects.create_user(username="carl", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder1.bidder_profile, actor=self.officer)
        self.bid = place_bid(self.auction, bidder_user=self.bidder1, amount=Decimal("10000"))

    def test_invalidate_requires_reason(self):
        with self.assertRaises(ValueError):
            invalidate_bid(self.bid, actor=self.officer, reason="")

    def test_invalidate_recomputes_current_highest_bid(self):
        invalidate_bid(self.bid, actor=self.officer, reason="Suspected fraud")
        self.bid.refresh_from_db()
        self.auction.refresh_from_db()
        self.assertEqual(self.bid.status, Bid.Status.INVALIDATED)
        self.assertIsNone(self.auction.current_highest_bid)


class CloseAuctionTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="off4", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="sellerE", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Machinery")
        self.bidder1 = User.objects.create_user(username="dora", password="x", role=User.Role.BIDDER)
        self.bidder2 = User.objects.create_user(username="evan", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder1.bidder_profile, actor=self.officer)
        verify_profile(self.bidder2.bidder_profile, actor=self.officer)

    def test_close_with_no_reserve_declares_highest_bidder_winner(self):
        auction = make_live_auction(self.seller.seller_profile, self.category, title="No reserve")
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        place_bid(auction, bidder_user=self.bidder2, amount=Decimal("11000"))
        closed = close_auction(auction, actor=self.officer)
        self.assertEqual(closed.status, Auction.Status.CLOSED)
        self.assertEqual(closed.winner, self.bidder2)
        self.assertEqual(closed.final_price, Decimal("11000"))
        self.assertTrue(closed.reserve_met)

    def test_close_with_unmet_reserve_has_no_winner(self):
        auction = make_live_auction(
            self.seller.seller_profile, self.category, title="High reserve", reserve_price=Decimal("50000")
        )
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        closed = close_auction(auction, actor=self.officer)
        self.assertIsNone(closed.winner)
        self.assertIsNone(closed.final_price)
        self.assertFalse(closed.reserve_met)

    def test_close_with_no_bids_has_no_winner_and_no_reserve_met_flag(self):
        auction = make_live_auction(self.seller.seller_profile, self.category, title="No bids")
        closed = close_auction(auction, actor=self.officer)
        self.assertIsNone(closed.winner)
        self.assertIsNone(closed.reserve_met)

    def test_tie_bids_broken_by_earliest_sequence(self):
        """Business Rule BR-10: identical amounts break by earliest accepted
        sequence — simulated here via direct creation since place_bid's
        increment rule would normally prevent two equal bids in sequence."""
        auction = make_live_auction(self.seller.seller_profile, self.category, title="Tie test")
        Bid.objects.create(auction=auction, bidder=self.bidder1.bidder_profile, amount=Decimal("15000"), sequence_no=1)
        Bid.objects.create(auction=auction, bidder=self.bidder2.bidder_profile, amount=Decimal("15000"), sequence_no=2)
        auction.current_highest_bid = Decimal("15000")
        auction.save(update_fields=["current_highest_bid"])
        closed = close_auction(auction, actor=self.officer)
        self.assertEqual(closed.winner, self.bidder1)  # earlier sequence_no wins the tie


class PlaceBidViewTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="off5", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="sellerF", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Household Goods")
        self.auction = make_live_auction(self.seller.seller_profile, self.category)
        self.bidder = User.objects.create_user(username="finn", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder.bidder_profile, actor=self.officer)

    def test_bidder_can_place_bid_via_view(self):
        self.client.login(username="finn", password="x")
        response = self.client.post(reverse("bidding:place_bid", args=[self.auction.pk]), {"amount": "10000"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bid.objects.filter(auction=self.auction, bidder=self.bidder.bidder_profile).exists())

    def test_seller_cannot_place_bid_via_view(self):
        # Seller has no bidder_profile / is not role BIDDER, so BidderRequiredMixin blocks it.
        self.client.login(username="sellerF", password="x")
        response = self.client.post(reverse("bidding:place_bid", args=[self.auction.pk]), {"amount": "10000"})
        self.assertEqual(response.status_code, 403)
