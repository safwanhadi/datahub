import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def approve_existing_profiles(apps, schema_editor):
    AccountProfile = apps.get_model("myaccount", "AccountProfile")
    AccountProfile.objects.update(access_status="approved")


class Migration(migrations.Migration):
    dependencies = [
        ("myaccount", "0002_simadu_official_access"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="accountprofile", name="access_status", field=models.CharField(choices=[("pending", "Menunggu persetujuan"), ("approved", "Disetujui"), ("rejected", "Ditolak"), ("suspended", "Ditangguhkan")], default="pending", max_length=16, verbose_name="status akses")),
        migrations.AddField(model_name="accountprofile", name="access_notes", field=models.TextField(blank=True, verbose_name="catatan akses")),
        migrations.AddField(model_name="accountprofile", name="last_sso_attempt_at", field=models.DateTimeField(blank=True, null=True, verbose_name="percobaan SSO terakhir")),
        migrations.AddField(model_name="accountprofile", name="requested_at", field=models.DateTimeField(auto_now_add=True, null=True, verbose_name="diminta pada")),
        migrations.AddField(model_name="accountprofile", name="reviewed_at", field=models.DateTimeField(blank=True, null=True, verbose_name="ditinjau pada")),
        migrations.AddField(model_name="accountprofile", name="reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_account_profiles", to=settings.AUTH_USER_MODEL, verbose_name="ditinjau oleh")),
        migrations.RunPython(approve_existing_profiles, migrations.RunPython.noop),
        migrations.AlterField(model_name="accountprofile", name="requested_at", field=models.DateTimeField(auto_now_add=True, verbose_name="diminta pada")),
    ]
