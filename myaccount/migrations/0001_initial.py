# Generated manually for the initial myaccount application.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "simadu_subject",
                    models.CharField(
                        blank=True,
                        help_text="ID permanen pengguna dari endpoint profil SIMADU.",
                        max_length=255,
                        null=True,
                        unique=True,
                        verbose_name="ID pengguna SIMADU",
                    ),
                ),
                (
                    "sso_linked_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="terhubung ke SSO pada",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="dibuat pada")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="diperbarui pada")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="pengguna",
                    ),
                ),
            ],
            options={
                "verbose_name": "profil akun",
                "verbose_name_plural": "profil akun",
            },
        ),
    ]
