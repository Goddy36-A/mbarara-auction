from django import forms
from django.core.exceptions import ValidationError

from apps.auctions.models import Auction, AuctionCategory

from .models import AuctionImage

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB (Section 44)


class AuctionForm(forms.ModelForm):
    """Seller-facing create/edit form (Section 15). Only editable while the
    auction is still DRAFT — the view enforces that, not this form, since
    the form itself is reused for both create and edit."""

    class Meta:
        model = Auction
        fields = [
            "category", "title", "description", "location",
            "starting_price", "reserve_price", "min_increment",
            "start_time", "end_time", "extension_minutes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = AuctionCategory.objects.all()
        self.fields["reserve_price"].required = False

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if start and end and start >= end:
            raise ValidationError("Start time must be before end time.")
        reserve = cleaned.get("reserve_price")
        starting = cleaned.get("starting_price")
        if reserve is not None and starting is not None and reserve < starting:
            raise ValidationError("Reserve price cannot be lower than the starting price.")
        return cleaned


class AuctionImageForm(forms.ModelForm):
    class Meta:
        model = AuctionImage
        fields = ["image", "sort_order"]

    def clean_image(self):
        image = self.cleaned_data["image"]
        content_type = getattr(image, "content_type", None)
        if content_type and content_type not in ALLOWED_IMAGE_TYPES:
            raise ValidationError("Only JPEG, PNG, or WEBP images are allowed.")
        if image.size > MAX_IMAGE_SIZE_BYTES:
            raise ValidationError("Image must be smaller than 5MB.")
        return image


AuctionImageFormSet = forms.inlineformset_factory(
    Auction, AuctionImage, form=AuctionImageForm, extra=3, can_delete=True
)
