from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group


class ManagedUserForm(forms.ModelForm):
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
