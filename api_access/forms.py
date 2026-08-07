from django import forms
from django.forms import inlineformset_factory

from .models import ApiProduct, ExternalApiClient, ExternalApiGrant


class ExternalApiClientForm(forms.ModelForm):
    class Meta:
        model = ExternalApiClient
        fields = ("name", "client_id", "requests_per_minute", "is_active")


class ApiProductForm(forms.ModelForm):
    class Meta:
        model = ApiProduct
        fields = ("name", "description", "required_scope", "is_active")


class GrantForm(forms.ModelForm):
    class Meta:
        model = ExternalApiGrant
        fields = ("product", "is_active", "expires_at")
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expires_at"].input_formats = ("%Y-%m-%dT%H:%M",)
        self.fields["product"].queryset = ApiProduct.objects.order_by("name")


GrantFormSet = inlineformset_factory(
    ExternalApiClient,
    ExternalApiGrant,
    form=GrantForm,
    extra=1,
    can_delete=True,
)
