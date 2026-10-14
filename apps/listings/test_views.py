import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.auctions.models import Auction
from apps.auctions.services import Status
from apps.core.testing import make_auction, make_category, make_officer, make_user

from .forms import AuctionForm, AuctionImageForm, MAX_IMAGE_SIZE_BYTES
from .models import AuctionImage


def form_data(category, **over):
    now = timezone.now()
    data = {
        "category": category.pk, "title": "Table", "description": "Nice", "location": "Mbarara",
        "starting_price": "20000", "min_increment": "1000", "extension_minutes": "0",
        "start_time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "end_time": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
    }
    data.update(over)
    return data


def image_bytes(fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, fmt)
    return buf.getvalue()


def png_bytes():
    return image_bytes("PNG")


class AuctionFormValidationTests(TestCase):
    def setUp(self):
        self.cat = make_category()

    def test_valid(self):
        self.assertTrue(AuctionForm(form_data(self.cat)).is_valid())

    def test_start_must_be_before_end(self):
        now = timezone.now()
        f = AuctionForm(form_data(self.cat, start_time=(now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")))
        self.assertFalse(f.is_valid())

    def test_reserve_below_starting_price_rejected(self):
        self.assertFalse(AuctionForm(form_data(self.cat, reserve_price="5000")).is_valid())

    def test_reserve_optional_and_equal_allowed(self):
        self.assertTrue(AuctionForm(form_data(self.cat, reserve_price="20000")).is_valid())
        self.assertTrue(AuctionForm(form_data(self.cat, reserve_price="")).is_valid())

    def test_missing_required_fields(self):
        data = form_data(self.cat)
        del data["title"]
        self.assertFalse(AuctionForm(data).is_valid())


class ImageValidationTests(TestCase):
    def test_rejects_gif(self):
        f = SimpleUploadedFile("x.gif", image_bytes("GIF"), content_type="image/gif")
        form = AuctionImageForm({"sort_order": 0}, {"image": f})
        self.assertFalse(form.is_valid())

    def test_rejects_non_image_file(self):
        f = SimpleUploadedFile("x.png", b"not an image at all", content_type="image/png")
        form = AuctionImageForm({"sort_order": 0}, {"image": f})
        self.assertFalse(form.is_valid())

    def test_rejects_oversize(self):
        f = SimpleUploadedFile("x.png", png_bytes(), content_type="image/png")
        f.size = MAX_IMAGE_SIZE_BYTES + 1
        form = AuctionImageForm({"sort_order": 0}, {"image": f})
        self.assertFalse(form.is_valid())

    def test_accepts_png(self):
        f = SimpleUploadedFile("x.png", png_bytes(), content_type="image/png")
        form = AuctionImageForm({"sort_order": 0}, {"image": f})
        self.assertTrue(form.is_valid(), form.errors)


class ListingViewTests(TestCase):
    def setUp(self):
        self.cat = make_category()
        self.seller = make_user(User.Role.SELLER)
        self.other = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)
        self.officer = make_officer()

    def test_bidder_cannot_create_listing(self):
        self.client.force_login(self.bidder)
        self.assertEqual(self.client.get(reverse("listings:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("listings:create"), form_data(self.cat)).status_code, 403)
        self.assertFalse(Auction.objects.exists())

    def test_anonymous_cannot_create_listing(self):
        self.assertIn(self.client.get(reverse("listings:create")).status_code, (302, 403))

    def test_invalid_post_creates_nothing_and_rerenders(self):
        self.client.force_login(self.seller)
        resp = self.client.post(reverse("listings:create"), form_data(self.cat, starting_price="-5"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Auction.objects.exists())

    def test_my_listings_shows_only_own(self):
        make_auction(self.seller, to=Status.DRAFT, title="Mine")
        make_auction(self.other, to=Status.DRAFT, title="Theirs")
        self.client.force_login(self.seller)
        body = self.client.get(reverse("listings:my_listings")).content.decode()
        self.assertIn("Mine", body)
        self.assertNotIn("Theirs", body)

    def test_edit_draft_updates_fields(self):
        a = make_auction(self.seller, to=Status.DRAFT, title="Old")
        self.client.force_login(self.seller)
        data = form_data(self.cat, title="New title")
        data.update({"images-TOTAL_FORMS": "0", "images-INITIAL_FORMS": "0", "images-MIN_NUM_FORMS": "0", "images-MAX_NUM_FORMS": "1000"})
        resp = self.client.post(reverse("listings:edit", args=[a.pk]), data)
        self.assertEqual(resp.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.title, "New title")

    def test_edit_after_submit_forbidden(self):
        a = make_auction(self.seller, to=Status.SUBMITTED)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("listings:edit", args=[a.pk])).status_code, 403)

    def test_cannot_submit_someone_elses_listing(self):
        a = make_auction(self.seller, to=Status.DRAFT)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("listings:submit", args=[a.pk])).status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.DRAFT)

    def test_double_submit_is_harmless(self):
        a = make_auction(self.seller, to=Status.DRAFT)
        self.client.force_login(self.seller)
        self.client.post(reverse("listings:submit", args=[a.pk]))
        resp = self.client.post(reverse("listings:submit", args=[a.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.SUBMITTED)

    def test_approve_and_reject_require_staff(self):
        a = make_auction(self.seller, to=Status.SUBMITTED)
        for user in (self.seller, self.bidder):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("listings:approve", args=[a.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("listings:reject", args=[a.pk]), {"reason": "x"}).status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.SUBMITTED)

    def test_reject_without_reason_changes_nothing(self):
        a = make_auction(self.seller, to=Status.SUBMITTED)
        self.client.force_login(self.officer)
        self.client.post(reverse("listings:reject", args=[a.pk]), {"reason": ""})
        a.refresh_from_db()
        self.assertEqual(a.status, Status.SUBMITTED)

    def test_reject_with_reason_and_seller_notified(self):
        from apps.notifications.models import Notification
        a = make_auction(self.seller, to=Status.SUBMITTED)
        self.client.force_login(self.officer)
        self.client.post(reverse("listings:reject", args=[a.pk]), {"reason": "Blurry photos"})
        a.refresh_from_db()
        self.assertEqual(a.status, Status.REJECTED)
        n = Notification.objects.get(recipient=self.seller, event=Notification.Event.LISTING_REJECTED)
        self.assertIn("Blurry photos", n.message)

    def test_approve_schedules_and_cannot_approve_twice(self):
        a = make_auction(self.seller, to=Status.SUBMITTED)
        self.client.force_login(self.officer)
        self.client.post(reverse("listings:approve", args=[a.pk]))
        a.refresh_from_db()
        self.assertEqual(a.status, Status.SCHEDULED)
        self.client.post(reverse("listings:approve", args=[a.pk]))
        a.refresh_from_db()
        self.assertEqual(a.status, Status.SCHEDULED)

    def test_approval_queue_lists_only_submitted(self):
        make_auction(self.seller, to=Status.SUBMITTED, title="InQueue")
        make_auction(self.seller, to=Status.DRAFT, title="NotInQueue")
        self.client.force_login(self.officer)
        body = self.client.get(reverse("listings:approval_queue")).content.decode()
        self.assertIn("InQueue", body)
        self.assertNotIn("NotInQueue", body)

    def test_get_on_post_only_endpoints_not_allowed(self):
        a = make_auction(self.seller, to=Status.SUBMITTED)
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse("listings:approve", args=[a.pk])).status_code, 405)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("listings:submit", args=[a.pk])).status_code, 405)
