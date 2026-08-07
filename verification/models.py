import hashlib
import secrets
import uuid
from django.utils import timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SimrsApiEndpoint(models.Model):
    class Code(models.TextChoices):
        INPATIENT_INDICATORS = "inpatient-indicators", "Indikator Rawat Inap"
        HEALTH_AGGREGATE = "health-aggregate", "Indikator Kesehatan (Agregat)"
        VISITS = "visits", "Kunjungan Pasien"
        TOP_DISEASES = "top-diseases", "10 Penyakit Terbanyak"
        TOURIST_VISITS = "tourist-visits", "Kunjungan Wisatawan"
        DISEASE_GROUPS = "disease-groups", "Kelompok Penyakit"

    code = models.CharField("kode endpoint", max_length=40, choices=Code, unique=True)
    name = models.CharField("nama endpoint", max_length=160)
    url = models.URLField("URL API", max_length=500)
    is_active = models.BooleanField("aktif", default=True)
    timeout_seconds = models.PositiveSmallIntegerField("timeout (detik)", default=30)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_simrs_endpoints",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "endpoint API SIMRS"
        verbose_name_plural = "endpoint API SIMRS"

    def __str__(self):
        return f"{self.name} ({self.code})"


class InpatientIndicatorStandard(models.Model):
    class Indicator(models.TextChoices):
        ALOS = "alos", "ALOS"
        BOR = "bor", "BOR"
        BTO = "bto", "BTO"
        TOI = "toi", "TOI"
        GDR = "gdr", "GDR"
        NDR = "ndr", "NDR"

    class PolicyLevel(models.TextChoices):
        NATIONAL = "national", "Kebijakan nasional"
        INTERNAL = "internal", "Kebijakan internal"

    class PeriodBasis(models.TextChoices):
        REPORTING = "reporting", "Sesuai periode laporan"
        ANNUAL = "annual", "Tahunan (annualisasi)"

    indicator = models.CharField("indikator", max_length=10, choices=Indicator)
    policy_level = models.CharField("tingkat kebijakan", max_length=10, choices=PolicyLevel)
    minimum_value = models.DecimalField("batas bawah", max_digits=12, decimal_places=2, null=True, blank=True)
    maximum_value = models.DecimalField("batas atas", max_digits=12, decimal_places=2, null=True, blank=True)
    maximum_exclusive = models.BooleanField("batas atas harus kurang dari", default=False)
    unit = models.CharField("satuan", max_length=40)
    period_basis = models.CharField("dasar periode", max_length=12, choices=PeriodBasis, default=PeriodBasis.REPORTING)
    effective_from = models.DateField("berlaku mulai", default=timezone.localdate)
    effective_until = models.DateField("berlaku sampai", null=True, blank=True)
    reference_name = models.CharField("nama kebijakan/acuan", max_length=255)
    reference_url = models.URLField("tautan acuan", max_length=500, blank=True)
    notes = models.TextField("catatan", blank=True)
    is_active = models.BooleanField("aktif", default=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_indicator_standards")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("indicator", "-effective_from", "-policy_level")
        constraints = [models.UniqueConstraint(fields=("indicator", "policy_level", "effective_from"), name="unique_indicator_policy_start")]
        verbose_name = "standar indikator rawat inap"
        verbose_name_plural = "standar indikator rawat inap"

    def clean(self):
        super().clean()
        if self.minimum_value is None and self.maximum_value is None:
            raise ValidationError("Isi minimal salah satu batas standar.")
        if self.minimum_value is not None and self.maximum_value is not None and self.minimum_value > self.maximum_value:
            raise ValidationError({"maximum_value": "Batas atas harus lebih besar atau sama dengan batas bawah."})
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValidationError({"effective_until": "Tanggal akhir tidak boleh sebelum tanggal mulai."})

    def __str__(self):
        return f"{self.get_indicator_display()} — {self.get_policy_level_display()} ({self.effective_from:%d-%m-%Y})"


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
    period = models.DateField("periode", help_text="Tanggal awal laporan")
    period_type = models.CharField("jenis periode", max_length=12, default="month")
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
        constraints = [models.UniqueConstraint(fields=("period_type", "period_start", "period_end"), name="unique_inpatient_reporting_period")]

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
        permissions = (
            ("approve_verifiedinpatientindicator", "Can approve verified inpatient indicator"),
        )

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


class MonthlyHealthIndicatorSource(models.Model):
    """Snapshot sumber indikator kesehatan sesuai kontrak metadata."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.DateField("periode")
    period_type = models.CharField("jenis periode", max_length=12, default="month")
    period_start = models.DateField("tanggal awal", null=True)
    period_end = models.DateField("tanggal akhir", null=True)
    hospital_code = models.CharField("kode rumah sakit", max_length=40)
    hospital_name = models.CharField("nama rumah sakit", max_length=180)
    source_data = models.JSONField("data sumber ternormalisasi")
    raw_response = models.JSONField("respons asli API")
    fetched_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-period",)
        verbose_name = "data sumber indikator kesehatan bulanan"
        verbose_name_plural = "data sumber indikator kesehatan bulanan"
        constraints = [models.UniqueConstraint(fields=("period_type", "period_start", "period_end"), name="unique_health_reporting_period")]

    def __str__(self):
        return f"Indikator kesehatan {self.period:%B %Y}"


class VerifiedMonthlyHealthIndicator(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Sedang diperiksa"
        APPROVED = "approved", "Terverifikasi"

    source = models.OneToOneField(MonthlyHealthIndicatorSource, on_delete=models.PROTECT, related_name="verification")
    period = models.DateField("periode")
    verified_data = models.JSONField("data hasil verifikasi")
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    notes = models.TextField("catatan", blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-period",)
        verbose_name = "hasil verifikasi indikator kesehatan bulanan"
        verbose_name_plural = "hasil verifikasi indikator kesehatan bulanan"
        permissions = (
            ("approve_verifiedmonthlyhealthindicator", "Can approve verified monthly health indicator"),
        )

    def __str__(self):
        return f"Verifikasi indikator kesehatan {self.period:%B %Y}"

    def to_payload(self):
        """Bangun kontrak API dari tabel row; JSON bukan sumber operasional."""
        if not any((self.visit_rows.exists(), self.top_disease_rows.exists(), self.tourist_visit_rows.exists(), self.disease_group_rows.exists())):
            # Kompatibilitas snapshot lama; migrasi produksi mengisi tabel row.
            return self.verified_data
        return {
            "hospital": {
                "code": self.source.hospital_code,
                "name": self.source.hospital_name,
            },
            "visits": [
                {"installation": row.installation, "payment_status": row.payment_status, "count": row.count}
                for row in self.visit_rows.all()
            ],
            "top_diseases": [
                {"installation": row.installation, "icd10_code": row.icd10_code, "name": row.name, "patient_count": row.patient_count}
                for row in self.top_disease_rows.all()
            ],
            "tourist_visits": [
                {"category": row.category, "origin": row.origin, "count": row.count}
                for row in self.tourist_visit_rows.all()
            ],
            "disease_groups": [
                {"code": row.code, "icd10_range": row.icd10_range, "patient_count": row.patient_count}
                for row in self.disease_group_rows.all()
            ],
        }


class VerifiedHealthVisitRow(models.Model):
    verification = models.ForeignKey(VerifiedMonthlyHealthIndicator, on_delete=models.CASCADE, related_name="visit_rows")
    installation = models.CharField(max_length=20)
    payment_status = models.CharField(max_length=30)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("installation", "payment_status")
        constraints = [models.UniqueConstraint(fields=("verification", "installation", "payment_status"), name="unique_verified_health_visit_row")]


class VerifiedTopDiseaseRow(models.Model):
    verification = models.ForeignKey(VerifiedMonthlyHealthIndicator, on_delete=models.CASCADE, related_name="top_disease_rows")
    installation = models.CharField(max_length=20)
    rank = models.PositiveSmallIntegerField()
    icd10_code = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    patient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("installation", "rank")
        constraints = [models.UniqueConstraint(fields=("verification", "installation", "rank"), name="unique_verified_top_disease_rank")]


class VerifiedTouristVisitRow(models.Model):
    verification = models.ForeignKey(VerifiedMonthlyHealthIndicator, on_delete=models.CASCADE, related_name="tourist_visit_rows")
    category = models.CharField(max_length=20)
    origin = models.CharField(max_length=160)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("category", "origin")
        constraints = [models.UniqueConstraint(fields=("verification", "category", "origin"), name="unique_verified_tourist_visit_row")]


class VerifiedDiseaseGroupRow(models.Model):
    verification = models.ForeignKey(VerifiedMonthlyHealthIndicator, on_delete=models.CASCADE, related_name="disease_group_rows")
    code = models.CharField(max_length=30)
    icd10_range = models.CharField(max_length=80)
    patient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("code",)
        constraints = [models.UniqueConstraint(fields=("verification", "code"), name="unique_verified_disease_group_row")]


class MonthlyHealthIndicatorAudit(models.Model):
    record = models.ForeignKey(VerifiedMonthlyHealthIndicator, on_delete=models.CASCADE, related_name="audits")
    action = models.CharField(max_length=30)
    before_data = models.JSONField(null=True)
    after_data = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
