from django.db import migrations


REGION_MODELS = ("administrativeregion", "regionalias")
REGION_ACTIONS = ("view", "add", "change")


def assign_region_mapping_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permissions = Permission.objects.filter(
        content_type__app_label="verification",
        content_type__model__in=REGION_MODELS,
        codename__in=(
            f"{action}_{model}"
            for model in REGION_MODELS
            for action in REGION_ACTIONS
        ),
    )
    verifier, _ = Group.objects.get_or_create(name="Verifikator")
    verifier.permissions.add(*permissions)


def remove_region_mapping_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permissions = Permission.objects.filter(
        content_type__app_label="verification",
        content_type__model__in=REGION_MODELS,
        codename__in=(
            f"{action}_{model}"
            for model in REGION_MODELS
            for action in REGION_ACTIONS
        ),
    )
    verifier = Group.objects.filter(name="Verifikator").first()
    if verifier:
        verifier.permissions.remove(*permissions)


class Migration(migrations.Migration):
    dependencies = [("verification", "0026_alter_inpatientindicatorsource_calculated_alos_and_more")]
    operations = [
        migrations.RunPython(
            assign_region_mapping_permissions,
            remove_region_mapping_permissions,
        )
    ]
