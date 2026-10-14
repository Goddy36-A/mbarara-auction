"""Access-control matrix: every URL, for every kind of visitor. If a new URL
is added to the project and not listed here, test_every_url_is_covered fails
so it can't silently ship without an access decision."""
from django.test import Client, TestCase
from django.urls import get_resolver, reverse

from apps.accounts.models import User
from apps.auctions.services import Status
from apps.bidding.services import close_auction, place_bid
from apps.core.testing import make_auction, make_user
from apps.disputes.services import open_dispute

ANON, BIDDER, SELLER, OFFICER = "anon", "bidder", "seller", "officer"
OK, DENY = "ok", "deny"   # DENY = 403, or a 302 to login for anonymous
ANY_STATUS_OK = (200, 302)


class AccessMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.officer = make_user(User.Role.OFFICER)
        cls.seller = make_user(User.Role.SELLER)
        cls.other_seller = make_user(User.Role.SELLER)
        cls.bidder = make_user(User.Role.BIDDER)
        cls.auction = make_auction(cls.seller)
        place_bid(cls.auction, bidder_user=cls.bidder, amount=10000)
        cls.draft = make_auction(cls.seller, to=Status.DRAFT)
        cls.submitted = make_auction(cls.seller, to=Status.SUBMITTED)

    def login(self, who):
        c = Client()
        user = {BIDDER: self.bidder, SELLER: self.seller, OFFICER: self.officer}.get(who)
        if user:
            c.force_login(user)
        return c

    def assertAccess(self, who, url, allowed, method="get", data=None):
        c = self.login(who)
        resp = getattr(c, method)(url, data or {})
        if allowed:
            self.assertNotIn(resp.status_code, (401, 403, 404, 405, 500), f"{who} {method} {url} -> {resp.status_code}")
        else:
            self.assertIn(resp.status_code, (302, 403), f"{who} {method} {url} -> {resp.status_code}")
            if resp.status_code == 302:
                self.assertEqual(who, ANON, f"{who} was redirected from {url}")
                self.assertIn("/accounts/login/", resp["Location"])

    def test_page_matrix(self):
        pages = {
            "core:home": {ANON: 1, BIDDER: 1, SELLER: 1, OFFICER: 1},
            "auctions:browse": {ANON: 1, BIDDER: 1, SELLER: 1, OFFICER: 1},
            "core:dashboard": {ANON: 0, BIDDER: 1, SELLER: 1, OFFICER: 1},
            "notifications:inbox": {ANON: 0, BIDDER: 1, SELLER: 1, OFFICER: 1},
            "bidding:my_bids": {ANON: 0, BIDDER: 1, SELLER: 0, OFFICER: 1},
            "payments:my_payments": {ANON: 0, BIDDER: 1, SELLER: 0, OFFICER: 1},
            "payments:seller_payments": {ANON: 0, BIDDER: 0, SELLER: 1, OFFICER: 1},
            "listings:my_listings": {ANON: 0, BIDDER: 0, SELLER: 1, OFFICER: 1},
            "listings:create": {ANON: 0, BIDDER: 0, SELLER: 1, OFFICER: 0},  # officers have no seller profile
            "listings:approval_queue": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "payments:queue": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "accounts:verification_queue": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "disputes:queue": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "disputes:mine": {ANON: 0, BIDDER: 1, SELLER: 1, OFFICER: 1},
            "reports:dashboard": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "reports:auctions_csv": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
            "reports:payments_csv": {ANON: 0, BIDDER: 0, SELLER: 0, OFFICER: 1},
        }
        for name, rule in pages.items():
            for who, allowed in rule.items():
                with self.subTest(url=name, who=who):
                    self.assertAccess(who, reverse(name), bool(allowed))

    def test_admin_site_closed_to_non_superusers(self):
        for who in (ANON, BIDDER, SELLER, OFFICER):
            resp = self.login(who).get("/admin/")
            self.assertEqual(resp.status_code, 302, who)
            self.assertIn("/admin/login/", resp["Location"])

    def test_draft_and_submitted_hidden_from_non_owners(self):
        for who in (ANON, BIDDER):
            for a in (self.draft, self.submitted):
                self.assertEqual(self.login(who).get(reverse("auctions:detail", args=[a.pk])).status_code, 404)
        self.assertEqual(self.login(SELLER).get(reverse("auctions:detail", args=[self.draft.pk])).status_code, 200)

    def test_object_level_seller_isolation(self):
        c = Client()
        c.force_login(self.other_seller)
        self.assertEqual(c.get(reverse("listings:edit", args=[self.draft.pk])).status_code, 403)
        self.assertEqual(c.post(reverse("listings:submit", args=[self.draft.pk])).status_code, 403)

    def test_state_changing_endpoints_reject_get(self):
        for name, who, args in [
            ("listings:submit", SELLER, [self.draft.pk]), ("listings:approve", OFFICER, [self.submitted.pk]),
            ("listings:reject", OFFICER, [self.submitted.pk]), ("bidding:place_bid", BIDDER, [self.auction.pk]),
            ("notifications:mark_all_read", BIDDER, []), ("payments:mark_paid", OFFICER, [1]),
            ("payments:mark_failed", OFFICER, [1]), ("disputes:resolve", OFFICER, [1]), ("disputes:take", OFFICER, [1]),
        ]:
            with self.subTest(url=name):
                self.assertEqual(self.login(who).get(reverse(name, args=args)).status_code, 405)

    def test_csrf_enforced_on_state_changing_posts(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.bidder)
        resp = c.post(reverse("bidding:place_bid", args=[self.auction.pk]), {"amount": "50000"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.auction.bids.count(), 1)
        c.force_login(self.officer)
        self.assertEqual(c.post(reverse("listings:approve", args=[self.submitted.pk])).status_code, 403)

    def test_privacy_bidder_username_not_in_public_html(self):
        html = Client().get(reverse("auctions:detail", args=[self.auction.pk])).content.decode()
        self.assertNotIn(self.bidder.username, html)
        self.assertIn("Bidder A", html)
        staff_html = self.login(OFFICER).get(reverse("auctions:detail", args=[self.auction.pk])).content.decode()
        self.assertIn(self.bidder.username, staff_html)

    def test_no_sensitive_fields_leak_in_pages(self):
        for name, args in [("auctions:detail", [self.auction.pk]), ("auctions:browse", [])]:
            html = Client().get(reverse(name, args=args)).content.decode()
            for secret in (self.bidder.email, self.seller.email, "pbkdf2_", "reserve_price"):
                self.assertNotIn(secret, html)

    def test_dispute_privacy_between_participants_and_strangers(self):
        from apps.core.testing import make_category
        a = make_auction(self.seller, title="Disputed one")
        place_bid(a, bidder_user=self.bidder, amount=10000)
        a.refresh_from_db()
        from django.utils import timezone
        from datetime import timedelta
        type(a).objects.filter(pk=a.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        a.refresh_from_db()
        close_auction(a)
        a.refresh_from_db()
        d = open_dispute(a, raised_by=self.bidder, category="OTHER", description="private text")
        url = reverse("disputes:detail", args=[d.pk])
        self.assertEqual(self.login(BIDDER).get(url).status_code, 200)
        self.assertEqual(self.login(SELLER).get(url).status_code, 200)
        self.assertEqual(self.login(OFFICER).get(url).status_code, 200)
        stranger = make_user(User.Role.BIDDER)
        c = Client()
        c.force_login(stranger)
        self.assertEqual(c.get(url).status_code, 403)
        self.assertEqual(Client().get(url).status_code, 302)

    def test_every_url_is_covered(self):
        """Fail if a project URL is added that this matrix doesn't know about."""
        known = {
            "core:home", "core:dashboard", "auctions:browse", "auctions:detail", "notifications:inbox",
            "notifications:mark_read", "notifications:mark_all_read", "bidding:my_bids", "bidding:place_bid",
            "payments:my_payments", "payments:seller_payments", "payments:queue", "payments:mark_paid",
            "payments:mark_failed", "listings:my_listings", "listings:create", "listings:edit", "listings:submit",
            "listings:approval_queue", "listings:approve", "listings:reject", "accounts:register", "accounts:login",
            "accounts:logout", "accounts:password_change", "accounts:password_change_done", "accounts:password_reset",
            "accounts:password_reset_done", "accounts:password_reset_confirm", "accounts:password_reset_complete",
            "accounts:verification_queue", "accounts:verify_seller", "accounts:verify_bidder", "disputes:mine",
            "disputes:queue", "disputes:create", "disputes:detail", "disputes:take", "disputes:resolve",
            "reports:dashboard", "reports:auctions_csv", "reports:payments_csv",
        }
        resolver = get_resolver()
        actual = set()
        for ns, (_, sub) in resolver.namespace_dict.items():
            if ns == "admin":
                continue
            for name in sub.reverse_dict:
                if isinstance(name, str):
                    actual.add(f"{ns}:{name}")
        self.assertEqual(actual - known, set(), "New URLs need an entry in the access matrix")


class OfficerWithoutProfileTests(TestCase):
    """Regression: officers pass role checks but have no seller/bidder profile;
    these URLs used to raise 500 (RelatedObjectDoesNotExist)."""

    def test_officer_gets_empty_lists_not_500(self):
        c = Client()
        c.force_login(make_user(User.Role.OFFICER))
        for name in ("bidding:my_bids", "payments:seller_payments", "listings:my_listings"):
            self.assertEqual(c.get(reverse(name)).status_code, 200, name)

    def test_officer_cannot_create_listing(self):
        c = Client()
        c.force_login(make_user(User.Role.OFFICER))
        self.assertEqual(c.get(reverse("listings:create")).status_code, 403)
        self.assertEqual(c.post(reverse("listings:create"), {"title": "x"}).status_code, 403)
