import json
import re
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
    AdministrativeRegion,
    RegionAlias,
    InpatientIndicatorAudit,
    InpatientIndicatorSource,
    InpatientRoomIndicatorSource,
    MonthlyHealthIndicatorAudit,
    MonthlyHealthIndicatorSource,
    HealthIndicatorVerification,
    VerifiedInpatientIndicator,
    VerifiedInpatientRoomIndicator,
    VerifiedMonthlyHealthIndicator,
    VerifiedHealthVisitRow,
    VerifiedTopDiseaseRow,
    VerifiedTouristVisitRow,
    VerifiedDiseaseGroupRow,
    normalize_region_name,
    normalize_region_code,
)
from .oauth import get_simrs_access_token
from .health_metadata import HEALTH_VERIFICATION_GROUPS, normalize_health_payload


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
            # Nilai awal perhitungan dari SIMRS tetap diarsipkan.
            **{key: Decimal(str(source_indicator[key])) for key in ("alos", "bor", "bto", "toi", "gdr", "ndr")},
            # DataHub menghitung ulang hanya dari data dasar yang diterima.
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
            working_beds=source.beds,
            working_care_days=source.care_days,
            working_discharged_patients=source.discharged_patients,
            working_deaths=source.deaths,
            working_deaths_over_48h=source.deaths_over_48h,
            working_days_in_period=source.days_in_period,
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
    _store_inpatient_room_indicators(
        source=source,
        verification=source.verification,
        rooms=payload.get("ruangan", []),
        days=(end - start).days + 1,
    )
    return source


def _room_value(row, *names, default=0):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _store_inpatient_room_indicators(*, source, verification, rooms, days):
    if not isinstance(rooms, list):
        raise ValueError("Data indikator per ruang harus berupa array.")
    for index, row in enumerate(rooms):
        code = str(_room_value(row, "kode_ruang", "kd_bangsal", "code", default="")).strip()
        name = str(_room_value(row, "nama_ruang", "bangsal", "name", default="")).strip()
        if not code or not name:
            raise ValueError(f"ruangan[{index}] wajib memiliki kode dan nama ruang.")
        basics = {
            "beds": int(_room_value(row, "jumlah_bed", "bed")),
            "care_days": int(_room_value(row, "hari_perawatan", "hp")),
            "discharged": int(_room_value(row, "pasien_keluar", "d")),
            "deaths": int(_room_value(row, "pasien_mati", "mati")),
            "deaths_over_48h": int(_room_value(row, "pasien_mati_48", "mati_48")),
            "days": days,
        }
        calculated = calculate_inpatient_indicators(**basics)
        is_special = any(
            re.search(rf"(^|[^A-Z0-9]){re.escape(keyword)}([^A-Z0-9]|$)", name.upper())
            for keyword in settings.INPATIENT_TOTAL_EXCLUDED_ROOM_KEYWORDS
        )
        source_room, _ = InpatientRoomIndicatorSource.objects.update_or_create(
            source=source, room_code=code,
            defaults={
                "room_name": name, "is_special": is_special,
                "beds": basics["beds"], "care_days": basics["care_days"],
                "discharged_patients": basics["discharged"], "deaths": basics["deaths"],
                "deaths_over_48h": basics["deaths_over_48h"],
                **{key: Decimal(str(_room_value(row, key, default=calculated[key]))) for key in calculated},
            },
        )
        VerifiedInpatientRoomIndicator.objects.update_or_create(
            verification=verification, source_room=source_room,
            defaults=calculated,
        )


