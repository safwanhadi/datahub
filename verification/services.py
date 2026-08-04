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
    ImportBatch,
    InpatientIndicatorAudit,
    InpatientIndicatorSource,
    StagedRecord,
    VerificationAudit,
    VerifiedInpatientIndicator,
    VerifiedRecord,
)
from .oauth import get_simrs_access_token


@transaction.atomic
def import_records(*, source, reference, record_type, rows, user=None):
    batch = ImportBatch.objects.create(
        source=source, reference=reference, imported_by=user
    )
    records = [
        StagedRecord(
            batch=batch,
            source_key=str(row["source_key"]),
            record_type=record_type,
            raw_data=row,
        )
        for row in rows
    ]
    # save() menghitung checksum; bulk_create tidak memanggil save().
    for record in records:
        record.save()
    batch.status = ImportBatch.Status.COMPLETED
    batch.total_records = len(records)
    batch.completed_at = timezone.now()
    batch.save(update_fields=("status", "total_records", "completed_at"))
    return batch


@transaction.atomic
def begin_verification(staged, user):
    verified, created = VerifiedRecord.objects.get_or_create(
        staged_record=staged,
        defaults={"verified_data": staged.raw_data, "verified_by": user},
    )
    if created:
        staged.status = StagedRecord.Status.IN_REVIEW
        staged.save(update_fields=("status",))
        VerificationAudit.objects.create(
            record=verified,
            action="copied_from_staging",
            after_data=verified.verified_data,
            actor=user,
        )
    return verified


@transaction.atomic
def save_verification(*, verified, data, notes, user, approve=False):
    before = verified.verified_data
    verified.verified_data = data
    verified.verification_notes = notes
    verified.verified_by = user
    action = "updated"
    if approve:
        verified.status = VerifiedRecord.Status.APPROVED
        verified.approved_at = timezone.now()
        verified.staged_record.status = StagedRecord.Status.VERIFIED
        verified.staged_record.save(update_fields=("status",))
        action = "approved"
    verified.save()
    VerificationAudit.objects.create(
        record=verified,
        action=action,
        before_data=before,
        after_data=data,
        notes=notes,
        actor=user,
    )
    return verified


@transaction.atomic
def store_inpatient_indicator(*, period, payload, user=None):
    basic = payload["data_dasar"]
    source_indicator = payload["indikator"]
    calculated = calculate_inpatient_indicators(
        beds=basic["jumlah_bed"],
        care_days=basic["hari_perawatan"],
        discharged=basic["pasien_keluar"],
        deaths=basic["pasien_mati"],
        deaths_over_48h=basic["pasien_mati_48"],
        days=payload.get("periode", {}).get(
            "hari", monthrange(period.year, period.month)[1]
        ),
    )
    start = date(period.year, period.month, 1)
    end = date(period.year, period.month, monthrange(period.year, period.month)[1])
    source, _ = InpatientIndicatorSource.objects.update_or_create(
        period=start,
        defaults={
            "period_start": start,
            "period_end": end,
            "days_in_period": payload.get("periode", {}).get("hari", end.day),
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


def fetch_inpatient_indicator(*, period, user=None):
    if not settings.SIMRS_INDICATOR_API_URL:
        raise ImproperlyConfigured("SIMRS_INDICATOR_API_URL belum dikonfigurasi.")
    start = date(period.year, period.month, 1)
    end = date(period.year, period.month, monthrange(period.year, period.month)[1])
    separator = "&" if "?" in settings.SIMRS_INDICATOR_API_URL else "?"
    url = settings.SIMRS_INDICATOR_API_URL + separator + urlencode(
        {"tgl_awal": start.isoformat(), "tgl_akhir": end.isoformat()}
    )
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {get_simrs_access_token()}",
    }
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        payload = json.load(response)
    return store_inpatient_indicator(period=period, payload=payload, user=user)


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
