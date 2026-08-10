from calendar import monthrange
from copy import deepcopy
from datetime import date

from django import forms
from django.forms import inlineformset_factory

from .health_metadata import normalize_health_payload
from .models import AdministrativeRegion, InpatientIndicatorStandard, RegionAlias, SimrsApiEndpoint, VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator


class AdministrativeRegionForm(forms.ModelForm):
    class Meta:
        model = AdministrativeRegion
        fields = ("official_code", "name", "region_type", "parent", "island_group", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_type = self.data.get("region_type") if self.is_bound else getattr(self.instance, "region_type", "")
        parent_types = {
            "province": (),
            "regency": ("province",),
            "city": ("province",),
            "district": ("regency", "city"),
            "village": ("district",),
        }.get(selected_type, ("province", "regency", "city", "district"))
        self.fields["parent"].queryset = AdministrativeRegion.objects.filter(
            region_type__in=parent_types, is_active=True
        ).order_by("name")


class RegionAliasForm(forms.ModelForm):
    class Meta:
        model = RegionAlias
        fields = ("alias", "source_system", "is_active")


RegionAliasFormSet = inlineformset_factory(
    AdministrativeRegion, RegionAlias, form=RegionAliasForm, extra=1, can_delete=True
)


class SimrsApiEndpointForm(forms.ModelForm):
    class Meta:
        model = SimrsApiEndpoint
        fields = ("code", "name", "url", "timeout_seconds", "is_active")
        widgets = {"url": forms.URLInput(attrs={"placeholder": "https://simrs.example/api/..."})}

    def clean_timeout_seconds(self):
        timeout = self.cleaned_data["timeout_seconds"]
        if timeout > 300:
            raise forms.ValidationError("Timeout maksimal 300 detik.")
        return timeout


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

    def __init__(self, *args, payload, notes="", indicator_code=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = deepcopy(payload)
        self.indicator_code = indicator_code
        self.fields["notes"].initial = notes
        self.visit_rows = []
        self.disease_rows = []
        self.tourist_rows = []
        self.group_rows = []

        for index, row in enumerate(self.payload.get("visits", [])):
            installation = {
                "outpatient-visits": "outpatient",
                "inpatient-visits": "inpatient",
                "emergency-visits": "emergency",
            }.get(indicator_code)
            if installation and row.get("installation") != installation:
                continue
            if indicator_code and not installation:
                continue
            name = f"visit_{index}_count"
            self.fields[name] = forms.IntegerField(min_value=0, initial=row.get("count", 0))
            self.visit_rows.append({"installation": row.get("installation"), "payment_status": row.get("payment_status"), "count": name})

        for index, row in enumerate(self.payload.get("top_diseases", [])):
            if indicator_code and indicator_code != "top-diseases":
                continue
            code, name, count = f"disease_{index}_code", f"disease_{index}_name", f"disease_{index}_count"
            self.fields[code] = forms.CharField(initial=row.get("icd10_code", ""))
            self.fields[name] = forms.CharField(initial=row.get("name", ""))
            self.fields[count] = forms.IntegerField(min_value=0, initial=row.get("patient_count", 0))
            self.disease_rows.append({"installation": row.get("installation"), "code": code, "name": name, "count": count})

        for index, row in enumerate(self.payload.get("tourist_visits", [])):
            if indicator_code and indicator_code != "tourist-visits":
                continue
            origin, count = f"tourist_{index}_origin", f"tourist_{index}_count"
            self.fields[origin] = forms.CharField(initial=row.get("origin", ""))
            self.fields[count] = forms.IntegerField(min_value=0, initial=row.get("count", 0))
            category = row.get("category")
            category_label = {
                "domestic": "Wisatawan Nusantara",
                "international": "Wisatawan Mancanegara",
                "wisnus": "Wisatawan Nusantara",
                "wisman": "Wisatawan Mancanegara",
            }.get(category, category)
            self.tourist_rows.append({
                "category": category, "category_label": category_label,
                "origin": origin, "count": count,
                "mapped_code": row.get("mapped_code"),
                "mapped_name": row.get("mapped_name"),
                "mapping_status": row.get("mapping_status", "Belum dikenali"),
                "cleaning_method": row.get("cleaning_method", "unresolved"),
            })

        for index, row in enumerate(self.payload.get("disease_groups", [])):
            if indicator_code and indicator_code != "kjsu-evaluation" and row.get("code") != indicator_code.removesuffix("-patients"):
                continue
            name = f"group_{index}_count"
            self.fields[name] = forms.IntegerField(min_value=0, initial=row.get("patient_count", 0))
            self.group_rows.append({"code": row.get("code"), "icd10_range": row.get("icd10_range"), "count": name})

        self.bound_visit_rows = self.bound_rows(self.visit_rows)
        self.bound_disease_rows = self.bound_rows(self.disease_rows)
        self.bound_tourist_rows = self.bound_rows(self.tourist_rows)
        self.bound_group_rows = self.bound_rows(self.group_rows)
        self.tourist_mapping_summary = self.build_tourist_mapping_summary()

    def build_tourist_mapping_summary(self):
        """Ringkas variasi nama SIMRS ke satu nama wilayah baku."""
        groups = {}
        method_labels = {
            "official_code": "Kode resmi",
            "exact_name": "Nama baku",
            "alias": "Alias",
            "unresolved": "Belum dikenali",
        }
        for index, row in enumerate(self.payload.get("tourist_visits", [])):
            category = row.get("category")
            if category == "international":
                canonical_code, canonical_name = "INTL", "Luar Indonesia"
            else:
                canonical_code = row.get("mapped_code") or "—"
                canonical_name = row.get("mapped_name") or "Belum dikenali"
            key = (category, canonical_code, canonical_name, row.get("mapping_status", "Belum dikenali"))
            item = groups.setdefault(key, {
                "category": {
                    "domestic": "Wisatawan Nusantara",
                    "international": "Wisatawan Mancanegara",
                }.get(category, category),
                "canonical_code": canonical_code,
                "canonical_name": canonical_name,
                "raw_names": [],
                "methods": [],
                "status": row.get("mapping_status", "Belum dikenali"),
                "count": 0,
            })
            raw_name = row.get("origin") or "—"
            if raw_name not in item["raw_names"]:
                item["raw_names"].append(raw_name)
            method = method_labels.get(row.get("cleaning_method"), row.get("cleaning_method") or "—")
            if category == "international":
                method = "Agregasi internasional"
            if method not in item["methods"]:
                item["methods"].append(method)
            field_name = f"tourist_{index}_count"
            try:
                count = int(self.data.get(field_name)) if self.is_bound and field_name in self.data else int(row.get("count", 0))
            except (TypeError, ValueError):
                count = int(row.get("count", 0))
            item["count"] += count
        for item in groups.values():
            item["raw_names"].sort()
            item["methods"].sort()
        return sorted(groups.values(), key=lambda item: (item["canonical_name"], item["category"]))

    def bound_rows(self, rows):
        return [{key: self[value] if key in {"count", "name", "origin"} or key == "code" and isinstance(value, str) and value in self.fields else value for key, value in row.items()} for row in rows]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        result = deepcopy(self.payload)
        for index, row in enumerate(result.get("visits", [])):
            field = f"visit_{index}_count"
            if field in cleaned:
                row["count"] = cleaned[field]
        for index, row in enumerate(result.get("top_diseases", [])):
            if f"disease_{index}_count" in cleaned:
                row["icd10_code"] = cleaned[f"disease_{index}_code"]
                row["name"] = cleaned[f"disease_{index}_name"]
                row["patient_count"] = cleaned[f"disease_{index}_count"]
        for index, row in enumerate(result.get("tourist_visits", [])):
            if f"tourist_{index}_count" in cleaned:
                row["origin"] = cleaned[f"tourist_{index}_origin"]
                row["count"] = cleaned[f"tourist_{index}_count"]
        for index, row in enumerate(result.get("disease_groups", [])):
            field = f"group_{index}_count"
            if field in cleaned:
                row["patient_count"] = cleaned[field]
        cleaned["verified_data"] = normalize_health_payload(result)
        return cleaned



class InpatientWorkingDataCorrectionForm(forms.Form):
    beds = forms.IntegerField(label="Tempat tidur", min_value=0)
    care_days = forms.IntegerField(label="Hari perawatan", min_value=0)
    discharged_patients = forms.IntegerField(label="Pasien keluar", min_value=0)
    deaths = forms.IntegerField(label="Pasien meninggal", min_value=0)
    deaths_over_48h = forms.IntegerField(label="Meninggal > 48 jam", min_value=0)
    days_in_period = forms.IntegerField(label="Jumlah hari", min_value=1, max_value=366)
    reason = forms.CharField(
        label="Alasan koreksi",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Jelaskan perbedaan data SIMRS dengan data nyata di lapangan.",
    )

    def clean(self):
        cleaned = super().clean()
        deaths = cleaned.get("deaths")
        deaths_over_48h = cleaned.get("deaths_over_48h")
        discharged = cleaned.get("discharged_patients")
        if deaths is not None and deaths_over_48h is not None and deaths_over_48h > deaths:
            self.add_error("deaths_over_48h", "Kematian >48 jam tidak boleh melebihi seluruh kematian.")
        if deaths is not None and discharged is not None and deaths > discharged:
            self.add_error("deaths", "Jumlah kematian tidak boleh melebihi pasien keluar.")
        return cleaned
