from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from .models import BidderProfile, SellerProfile, User, VerificationStatus
from .permissions import check_owner
from .services import reject_profile, suspend_bidder, verify_profile


class RegistrationTests(TestCase):
    def test_bidder_can_register_and_is_logged_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "testbidder",
                "email": "bidder@example.com",
                "phone_number": "+256700000000",
                "role": User.Role.BIDDER,
                "password1": "a-strong-passw0rd!",
                "password2": "a-strong-passw0rd!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="testbidder", role=User.Role.BIDDER).exists())

    def test_admin_role_not_selectable_at_registration(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "sneaky",
                "email": "sneaky@example.com",
                "role": "ADMIN",
                "password1": "a-strong-passw0rd!",
                "password2": "a-strong-passw0rd!",
            },
        )
        self.assertFalse(User.objects.filter(username="sneaky", role="ADMIN").exists())


class ProfileCreationSignalTests(TestCase):
    def test_seller_gets_seller_profile_automatically(self):
        user = User.objects.create_user(username="seller1", password="x", role=User.Role.SELLER)
        self.assertTrue(SellerProfile.objects.filter(user=user).exists())
        self.assertFalse(BidderProfile.objects.filter(user=user).exists())
        self.assertEqual(user.seller_profile.verification_status, VerificationStatus.PENDING)

    def test_bidder_gets_bidder_profile_automatically(self):
        user = User.objects.create_user(username="bidder1", password="x", role=User.Role.BIDDER)
        self.assertTrue(BidderProfile.objects.filter(user=user).exists())
        self.assertFalse(SellerProfile.objects.filter(user=user).exists())

    def test_admin_gets_no_profile(self):
        admin = User.objects.create_user(username="admin1", password="x", role=User.Role.ADMIN)
        self.assertFalse(SellerProfile.objects.filter(user=admin).exists())
        self.assertFalse(BidderProfile.objects.filter(user=admin).exists())


class VerificationServiceTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="officer1", password="x", role=User.Role.OFFICER)
        self.seller = User.objects.create_user(username="seller2", password="x", role=User.Role.SELLER)
        self.bidder = User.objects.create_user(username="bidder2", password="x", role=User.Role.BIDDER)

    def test_verify_seller_profile(self):
        profile = self.seller.seller_profile
        verify_profile(profile, actor=self.officer, reason="ID checked")
        profile.refresh_from_db()
        self.assertEqual(profile.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(profile.verified_by, self.officer)
        self.assertIsNotNone(profile.verified_at)

    def test_reject_requires_reason(self):
        profile = self.seller.seller_profile
        with self.assertRaises(ValueError):
            reject_profile(profile, actor=self.officer, reason="")

    def test_suspend_bidder_blocks_eligibility(self):
        profile = self.bidder.bidder_profile
        verify_profile(profile, actor=self.officer)
        self.assertTrue(profile.is_eligible_to_bid)
        suspend_bidder(profile, actor=self.officer, reason="Suspicious activity")
        profile.refresh_from_db()
        self.assertFalse(profile.is_eligible_to_bid)


class VerificationQueueViewTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(username="officer2", password="x", role=User.Role.OFFICER)
        self.bidder = User.objects.create_user(username="bidder3", password="x", role=User.Role.BIDDER)

    def test_bidder_cannot_access_verification_queue(self):
        self.client.login(username="bidder3", password="x")
        response = self.client.get(reverse("accounts:verification_queue"))
        self.assertEqual(response.status_code, 403)

    def test_officer_can_access_and_approve(self):
        self.client.login(username="officer2", password="x")
        response = self.client.get(reverse("accounts:verification_queue"))
        self.assertEqual(response.status_code, 200)

        profile = self.bidder.bidder_profile
        response = self.client.post(
            reverse("accounts:verify_bidder", args=[profile.pk]),
            {"decision": "approve", "reason": "docs checked"},
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.verification_status, VerificationStatus.VERIFIED)


class OwnerPermissionHelperTests(TestCase):
    def test_check_owner_allows_the_owner(self):
        user = User.objects.create_user(username="owner1", password="x")
        check_owner(user, user)  # should not raise

    def test_check_owner_blocks_a_different_user(self):
        user = User.objects.create_user(username="owner2", password="x")
        other = User.objects.create_user(username="intruder", password="x")
        with self.assertRaises(PermissionDenied):
            check_owner(other, user, allow_staff=False)

    def test_check_owner_allows_staff_by_default(self):
        user = User.objects.create_user(username="owner3", password="x")
        staff = User.objects.create_user(username="staffer", password="x", role=User.Role.ADMIN, is_staff=True)
        check_owner(staff, user)  # should not raise
