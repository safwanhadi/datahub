from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("verification", "0019_region_master_and_cleaning")]
    operations = [
        migrations.AlterField(
            model_name="administrativeregion",
            name="region_type",
            field=models.CharField(
                choices=[
                    ("country", "Negara"), ("province", "Provinsi"),
                    ("regency", "Kabupaten"), ("city", "Kota"),
                    ("district", "Kecamatan"), ("village", "Desa/Kelurahan"),
                    ("other", "Lainnya"),
                ],
                max_length=20,
                verbose_name="jenis wilayah",
            ),
        ),
    ]
