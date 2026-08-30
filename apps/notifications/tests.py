from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import reject_profile, suspend_bidder, verify_profile
from apps.auctions.models import Auction, AuctionCategory
from apps.auctions.services import approve, reject, submit_for_review, transition, Status
from apps.bidding.services import close_auction, place_bid

from .models import Notification
from .services import mark_all_read, mark_read, notify, unread_count


def make_live_auction(seller_profile, category, **overrides):
    """Mirrors apps.bidding.tests.make_live_auction — kept as a separate
    copy rather than a cross-app import so this app's tests don't depend
    on bidding's test module layout."""
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
    officer = User.objects.create_user(username=f"notifofficer_{auction.pk}", password="x", role=User.Role.OFFICER)
    submit_for_review(auction, actor=seller_profile.user)
    approve(auction, actor=officer)
    auction.refresh_from_db()
    transition(auction, Status.LIVE, actor=officer, reason="test setup")
    auction.refresh_from_db()
    return auction


class NotifyServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="recipient1", password="x", role=User.Role.BIDDER)

    def test_notify_creates_notification_and_delivers_synchronously(self):
        # CELERY_TASK_ALWAYS_EAGER=True in testing settings means .delay()
        # runs deliver_notification inline — this exercises that path too.
        n = notify(recipient=self.user, event=Notification.Event.ACCOUNT_VERIFIED, title="Hi", message="Welcome")
        self.assertIsNotNone(n.pk)
        self.assertFalse(n.is_read)
        self.assertEqual(n.channel, Notification.Channel.IN_APP)

    def test_notify_with_no_recipient_is_a_noop(self):
        self.assertIsNone(notify(recipient=None, event=Notification.Event.AUCTION_WON, title="x", message="y"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_records_related_object(self):
        n = notify(
            recipient=self.user, event=Notification.Event.ACCOUNT_VERIFIED, title="Hi", message="Welcome",
            obj=self.user,
        )
        self.assertEqual(n.related_object_type, "User")
        self.assertEqual(n.related_object_id, str(self.user.pk))


class ReadStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="recipient2", password="x", role=User.Role.BIDDER)
        self.other = User.objects.create_user(username="recipient3", password="x", role=User.Role.BIDDER)
        self.n1 = notify(recipient=self.user, event=Notification.Event.AUCTION_WON, title="a", message="a")
        self.n2 = notify(recipient=self.user, event=Notification.Event.AUCTION_WON, title="b", message="b")

    def test_unread_count(self):
        self.assertEqual(unread_count(self.user), 2)

    def test_mark_read_updates_single_notification(self):
        mark_read(self.n1, user=self.user)
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)
        self.assertEqual(unread_count(self.user), 1)

    def test_mark_read_by_non_owner_raises(self):
        with self.assertRaises(PermissionError):
            mark_read(self.n1, user=self.other)

    def test_mark_all_read(self):
        mark_all_read(self.user)
        self.assertEqual(unread_count(self.user), 0)

    def test_unread_count_for_anonymous_is_zero(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(unread_count(AnonymousUser()), 0)


class TriggerIntegrationTests(TestCase):
    """Confirms the other apps' service layers actually raise the right
    notification at the right point, not just that notify() itself works."""

    def setUp(self):
        self.officer = User.objects.create_user(username="notifoff1", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="notifseller1", password="x", role=User.Role.SELLER)
        self.category = AuctionCategory.objects.create(name="Electronics")
        self.bidder1 = User.objects.create_user(username="notifbidder1", password="x", role=User.Role.BIDDER)
        self.bidder2 = User.objects.create_user(username="notifbidder2", password="x", role=User.Role.BIDDER)
        verify_profile(self.bidder1.bidder_profile, actor=self.officer)
        verify_profile(self.bidder2.bidder_profile, actor=self.officer)

    def test_listing_approval_notifies_seller(self):
        from django.utils import timezone

        auction = Auction.objects.create(
            seller=self.seller.seller_profile, category=self.category, title="Sofa", description="Nice sofa",
            starting_price=Decimal("5000"), start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1),
        )
        submit_for_review(auction, actor=self.seller)
        approve(auction, actor=self.officer)
        self.assertTrue(
            Notification.objects.filter(recipient=self.seller, event=Notification.Event.LISTING_APPROVED).exists()
        )

    def test_listing_rejection_notifies_seller_with_reason(self):
        from django.utils import timezone

        auction = Auction.objects.create(
            seller=self.seller.seller_profile, category=self.category, title="Chair", description="A chair",
            starting_price=Decimal("5000"), start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1),
        )
        submit_for_review(auction, actor=self.seller)
        reject(auction, actor=self.officer, reason="Photos too blurry")
        note = Notification.objects.get(recipient=self.seller, event=Notification.Event.LISTING_REJECTED)
        self.assertIn("Photos too blurry", note.message)

    def test_account_verification_notifies_bidder(self):
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.bidder1, event=Notification.Event.ACCOUNT_VERIFIED
            ).exists()
        )

    def test_account_rejection_notifies_with_reason(self):
        candidate = User.objects.create_user(username="notifcand1", password="x", role=User.Role.BIDDER)
        reject_profile(candidate.bidder_profile, actor=self.officer, reason="ID mismatch")
        note = Notification.objects.get(recipient=candidate, event=Notification.Event.ACCOUNT_REJECTED)
        self.assertIn("ID mismatch", note.message)

    def test_suspension_notifies_bidder(self):
        suspend_bidder(self.bidder1.bidder_profile, actor=self.officer, reason="Suspicious activity")
        self.assertTrue(
            Notification.objects.filter(recipient=self.bidder1, event=Notification.Event.ACCOUNT_SUSPENDED).exists()
        )

    def test_outbid_notifies_previous_highest_bidder(self):
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        place_bid(auction, bidder_user=self.bidder2, amount=Decimal("11000"))
        self.assertTrue(
            Notification.objects.filter(recipient=self.bidder1, event=Notification.Event.OUTBID).exists()
        )
        # The bidder who just took the lead should not notify themselves.
        self.assertFalse(
            Notification.objects.filter(recipient=self.bidder2, event=Notification.Event.OUTBID).exists()
        )

    def test_repeat_bid_by_same_bidder_does_not_self_notify(self):
        auction = make_live_auction(self.seller.seller_profile, self.category)
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("11000"))
        self.assertFalse(
            Notification.objects.filter(recipient=self.bidder1, event=Notification.Event.OUTBID).exists()
        )

    def test_auction_won_notifies_winner(self):
        auction = make_live_auction(self.seller.seller_profile, self.category, title="Won item")
        place_bid(auction, bidder_user=self.bidder1, amount=Decimal("10000"))
        close_auction(auction, actor=self.officer)
        self.assertTrue(
            Notification.objects.filter(recipient=self.bidder1, event=Notification.Event.AUCTION_WON).exists()
        )

    def test_auction_closed_with_no_winner_notifies_seller(self):
        auction = make_live_auction(self.seller.seller_profile, self.category, title="No bids item")
        close_auction(auction, actor=self.officer)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.seller, event=Notification.Event.AUCTION_CLOSED_NO_WINNER
            ).exists()
        )

    def test_auction_going_live_notifies_seller(self):
        make_live_auction(self.seller.seller_profile, self.category, title="Live notice")
        self.assertTrue(
            Notification.objects.filter(recipient=self.seller, event=Notification.Event.AUCTION_LIVE).exists()
        )


class InboxViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="inboxuser1", password="x", role=User.Role.BIDDER)
        self.other = User.objects.create_user(username="inboxuser2", password="x", role=User.Role.BIDDER)
        self.n1 = notify(recipient=self.user, event=Notification.Event.AUCTION_WON, title="a", message="a")
        self.n_other = notify(recipient=self.other, event=Notification.Event.AUCTION_WON, title="b", message="b")

    def test_inbox_requires_login(self):
        response = self.client.get(reverse("notifications:inbox"))
        self.assertEqual(response.status_code, 302)

    def test_inbox_only_shows_own_notifications(self):
        self.client.login(username="inboxuser1", password="x")
        response = self.client.get(reverse("notifications:inbox"))
        self.assertContains(response, "a")
        self.assertNotContains(response, "b")

    def test_mark_read_via_view(self):
        self.client.login(username="inboxuser1", password="x")
        self.client.post(reverse("notifications:mark_read", args=[self.n1.pk]))
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_cannot_mark_read_someone_elses_notification(self):
        self.client.login(username="inboxuser1", password="x")
        response = self.client.post(reverse("notifications:mark_read", args=[self.n_other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_via_view(self):
        notify(recipient=self.user, event=Notification.Event.AUCTION_WON, title="c", message="c")
        self.client.login(username="inboxuser1", password="x")
        self.client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(unread_count(self.user), 0)
        self.assertEqual(unread_count(self.other), 1)  # untouched
