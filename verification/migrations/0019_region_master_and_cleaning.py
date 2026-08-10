import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_and_permissions(apps, schema_editor):
    Tourist = apps.get_model("verification", "VerifiedTouristVisitRow")
    for row in Tourist.objects.all().iterator():
        row.origin_raw = row.origin
        row.save(update_fields=("origin_raw",))

    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    permissions = []
    for model in ("administrativeregion", "regionalias"):
        content_type, _ = ContentType.objects.get_or_create(app_label="verification", model=model)
        for action in ("view", "add", "change"):
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type, codename=f"{action}_{model}",
                defaults={"name": f"Can {action} {model}"},
            )
            permissions.append(permission)
    administrator.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("verification", "0018_remove_health_aggregate_endpoint"),
    ]
    operations = [
        migrations.CreateModel(
            name="AdministrativeRegion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("official_code", models.CharField(max_length=30, unique=True, verbose_name="kode wilayah resmi")),
                ("name", models.CharField(max_length=180, verbose_name="nama wilayah baku")),
                ("normalized_name", models.CharField(db_index=True, editable=False, max_length=180)),
                ("region_type", models.CharField(choices=[("country", "Negara"), ("province", "Provinsi"), ("regency", "Kabupaten"), ("city", "Kota"), ("district", "Kecamatan"), ("other", "Lainnya")], max_length=20, verbose_name="jenis wilayah")),
                ("island_group", models.CharField(blank=True, max_length=120, verbose_name="kelompok pulau/analitik")),
                ("is_active", models.BooleanField(default=True, verbose_name="aktif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="verification.administrativeregion", verbose_name="wilayah induk")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_regions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "master wilayah", "verbose_name_plural": "master wilayah", "ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="RegionAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alias", models.CharField(max_length=180, verbose_name="nama/alias dari sumber")),
                ("normalized_alias", models.CharField(editable=False, max_length=180, unique=True)),
                ("source_system", models.CharField(default="SIMRS", max_length=50, verbose_name="sistem sumber")),
                ("is_active", models.BooleanField(default=True, verbose_name="aktif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("region", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="verification.administrativeregion")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_region_aliases", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "alias wilayah", "verbose_name_plural": "alias wilayah", "ordering": ("alias",)},
        ),
        migrations.AddField(model_name="verifiedtouristvisitrow", name="cleaning_method", field=models.CharField(choices=[("official_code", "Kode resmi"), ("exact_name", "Nama baku"), ("alias", "Alias"), ("unresolved", "Belum dikenali")], default="unresolved", max_length=20)),
        migrations.AddField(model_name="verifiedtouristvisitrow", name="origin_code", field=models.CharField(blank=True, max_length=30, verbose_name="kode wilayah dari SIMRS")),
        migrations.AddField(model_name="verifiedtouristvisitrow", name="origin_raw", field=models.CharField(blank=True, max_length=160, verbose_name="nama wilayah asli")),
        migrations.AddField(model_name="verifiedtouristvisitrow", name="region", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tourist_visit_rows", to="verification.administrativeregion")),
        migrations.RunPython(backfill_and_permissions, migrations.RunPython.noop),
    ]
