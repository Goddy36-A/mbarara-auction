"""
Verification workflow service functions. Kept out of views/admin so the
same logic is reachable from the web UI, Django Admin actions, and future
management commands without duplicating the audit-logging step.
"""
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.notifications.services import (
    notify_account_rejected,
    notify_account_verified,
    notify_bidder_reactivated,
    notify_bidder_suspended,
)

from .models import BidderProfile, SellerProfile, VerificationStatus


def _apply_verification(profile, *, status, actor, reason=""):
    profile.verification_status = status
    profile.verified_at = timezone.now()
    profile.verified_by = actor
    profile.save(update_fields=["verification_status", "verified_at", "verified_by", "updated_at"])
    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.USER_VERIFIED if status == VerificationStatus.VERIFIED else AuditLog.Action.USER_SUSPENDED,
        obj=profile,
        reason=reason,
        new_status=status,
        profile_user_id=profile.user_id,
    )
    if status == VerificationStatus.VERIFIED:
        notify_account_verified(profile)
    else:
        notify_account_rejected(profile, reason=reason)
    return profile


def verify_profile(profile, *, actor, reason=""):
    """Approve a seller or bidder profile. `actor` must be an officer/admin
    — enforced by the calling view/admin action, not here, since this
    function is also meant to be usable from trusted management commands."""
    return _apply_verification(profile, status=VerificationStatus.VERIFIED, actor=actor, reason=reason)


def reject_profile(profile, *, actor, reason=""):
    if not reason:
        raise ValueError("A reason is required when rejecting a profile (Section 16: 'Record ... Reason').")
    return _apply_verification(profile, status=VerificationStatus.REJECTED, actor=actor, reason=reason)


def suspend_bidder(profile: BidderProfile, *, actor, reason=""):
    if not reason:
        raise ValueError("A reason is required when suspending an account.")
    profile.account_status = BidderProfile.AccountStatus.SUSPENDED
    profile.save(update_fields=["account_status", "updated_at"])
    AuditLog.record(actor=actor, action=AuditLog.Action.USER_SUSPENDED, obj=profile, reason=reason)
    notify_bidder_suspended(profile, reason=reason)
    return profile


def reactivate_bidder(profile: BidderProfile, *, actor, reason=""):
    profile.account_status = BidderProfile.AccountStatus.ACTIVE
    profile.save(update_fields=["account_status", "updated_at"])
    AuditLog.record(actor=actor, action=AuditLog.Action.USER_VERIFIED, obj=profile, reason=reason or "Reactivated")
    notify_bidder_reactivated(profile)
    return profile


def pending_profiles():
    """Combined queue for the administrator verification screen (Section 11:
    'Administrator should be able to ... Manage verification status')."""
    return {
        "sellers": SellerProfile.objects.filter(verification_status=VerificationStatus.PENDING).select_related("user"),
        "bidders": BidderProfile.objects.filter(verification_status=VerificationStatus.PENDING).select_related("user"),
    }
