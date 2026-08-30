from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import User


class RegistrationForm(UserCreationForm):
    """
    Self-service registration. Role is limited to SELLER/BIDDER here —
    ADMIN and OFFICER accounts are provisioned by an existing administrator
    (via Django Admin or a future admin-only view), never through public
    self-registration.
    """

    role = None  # set in __init__ so choices exclude ADMIN/OFFICER

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "phone_number", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["role"] = self.base_fields.get("role")
        from django import forms as dj_forms

        self.fields["role"] = dj_forms.ChoiceField(
            choices=[
                (User.Role.BIDDER, "Bidder — I want to bid on auctions"),
                (User.Role.SELLER, "Seller — I want to list items for auction"),
            ],
            initial=User.Role.BIDDER,
        )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email
