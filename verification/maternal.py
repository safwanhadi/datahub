"""Internal maternal/perinatal aggregate contract and audited workflow."""
from calendar import monthrange
from copy import deepcopy
from datetime import date
from urllib.parse import urlencode

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MaternalPerinatalSnapshot, MaternalPerinatalRecord, MaternalPerinatalAudit, SimrsApiEndpoint
from .oauth import get_simrs_access_token
from .services import resolve_simrs_endpoint, _fetch_simrs_json


METRICS = {
    "deliveries_total": "Ibu bersalin di RS",
    "deliveries_vaginal": "Persalinan pervaginam",
    "deliveries_caesarean": "Persalinan seksio sesarea",
    "deliveries_other": "Persalinan dengan cara belum terklasifikasi",
    "live_births": "Bayi lahir hidup di RS",
    "stillbirths_28w": "Lahir mati di RS, usia kehamilan ≥28 minggu",
    "stillbirths_22_27w": "Lahir mati di RS, usia kehamilan 22–27 minggu",
    "stillbirths_unknown_ga": "Lahir mati di RS, usia kehamilan belum diketahui",
    "maternal_discharges": "Episode maternal keluar RS",
    "perinatal_discharges": "Episode neonatal keluar RS",
    "maternal_deaths": "Kematian maternal terkonfirmasi di RS",
    "pregnancy_related_deaths_unclassified": "Kematian terkait waktu kehamilan, belum diklasifikasi",
    "neonatal_deaths_early": "Kematian neonatal di RS usia 0–6 hari",
    "neonatal_deaths_late": "Kematian neonatal di RS usia 7–27 hari",
    "newborn_deaths_age_unknown": "Kematian bayi di RS dengan umur belum diketahui",
    "maternal_referral_admissions": "Episode masuk maternal melalui rujukan",
    "neonatal_inborn_admissions": "Episode masuk neonatal, lahir di RS ini",
    "neonatal_outborn_admissions": "Episode masuk neonatal, lahir di luar RS",
}
RANKINGS = {"maternal_diagnoses": "Kasus maternal terbanyak", "perinatal_diagnoses": "Kasus neonatal terbanyak"}


def _error(message):
    raise ValidationError(message)


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        _error(f"Struktur {label} harus berisi: {', '.join(expected)}.")


def _count(value, label):
    if value is not None and (type(value) is not int or value < 0):
        _error(f"{label} harus integer nonnegatif atau null jika belum tersedia.")


def validate_maternal(payload, start, end):
    _keys(payload, ("schema_version", "period", "hospital", "metrics", *RANKINGS), "respons maternal")
    if payload["schema_version"] != "1.0":
        _error("Versi kontrak maternal harus 1.0.")
    _keys(payload["period"], ("start", "end"), "period")
    if payload["period"] != {"start": start.isoformat(), "end": end.isoformat()}:
        _error("Periode respons berbeda dari periode permintaan.")
    _keys(payload["hospital"], ("code", "name"), "hospital")
    for value in payload["hospital"].values():
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            _error("Kode dan nama rumah sakit wajib berupa teks, maksimal 160 karakter.")
    _keys(payload["metrics"], METRICS, "metrics")
    metrics = payload["metrics"]
    for key, value in metrics.items():
        _count(value, key)
    parts = [metrics[key] for key in ("deliveries_vaginal", "deliveries_caesarean", "deliveries_other")]
    if metrics["deliveries_total"] is not None and all(v is not None for v in parts):
        if sum(parts) != metrics["deliveries_total"]:
            _error("Jumlah cara persalinan harus sama dengan total ibu bersalin.")
    for key, denominator in (("maternal_diagnoses", "maternal_discharges"), ("perinatal_diagnoses", "perinatal_discharges")):
        rows = payload[key]
        if rows is None:
            continue
        if not isinstance(rows, list) or len(rows) > 5000:
            _error(f"{key} harus array maksimal 5000 baris atau null.")
        seen = set()
        for row in rows:
            _keys(row, ("icd10_code", "name", "count"), key)
            if not isinstance(row["icd10_code"], str) or not row["icd10_code"].strip() or len(row["icd10_code"]) > 20:
                _error("Kode diagnosis wajib berupa teks maksimal 20 karakter.")
            if not isinstance(row["name"], str) or not row["name"].strip() or len(row["name"]) > 255:
                _error("Nama diagnosis wajib berupa teks maksimal 255 karakter.")
            if row["icd10_code"] in seen:
                _error(f"Kode diagnosis berulang pada {key}.")
            seen.add(row["icd10_code"])
            _count(row["count"], key)
            if row["count"] is None:
                _error("Jumlah diagnosis tidak boleh null; gunakan null untuk seluruh daftar jika belum tersedia.")
        if metrics[denominator] is not None and sum(row["count"] for row in rows) > metrics[denominator]:
            _error(f"Jumlah diagnosis utama melebihi {denominator}.")
    return deepcopy(payload)


