import hashlib
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class DataSource(models.Model):
    name = models.CharField("nama sumber", max_length=120, unique=True)
    code = models.SlugField("kode", max_length=60, unique=True)
    description = models.TextField("keterangan", blank=True)
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "sumber data"
        verbose_name_plural = "sumber data"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Diproses"
        COMPLETED = "completed", "Selesai"
        FAILED = "failed", "Gagal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="batches")
    reference = models.CharField("referensi", max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.PROCESSING)
    total_records = models.PositiveIntegerField(default=0)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.reference or str(self.id)


class StagedRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Menunggu"
        IN_REVIEW = "in_review", "Sedang diperiksa"
        VERIFIED = "verified", "Terverifikasi"
        REJECTED = "rejected", "Ditolak"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="records")
    source_key = models.CharField("kunci data SIMRS", max_length=190)
    record_type = models.CharField("jenis data", max_length=80, db_index=True)
    raw_data = models.JSONField("data asli")
    source_updated_at = models.DateTimeField(null=True, blank=True)
    checksum = models.CharField(max_length=64, editable=False)
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-imported_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "source_key"), name="unique_source_key_per_batch"
            )
        ]
        indexes = [models.Index(fields=("record_type", "status"))]

    def clean(self):
        if not isinstance(self.raw_data, dict):
            raise ValidationError({"raw_data": "Data harus berupa objek JSON."})

    def save(self, *args, **kwargs):
        import json

        normalized = json.dumps(self.raw_data, sort_keys=True, separators=(",", ":"))
        self.checksum = hashlib.sha256(normalized.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.record_type}: {self.source_key}"


class VerifiedRecord(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draf"
        APPROVED = "approved", "Disetujui"
        PUBLISHED = "published", "Dipublikasikan"
        REJECTED = "rejected", "Ditolak"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staged_record = models.OneToOneField(
        StagedRecord, on_delete=models.PROTECT, related_name="verified_record"
    )
    verified_data = models.JSONField("data hasil verifikasi")
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT, db_index=True)
    verification_notes = models.TextField("catatan verifikasi", blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if not isinstance(self.verified_data, dict):
            raise ValidationError({"verified_data": "Data harus berupa objek JSON."})

    def __str__(self):
        return f"Verifikasi {self.staged_record}"


class VerificationAudit(models.Model):
    record = models.ForeignKey(VerifiedRecord, on_delete=models.CASCADE, related_name="audits")
    action = models.CharField(max_length=40)
    before_data = models.JSONField(null=True, blank=True)
    after_data = models.JSONField(null=True, blank=True)
    notes = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ExternalApiToken(models.Model):
    name = models.CharField("nama aplikasi", max_length=120)
    prefix = models.CharField(max_length=12, unique=True, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "token API eksternal"
        verbose_name_plural = "token API eksternal"

    @classmethod
    def issue(cls, *, name, created_by=None, expires_at=None):
        raw = f"simrs_{secrets.token_urlsafe(32)}"
        instance = cls.objects.create(
            name=name,
            prefix=raw[:12],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            created_by=created_by,
            expires_at=expires_at,
        )
        return instance, raw

    @classmethod
    def authenticate(cls, raw):
        return cls.objects.filter(
            key_hash=hashlib.sha256(raw.encode()).hexdigest(), is_active=True
        ).first()

    def __str__(self):
        return f"{self.name} ({self.prefix}...)"


class InpatientIndicatorSource(models.Model):
    """Snapshot JSON PHP dan perhitungan ulang Django; tidak diedit verifikator."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.DateField("periode", unique=True, help_text="Tanggal pertama bulan laporan")
    period_start = models.DateField("tanggal awal")
    period_end = models.DateField("tanggal akhir")
    days_in_period = models.PositiveSmallIntegerField("jumlah hari")
    beds = models.PositiveIntegerField("tempat tidur")
    care_days = models.PositiveIntegerField("hari perawatan")
    discharged_patients = models.PositiveIntegerField("pasien keluar")
    deaths = models.PositiveIntegerField("pasien meninggal")
    deaths_over_48h = models.PositiveIntegerField("meninggal > 48 jam")
    alos = models.DecimalField(max_digits=10, decimal_places=2)
    bor = models.DecimalField(max_digits=10, decimal_places=2)
    bto = models.DecimalField(max_digits=10, decimal_places=2)
    toi = models.DecimalField(max_digits=10, decimal_places=2)
    gdr = models.DecimalField(max_digits=10, decimal_places=2)
    ndr = models.DecimalField(max_digits=10, decimal_places=2)
    calculated_alos = models.DecimalField("ALOS hitung Django", max_digits=10, decimal_places=2, default=0)
    calculated_bor = models.DecimalField("BOR hitung Django", max_digits=10, decimal_places=2, default=0)
    calculated_bto = models.DecimalField("BTO hitung Django", max_digits=10, decimal_places=2, default=0)
    calculated_toi = models.DecimalField("TOI hitung Django", max_digits=10, decimal_places=2, default=0)
    calculated_gdr = models.DecimalField("GDR hitung Django", max_digits=10, decimal_places=2, default=0)
    calculated_ndr = models.DecimalField("NDR hitung Django", max_digits=10, decimal_places=2, default=0)
    raw_response = models.JSONField("respons asli PHP")
    fetched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-period",)
        verbose_name = "data asli indikator rawat inap"

    def __str__(self):
        return self.period.strftime("%B %Y")


class VerifiedInpatientIndicator(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Sedang diperiksa"
        APPROVED = "approved", "Terverifikasi"

    source = models.OneToOneField(
        InpatientIndicatorSource, on_delete=models.PROTECT, related_name="verification"
    )
    period = models.DateField("periode")
    alos = models.DecimalField("ALOS (hari)", max_digits=10, decimal_places=2)
    bor = models.DecimalField("BOR (%)", max_digits=10, decimal_places=2)
    bto = models.DecimalField("BTO (kali)", max_digits=10, decimal_places=2)
    toi = models.DecimalField("TOI (hari)", max_digits=10, decimal_places=2)
    gdr = models.DecimalField("GDR (per 1.000)", max_digits=10, decimal_places=2)
    ndr = models.DecimalField("NDR (per 1.000)", max_digits=10, decimal_places=2)
    notes = models.TextField("catatan", blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-period",)
        verbose_name = "hasil verifikasi indikator rawat inap"

    def __str__(self):
        return f"Indikator {self.period:%B %Y}"


class InpatientIndicatorAudit(models.Model):
    record = models.ForeignKey(
        VerifiedInpatientIndicator, on_delete=models.CASCADE, related_name="audits"
    )
    action = models.CharField(max_length=30)
    before_data = models.JSONField(null=True)
    after_data = models.JSONField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
