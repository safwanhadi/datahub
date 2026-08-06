from django.db import migrations


ROLE_PERMISSIONS = {
    "Pembaca": (),
    "Petugas Data": (
        "add_importbatch",
        "add_inpatientindicatorsource",
        "add_monthlyhealthindicatorsource",
    ),
    "Verifikator": (
        "change_verifiedrecord",
        "approve_verifiedrecord",
        "change_verifiedinpatientindicator",
        "approve_verifiedinpatientindicator",
        "change_verifiedmonthlyhealthindicator",
        "approve_verifiedmonthlyhealthindicator",
    ),
}

PERMISSION_MODELS = {
    "add_importbatch": "importbatch",
    "add_inpatientindicatorsource": "inpatientindicatorsource",
    "add_monthlyhealthindicatorsource": "monthlyhealthindicatorsource",
    "change_verifiedrecord": "verifiedrecord",
    "approve_verifiedrecord": "verifiedrecord",
    "change_verifiedinpatientindicator": "verifiedinpatientindicator",
    "approve_verifiedinpatientindicator": "verifiedinpatientindicator",
    "change_verifiedmonthlyhealthindicator": "verifiedmonthlyhealthindicator",
    "approve_verifiedmonthlyhealthindicator": "verifiedmonthlyhealthindicator",
}


def seed_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    permissions = {}
    for codename, model in PERMISSION_MODELS.items():
        content_type, _ = ContentType.objects.get_or_create(
            app_label="verification", model=model
        )
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": codename.replace("_", " ").capitalize()},
        )
        permissions[codename] = permission

    for role, codenames in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=role)
        group.permissions.set(permissions[codename] for codename in codenames)

    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    administrator.permissions.set(permissions.values())


def remove_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(
        name__in=(*ROLE_PERMISSIONS.keys(), "Administrator DataHub")
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("verification", "0006_user_role_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_roles),
    ]