def _audit(record, action, before, user):
    MaternalPerinatalAudit.objects.create(
        record=record, source=record.source, action=action, before_data=before,
        after_data=record.working_data, notes=record.notes, actor=user,
    )


@transaction.atomic
def store_maternal(payload, start, end, user):
    if start.day != 1 or end != date(start.year, start.month, monthrange(start.year, start.month)[1]):
        _error("Pengambilan maternal hanya satu bulan kalender penuh; rentang panjang dihitung dari bulan-bulan terverifikasi.")
    data = validate_maternal(payload, start, end)
    previous = MaternalPerinatalSnapshot.objects.order_by("pk").first()
    if previous and previous.payload["hospital"]["code"] != data["hospital"]["code"]:
        _error("Kode rumah sakit berbeda dari snapshot maternal sebelumnya.")
    snapshot = MaternalPerinatalSnapshot.objects.create(period_start=start, period_end=end, payload=data, fetched_by=user)
    record, created = MaternalPerinatalRecord.objects.get_or_create(
        period_start=start, period_end=end, defaults={"source": snapshot, "working_data": data},
    )
    if created:
        _audit(record, "copied_from_simrs", None, user)
    return record


def fetch_maternal(start, end, user):
    url, timeout = resolve_simrs_endpoint(SimrsApiEndpoint.Code.MATERNAL_PERINATAL)
    url += ("&" if "?" in url else "?") + urlencode({"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()})
    payload = _fetch_simrs_json(url, headers={"Accept": "application/json", "Authorization": f"Bearer {get_simrs_access_token()}"}, timeout=timeout, endpoint_name="maternal perinatal")
    return store_maternal(payload, start, end, user)


class MaternalVerificationForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput)
    notes = forms.CharField(label="Alasan koreksi / catatan verifikasi", widget=forms.Textarea(attrs={"rows": 3}), required=True)

    def __init__(self, *args, record, **kwargs):
        super().__init__(*args, **kwargs)
        self.record = record
        self.fields["revision"].initial = record.revision
        self.fields["notes"].initial = record.notes
        self.metric_fields = []
        self.diagnosis_groups = []
        for key, label in METRICS.items():
            field = f"metric_{key}"
            self.fields[field] = forms.IntegerField(label=label, min_value=0, required=False, initial=record.working_data["metrics"][key])
            self.metric_fields.append(self[field])
        for key, label in RANKINGS.items():
            rows = []
            for i, row in enumerate(record.working_data[key] or []):
                field = f"{key}_{i}"
                self.fields[field] = forms.IntegerField(min_value=0, initial=row["count"])
                rows.append({**row, "field": self[field]})
            self.diagnosis_groups.append({"label": label, "rows": rows})

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        data = deepcopy(self.record.working_data)
        data["metrics"] = {key: cleaned[f"metric_{key}"] for key in METRICS}
        for key in RANKINGS:
            for i, row in enumerate(data[key] or []):
                row["count"] = cleaned[f"{key}_{i}"]
        cleaned["payload"] = validate_maternal(data, self.record.period_start, self.record.period_end)
        return cleaned


@transaction.atomic
def save_maternal(pk, revision, user, *, data=None, notes="", approve=False, reload=False):
    record = MaternalPerinatalRecord.objects.select_for_update().get(pk=pk)
    if revision != record.revision:
        _error("Data telah diperbarui pengguna lain. Buka ulang halaman sebelum menyimpan.")
    before = deepcopy(record.working_data)
    if reload:
        record.source = MaternalPerinatalSnapshot.objects.filter(period_start=record.period_start, period_end=record.period_end).latest("pk")
        data = record.source.payload
        notes = "Memuat ulang snapshot SIMRS terbaru; perlu pemeriksaan ulang."
        approve = False
    if not notes.strip():
        _error("Catatan verifikasi wajib diisi.")
    record.working_data = validate_maternal(data, record.period_start, record.period_end)
    record.status = "approved" if approve else "draft"
    record.notes = notes
    record.verified_by = user
    record.verified_at = timezone.now() if approve else None
    record.revision += 1
    record.save()
    _audit(record, "reloaded" if reload else "approved" if approve else "updated", before, user)
    return record


def summarize_maternal(records):
    records = list(records)
    metrics = []
    for key, label in METRICS.items():
        values = [r.working_data["metrics"][key] for r in records]
        known = [v for v in values if v is not None]
        metrics.append({"key": key, "label": label, "value": sum(known) if known else None, "partial": len(known) < len(values)})
    rankings = []
    for key, label in RANKINGS.items():
        groups = {}
        for record in records:
            for row in record.working_data[key] or []:
                item = groups.setdefault(row["icd10_code"], {**row, "count": 0})
                item["count"] += row["count"]
        rankings.append({"label": label, "partial": any(r.working_data[key] is None for r in records), "rows": sorted(groups.values(), key=lambda r: (-r["count"], r["icd10_code"]))[:10]})
    return {"metrics": metrics, "rankings": rankings}
