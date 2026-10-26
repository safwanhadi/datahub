from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("verification", "0028_remove_verifiedtouristvisitrow_unique_verified_tourist_visit_row"),
    ]

    operations = [
        migrations.AddField(
            model_name="verifiedtouristvisitrow",
            name="installation",
            field=models.CharField(
                "instalasi", max_length=20, default="other",
                choices=[("outpatient", "Rawat jalan"), ("inpatient", "Rawat inap"), ("emergency", "IGD"), ("other", "Lainnya")],
            ),
        ),
    ]
