from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.services import suspend_bidder, verify_profile
from apps.auctions.services import Status, reject
from apps.core.testing import make_auction, make_user

from .models import AuditLog


class AuditLogTests(TestCase):
    def test_record_stores_actor_object_reason_and_metadata(self):
        officer = make_user(User.Role.OFFICER)
        b = make_user(User.Role.BIDDER, verified=False)
        log = AuditLog.record(actor=officer, action=AuditLog.Action.USER_VERIFIED, obj=b.bidder_profile, reason="ok", extra=1)
        self.assertEqual((log.object_type, log.object_id), ("BidderProfile", str(b.bidder_profile.pk)))
        self.assertEqual(log.metadata, {"extra": 1})
        self.assertEqual(log.actor, officer)

    def test_actor_may_be_none_for_system_events(self):
        b = make_user(User.Role.BIDDER)
        self.assertIsNone(AuditLog.record(actor=None, action=AuditLog.Action.USER_REGISTERED, obj=b).actor)

    def test_actor_deletion_keeps_log(self):
        officer = make_user(User.Role.OFFICER, username="gone")
        AuditLog.record(actor=officer, action=AuditLog.Action.USER_REGISTERED, obj=officer)
        officer.delete()
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertIsNone(AuditLog.objects.get().actor)

    def test_key_workflow_events_are_logged(self):
        officer = make_user(User.Role.OFFICER)
        seller = make_user(User.Role.SELLER)
        bidder = make_user(User.Role.BIDDER)
        verify_profile(bidder.bidder_profile, actor=officer)
        suspend_bidder(bidder.bidder_profile, actor=officer, reason="r")
        a = make_auction(seller, to=Status.SUBMITTED)
        reject(a, actor=officer, reason="bad")
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"USER_VERIFIED", "USER_SUSPENDED", "AUCTION_CREATED", "AUCTION_REJECTED"} <= actions)

    def test_reject_logs_reason(self):
        officer = make_user(User.Role.OFFICER)
        a = make_auction(make_user(User.Role.SELLER), to=Status.SUBMITTED)
        reject(a, actor=officer, reason="Photos missing")
        self.assertEqual(AuditLog.objects.get(action="AUCTION_REJECTED").reason, "Photos missing")
