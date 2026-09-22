from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import AdministrativeRegion, RegionAlias, SimrsApiEndpoint, VerifiedTouristVisitRow
from .services import store_monthly_health_indicators


class SimrsEndpointManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("simrs-admin", password="secret")
        self.admin.groups.add(Group.objects.get(name="Administrator DataHub"))
        self.regular = get_user_model().objects.create_user("simrs-regular", password="secret")

    def test_only_administrator_can_open_simrs_configuration(self):
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(reverse("verification:simrs-endpoint-list")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("verification:simrs-endpoint-list")).status_code, 200)

    def test_administrator_can_create_endpoint_from_ui(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("verification:simrs-endpoint-create"), {
            "code": SimrsApiEndpoint.Code.VISITS,
            "name": "Kunjungan SIMRS",
            "url": "https://simrs.example.test/api/visits",
            "timeout_seconds": "45",
            "is_active": "on",
        })

        self.assertRedirects(response, reverse("verification:simrs-endpoint-list"))
        endpoint = SimrsApiEndpoint.objects.get(code=SimrsApiEndpoint.Code.VISITS)
        self.assertEqual(endpoint.timeout_seconds, 45)
        self.assertEqual(endpoint.updated_by, self.admin)

    def test_data_officer_can_manage_simrs_but_verifier_cannot(self):
        officer = get_user_model().objects.create_user("simrs-officer", password="secret")
        officer.groups.add(Group.objects.get(name="Petugas Data"))
        verifier = get_user_model().objects.create_user("rm-verifier", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))

        self.client.force_login(officer)
        self.assertEqual(self.client.get(reverse("verification:simrs-endpoint-list")).status_code, 200)
        self.client.force_login(verifier)
        self.assertEqual(self.client.get(reverse("verification:simrs-endpoint-list")).status_code, 403)

    def test_workflow_pages_follow_department_roles(self):
        officer = get_user_model().objects.create_user("data-simrs", password="secret")
        officer.groups.add(Group.objects.get(name="Petugas Data"))
        verifier = get_user_model().objects.create_user("verifier-rm", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))
        reader = get_user_model().objects.create_user("dashboard-reader", password="secret")
        reader.groups.add(Group.objects.get(name="Pembaca"))

        self.client.force_login(officer)
        response = self.client.get(reverse("verification:indicators"))
        self.assertContains(response, "Data SIMRS Rawat Inap")
        self.assertNotContains(response, "Periksa &amp; verifikasi")
        self.assertEqual(self.client.post(reverse("verification:indicator-verify", args=["00000000-0000-0000-0000-000000000000"])).status_code, 403)

        self.client.force_login(verifier)
        response = self.client.get(reverse("verification:indicators"))
        self.assertContains(response, "Verifikasi Rawat Inap")
        self.assertEqual(self.client.post(reverse("verification:indicator-sync")).status_code, 403)

        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("verification:indicators")).status_code, 302)
        self.assertEqual(self.client.get(reverse("verification:dashboard")).status_code, 200)

    def test_verifier_can_manage_region_mapping(self):
        verifier = get_user_model().objects.create_user("region-verifier", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))
        self.client.force_login(verifier)

        response = self.client.get(reverse("verification:region-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Master Wilayah")

        response = self.client.post(reverse("verification:region-create"), {
            "official_code": "ID-TEST",
            "name": "Wilayah Uji",
            "region_type": AdministrativeRegion.RegionType.OTHER,
            "is_active": "on",
            "aliases-TOTAL_FORMS": "0",
            "aliases-INITIAL_FORMS": "0",
            "aliases-MIN_NUM_FORMS": "0",
            "aliases-MAX_NUM_FORMS": "1000",
        })

        self.assertRedirects(response, reverse("verification:region-list"))
        self.assertTrue(AdministrativeRegion.objects.filter(official_code="ID-TEST").exists())

    def test_region_form_uses_searchable_select2_parent_filter(self):
        verifier = get_user_model().objects.create_user("region-select2", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))
        self.client.force_login(verifier)
        response = self.client.get(reverse("verification:region-create"))
        self.assertContains(response, "select2@4.1.0-rc.0/dist/css/select2.min.css")
        self.assertContains(response, "select2@4.1.0-rc.0/dist/js/select2.min.js")
        self.assertContains(response, 'class="js-region-parent"')
        self.assertContains(response, "Cari kode atau nama wilayah induk")
        self.assertContains(response, "minimumInputLength: 3")
        self.assertContains(response, "karakter lagi")

    def test_region_alias_field_uses_editable_simrs_suggestions(self):
        verifier = get_user_model().objects.create_user("alias-select2", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))
        self.client.force_login(verifier)
        response = self.client.get(reverse("verification:region-create"))
        self.assertContains(response, 'class="js-simrs-alias"')
        self.assertContains(response, "tags: true")
        self.assertContains(response, reverse("verification:region-alias-suggestions"))
        self.assertContains(response, "Nilai tetap disimpan sebagai teks")

    def test_region_identity_fields_use_searchable_master_suggestions(self):
        verifier = get_user_model().objects.create_user("canonical-select2", password="secret")
        verifier.groups.add(Group.objects.get(name="Verifikator"))
        self.client.force_login(verifier)
        response = self.client.get(reverse("verification:region-create"))
        self.assertContains(response, 'data-search-field="code"')
        self.assertContains(response, 'data-search-field="name"')
        self.assertContains(response, reverse("verification:canonical-region-suggestions"))
        self.assertContains(response, "Memilih wilayah yang sudah tersedia")

    def test_canonical_region_suggestions_search_code_and_name(self):
        region = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah", region_type="regency"
        )
        self.client.force_login(self.admin)
        by_name = self.client.get(
            reverse("verification:canonical-region-suggestions"), {"q": "Lombok Tengah", "field": "name"}
        ).json()["results"]
        by_code = self.client.get(
            reverse("verification:canonical-region-suggestions"), {"q": "52.02", "field": "code"}
        ).json()["results"]
        self.assertEqual(by_name[0]["id"], region.name)
        self.assertEqual(by_code[0]["id"], region.official_code)
        self.assertEqual(by_code[0]["edit_url"], reverse("verification:region-edit", args=[region.pk]))

    def test_alias_suggestions_only_use_unmapped_domestic_simrs_values(self):
        region = AdministrativeRegion.objects.create(
            official_code="52.02", name="Kabupaten Lombok Tengah", region_type="regency"
        )
        RegionAlias.objects.create(region=region, alias="SUDAH DIPETAKAN")
        store_monthly_health_indicators(period=date(2026, 9, 1), payload={
            "hospital": {"code": "RS-M", "name": "RS Mandalika"},
            "visits": [], "top_diseases": [], "disease_groups": [],
            "tourist_visits": [
                {"category": "domestic", "origin": "BELUM DIKENALI", "count": 4},
                {"category": "domestic", "origin": "SUDAH DIPETAKAN", "count": 2},
                {"category": "international", "origin": "Australia", "count": 3},
            ],
        })
        self.client.force_login(self.admin)
        response = self.client.get(reverse("verification:region-alias-suggestions"), {"q": ""})
        self.assertEqual(response.status_code, 200)
        result_ids = {item["id"] for item in response.json()["results"]}
        self.assertIn("BELUM DIKENALI", result_ids)
        self.assertNotIn("SUDAH DIPETAKAN", result_ids)
        self.assertNotIn("Australia", result_ids)

    def test_user_without_region_permission_cannot_open_mapping(self):
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(reverse("verification:region-list")).status_code, 403)
