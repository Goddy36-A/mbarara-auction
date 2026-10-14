from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.auctions.models import Auction
from apps.auctions.services import Status
from apps.bidding.services import BidRejected, place_bid
from apps.core.testing import make_auction, make_user
from apps.notifications.models import Notification
from apps.payments.models import Payment

from . import scheduling
from .scheduling import SchedulingError


class SchedulingBase(TestCase):
    def setUp(self):
        self.officer = make_user(User.Role.OFFICER)
        self.seller = make_user(User.Role.SELLER)
        self.bidder = make_user(User.Role.BIDDER)
        self.now = timezone.now()

    def scheduled(self, **kw):
        kw.setdefault("start_time", self.now + timedelta(hours=2))
        kw.setdefault("end_time", self.now + timedelta(hours=5))
        return make_auction(self.seller, to=Status.SCHEDULED, **kw)

    def live(self, **kw):
        return make_auction(self.seller, to=Status.LIVE, **kw)


class StartNowTests(SchedulingBase):
    def test_start_now_opens_bidding_before_start_time(self):
        a = self.scheduled()
        scheduling.start_now(a, actor=self.officer)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.LIVE)
        self.assertLessEqual(a.start_time, timezone.now())
        self.assertTrue(a.is_biddable)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        self.assertTrue(AuditLog.objects.filter(action="AUCTION_STARTED").exists())
        self.assertTrue(AuditLog.objects.filter(action="AUCTION_RESCHEDULED", reason="Started early by staff").exists())

    def test_only_scheduled_can_be_started(self):
        with self.assertRaises(SchedulingError):
            scheduling.start_now(self.live(), actor=self.officer)

    def test_cannot_start_if_end_time_passed(self):
        a = self.scheduled()
        Auction.objects.filter(pk=a.pk).update(start_time=self.now - timedelta(hours=2), end_time=self.now - timedelta(minutes=1))
        a.refresh_from_db()
        with self.assertRaises(SchedulingError):
            scheduling.start_now(a, actor=self.officer)

    def test_bid_before_start_is_still_rejected(self):
        a = self.scheduled()
        with self.assertRaises(BidRejected):
            place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))


class RescheduleTests(SchedulingBase):
    def test_reschedule_scheduled_changes_both_and_notifies(self):
        a = self.scheduled()
        new_start, new_end = self.now + timedelta(days=1), self.now + timedelta(days=2)
        scheduling.reschedule(a, actor=self.officer, reason="Seller request", start_time=new_start, end_time=new_end)
        a.refresh_from_db()
        self.assertEqual((a.start_time, a.end_time), (new_start, new_end))
        log = AuditLog.objects.get(action="AUCTION_RESCHEDULED")
        self.assertEqual(log.reason, "Seller request")
        self.assertIn("old_start", log.metadata)
        self.assertTrue(Notification.objects.filter(event="AUCTION_RESCHEDULED", recipient=self.seller).exists())

    def test_reason_required(self):
        with self.assertRaises(SchedulingError):
            scheduling.reschedule(self.scheduled(), actor=self.officer, reason=" ", end_time=self.now + timedelta(days=1))

    def test_validation_rules(self):
        a = self.scheduled()
        bad = [
            dict(),  # nothing to change
            dict(start_time=self.now + timedelta(days=3), end_time=self.now + timedelta(days=2)),  # start after end
            dict(end_time=self.now - timedelta(minutes=1)),  # end in the past
            dict(start_time=self.now - timedelta(minutes=1)),  # start in the past
        ]
        for kw in bad:
            with self.assertRaises(SchedulingError, msg=str(kw)):
                scheduling.reschedule(a, actor=self.officer, reason="r", **kw)
        a.refresh_from_db()
        self.assertEqual(a.start_time, self.now + timedelta(hours=2))

    def test_live_auction_can_only_be_extended_and_start_is_locked(self):
        a = self.live()
        with self.assertRaises(SchedulingError):  # shorten
            scheduling.reschedule(a, actor=self.officer, reason="r", end_time=a.end_time - timedelta(minutes=10))
        with self.assertRaises(SchedulingError):  # change start
            scheduling.reschedule(a, actor=self.officer, reason="r", start_time=self.now + timedelta(hours=1))
        later = a.end_time + timedelta(hours=1)
        scheduling.reschedule(a, actor=self.officer, reason="Extend for demand", end_time=later)
        a.refresh_from_db()
        self.assertEqual(a.end_time, later)

    def test_bidders_with_bids_are_notified_of_reschedule(self):
        a = self.live()
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        scheduling.reschedule(a, actor=self.officer, reason="r", end_time=a.end_time + timedelta(hours=1))
        self.assertTrue(Notification.objects.filter(event="AUCTION_RESCHEDULED", recipient=self.bidder).exists())

    def test_finished_auctions_cannot_be_rescheduled(self):
        a = self.live()
        Auction.objects.filter(pk=a.pk).update(end_time=self.now - timedelta(seconds=1))
        a.refresh_from_db()
        scheduling.end_now(a, actor=self.officer, reason="done")
        a.refresh_from_db()
        with self.assertRaises(SchedulingError):
            scheduling.reschedule(a, actor=self.officer, reason="r", end_time=self.now + timedelta(days=1))


