import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .models import (
    SimrsApiEndpoint,
    InpatientIndicatorAudit,
    InpatientIndicatorSource,
    MonthlyHealthIndicatorAudit,
    MonthlyHealthIndicatorSource,
    VerifiedInpatientIndicator,
    VerifiedMonthlyHealthIndicator,
    VerifiedHealthVisitRow,
    VerifiedTopDiseaseRow,
    VerifiedTouristVisitRow,
    VerifiedDiseaseGroupRow,
)
from .oauth import get_simrs_access_token
from .health_metadata import normalize_health_payload


def resolve_simrs_endpoint(code, fallback_url=""):
    """Ambil URL dinamis dari database, dengan fallback environment lama."""
    endpoint = SimrsApiEndpoint.objects.filter(code=code).first()
    if endpoint:
        if not endpoint.is_active:
            raise ImproperlyConfigured(f"Endpoint SIMRS {endpoint.name} sedang dinonaktifkan.")
        return endpoint.url, endpoint.timeout_seconds
    if fallback_url:
        return fallback_url, 30
    raise ImproperlyConfigured(f"Endpoint SIMRS {code} belum dikonfigurasi.")


@transaction.atomic
def store_inpatient_indicator(*, period=None, period_start=None, period_end=None, period_type="month", payload, user=None):
    start = period_start or period
    if start is None:
        raise ValueError("Tanggal awal periode wajib tersedia.")
    end = period_end or date(start.year, start.month, monthrange(start.year, start.month)[1])
    basic = payload["data_dasar"]
    source_indicator = payload["indikator"]
    calculated = calculate_inpatient_indicators(
        beds=basic["jumlah_bed"],
        care_days=basic["hari_perawatan"],
        discharged=basic["pasien_keluar"],
        deaths=basic["pasien_mati"],
        deaths_over_48h=basic["pasien_mati_48"],
        days=payload.get("periode", {}).get("hari", (end - start).days + 1),
    )
    source, _ = InpatientIndicatorSource.objects.update_or_create(
        period_type=period_type,
        period_start=start,
        period_end=end,
        defaults={
            "period": start,
            "period_start": start,
            "period_end": end,
            "days_in_period": payload.get("periode", {}).get("hari", (end - start).days + 1),
            "beds": basic["jumlah_bed"],
            "care_days": basic["hari_perawatan"],
            "discharged_patients": basic["pasien_keluar"],
            "deaths": basic["pasien_mati"],
            "deaths_over_48h": basic["pasien_mati_48"],
            # Nilai awal perhitungan dari PHP tetap diarsipkan.
            **{key: Decimal(str(source_indicator[key])) for key in ("alos", "bor", "bto", "toi", "gdr", "ndr")},
            # Django menghitung ulang hanya dari data dasar yang diterima.
            **{f"calculated_{key}": calculated[key] for key in ("alos", "bor", "bto", "toi", "gdr", "ndr")},
            "raw_response": payload,
            "fetched_by": user,
        },
    )
    # Jika sudah disetujui, snapshot baru tidak menimpa hasil verifikasi.
    if not hasattr(source, "verification"):
        verified = VerifiedInpatientIndicator.objects.create(
            source=source,
            period=start,
            **{key: getattr(source, f"calculated_{key}") for key in ("alos", "bor", "bto", "toi", "gdr", "ndr")},
            verified_by=user,
        )
        InpatientIndicatorAudit.objects.create(
            record=verified,
            action="copied_from_simrs",
            before_data=None,
            after_data={key: str(getattr(verified, key)) for key in ("alos", "bor", "bto", "toi", "gdr", "ndr")},
            actor=user,
        )
    return source


def calculate_inpatient_indicators(
    *, beds, care_days, discharged, deaths, deaths_over_48h, days
):
    """Rumus Barber Johnson berdasarkan data dasar JSON, independen dari nilai PHP."""
    beds = int(beds)
    care_days = int(care_days)
    discharged = int(discharged)
    deaths = int(deaths)
    deaths_over_48h = int(deaths_over_48h)
    days = int(days)
    if min(beds, care_days, discharged, deaths, deaths_over_48h, days) < 0:
        raise ValueError("Data dasar tidak boleh bernilai negatif.")
    if days == 0:
        raise ValueError("Jumlah hari periode harus lebih dari nol.")
    patient_divisor = Decimal(discharged or 1)
    bed_divisor = Decimal(beds or 1)
    capacity = bed_divisor * days
    care = Decimal(care_days)
    indicators = {
        "alos": care / patient_divisor,
        "bor": care / capacity * 100,
        "bto": Decimal(discharged) / bed_divisor,
        "toi": (capacity - care) / patient_divisor,
        "gdr": Decimal(deaths) / patient_divisor * 1000,
        "ndr": Decimal(deaths_over_48h) / patient_divisor * 1000,
    }
    return {key: value.quantize(Decimal("0.01")) for key, value in indicators.items()}


