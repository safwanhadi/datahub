from django.db import migrations


PRODUCTS = {
    "outpatient-visits": "Kunjungan Rawat Jalan",
    "inpatient-visits": "Kunjungan Rawat Inap",
    "emergency-visits": "Kunjungan IGD",
    "top-diseases": "10 Penyakit Terbanyak",
    "patient-satisfaction": "Kepuasan Pasien/Simaskot",
    "tourist-visits": "Kunjungan Wisatawan",
    "cancer-patients": "Pasien Kanker",
    "heart-patients": "Pasien Jantung",
    "stroke-patients": "Pasien Stroke",
    "uronephrology-patients": "Pasien Uronefrologi",
}


def create_products(apps, schema_editor):
    ApiProduct = apps.get_model("api_access", "ApiProduct")
    for code, name in PRODUCTS.items():
        ApiProduct.objects.update_or_create(
            code=f"health-{code}",
            defaults={"name": name, "description": f"Membaca {name} yang telah diverifikasi.", "required_scope": "read:dash", "is_active": True},
        )


def remove_products(apps, schema_editor):
    apps.get_model("api_access", "ApiProduct").objects.filter(code__in=[f"health-{code}" for code in PRODUCTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("api_access", "0003_update_external_scope_to_read_dash")]
    operations = [migrations.RunPython(create_products, remove_products)]