class PauseResumeCancelEndTests(SchedulingBase):
    def test_pause_blocks_bids_then_resume_restores(self):
        a = self.live()
        scheduling.pause(a, actor=self.officer, reason="Investigating complaint")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.PAUSED)
        with self.assertRaises(BidRejected):
            place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        scheduling.resume(a, actor=self.officer)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.LIVE)
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"AUCTION_PAUSED", "AUCTION_RESUMED"} <= actions)

    def test_pause_requires_reason_and_live(self):
        with self.assertRaises(SchedulingError):
            scheduling.pause(self.live(), actor=self.officer, reason="")
        with self.assertRaises(Exception):
            scheduling.pause(self.scheduled(), actor=self.officer, reason="x")

    def test_cannot_resume_after_end_time_passed_while_paused(self):
        a = self.live()
        scheduling.pause(a, actor=self.officer, reason="x")
        Auction.objects.filter(pk=a.pk).update(end_time=self.now - timedelta(seconds=1))
        a.refresh_from_db()
        with self.assertRaises(SchedulingError):
            scheduling.resume(a, actor=self.officer)
        scheduling.reschedule(a, actor=self.officer, reason="new end", end_time=self.now + timedelta(hours=1))
        scheduling.resume(a, actor=self.officer)
        a.refresh_from_db()
        self.assertEqual(a.status, Status.LIVE)

    def test_cancel_notifies_bidders_and_keeps_bids(self):
        a = self.live()
        place_bid(a, bidder_user=self.bidder, amount=Decimal("10000"))
        a.refresh_from_db()
        scheduling.cancel_auction(a, actor=self.officer, reason="Item withdrawn")
        a.refresh_from_db()
        self.assertEqual(a.status, Status.CANCELLED)
        self.assertEqual(a.bids.count(), 1)
        self.assertIsNone(a.winner)
        self.assertFalse(Payment.objects.filter(auction=a).exists())
        for u in (self.seller, self.bidder):
            self.assertTrue(Notification.objects.filter(event="AUCTION_CANCELLED", recipient=u).exists())

    def test_cancel_requires_reason_and_valid_status(self):
        with self.assertRaises(SchedulingError):
            scheduling.cancel_auction(self.scheduled(), actor=self.officer, reason="")
        a = self.scheduled()
        scheduling.cancel_auction(a, actor=self.officer, reason="x")
        a.refresh_from_db()
        with self.assertRaises(SchedulingError):
            scheduling.cancel_auction(a, actor=self.officer, reason="again")

    def test_end_now_picks_winner_and_creates_payment(self):
        a = self.live(reserve_price=Decimal("12000"))
        place_bid(a, bidder_user=self.bidder, amount=Decimal("15000"))
        a.refresh_from_db()
        scheduling.end_now(a, actor=self.officer, reason="Seller accepted")
        a.refresh_from_db()
        self.assertEqual((a.status, a.winner, a.final_price), (Status.CLOSED, self.bidder, Decimal("15000.00")))
        self.assertTrue(Payment.objects.filter(auction=a).exists())

    def test_end_now_respects_reserve(self):
        a = self.live(reserve_price=Decimal("50000"))
        place_bid(a, bidder_user=self.bidder, amount=Decimal("15000"))
        a.refresh_from_db()
        scheduling.end_now(a, actor=self.officer, reason="x")
        a.refresh_from_db()
        self.assertIsNone(a.winner)

    def test_end_now_needs_live_and_reason(self):
        with self.assertRaises(SchedulingError):
            scheduling.end_now(self.live(), actor=self.officer, reason="")
        with self.assertRaises(SchedulingError):
            scheduling.end_now(self.scheduled(), actor=self.officer, reason="x")


