from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import AccountProfile


class ManagedUserForm(forms.ModelForm):
    access_status = forms.ChoiceField(
        label="Status akses", choices=AccountProfile.AccessStatus.choices,
        initial=AccountProfile.AccessStatus.APPROVED, required=False,
    )
    access_notes = forms.CharField(
        label="Catatan keputusan", required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    roles = forms.ModelMultipleChoiceField(
        label="Peran DataHub",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    new_password = forms.CharField(
        label="Password baru",
        required=False,
        widget=forms.PasswordInput,
        help_text="Kosongkan untuk akun SSO atau jika password tidak ingin diubah.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Group.objects.filter(
            name__in=("Pembaca", "Petugas Data", "Verifikator", "Administrator DataHub")
        ).order_by("name")
        if self.instance.pk:
            self.fields["roles"].initial = self.instance.groups.all()
            profile = getattr(self.instance, "account_profile", None)
            if profile:
                self.fields["access_status"].initial = profile.access_status
                self.fields["access_notes"].initial = profile.access_notes

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("access_status")
        if status == AccountProfile.AccessStatus.APPROVED and not cleaned_data.get("roles"):
            self.add_error("roles", "Pilih sedikitnya satu peran sebelum menyetujui akses.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("new_password")
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
            user.groups.set(self.cleaned_data["roles"])
        return user
