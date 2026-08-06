from django.db import migrations


ENDPOINTS = (
    ("inpatient-indicators", "Indikator Rawat Inap", "http://dash.rsmandalika.com/kominfo/api/get_rawat_api.php"),
)


def seed_endpoints(apps, schema_editor):
    Endpoint = apps.get_model("verification", "SimrsApiEndpoint")
    for code, name, url in ENDPOINTS:
        Endpoint.objects.get_or_create(
            code=code,
            defaults={"name": name, "url": url, "is_active": True, "timeout_seconds": 30},
        )


def remove_seeded_endpoints(apps, schema_editor):
    apps.get_model("verification", "SimrsApiEndpoint").objects.filter(
        code__in=[code for code, _, _ in ENDPOINTS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("verification", "0012_dynamic_simrs_endpoints")]
    operations = [migrations.RunPython(seed_endpoints, remove_seeded_endpoints)]
