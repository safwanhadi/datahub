import datetime

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


DEFAULTS = (
    ("alos", 6, 9, False, "hari", "reporting"),
    ("bor", 60, 85, False, "%", "reporting"),
    ("bto", 40, 50, False, "kali", "annual"),
    ("toi", 1, 3, False, "hari", "reporting"),
    ("gdr", None, 45, False, "per 1.000", "reporting"),
    ("ndr", None, 25, True, "per 1.000", "reporting"),
)


def seed_standards_and_permissions(apps, schema_editor):
    Standard = apps.get_model("verification", "InpatientIndicatorStandard")
    for indicator, minimum, maximum, exclusive, unit, basis in DEFAULTS:
        Standard.objects.get_or_create(
            indicator=indicator,
            policy_level="national",
            effective_from=datetime.date(2005, 1, 1),
            defaults={
                "minimum_value": minimum,
                "maximum_value": maximum,
                "maximum_exclusive": exclusive,
                "unit": unit,
                "period_basis": basis,
                "reference_name": "Petunjuk Teknis Kementerian Kesehatan",
                "reference_url": "https://www.kemkes.go.id/app_asset/file_content_download/172247989066aaf512936579.51341712.pdf",
                "is_active": True,
            },
        )

    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.get_or_create(
        app_label="verification", model="inpatientindicatorstandard"
    )
    permissions = []
    for action in ("add", "change", "view"):
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=f"{action}_inpatientindicatorstandard",
            defaults={"name": f"Can {action} inpatient indicator standard"},
        )
        permissions.append(permission)
    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    administrator.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("verification", "0015_remove_importbatch_source_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="InpatientIndicatorStandard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("indicator", models.CharField(choices=[("alos", "ALOS"), ("bor", "BOR"), ("bto", "BTO"), ("toi", "TOI"), ("gdr", "GDR"), ("ndr", "NDR")], max_length=10, verbose_name="indikator")),
                ("policy_level", models.CharField(choices=[("national", "Kebijakan nasional"), ("internal", "Kebijakan internal")], max_length=10, verbose_name="tingkat kebijakan")),
                ("minimum_value", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="batas bawah")),
                ("maximum_value", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="batas atas")),
                ("maximum_exclusive", models.BooleanField(default=False, verbose_name="batas atas harus kurang dari")),
                ("unit", models.CharField(max_length=40, verbose_name="satuan")),
                ("period_basis", models.CharField(choices=[("reporting", "Sesuai periode laporan"), ("annual", "Tahunan (annualisasi)")], default="reporting", max_length=12, verbose_name="dasar periode")),
                ("effective_from", models.DateField(default=django.utils.timezone.localdate, verbose_name="berlaku mulai")),
                ("effective_until", models.DateField(blank=True, null=True, verbose_name="berlaku sampai")),
                ("reference_name", models.CharField(max_length=255, verbose_name="nama kebijakan/acuan")),
                ("reference_url", models.URLField(blank=True, max_length=500, verbose_name="tautan acuan")),
                ("notes", models.TextField(blank=True, verbose_name="catatan")),
                ("is_active", models.BooleanField(default=True, verbose_name="aktif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_indicator_standards", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "standar indikator rawat inap",
                "verbose_name_plural": "standar indikator rawat inap",
                "ordering": ("indicator", "-effective_from", "-policy_level"),
                "constraints": [models.UniqueConstraint(fields=("indicator", "policy_level", "effective_from"), name="unique_indicator_policy_start")],
            },
        ),
        migrations.RunPython(seed_standards_and_permissions, migrations.RunPython.noop),
    ]
