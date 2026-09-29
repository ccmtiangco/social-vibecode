from django import forms

from .models import AdCampaign, AdCreative
from .services import MAX_PURCHASE_AMOUNT_MINOR


class CampaignForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        input_formats=('%Y-%m-%dT%H:%M',),
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'type': 'datetime-local'},
        ),
    )
    ends_at = forms.DateTimeField(
        input_formats=('%Y-%m-%dT%H:%M',),
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'type': 'datetime-local'},
        ),
    )

    class Meta:
        model = AdCampaign
        fields = ('name', 'starts_at', 'ends_at', 'currency_code', 'impression_cost_minor')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Campaign name'}),
            'currency_code': forms.TextInput(attrs={'maxlength': 3}),
            'impression_cost_minor': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }


class AdCreativeForm(forms.ModelForm):
    class Meta:
        model = AdCreative
        fields = ('headline', 'body', 'image', 'destination_url', 'is_active')
        widgets = {
            'headline': forms.TextInput(attrs={'placeholder': 'A short headline'}),
            'body': forms.Textarea(attrs={'rows': 4}),
            'image': forms.ClearableFileInput(
                attrs={'accept': 'image/jpeg,image/png,image/webp'}
            ),
            'destination_url': forms.URLInput(attrs={'placeholder': 'https://example.com'}),
        }


class SimulatedPurchaseForm(forms.Form):
    amount_minor = forms.IntegerField(
        min_value=1,
        max_value=MAX_PURCHASE_AMOUNT_MINOR,
        label='Amount to add (minor units, e.g. cents)',
        widget=forms.NumberInput(attrs={'min': 1, 'step': 1}),
    )
