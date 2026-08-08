from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import AdministrativeRegion, RegionAlias, VerifiedTouristVisitRow
from .services import store_monthly_health_indicators
from .forms import MonthlyHealthVerificationForm


class RegionCleaningTests(TestCase):
    def payload(self, tourist_rows):
        return {
            "hospital": {"code": "RS-M", "name": "RS Mandalika"},
            "visits": [], "top_diseases": [], "disease_groups": [],
            "tourist_visits": tourist_rows,
        }

    def test_lombok_tengah_alias_variations_are_cleaned_but_excluded(self):
        region = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah",
            region_type="regency", island_group="Lombok",
        )
        RegionAlias.objects.create(region=region, alias="LOTENG")
        RegionAlias.objects.create(region=region, alias="LOITENG")
        source = store_monthly_health_indicators(period=date(2026, 10, 1), payload=self.payload([
            {"category": "domestic", "origin": "LOTENG", "count": 4},
            {"category": "domestic", "origin": "LOITENG", "count": 2},
        ]))

        rows = source.verification.tourist_visit_rows.all()
        self.assertTrue(all(row.region_id == region.pk for row in rows))
        self.assertEqual(len(source.verification.to_working_payload()["tourist_visits"]), 2)
        cleaned = source.verification.to_payload()["tourist_visits"]
        self.assertEqual(cleaned, [])

    def test_only_outside_lombok_tengah_is_counted_and_international_is_combined(self):
        lombok = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah",
            region_type="regency", island_group="Lombok",
        )
        bali = AdministrativeRegion.objects.create(
            official_code="51", name="Bali", region_type="province",
        )
        mataram = AdministrativeRegion.objects.create(
            official_code="52.71", name="Kota Mataram", region_type="city",
            island_group="Lombok",
        )
        source = store_monthly_health_indicators(period=date(2026, 10, 15), payload=self.payload([
            {"category": "domestic", "origin_code": lombok.official_code, "origin": "LOTENG", "count": 10},
            {"category": "domestic", "origin_code": bali.official_code, "origin": "Bali", "count": 5},
            {"category": "domestic", "origin_code": mataram.official_code, "origin": "Mataram", "count": 6},
            {"category": "domestic", "origin": "BELUM DIKENALI", "count": 4},
            {"category": "international", "origin": "Australia", "count": 2},
            {"category": "international", "origin": "Malaysia", "count": 3},
        ]))

        cleaned = source.verification.to_payload()["tourist_visits"]
        self.assertEqual(len(cleaned), 3)
        wisnus = [row for row in cleaned if row["category"] == "wisnus"]
        self.assertEqual(sum(row["count"] for row in wisnus), 11)
        self.assertSetEqual({row["origin"] for row in wisnus}, {"Bali", "Kota Mataram"})
        international = next(row for row in cleaned if row["category"] == "wisman")
        self.assertEqual(international["category_label"], "Wisatawan Mancanegara")
        self.assertEqual(international["origin"], "Luar Indonesia")
        self.assertEqual(international["count"], 5)

    def test_integer_official_code_maps_to_dotted_master_code(self):
        region = AdministrativeRegion.objects.create(
            official_code="52.71", name="Kota Mataram", region_type="city",
        )
        source = store_monthly_health_indicators(period=date(2026, 11, 1), payload=self.payload([
            {"category": "domestic", "origin_code": 5271, "origin": "MATARAM", "count": 3},
        ]))

        row = source.verification.tourist_visit_rows.get()
        self.assertEqual(row.region, region)
        self.assertEqual(row.cleaning_method, "official_code")
        self.assertEqual(row.origin_code, "52.71")

    def test_lombok_tengah_subregion_is_also_excluded(self):
        district = AdministrativeRegion.objects.create(
            official_code="52.02.01", name="Kecamatan Praya",
            region_type="district", island_group="Lombok",
        )
        source = store_monthly_health_indicators(period=date(2027, 3, 1), payload=self.payload([
            {"category": "domestic", "origin_code": 520201, "origin": "Praya", "count": 9},
        ]))

        self.assertEqual(source.verification.to_payload()["tourist_visits"], [])
        working = source.verification.to_working_payload()["tourist_visits"][0]
        self.assertEqual(working["mapping_status"], "Dikecualikan — Kabupaten Lombok Tengah")

    def test_verification_form_summarizes_aliases_by_canonical_name(self):
        region = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah",
            region_type="regency", island_group="Lombok",
        )
        RegionAlias.objects.create(region=region, alias="LOTENG")
        RegionAlias.objects.create(region=region, alias="LOITENG")
        source = store_monthly_health_indicators(period=date(2027, 1, 1), payload=self.payload([
            {"category": "domestic", "origin": "LOTENG", "count": 4},
            {"category": "domestic", "origin": "LOITENG", "count": 2},
        ]))

        form = MonthlyHealthVerificationForm(
            payload=source.verification.to_working_payload(),
            indicator_code="tourist-visits",
        )

        self.assertEqual(len(form.tourist_mapping_summary), 1)
        summary = form.tourist_mapping_summary[0]
        self.assertEqual(summary["canonical_name"], "Kabupaten Lombok Tengah")
        self.assertEqual(summary["canonical_code"], "52.02")
        self.assertEqual(summary["raw_names"], ["LOITENG", "LOTENG"])
        self.assertEqual(summary["count"], 6)

    def test_village_name_is_not_auto_matched_without_official_code(self):
        AdministrativeRegion.objects.create(
            official_code="33.10.25.1002", name="Kabupaten", region_type="village",
        )
        source = store_monthly_health_indicators(period=date(2026, 11, 15), payload=self.payload([
            {"category": "domestic", "origin": "KABUPATEN", "count": 3},
        ]))

        row = source.verification.tourist_visit_rows.get()
        self.assertIsNone(row.region_id)
        self.assertEqual(row.cleaning_method, "unresolved")

    def test_saving_alias_from_ui_reprocesses_unresolved_rows(self):
        source = store_monthly_health_indicators(period=date(2026, 12, 1), payload=self.payload([
            {"category": "domestic", "origin": "LOOTENG", "count": 1},
        ]))
        admin = get_user_model().objects.create_user("region-admin", password="secret")
        admin.groups.add(Group.objects.get(name="Administrator DataHub"))
        self.client.force_login(admin)
        response = self.client.post(reverse("verification:region-create"), {
            "official_code": "52.02", "name": "Kabupaten Lombok Tengah",
            "region_type": "regency", "parent": "", "island_group": "Lombok", "is_active": "on",
            "aliases-TOTAL_FORMS": "1", "aliases-INITIAL_FORMS": "0",
            "aliases-MIN_NUM_FORMS": "0", "aliases-MAX_NUM_FORMS": "1000",
            "aliases-0-alias": "LOOTENG", "aliases-0-source_system": "SIMRS", "aliases-0-is_active": "on",
        })

        self.assertRedirects(response, reverse("verification:region-list"))
        row = VerifiedTouristVisitRow.objects.get(verification=source.verification)
        self.assertEqual(row.region.official_code, "52.02")
