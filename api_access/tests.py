from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from verification.models import InpatientIndicatorSource, MonthlyHealthIndicatorSource, VerifiedInpatientIndicator, VerifiedMonthlyHealthIndicator

from .models import ApiAccessLog, ApiProduct, ExternalApiClient, ExternalApiGrant


@override_settings(SECURE_SSL_REDIRECT=False)
class SeparatedApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("internal-user", password="secret")
        source = InpatientIndicatorSource.objects.create(
            period=date(2026, 8, 1),
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            days_in_period=31,
            beds=100,
            care_days=2400,
            discharged_patients=400,
            deaths=10,
            deaths_over_48h=5,
            alos=6,
            bor=77.42,
            bto=4,
            toi=1.75,
            gdr=25,
            ndr=12.5,
            calculated_alos=6,
            calculated_bor=77.42,
            calculated_bto=4,
            calculated_toi=1.75,
            calculated_gdr=25,
            calculated_ndr=12.5,
            raw_response={},
        )
        VerifiedInpatientIndicator.objects.create(
            source=source,
            period=source.period,
            alos=6,
            bor=77.42,
            bto=4,
            toi=1.75,
            gdr=25,
            ndr=12.5,
            status=VerifiedInpatientIndicator.Status.APPROVED,
            verified_at=timezone.now(),
        )
        self.external_client = ExternalApiClient.objects.create(
            client_id="external-dashboard",
            name="Dashboard Eksternal",
        )
        ExternalApiGrant.objects.create(
            client=self.external_client,
            product=ApiProduct.objects.get(code="indicator-bor"),
        )
        health_source = MonthlyHealthIndicatorSource.objects.create(
            period=date(2026, 8, 1), hospital_code="RS-M", hospital_name="RS Mandalika",
            source_data={"hospital": {"code": "RS-M", "name": "RS Mandalika"}, "visits": [{"installation": "outpatient", "payment_status": "bpjs", "count": 25}]}, raw_response={},
        )
        VerifiedMonthlyHealthIndicator.objects.create(
            source=health_source, period=health_source.period, verified_data=health_source.source_data,
            status=VerifiedMonthlyHealthIndicator.Status.APPROVED, verified_at=timezone.now(),
        )
        ExternalApiGrant.objects.create(
            client=self.external_client,
            product=ApiProduct.objects.get(code="health-outpatient-visits"),
        )

    def test_internal_api_requires_session_and_exposes_all_indicators(self):
        url = reverse("api_internal:inpatient-indicators")
        self.assertIn(self.client.get(url).status_code, (401, 403))
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "approved")

    @patch(
        "api_access.authentication.introspect_raw_access_token",
        return_value={
            "active": True,
            "client_id": "external-dashboard",
            "scope": "read:dash",
        },
    )
    def test_external_client_only_accesses_granted_product(self, introspect_mock):
        headers = {"HTTP_AUTHORIZATION": "Bearer opaque-token"}
        allowed = self.client.get(
            reverse("api_external:indicator", args=["bor"]), **headers
        )
        denied = self.client.get(
            reverse("api_external:indicator", args=["alos"]), **headers
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["results"][0]["nilai"], 77.42)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(ApiAccessLog.objects.count(), 2)

    def test_external_schema_does_not_include_internal_routes(self):
        response = self.client.get(reverse("external-schema"))
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/external/v1/indicators/{indicator}/", body)
        self.assertNotIn("verified_by", body)

    @patch(
        "api_access.authentication.introspect_raw_access_token",
        return_value={"active": True, "client_id": "external-dashboard", "scope": "read:dash"},
    )
    def test_external_health_indicator_uses_verified_copy(self, introspect_mock):
        response = self.client.get(
            reverse("api_external:health-indicator", args=["outpatient-visits"]),
            HTTP_AUTHORIZATION="Bearer opaque-token",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["data"]["total"], 25)

    def test_legacy_api_v1_routes_are_removed(self):
        self.assertEqual(self.client.get("/api/v1/indikator/bor/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/data/kunjungan/").status_code, 404)
