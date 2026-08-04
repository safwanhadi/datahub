import json

from django import forms

from .models import DataSource, VerifiedInpatientIndicator, VerifiedRecord


class ImportForm(forms.Form):
    source = forms.ModelChoiceField(queryset=DataSource.objects.filter(is_active=True))
    reference = forms.CharField(max_length=150, required=False)
    record_type = forms.SlugField(max_length=80, help_text="Contoh: kunjungan, pasien, billing")
    data = forms.JSONField(
        widget=forms.Textarea(attrs={"rows": 12}),
        help_text='Array JSON. Setiap item wajib memiliki "source_key".',
    )

    def clean_data(self):
        data = self.cleaned_data["data"]
        if not isinstance(data, list) or not data:
            raise forms.ValidationError("Data harus berupa array JSON yang tidak kosong.")
        for index, item in enumerate(data):
            if not isinstance(item, dict) or not item.get("source_key"):
                raise forms.ValidationError(
                    f'Item ke-{index + 1} wajib berupa objek dan memiliki "source_key".'
                )
        return data


class VerificationForm(forms.ModelForm):
    verified_data_text = forms.CharField(
        label="Data hasil verifikasi (JSON)",
        widget=forms.Textarea(attrs={"rows": 18, "class": "code-editor"}),
    )

    class Meta:
        model = VerifiedRecord
        fields = ("verification_notes",)
        widgets = {"verification_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["verified_data_text"].initial = json.dumps(
            self.instance.verified_data, indent=2, ensure_ascii=False
        )

    def clean_verified_data_text(self):
        try:
            value = json.loads(self.cleaned_data["verified_data_text"])
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"JSON tidak valid: {exc}") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError("Data hasil verifikasi harus berupa objek JSON.")
        return value


class IndicatorPeriodForm(forms.Form):
    period = forms.DateField(
        label="Bulan data",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(attrs={"type": "month"}),
    )


class InpatientIndicatorVerificationForm(forms.ModelForm):
    class Meta:
        model = VerifiedInpatientIndicator
        fields = ("alos", "bor", "bto", "toi", "gdr", "ndr", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        values = super().clean()
        for field in ("alos", "bor", "bto", "toi", "gdr", "ndr"):
            if values.get(field) is not None and values[field] < 0:
                self.add_error(field, "Nilai tidak boleh negatif.")
        return values