class SweepTests(SchedulingBase):
    def test_sweep_starts_due_and_closes_ended(self):
        due = self.scheduled()
        Auction.objects.filter(pk=due.pk).update(start_time=self.now - timedelta(minutes=1))
        later = self.scheduled(title="later")
        ended = self.live(title="ended")
        place_bid(ended, bidder_user=self.bidder, amount=Decimal("10000"))
        Auction.objects.filter(pk=ended.pk).update(end_time=self.now - timedelta(seconds=1))
        self.assertEqual(scheduling.sweep_due(actor=self.officer), (1, 1))
        for a in (due, later, ended):
            a.refresh_from_db()
        self.assertEqual((due.status, later.status, ended.status), (Status.LIVE, Status.SCHEDULED, Status.CLOSED))
        self.assertEqual(scheduling.sweep_due(actor=self.officer), (0, 0))


class CountdownPropertyTests(SchedulingBase):
    def test_seconds_until_start_and_end(self):
        a = self.scheduled()
        self.assertTrue(7190 <= a.seconds_until_start <= 7200)
        self.assertTrue(17990 <= a.seconds_until_end <= 18000)

    def test_never_negative(self):
        a = self.live()
        Auction.objects.filter(pk=a.pk).update(start_time=self.now - timedelta(hours=3), end_time=self.now - timedelta(hours=1))
        a.refresh_from_db()
        self.assertEqual((a.seconds_until_start, a.seconds_until_end), (0, 0))


