import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.core.testing import make_user


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user(User.Role.BIDDER, username="loginuser")

    def test_login_success_redirects_to_dashboard(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "loginuser", "password": "pw12345!"})
        self.assertRedirects(resp, reverse("core:dashboard"))

    def test_wrong_password_rejected(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "loginuser", "password": "nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivated_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.client.post(reverse("accounts:login"), {"username": "loginuser", "password": "pw12345!"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_dashboard_requires_login(self):
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 302)


class RegistrationValidationTests(TestCase):
    def payload(self, **over):
        data = {"username": "newuser", "email": "new@example.com", "phone_number": "0700000000",
                "role": "BIDDER", "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"}
        data.update(over)
        return data

    def test_duplicate_email_rejected_case_insensitively(self):
        make_user(User.Role.BIDDER, username="first").__class__.objects.filter(username="first").update(email="dup@example.com")
        resp = self.client.post(reverse("accounts:register"), self.payload(email="DUP@example.com"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_duplicate_username_rejected(self):
        make_user(User.Role.BIDDER, username="newuser")
        resp = self.client.post(reverse("accounts:register"), self.payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(username="newuser").count(), 1)

    def test_password_mismatch_and_weak_rejected(self):
        self.assertEqual(self.client.post(reverse("accounts:register"), self.payload(password2="different")).status_code, 200)
        self.assertEqual(self.client.post(reverse("accounts:register"), self.payload(password1="12345678", password2="12345678")).status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_officer_role_cannot_be_forced(self):
        for role in ("OFFICER", "ADMIN"):
            self.client.post(reverse("accounts:register"), self.payload(role=role, username=f"x{role}"))
        self.assertFalse(User.objects.filter(role__in=["OFFICER", "ADMIN"]).exists())

    def test_new_accounts_start_pending_and_unverified(self):
        self.client.post(reverse("accounts:register"), self.payload(role="SELLER"))
        u = User.objects.get(username="newuser")
        self.assertEqual(u.seller_profile.verification_status, "PENDING")
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)

    def test_seller_dashboard_and_bidder_dashboard_render(self):
        for role in (User.Role.SELLER, User.Role.BIDDER, User.Role.OFFICER):
            self.client.force_login(make_user(role))
            resp = self.client.get(reverse("core:dashboard"))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Welcome")


class PasswordFlowTests(TestCase):
    def setUp(self):
        self.user = make_user(User.Role.BIDDER, username="pwuser")

    def test_change_password(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": "pw12345!", "new_password1": "An0ther-Strong-1", "new_password2": "An0ther-Strong-1"})
        self.assertRedirects(resp, reverse("accounts:password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("An0ther-Strong-1"))

    def test_change_password_wrong_old(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:password_change"), {
            "old_password": "wrong", "new_password1": "An0ther-Strong-1", "new_password2": "An0ther-Strong-1"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pw12345!"))

    def test_change_requires_login(self):
        self.assertEqual(self.client.get(reverse("accounts:password_change")).status_code, 302)

    def test_reset_email_and_confirm(self):
        self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/\s]+(/accounts/reset/[^\s]+)", mail.outbox[0].body).group(1)
        resp = self.client.get(link, follow=True)
        self.assertEqual(resp.status_code, 200)
        post_url = resp.request["PATH_INFO"]
        self.client.post(post_url, {"new_password1": "Reset-Pass-123", "new_password2": "Reset-Pass-123"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Reset-Pass-123"))

    def test_reset_for_unknown_email_does_not_leak_or_send(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class SuspensionTests(TestCase):
    def test_reactivate_restores_eligibility_and_notifies(self):
        from apps.accounts.services import reactivate_bidder, suspend_bidder
        from apps.notifications.models import Notification
        officer = make_user(User.Role.OFFICER)
        b = make_user(User.Role.BIDDER)
        suspend_bidder(b.bidder_profile, actor=officer, reason="Fraud report")
        b.bidder_profile.refresh_from_db()
        self.assertFalse(b.bidder_profile.is_eligible_to_bid)
        reactivate_bidder(b.bidder_profile, actor=officer)
        b.bidder_profile.refresh_from_db()
        self.assertTrue(b.bidder_profile.is_eligible_to_bid)
        events = set(Notification.objects.filter(recipient=b).values_list("event", flat=True))
        self.assertTrue({"ACCOUNT_SUSPENDED", "ACCOUNT_REACTIVATED"} <= events)

    def test_suspend_requires_reason(self):
        from apps.accounts.services import suspend_bidder
        b = make_user(User.Role.BIDDER)
        with self.assertRaises(ValueError):
            suspend_bidder(b.bidder_profile, actor=make_user(User.Role.OFFICER), reason="")
