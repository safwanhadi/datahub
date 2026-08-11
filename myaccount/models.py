from django.conf import settings
from django.db import models


class AccountProfile(models.Model):
    """Data tambahan untuk akun Django yang terhubung dengan SIMADU."""

    class AccessStatus(models.TextChoices):
        PENDING = "pending", "Menunggu persetujuan"
        APPROVED = "approved", "Disetujui"
        REJECTED = "rejected", "Ditolak"
        SUSPENDED = "suspended", "Ditangguhkan"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_profile",
        verbose_name="pengguna",
    )
    access_status = models.CharField(
        "status akses", max_length=16,
        choices=AccessStatus.choices, default=AccessStatus.PENDING,
    )
    requested_at = models.DateTimeField("diminta pada", auto_now_add=True)
    last_sso_attempt_at = models.DateTimeField("percobaan SSO terakhir", null=True, blank=True)
    reviewed_at = models.DateTimeField("ditinjau pada", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="reviewed_account_profiles", null=True, blank=True,
        verbose_name="ditinjau oleh",
    )
    access_notes = models.TextField("catatan akses", blank=True)
    simadu_subject = models.CharField(
        "ID pengguna SIMADU",
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="ID permanen pengguna dari endpoint profil SIMADU.",
    )
    sso_linked_at = models.DateTimeField(
        "terhubung ke SSO pada",
        null=True,
        blank=True,
    )
    is_simadu_official = models.BooleanField(
        "pejabat SIMADU",
        default=False,
        help_text="Status terakhir dari field pejabat pada endpoint api/me SIMADU.",
    )
    official_status_checked_at = models.DateTimeField(
        "status pejabat diperiksa pada",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diperbarui pada", auto_now=True)

    class Meta:
        verbose_name = "profil akun"
        verbose_name_plural = "profil akun"

    def __str__(self):
        return self.user.get_username()

    @property
    def has_datahub_access(self):
        return self.access_status == self.AccessStatus.APPROVED
