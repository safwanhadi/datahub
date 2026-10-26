from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import AdministrativeRegion, RegionAlias, VerifiedTouristVisitRow
from .services import save_monthly_health_verification, store_monthly_health_indicators
from .forms import MonthlyHealthVerificationForm


class RegionCleaningTests(TestCase):
    def test_reload_latest_tourists_imports_installation_without_replacing_other_indicators(self):
        payload = self.payload([{"category": "international", "origin": "-", "count": 2}])
        payload["visits"] = [{"installation": "outpatient", "payment_status": "bpjs", "count": 10}]
        source = store_monthly_health_indicators(period=date(2026, 10, 1), payload=payload)
        record = source.verification
        record.indicator_verifications.update(status="approved")
        record.visit_rows.update(count=15)
        latest = self.payload([{"installation": "outpatient", "category": "international", "origin": "-", "count": 62}])
        store_monthly_health_indicators(period=date(2026, 10, 1), payload=latest)
        self.assertEqual(record.tourist_visit_rows.get().installation, "other")
        user = get_user_model().objects.create_user("reload-tourists-admin", is_superuser=True, is_staff=True)
        self.client.force_login(user)
        url = reverse("verification:health-indicator-verify", args=[source.pk, "tourist-visits"])
        self.assertContains(self.client.get(url), "Muat data wisatawan dari tarikan terbaru")
        self.assertRedirects(self.client.post(url, {"action": "reload-tourists"}), url)
        self.assertEqual(record.tourist_visit_rows.get().installation, "outpatient")
        self.assertEqual(record.tourist_visit_rows.get().count, 62)
        self.assertEqual(record.visit_rows.get().count, 15)
        self.assertEqual(record.indicator_verifications.get(indicator_code="tourist-visits").status, "draft")
        self.assertEqual(record.indicator_verifications.get(indicator_code="outpatient-visits").status, "approved")
        source.refresh_from_db()
        self.assertEqual(source.raw_response, latest)
        audit = record.audits.latest("created_at")
        self.assertEqual(audit.before_data["tourist_visits"][0]["count"], 2)
        self.assertEqual(audit.after_data["tourist_visits"][0]["installation"], "outpatient")
        self.assertEqual(audit.actor, user)

    def test_tourist_installations_survive_verification_and_dashboard_aggregation(self):
        region = AdministrativeRegion.objects.create(
            official_code="51", name="Bali", region_type="province",
        )
        local = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah", region_type="regency",
        )
        tourists = [
            {"category": "international", "origin": "Australia", "installation": installation, "count": count}
            for installation, count in [("outpatient", 2), ("inpatient", 3), ("emergency", 4), (None, 5), ("unknown", 6)]
        ] + [
            {"category": "international", "origin": "Australia", "count": 7},
            {"category": "domestic", "origin": region.name, "origin_code": region.official_code, "installation": "outpatient", "count": 8},
            {"category": "domestic", "origin": local.name, "origin_code": local.official_code, "installation": "outpatient", "count": 99},
            {"category": "domestic", "origin": "Unknown", "installation": "emergency", "count": 99},
        ]
        source = store_monthly_health_indicators(period=date(2026, 10, 1), payload=self.payload(tourists))
        record = source.verification
        self.assertEqual(record.tourist_visit_rows.filter(installation="other").count(), 3)
        verifier = get_user_model().objects.create_user("installation-verifier")
        self.client.force_login(verifier)
        approval = record.indicator_verifications.get(indicator_code="tourist-visits")
        response = self.client.get(reverse("verification:dashboard"), {"reference": "2026-10"})
        self.assertIsNone(response.context["health_summary"])
        working = record.to_working_payload()
        form = MonthlyHealthVerificationForm(
            data={**{
                key: value for i, row in enumerate(working["tourist_visits"])
                for key, value in {
                    f"tourist_{i}_category": row["category"], f"tourist_{i}_origin": row["origin"],
                    f"tourist_{i}_count": row["count"],
                }.items()
            }, "notes": "Verifikasi instalasi"},
            payload=working, indicator_code="tourist-visits",
        )
        self.assertTrue(form.is_valid(), form.errors)
        save_monthly_health_verification(
            record=record, indicator_verification=approval, data=form.cleaned_data["verified_data"],
            notes="Verifikasi instalasi", user=verifier, approve=True,
        )
        self.assertEqual(record.to_working_payload()["tourist_visits"], working["tourist_visits"])
        source.refresh_from_db()
        self.assertEqual(source.raw_response["tourist_visits"], tourists)
        self.assertEqual(source.source_data["tourist_visits"], tourists)
        self.assertEqual(record.audits.latest("created_at").after_data["tourist_visits"], working["tourist_visits"])
        for mode in ("monthly", "quarterly", "semester", "yearly"):
            response = self.client.get(reverse("verification:dashboard"), {"reference": "2026-10", "period": mode})
            self.assertContains(response, "Asal instalasi kunjungan wisatawan")
            summary = response.context["health_summary"]
            rows = {row["label"]: row for row in summary["tourist_installations"]}
            self.assertEqual(rows["Rawat jalan"]["wisnus"], 8)
            self.assertEqual(rows["Rawat jalan"]["wisman"], 2)
            self.assertEqual(rows["Rawat inap"]["total"], 3)
            self.assertEqual(rows["IGD"]["total"], 4)
            self.assertEqual(rows["Lainnya"]["total"], 18)
            self.assertEqual(sum(row["total"] for row in rows.values()), summary["tourist_published_total"])
            self.assertEqual(summary["tourist_published_total"], 35)

    def test_duplicate_tourist_origins_preserve_all_rows_and_snapshot(self):
        payload = self.payload([
            {"category": "international", "origin": "LOMBOK TENGAH", "count": 3},
            {"category": "international", "origin": "LOMBOK TENGAH", "count": 5},
            {"category": "international", "origin": "LOMBOK TENGAH", "origin_code": "52.02", "count": 2},
        ])
        source = store_monthly_health_indicators(period=date(2026, 10, 1), payload=payload)
        record = source.verification
        self.assertEqual(record.tourist_visit_rows.count(), 3)
        self.assertEqual(sum(row.count for row in record.tourist_visit_rows.all()), 10)
        self.assertEqual(source.raw_response, payload)
        self.assertEqual(source.source_data["tourist_visits"], payload["tourist_visits"])
        self.assertEqual(record.to_payload()["tourist_visits"][0]["count"], 10)
        self.assertEqual(record.audits.get().after_data["tourist_visits"], payload["tourist_visits"])

        verifier = get_user_model().objects.create_user("duplicate-origin-verifier")
        save_monthly_health_verification(
            record=record,
            indicator_verification=record.indicator_verifications.get(indicator_code="tourist-visits"),
            data=record.to_working_payload(), notes="Verifikasi baris sumber berulang",
            user=verifier, approve=False,
        )
        self.assertEqual(record.tourist_visit_rows.count(), 3)
        self.assertEqual(record.audits.count(), 2)
        store_monthly_health_indicators(period=date(2026, 10, 1), payload=payload)
        self.assertEqual(record.tourist_visit_rows.count(), 3)
        source.refresh_from_db()
        self.assertEqual(source.raw_response, payload)

    def payload(self, tourist_rows):
        return {
            "hospital": {"code": "RS-M", "name": "RS Mandalika"},
            "visits": [], "top_diseases": [], "disease_groups": [],
            "tourist_visits": tourist_rows,
        }

    def test_manual_installation_mapping_preserves_source_and_is_audited(self):
        source = store_monthly_health_indicators(period=date(2026, 10, 1), payload=self.payload([
            {"category": "international", "origin": "Australia", "count": 3},
        ]))
        record = source.verification
        self.assertEqual(record.tourist_visit_rows.get().installation, "other")
        form = MonthlyHealthVerificationForm(
            data={"tourist_0_category": "international", "tourist_0_origin": "Australia",
                  "tourist_0_count": 3, "tourist_0_installation": "emergency", "notes": "Sesuai verifikasi IGD"},
            payload=record.to_working_payload(), indicator_code="tourist-visits",
        )
        self.assertTrue(form.is_valid(), form.errors)
        save_monthly_health_verification(
            record=record, indicator_verification=record.indicator_verifications.get(indicator_code="tourist-visits"),
            data=form.cleaned_data["verified_data"], notes=form.cleaned_data["notes"],
            user=get_user_model().objects.create_user("installation-mapper"), approve=False,
        )
        self.assertEqual(record.tourist_visit_rows.get().installation, "emergency")
        audit = record.audits.latest("created_at")
        self.assertNotIn("installation", audit.before_data["tourist_visits"][0])
        self.assertEqual(audit.after_data["tourist_visits"][0]["installation"], "emergency")
        source.refresh_from_db()
        self.assertNotIn("installation", source.raw_response["tourist_visits"][0])

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

    def test_verification_form_can_correct_tourist_category_without_changing_source(self):
        source = store_monthly_health_indicators(period=date(2027, 2, 1), payload=self.payload([
            {"category": "domestic", "origin": "Australia", "count": 3},
        ]))
        record = source.verification
        form = MonthlyHealthVerificationForm(
            data={
                "tourist_0_category": "international",
                "tourist_0_origin": "Australia",
                "tourist_0_count": "3",
                "notes": "Asal luar Indonesia tidak terjaring status izin tinggal SIMRS.",
            },
            payload=record.to_working_payload(),
            indicator_code="tourist-visits",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["verified_data"]["tourist_visits"][0]["category"], "international")
        verifier = get_user_model().objects.create_user("category-corrector")
        indicator_verification = record.indicator_verifications.get(indicator_code="tourist-visits")
        save_monthly_health_verification(
            record=record,
            indicator_verification=indicator_verification,
            data=form.cleaned_data["verified_data"],
            notes=form.cleaned_data["notes"],
            user=verifier,
            approve=False,
        )

        self.assertEqual(record.tourist_visit_rows.get().category, "international")
        audit = record.audits.latest("created_at")
        self.assertEqual(audit.before_data["tourist_visits"][0]["category"], "domestic")
        self.assertEqual(audit.after_data["tourist_visits"][0]["category"], "international")
        self.assertEqual(source.source_data["tourist_visits"][0]["category"], "domestic")

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
