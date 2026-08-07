from django.db import migrations


PERMISSIONS = (
    ("api_access", "apiproduct", "change_apiproduct", "Can change API product"),
    ("api_access", "externalapiclient", "add_externalapiclient", "Can add external API client"),
    ("api_access", "externalapiclient", "change_externalapiclient", "Can change external API client"),
    ("api_access", "externalapigrant", "add_externalapigrant", "Can add external API grant"),
    ("api_access", "externalapigrant", "change_externalapigrant", "Can change external API grant"),
    ("api_access", "externalapigrant", "delete_externalapigrant", "Can delete external API grant"),
    ("auth", "user", "add_user", "Can add user"),
    ("auth", "user", "change_user", "Can change user"),
)


def grant_ui_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    permissions = []
    for app_label, model, codename, name in PERMISSIONS:
        content_type, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={"name": name}
        )
        permissions.append(permission)
    administrator.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("api_access", "0004_health_indicator_products"),
        ("verification", "0015_remove_importbatch_source_and_more"),
    ]

    operations = [migrations.RunPython(grant_ui_permissions, migrations.RunPython.noop)]
