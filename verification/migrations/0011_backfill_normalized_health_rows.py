from django.db import migrations


def backfill_rows(apps, schema_editor):
    Verified = apps.get_model("verification", "VerifiedMonthlyHealthIndicator")
    Visit = apps.get_model("verification", "VerifiedHealthVisitRow")
    Disease = apps.get_model("verification", "VerifiedTopDiseaseRow")
    Tourist = apps.get_model("verification", "VerifiedTouristVisitRow")
    Group = apps.get_model("verification", "VerifiedDiseaseGroupRow")

    for verification in Verified.objects.all().iterator():
        data = verification.verified_data or {}
        Visit.objects.bulk_create([
            Visit(verification=verification, installation=row["installation"], payment_status=row["payment_status"], count=row.get("count", 0))
            for row in data.get("visits", [])
        ], ignore_conflicts=True)

        ranks = {}
        diseases = []
        for row in data.get("top_diseases", []):
            installation = row["installation"]
            ranks[installation] = ranks.get(installation, 0) + 1
            diseases.append(Disease(
                verification=verification,
                installation=installation,
                rank=ranks[installation],
                icd10_code=row["icd10_code"],
                name=row["name"],
                patient_count=row.get("patient_count", 0),
            ))
        Disease.objects.bulk_create(diseases, ignore_conflicts=True)

        Tourist.objects.bulk_create([
            Tourist(verification=verification, category=row["category"], origin=row.get("origin", ""), count=row.get("count", 0))
            for row in data.get("tourist_visits", [])
        ], ignore_conflicts=True)
        Group.objects.bulk_create([
            Group(verification=verification, code=row["code"], icd10_range=row.get("icd10_range", ""), patient_count=row.get("patient_count", 0))
            for row in data.get("disease_groups", [])
        ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("verification", "0010_normalized_health_rows")]
    operations = [migrations.RunPython(backfill_rows, migrations.RunPython.noop)]
