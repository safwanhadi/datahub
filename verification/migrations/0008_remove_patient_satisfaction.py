from django.db import migrations


def remove_patient_satisfaction(apps, schema_editor):
    Source = apps.get_model("verification", "MonthlyHealthIndicatorSource")
    Verified = apps.get_model("verification", "VerifiedMonthlyHealthIndicator")
    ApiProduct = apps.get_model("api_access", "ApiProduct")

    for source in Source.objects.all().iterator():
        changed = []
        for field in ("source_data", "raw_response"):
            payload = dict(getattr(source, field) or {})
            if payload.pop("patient_satisfaction", None) is not None:
                setattr(source, field, payload)
                changed.append(field)
        if changed:
            source.save(update_fields=changed)

    for record in Verified.objects.all().iterator():
        payload = dict(record.verified_data or {})
        if payload.pop("patient_satisfaction", None) is not None:
            record.verified_data = payload
            record.save(update_fields=("verified_data",))

    # Grant terkait ikut terhapus melalui relasi CASCADE.
    ApiProduct.objects.filter(code="health-patient-satisfaction").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("api_access", "0004_health_indicator_products"),
        ("verification", "0007_seed_user_roles"),
    ]

    operations = [
        migrations.RunPython(remove_patient_satisfaction, migrations.RunPython.noop),
    ]
