"""
Reusable server-side authorization helpers (Section 42: 'the backend must
independently verify permission' — never rely on a hidden button or a
role label alone). These are the building blocks later apps (auctions,
listings, bidding, disputes) import rather than re-implementing role checks.

Two layers are provided:
  - Role-level (does this user's account type allow this kind of action at
    all) via the mixins/decorators below.
  - Object-level (does this user own/administer *this specific* object) is
    left to each app's own view code, since only that app knows the
    relevant field (e.g. auction.seller.user == request.user) — see
    check_owner() as a small shared helper for that pattern.
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from functools import wraps


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Class-based view mixin. Subclass and set `allowed_roles`, e.g.
    allowed_roles = ("SELLER",) or ("ADMIN", "OFFICER")."""

    allowed_roles = ()
    raise_exception = True  # 403, not a silent redirect, once authenticated

    def test_func(self):
        user = self.request.user
        # Admins/officers can act as any role for administrative purposes;
        # everyone else must match one of the explicitly allowed roles.
        return user.is_officer_or_admin or user.role in self.allowed_roles


class SellerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("SELLER",)


class BidderRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("BIDDER",)


class StaffOrOfficerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """For administrative views: listing approval queue, verification
    queue, dispute resolution, audit log viewing."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_officer_or_admin


def role_required(*roles):
    """Function-based-view decorator equivalent of RoleRequiredMixin."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Login required.")
            if request.user.is_officer_or_admin or request.user.role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to perform this action.")

        return wrapped

    return decorator


def check_owner(request_user, owner_user, *, allow_staff=True):
    """
    Small shared helper for the common 'is this user allowed to
    edit/view this specific object' check (Section 42 examples: 'Sellers
    can only manage their own auctions', 'Bidders can only access their
    own private information'). Raises PermissionDenied rather than
    returning a bool, so a call site that forgets to check the return
    value can't silently proceed.
    """
    if allow_staff and getattr(request_user, "is_officer_or_admin", False):
        return
    if request_user != owner_user:
        raise PermissionDenied("You do not have permission to access this object.")
