from django.conf import settings
from django.db import models


class AccountProfile(models.Model):
    """Data tambahan untuk akun Django yang terhubung dengan SIMADU."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_profile",
        verbose_name="pengguna",
    )
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
