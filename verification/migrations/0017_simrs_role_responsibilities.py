from django.db import migrations


def assign_simrs_responsibilities(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="verification", model="simrsapiendpoint"
    )
    permissions = []
    for action in ("view", "add", "change"):
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=f"{action}_simrsapiendpoint",
            defaults={"name": f"Can {action} endpoint API SIMRS"},
        )
        permissions.append(permission)

    data_officer, _ = Group.objects.get_or_create(name="Petugas Data")
    administrator, _ = Group.objects.get_or_create(name="Administrator DataHub")
    data_officer.permissions.add(*permissions)
    administrator.permissions.add(*permissions)


def remove_simrs_responsibilities(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permissions = Permission.objects.filter(
        content_type__app_label="verification",
        content_type__model="simrsapiendpoint",
        codename__in=("view_simrsapiendpoint", "add_simrsapiendpoint", "change_simrsapiendpoint"),
    )
    group = Group.objects.filter(name="Petugas Data").first()
    if group:
        group.permissions.remove(*permissions)


class Migration(migrations.Migration):
    dependencies = [("verification", "0016_inpatient_indicator_standards")]
    operations = [migrations.RunPython(assign_simrs_responsibilities, remove_simrs_responsibilities)]
