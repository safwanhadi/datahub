from django.db import migrations, models


def remove_obsolete_aggregate(apps, schema_editor):
    apps.get_model("verification", "SimrsApiEndpoint").objects.filter(
        code="health-aggregate"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("verification", "0017_simrs_role_responsibilities")]
    operations = [
        migrations.AlterField(
            model_name="simrsapiendpoint",
            name="code",
            field=models.CharField(
                choices=[
                    ("inpatient-indicators", "Indikator Rawat Inap"),
                    ("visits", "Kunjungan Pasien"),
                    ("top-diseases", "10 Penyakit Terbanyak"),
                    ("tourist-visits", "Kunjungan Wisatawan"),
                    ("disease-groups", "Kelompok Penyakit"),
                ],
                max_length=40,
                unique=True,
                verbose_name="kode endpoint",
            ),
        ),
        migrations.RunPython(remove_obsolete_aggregate, migrations.RunPython.noop),
    ]
