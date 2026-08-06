from django.db import migrations


OLD_SCOPES = ("datahub.indicators.read", "datahub.records.read", "datahub.dash.read")


def update_scope(apps, schema_editor):
    ApiProduct = apps.get_model("api_access", "ApiProduct")
    ApiProduct.objects.filter(required_scope__in=OLD_SCOPES).update(
        required_scope="read:dash"
    )


def reverse_scope(apps, schema_editor):
    ApiProduct = apps.get_model("api_access", "ApiProduct")
    ApiProduct.objects.filter(required_scope="read:dash").update(
        required_scope="datahub.indicators.read"
    )


class Migration(migrations.Migration):
    dependencies = [("api_access", "0002_default_indicator_products")]

    operations = [migrations.RunPython(update_scope, reverse_scope)]
