from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import AdministrativeRegion, SimrsApiEndpoint


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

    def test_user_without_region_permission_cannot_open_mapping(self):
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(reverse("verification:region-list")).status_code, 403)
