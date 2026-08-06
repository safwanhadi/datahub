from django.db import migrations


def add_endpoint_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.get_or_create(
        app_label="verification", model="simrsapiendpoint"
    )
    permissions = []
    for action in ("add", "change", "view", "delete"):
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=f"{action}_simrsapiendpoint",
            defaults={"name": f"Can {action} endpoint API SIMRS"},
        )
        permissions.append(permission)
    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    administrator.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("verification", "0013_seed_simrs_endpoints")]
    operations = [migrations.RunPython(add_endpoint_permissions, migrations.RunPython.noop)]
