from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BidderProfile, SellerProfile, User


@receiver(post_save, sender=User)
def create_role_profile(sender, instance, created, **kwargs):
    """
    Every SELLER gets a SellerProfile and every BIDDER gets a BidderProfile
    the moment their account is created, so there's never a window where a
    user has a role but no matching profile row to attach verification
    status to. ADMIN/OFFICER accounts (provisioned via Django Admin, not
    self-registration — see accounts.forms.RegistrationForm) get neither.

    Uses get_or_create so this is safe to run again if a user's role
    changes later (e.g. an admin promotes a bidder to also sell) without
    duplicating or clobbering an existing profile.
    """
    if not created:
        return
    if instance.role == User.Role.SELLER:
        SellerProfile.objects.get_or_create(user=instance, defaults={"phone": instance.phone_number})
    elif instance.role == User.Role.BIDDER:
        BidderProfile.objects.get_or_create(user=instance, defaults={"phone": instance.phone_number})