def calculate_inpatient_indicators(
    *, beds, care_days, discharged, deaths, deaths_over_48h, days
):
    """Rumus Barber Johnson berdasarkan data dasar JSON, independen dari nilai SIMRS."""
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
    rooms_url, rooms_timeout = resolve_simrs_endpoint(
        SimrsApiEndpoint.Code.INPATIENT_ROOMS,
        settings.SIMRS_INPATIENT_ROOMS_API_URL,
    )
    separator = "&" if "?" in rooms_url else "?"
    rooms_request_url = rooms_url + separator + urlencode(
        {"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()}
    )
    with urlopen(Request(rooms_request_url, headers=headers), timeout=rooms_timeout) as response:
        rooms_payload = json.load(response)
    rooms = rooms_payload.get("data", rooms_payload.get("results", rooms_payload.get("ruangan")))
    if not isinstance(rooms, list):
        raise ValueError("Endpoint indikator per ruang harus mengembalikan data berupa array.")
    payload["ruangan"] = rooms
    return store_inpatient_indicator(period_start=start, period_end=end, period_type=period_type, payload=payload, user=user)


def resolve_region(origin_code, origin_name):
    code = normalize_region_code(origin_code)
    name = str(origin_name or "").strip()
    if code:
        region = AdministrativeRegion.objects.filter(official_code=code, is_active=True).first()
        if region:
            return region, "official_code"
    normalized = normalize_region_name(name)
    exact_matches = list(AdministrativeRegion.objects.filter(
        normalized_name=normalized, is_active=True,
        region_type__in=("province", "regency", "city", "district"),
    )[:2])
    if len(exact_matches) == 1:
        return exact_matches[0], "exact_name"
    alias = RegionAlias.objects.select_related("region").filter(
        normalized_alias=normalized, is_active=True, region__is_active=True
    ).first()
    return (alias.region, "alias") if alias else (None, "unresolved")


def reprocess_region_mappings(normalized_alias=None):
    rows = VerifiedTouristVisitRow.objects.filter(region__isnull=True)
    for row in rows:
        if normalized_alias and normalize_region_name(row.origin_raw or row.origin) != normalized_alias:
            continue
        region, method = resolve_region(row.origin_code, row.origin_raw or row.origin)
        if region:
            row.region, row.cleaning_method = region, method
            row.save(update_fields=("region", "cleaning_method"))


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
    tourist_rows = []
    for row in data.get("tourist_visits", []):
        origin = row.get("origin", "")
        origin_code = normalize_region_code(row.get("origin_code", ""))
        region, method = resolve_region(origin_code, origin)
        tourist_rows.append(VerifiedTouristVisitRow(
            verification=record, category=row["category"], origin=origin,
            origin_raw=origin, origin_code=origin_code, region=region,
            cleaning_method=method, count=row["count"],
        ))
    VerifiedTouristVisitRow.objects.bulk_create(tourist_rows)
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
    verified = source.verification
    existing_codes = set(
        verified.indicator_verifications.values_list("indicator_code", flat=True)
    )
    HealthIndicatorVerification.objects.bulk_create([
        HealthIndicatorVerification(record=verified, indicator_code=code)
        for code in HEALTH_VERIFICATION_GROUPS
        if code not in existing_codes
    ])
    return source


def fetch_monthly_health_indicators(*, period=None, period_start=None, period_end=None, period_type="month", user=None):
    start = period_start or period
    if start is None:
        raise ValueError("Tanggal awal periode wajib tersedia.")
    end = period_end or date(start.year, start.month, monthrange(start.year, start.month)[1])
    token = get_simrs_access_token()
    endpoint_map = (
        (SimrsApiEndpoint.Code.VISITS, "visits"),
        (SimrsApiEndpoint.Code.TOP_DISEASES, "top_diseases"),
        (SimrsApiEndpoint.Code.TOURIST_VISITS, "tourist_visits"),
        (SimrsApiEndpoint.Code.DISEASE_GROUPS, "disease_groups"),
    )
    payload = {"hospital": None}
    hospital_code = None
    for endpoint_code, payload_key in endpoint_map:
        endpoint_url, timeout = resolve_simrs_endpoint(endpoint_code)
        separator = "&" if "?" in endpoint_url else "?"
        url = endpoint_url + separator + urlencode(
            {"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()}
        )
        request = Request(url, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        })
        with urlopen(request, timeout=timeout) as response:
            endpoint_payload = json.load(response)
        hospital = endpoint_payload.get("hospital")
        if not isinstance(hospital, dict) or not hospital.get("code") or not hospital.get("name"):
            raise ValueError(f"Endpoint {endpoint_code} tidak memiliki hospital.code dan hospital.name.")
        if hospital_code is not None and str(hospital["code"]) != hospital_code:
            raise ValueError(f"Endpoint {endpoint_code} mengembalikan rumah sakit yang berbeda.")
        hospital_code = str(hospital["code"])
        payload["hospital"] = hospital
        results = endpoint_payload.get("results")
        if not isinstance(results, list):
            raise ValueError(f"Endpoint {endpoint_code} harus memiliki results berupa array.")
        payload[payload_key] = results
    return store_monthly_health_indicators(period_start=start, period_end=end, period_type=period_type, payload=payload, user=user)


@transaction.atomic
def save_monthly_health_verification(*, record, indicator_verification, data, notes, user, approve):
    normalized = normalize_health_payload(data)
    before = record.verified_data
    record.verified_data = normalized
    replace_health_indicator_rows(record, normalized)
    indicator_verification.notes = notes
    indicator_verification.verified_by = user
    if approve:
        indicator_verification.status = HealthIndicatorVerification.Status.APPROVED
        indicator_verification.verified_at = timezone.now()
    else:
        indicator_verification.status = HealthIndicatorVerification.Status.DRAFT
        indicator_verification.verified_at = None
    indicator_verification.save()
    record.save()
    # Kolom lama dipertahankan sebagai ringkasan kompatibilitas selama migrasi.
    all_approved = not record.indicator_verifications.exclude(
        status=HealthIndicatorVerification.Status.APPROVED
    ).exists()
    record.status = (
        VerifiedMonthlyHealthIndicator.Status.APPROVED
        if all_approved else VerifiedMonthlyHealthIndicator.Status.DRAFT
    )
    record.verified_at = timezone.now() if all_approved else None
    record.verified_by = user
    record.notes = "Seluruh indikator terverifikasi." if all_approved else ""
    record.save()
    MonthlyHealthIndicatorAudit.objects.create(
        record=record,
        action=f"{'approved' if approve else 'updated'}:{indicator_verification.indicator_code}",
        before_data=before,
        after_data=normalized,
        actor=user,
    )
    return record


@transaction.atomic
def save_inpatient_working_data_correction(*, record, cleaned_data, user):
    fields = (
        "beds", "care_days", "discharged_patients", "deaths",
        "deaths_over_48h", "days_in_period",
    )
    before = {field: getattr(record, f"working_{field}") for field in fields}
    after = {field: cleaned_data[field] for field in fields}
    if before == after:
        return False
    calculated = calculate_inpatient_indicators(
        beds=after["beds"], care_days=after["care_days"],
        discharged=after["discharged_patients"], deaths=after["deaths"],
        deaths_over_48h=after["deaths_over_48h"], days=after["days_in_period"],
    )
    for field, value in after.items():
        setattr(record, f"working_{field}", value)
    for indicator, value in calculated.items():
        setattr(record, indicator, value)
    record.notes = cleaned_data["reason"]
    record.status = VerifiedInpatientIndicator.Status.DRAFT
    record.verified_at = None
    record.verified_by = user
    record.save()
    InpatientIndicatorAudit.objects.create(
        record=record,
        action="corrected_working_data",
        before_data=before,
        after_data={**after, "calculated": {key: str(value) for key, value in calculated.items()}},
        actor=user,
    )
    return True
