from django import forms

from .models import Dispute


class DisputeForm(forms.Form):
    category = forms.ChoiceField(choices=Dispute.Category.choices)
    description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}), max_length=3000,
        help_text="What happened? Include dates, amounts and anything staff should check.",
    )