class ControlViewTests(SchedulingBase):
    def test_dashboard_lists_by_section_with_countdowns(self):
        s = self.scheduled(title="Upcoming lamp")
        l = self.live(title="Running chair")
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("control:dashboard"))
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Upcoming lamp", body)
        self.assertIn("Running chair", body)
        self.assertEqual(body.count("data-countdown"), 2)
        self.assertEqual([a.pk for a in resp.context["scheduled"]], [s.pk])
        self.assertEqual([a.pk for a in resp.context["live"]], [l.pk])

    def test_dashboard_warns_about_overdue_auctions(self):
        a = self.scheduled()
        Auction.objects.filter(pk=a.pk).update(start_time=self.now - timedelta(minutes=5))
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("control:dashboard"))
        self.assertEqual(resp.context["overdue_start"], 1)
        self.assertContains(resp, "Run sweep now")
        self.assertContains(resp, "not live yet")

    def test_start_now_via_view(self):
        a = self.scheduled()
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("control:start", args=[a.pk]))
        self.assertRedirects(resp, reverse("control:auction", args=[a.pk]))
        a.refresh_from_db()
        self.assertEqual(a.status, Status.LIVE)

    def test_error_is_shown_not_crashed(self):
        a = self.live()
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("control:start", args=[a.pk]), follow=True)
        self.assertContains(resp, "Only a scheduled auction can be started")

    def test_reschedule_view_parses_form_dates(self):
        a = self.scheduled()
        self.client.force_login(self.officer)
        local = timezone.localtime(self.now + timedelta(days=3))
        resp = self.client.post(reverse("control:reschedule", args=[a.pk]), {
            "start_time": (local).strftime("%Y-%m-%dT%H:%M"),
            "end_time": (local + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "reason": "Seller asked",
        }, follow=True)
        a.refresh_from_db()
        self.assertEqual(a.start_time.replace(second=0, microsecond=0), local.replace(second=0, microsecond=0))
        self.assertContains(resp, "Schedule updated")

    def test_reschedule_view_rejects_garbage(self):
        a = self.scheduled()
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("control:reschedule", args=[a.pk]), {"start_time": "not a date", "reason": "x"}, follow=True)
        self.assertContains(resp, "Enter valid dates")
        a.refresh_from_db()
        self.assertEqual(a.start_time, self.now + timedelta(hours=2))

    def test_pause_cancel_end_views_require_reason(self):
        a = self.live()
        self.client.force_login(self.officer)
        for name in ("pause", "cancel", "end"):
            self.client.post(reverse(f"control:{name}", args=[a.pk]), {"reason": ""})
            a.refresh_from_db()
            self.assertEqual(a.status, Status.LIVE, name)

    def test_manage_page_shows_only_valid_actions(self):
        self.client.force_login(self.officer)
        sched = self.scheduled()
        body = self.client.get(reverse("control:auction", args=[sched.pk])).content.decode()
        self.assertIn("Start now", body)
        self.assertNotIn("Pause bidding", body)
        live = self.live()
        body = self.client.get(reverse("control:auction", args=[live.pk])).content.decode()
        self.assertIn("Pause bidding", body)
        self.assertIn("End now", body)
        self.assertNotIn("Resume bidding", body)

    def test_manage_page_for_closed_auction_has_no_actions_and_history_renders(self):
        a = self.live()
        Auction.objects.filter(pk=a.pk).update(end_time=self.now - timedelta(seconds=1))
        a.refresh_from_db()
        scheduling.end_now(a, actor=self.officer, reason="done")
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("control:auction", args=[a.pk]))
        self.assertContains(resp, "No scheduling actions are available")
        self.assertContains(resp, "LIVE")  # history row

    def test_sweep_view(self):
        a = self.scheduled()
        Auction.objects.filter(pk=a.pk).update(start_time=self.now - timedelta(minutes=1))
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("control:sweep"), follow=True)
        self.assertContains(resp, "1 auction(s) started")

    def test_unknown_auction_404(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse("control:auction", args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("control:pause", args=[9999]), {"reason": "x"}).status_code, 404)


class PublicCountdownRenderingTests(SchedulingBase):
    def test_scheduled_detail_shows_opening_countdown_and_no_bid_box(self):
        a = self.scheduled()
        self.client.force_login(self.bidder)
        body = self.client.get(reverse("auctions:detail", args=[a.pk])).content.decode()
        self.assertIn("Bidding opens in", body)
        self.assertIn('data-countdown', body)
        self.assertNotIn("Place bid", body)
        self.assertIn("once the countdown reaches zero", body)

    def test_live_detail_shows_closing_countdown(self):
        a = self.live()
        body = self.client.get(reverse("auctions:detail", args=[a.pk])).content.decode()
        self.assertIn("Bidding closes in", body)

    def test_countdown_seconds_come_from_server(self):
        a = self.scheduled()
        resp = self.client.get(reverse("auctions:detail", args=[a.pk]))
        import re
        secs = int(re.search(r'data-seconds="(\d+)"', resp.content.decode()).group(1))
        self.assertTrue(7150 <= secs <= 7200)

    def test_closed_auction_has_no_countdown(self):
        a = self.live()
        Auction.objects.filter(pk=a.pk).update(end_time=self.now - timedelta(seconds=1))
        a.refresh_from_db()
        scheduling.end_now(a, actor=self.officer, reason="x")
        self.assertNotIn("data-countdown", self.client.get(reverse("auctions:detail", args=[a.pk])).content.decode())

    def test_paused_shows_paused_message(self):
        a = self.live()
        scheduling.pause(a, actor=self.officer, reason="x")
        self.assertContains(self.client.get(reverse("auctions:detail", args=[a.pk])), "paused by staff")

    def test_browse_and_home_show_countdowns(self):
        self.scheduled(title="Soon item")
        self.live(title="Now item")
        for name in ("auctions:browse", "core:home"):
            body = self.client.get(reverse(name)).content.decode()
            self.assertIn("Soon item", body)
            self.assertIn("Opens in", body)
            self.assertIn("Closes in", body)
