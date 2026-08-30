from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.auctions.models import Auction, AuctionCategory


class ListingWorkflowTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="officer3", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="seller3", password="x", role=User.Role.SELLER)
        self.other_seller = User.objects.create_user(username="seller4", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Furniture")

    def _create_via_view(self):
        self.client.login(username="seller3", password="x")
        now = timezone.now()
        return self.client.post(
            reverse("listings:create"),
            {
                "category": self.category.pk,
                "title": "Wooden chair",
                "description": "Handmade oak chair",
                "location": "Mbarara",
                "starting_price": "20000",
                "min_increment": "2000",
                "extension_minutes": "0",
                "start_time": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
                "end_time": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "images-TOTAL_FORMS": "0",
                "images-INITIAL_FORMS": "0",
                "images-MIN_NUM_FORMS": "0",
                "images-MAX_NUM_FORMS": "1000",
            },
        )

    def test_seller_can_create_draft_listing(self):
        response = self._create_via_view()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Auction.objects.filter(title="Wooden chair", status=Auction.Status.DRAFT).exists())

    def test_other_seller_cannot_edit_someone_elses_draft(self):
        self._create_via_view()
        auction = Auction.objects.get(title="Wooden chair")
        self.client.logout()
        self.client.login(username="seller4", password="x")
        response = self.client.get(reverse("listings:edit", args=[auction.pk]))
        self.assertEqual(response.status_code, 403)

    def test_submit_moves_to_submitted_and_then_officer_can_approve(self):
        self._create_via_view()
        auction = Auction.objects.get(title="Wooden chair")

        self.client.post(reverse("listings:submit", args=[auction.pk]))
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SUBMITTED)

        self.client.logout()
        self.client.login(username="officer3", password="x")
        response = self.client.get(reverse("listings:approval_queue"))
        self.assertContains(response, "Wooden chair")

        self.client.post(reverse("listings:approve", args=[auction.pk]), {"reason": "OK"})
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.SCHEDULED)

    def test_bidder_cannot_reach_approval_queue(self):
        User.objects.create_user(username="bidder5", password="x", role=User.Role.BIDDER)
        self.client.login(username="bidder5", password="x")
        response = self.client.get(reverse("listings:approval_queue"))
        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_once_submitted(self):
        self._create_via_view()
        auction = Auction.objects.get(title="Wooden chair")
        self.client.post(reverse("listings:submit", args=[auction.pk]))
        response = self.client.get(reverse("listings:edit", args=[auction.pk]))
        self.assertEqual(response.status_code, 403)
