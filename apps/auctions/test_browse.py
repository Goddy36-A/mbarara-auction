from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.auctions.services import Status
from apps.core.testing import make_auction, make_category, make_user


class BrowseTests(TestCase):
    def setUp(self):
        self.seller = make_user(User.Role.SELLER)
        self.electronics = make_category("Electronics")
        self.furniture = make_category("Furniture")
        self.phone = make_auction(self.seller, title="Samsung phone", category=self.electronics, description="Black")
        self.chair = make_auction(self.seller, title="Oak chair", category=self.furniture, description="Handmade phone-table style")
        self.upcoming = make_auction(self.seller, to=Status.SCHEDULED, title="Future lamp", category=self.furniture)
        self.draft = make_auction(self.seller, to=Status.DRAFT, title="Secret draft", category=self.furniture)
        self.submitted = make_auction(self.seller, to=Status.SUBMITTED, title="Pending thing", category=self.furniture)

    def titles(self, **params):
        resp = self.client.get(reverse("auctions:browse"), params)
        self.assertEqual(resp.status_code, 200)
        return {a.title for a in resp.context["auctions"]}

    def test_public_sees_only_publicly_visible(self):
        t = self.titles()
        self.assertEqual(t, {"Samsung phone", "Oak chair", "Future lamp"})

    def test_search_matches_title_and_description_case_insensitive(self):
        self.assertEqual(self.titles(q="PHONE"), {"Samsung phone", "Oak chair"})

    def test_category_filter(self):
        self.assertEqual(self.titles(category="electronics"), {"Samsung phone"})

    def test_status_filter(self):
        self.assertEqual(self.titles(status="SCHEDULED"), {"Future lamp"})

    def test_status_filter_cannot_expose_drafts(self):
        # The status filter narrows the already-public set; it can never widen it.
        self.assertEqual(self.titles(status="DRAFT"), set())
        self.assertEqual(self.titles(status="SUBMITTED"), set())

    def test_garbage_filters_do_not_crash(self):
        self.assertEqual(self.titles(status="<script>", category="nope"), set())

    def test_detail_anonymous_live_ok_and_hides_draft(self):
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[self.phone.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[self.draft.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[self.submitted.pk])).status_code, 404)

    def test_staff_can_preview_submitted(self):
        officer = make_user(User.Role.OFFICER)
        self.client.force_login(officer)
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[self.submitted.pk])).status_code, 200)

    def test_other_seller_cannot_preview_draft(self):
        other = make_user(User.Role.SELLER)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[self.draft.pk])).status_code, 404)

    def test_missing_auction_404(self):
        self.assertEqual(self.client.get(reverse("auctions:detail", args=[999999])).status_code, 404)
