from django.db import migrations


INDICATORS = {
    "alos": "Average Length of Stay",
    "bor": "Bed Occupancy Rate",
    "bto": "Bed Turn Over",
    "toi": "Turn Over Interval",
    "gdr": "Gross Death Rate",
    "ndr": "Net Death Rate",
}


def create_indicator_products(apps, schema_editor):
    ApiProduct = apps.get_model("api_access", "ApiProduct")
    for indicator, name in INDICATORS.items():
        ApiProduct.objects.update_or_create(
            code=f"indicator-{indicator}",
            defaults={
                "name": name,
                "description": f"Membaca indikator {indicator.upper()} yang telah diverifikasi.",
                "required_scope": "datahub.indicators.read",
                "is_active": True,
            },
        )


def remove_indicator_products(apps, schema_editor):
    ApiProduct = apps.get_model("api_access", "ApiProduct")
    ApiProduct.objects.filter(
        code__in=[f"indicator-{indicator}" for indicator in INDICATORS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("api_access", "0001_initial")]

    operations = [
        migrations.RunPython(create_indicator_products, remove_indicator_products),
    ]
