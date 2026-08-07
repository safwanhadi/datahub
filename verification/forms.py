from calendar import monthrange
from copy import deepcopy
from datetime import date

from django import forms

from .health_metadata import normalize_health_payload
from .models import InpatientIndicatorStandard, VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator


class InpatientIndicatorStandardForm(forms.ModelForm):
    class Meta:
        model = InpatientIndicatorStandard
        fields = (
            "indicator", "policy_level", "minimum_value", "maximum_value",
            "maximum_exclusive", "unit", "period_basis", "effective_from",
            "effective_until", "reference_name", "reference_url", "notes", "is_active",
        )
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
            "effective_until": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class IndicatorPeriodForm(forms.Form):
    PERIOD_TYPES = (("month", "Bulanan"), ("quarter", "Triwulan"), ("semester", "Semester"), ("year", "Tahunan"))
    period_type = forms.ChoiceField(label="Jenis periode", choices=PERIOD_TYPES)
    year = forms.IntegerField(label="Tahun", min_value=2000, max_value=2100, initial=date.today().year)
    month = forms.TypedChoiceField(label="Bulan", coerce=int, required=False, choices=[(i, date(2000, i, 1).strftime("%B")) for i in range(1, 13)])
    quarter = forms.TypedChoiceField(label="Triwulan", coerce=int, required=False, choices=((1, "I"), (2, "II"), (3, "III"), (4, "IV")))
    semester = forms.TypedChoiceField(label="Semester", coerce=int, required=False, choices=((1, "I"), (2, "II")))

    def clean(self):
        cleaned = super().clean()
        kind, year = cleaned.get("period_type"), cleaned.get("year")
        if not kind or not year:
            return cleaned
        if kind == "month":
            month = cleaned.get("month")
            if not month: self.add_error("month", "Pilih bulan."); return cleaned
            start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
        elif kind == "quarter":
            quarter = cleaned.get("quarter")
            if not quarter: self.add_error("quarter", "Pilih triwulan."); return cleaned
            first, last = (quarter - 1) * 3 + 1, quarter * 3
            start, end = date(year, first, 1), date(year, last, monthrange(year, last)[1])
        elif kind == "semester":
            semester = cleaned.get("semester")
            if not semester: self.add_error("semester", "Pilih semester."); return cleaned
            first, last = (1, 6) if semester == 1 else (7, 12)
            start, end = date(year, first, 1), date(year, last, monthrange(year, last)[1])
        else:
            start, end = date(year, 1, 1), date(year, 12, 31)
        cleaned["period_start"], cleaned["period_end"] = start, end
        return cleaned


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


class MonthlyHealthVerificationForm(forms.Form):
    """Form tabel untuk pegawai; struktur JSON dibangun kembali oleh sistem."""

    notes = forms.CharField(
        label="Catatan verifikasi",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, payload, notes="", **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = deepcopy(payload)
        self.fields["notes"].initial = notes
        self.visit_rows = []
        self.disease_rows = []
        self.tourist_rows = []
        self.group_rows = []

        for index, row in enumerate(self.payload.get("visits", [])):
            name = f"visit_{index}_count"
            self.fields[name] = forms.IntegerField(min_value=0, initial=row.get("count", 0))
            self.visit_rows.append({"installation": row.get("installation"), "payment_status": row.get("payment_status"), "count": name})

        for index, row in enumerate(self.payload.get("top_diseases", [])):
            code, name, count = f"disease_{index}_code", f"disease_{index}_name", f"disease_{index}_count"
            self.fields[code] = forms.CharField(initial=row.get("icd10_code", ""))
            self.fields[name] = forms.CharField(initial=row.get("name", ""))
            self.fields[count] = forms.IntegerField(min_value=0, initial=row.get("patient_count", 0))
            self.disease_rows.append({"installation": row.get("installation"), "code": code, "name": name, "count": count})

        for index, row in enumerate(self.payload.get("tourist_visits", [])):
            origin, count = f"tourist_{index}_origin", f"tourist_{index}_count"
            self.fields[origin] = forms.CharField(initial=row.get("origin", ""))
            self.fields[count] = forms.IntegerField(min_value=0, initial=row.get("count", 0))
            self.tourist_rows.append({"category": row.get("category"), "origin": origin, "count": count})

        for index, row in enumerate(self.payload.get("disease_groups", [])):
            name = f"group_{index}_count"
            self.fields[name] = forms.IntegerField(min_value=0, initial=row.get("patient_count", 0))
            self.group_rows.append({"code": row.get("code"), "icd10_range": row.get("icd10_range"), "count": name})

        self.bound_visit_rows = self.bound_rows(self.visit_rows)
        self.bound_disease_rows = self.bound_rows(self.disease_rows)
        self.bound_tourist_rows = self.bound_rows(self.tourist_rows)
        self.bound_group_rows = self.bound_rows(self.group_rows)

    def bound_rows(self, rows):
        return [{key: self[value] if key in {"count", "name", "origin"} or key == "code" and isinstance(value, str) and value in self.fields else value for key, value in row.items()} for row in rows]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        result = deepcopy(self.payload)
        for index, row in enumerate(result.get("visits", [])):
            row["count"] = cleaned[f"visit_{index}_count"]
        for index, row in enumerate(result.get("top_diseases", [])):
            row["icd10_code"] = cleaned[f"disease_{index}_code"]
            row["name"] = cleaned[f"disease_{index}_name"]
            row["patient_count"] = cleaned[f"disease_{index}_count"]
        for index, row in enumerate(result.get("tourist_visits", [])):
            row["origin"] = cleaned[f"tourist_{index}_origin"]
            row["count"] = cleaned[f"tourist_{index}_count"]
        for index, row in enumerate(result.get("disease_groups", [])):
            row["patient_count"] = cleaned[f"group_{index}_count"]
        cleaned["verified_data"] = normalize_health_payload(result)
        return cleaned