def fetch_inpatient_indicator(*, period=None, period_start=None, period_end=None, period_type="month", user=None):
    endpoint_url, timeout = resolve_simrs_endpoint(
        SimrsApiEndpoint.Code.INPATIENT_INDICATORS,
        settings.SIMRS_INDICATOR_API_URL,
    )
    start = period_start or period
    if start is None:
        raise ValueError("Tanggal awal periode wajib tersedia.")
    end = period_end or date(start.year, start.month, monthrange(start.year, start.month)[1])
    separator = "&" if "?" in endpoint_url else "?"
    url = endpoint_url + separator + urlencode(
        {"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()}
    )
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {get_simrs_access_token()}",
    }
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        payload = json.load(response)
    return store_inpatient_indicator(period_start=start, period_end=end, period_type=period_type, payload=payload, user=user)


def replace_health_indicator_rows(record, data):
    """Ganti tabel kerja verifikator dari payload yang sudah dinormalisasi."""
    record.visit_rows.all().delete()
    record.top_disease_rows.all().delete()
    record.tourist_visit_rows.all().delete()
    record.disease_group_rows.all().delete()
    VerifiedHealthVisitRow.objects.bulk_create([
        VerifiedHealthVisitRow(verification=record, installation=row["installation"], payment_status=row["payment_status"], count=row["count"])
        for row in data.get("visits", [])
    ])
    ranks = {}
    diseases = []
    for row in data.get("top_diseases", []):
        installation = row["installation"]
        ranks[installation] = ranks.get(installation, 0) + 1
        diseases.append(VerifiedTopDiseaseRow(verification=record, installation=installation, rank=ranks[installation], icd10_code=row["icd10_code"], name=row["name"], patient_count=row["patient_count"]))
    VerifiedTopDiseaseRow.objects.bulk_create(diseases)
    VerifiedTouristVisitRow.objects.bulk_create([
        VerifiedTouristVisitRow(verification=record, category=row["category"], origin=row.get("origin", ""), count=row["count"])
        for row in data.get("tourist_visits", [])
    ])
    VerifiedDiseaseGroupRow.objects.bulk_create([
        VerifiedDiseaseGroupRow(verification=record, code=row["code"], icd10_range=row["icd10_range"], patient_count=row["patient_count"])
        for row in data.get("disease_groups", [])
    ])


@transaction.atomic
def save_inpatient_verification(*, record, cleaned_data, user, approve):
    fields = ("alos", "bor", "bto", "toi", "gdr", "ndr")
    before = {key: str(getattr(record, key)) for key in fields}
    for key in fields:
        setattr(record, key, cleaned_data[key])
    record.notes = cleaned_data.get("notes", "")
    record.verified_by = user
    if approve:
        record.status = VerifiedInpatientIndicator.Status.APPROVED
        record.verified_at = timezone.now()
    record.save()
    InpatientIndicatorAudit.objects.create(
        record=record,
        action="approved" if approve else "updated",
        before_data=before,
        after_data={key: str(getattr(record, key)) for key in fields},
        actor=user,
    )
    return record


@transaction.atomic
def store_monthly_health_indicators(*, period=None, period_start=None, period_end=None, period_type="month", payload, user=None):
    normalized = normalize_health_payload(payload)
    start = period_start or period
    if start is None:
        raise ValueError("Tanggal awal periode wajib tersedia.")
    end = period_end or date(start.year, start.month, monthrange(start.year, start.month)[1])
    hospital = normalized["hospital"]
    source, _ = MonthlyHealthIndicatorSource.objects.update_or_create(
        period_type=period_type,
        period_start=start,
        period_end=end,
        defaults={
            "period": start,
            "hospital_code": str(hospital["code"]),
            "hospital_name": str(hospital["name"]),
            "source_data": normalized,
            "raw_response": payload,
            "fetched_by": user,
        },
    )
    if not hasattr(source, "verification"):
        verified = VerifiedMonthlyHealthIndicator.objects.create(
            source=source,
            period=start,
            verified_data=normalized,
            verified_by=user,
        )
        replace_health_indicator_rows(verified, normalized)
        MonthlyHealthIndicatorAudit.objects.create(
            record=verified,
            action="copied_from_simrs",
            before_data=None,
            after_data=normalized,
            actor=user,
        )
    return source


def fetch_monthly_health_indicators(*, period=None, period_start=None, period_end=None, period_type="month", user=None):
    endpoint_url, timeout = resolve_simrs_endpoint(
        SimrsApiEndpoint.Code.HEALTH_AGGREGATE,
        settings.SIMRS_HEALTH_API_URL,
    )
    start = period_start or period
    if start is None:
        raise ValueError("Tanggal awal periode wajib tersedia.")
    end = period_end or date(start.year, start.month, monthrange(start.year, start.month)[1])
    separator = "&" if "?" in endpoint_url else "?"
    url = endpoint_url + separator + urlencode(
        {"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()}
    )
    request = Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {get_simrs_access_token()}"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return store_monthly_health_indicators(period_start=start, period_end=end, period_type=period_type, payload=payload, user=user)


@transaction.atomic
def save_monthly_health_verification(*, record, data, notes, user, approve):
    normalized = normalize_health_payload(data)
    before = record.verified_data
    record.verified_data = normalized
    replace_health_indicator_rows(record, normalized)
    record.notes = notes
    record.verified_by = user
    if approve:
        record.status = VerifiedMonthlyHealthIndicator.Status.APPROVED
        record.verified_at = timezone.now()
    record.save()
    MonthlyHealthIndicatorAudit.objects.create(
        record=record,
        action="approved" if approve else "updated",
        before_data=before,
        after_data=normalized,
        actor=user,
    )
    return record
