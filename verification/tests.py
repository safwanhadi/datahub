import json
from io import BytesIO
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    DataSource,
    InpatientIndicatorSource,
    StagedRecord,
    VerificationAudit,
    VerifiedInpatientIndicator,
    VerifiedRecord,
    VerifiedHealthVisitRow,
    VerifiedTopDiseaseRow,
    VerifiedTouristVisitRow,
    VerifiedDiseaseGroupRow,
    SimrsApiEndpoint,
)
from .services import resolve_simrs_endpoint, store_inpatient_indicator, store_monthly_health_indicators
from .forms import IndicatorPeriodForm, MonthlyHealthVerificationForm
from .oauth import (
    get_simrs_access_token,
    introspect_raw_access_token,
)


class VerificationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("verifikator", password="secret123")
        self.user.user_permissions.add(
            Permission.objects.get(codename="add_importbatch"),
            Permission.objects.get(codename="change_verifiedrecord"),
            Permission.objects.get(codename="approve_verifiedrecord"),
        )
        self.source = DataSource.objects.create(name="SIMRS Khanza", code="simrs-khanza")
        self.client.force_login(self.user)

    def test_import_and_verify_record(self):
        response = self.client.post(
            reverse("verification:import"),
            {
                "source": self.source.pk,
                "reference": "sinkron-001",
                "record_type": "kunjungan",
                "data": json.dumps([{"source_key": "2026/0001", "nama": "Pasien A"}]),
            },
        )
        self.assertRedirects(response, reverse("verification:records"))
        staged = StagedRecord.objects.get()
        self.assertEqual(staged.status, StagedRecord.Status.PENDING)

        response = self.client.post(
            reverse("verification:verify", args=[staged.pk]),
            {
                "verified_data_text": json.dumps(
                    {"source_key": "2026/0001", "nama": "Pasien Valid"}
                ),
                "verification_notes": "Nama dikoreksi",
                "action": "approve",
            },
        )
        self.assertRedirects(response, reverse("verification:records"))
        staged.refresh_from_db()
        verified = VerifiedRecord.objects.get()
        self.assertEqual(staged.status, StagedRecord.Status.VERIFIED)
        self.assertEqual(verified.status, VerifiedRecord.Status.APPROVED)
        self.assertGreaterEqual(VerificationAudit.objects.count(), 2)

    def test_verified_indicator_keeps_source_snapshot_unchanged(self):
        source = store_inpatient_indicator(
            period=date(2026, 6, 1),
            user=self.user,
            payload={
                "periode": {"hari": 30, "awal": "2026-06-01", "akhir": "2026-06-30"},
                "data_dasar": {
                    "jumlah_bed": 100,
                    "hari_perawatan": 2100,
                    "pasien_keluar": 350,
                    "pasien_mati": 10,
                    "pasien_mati_48": 5,
                },
                "indikator": {
                    "alos": 6,
                    "bor": 999,
                    "bto": 3.5,
                    "toi": 2.57,
                    "gdr": 28.57,
                    "ndr": 14.29,
                },
            },
        )
        source.refresh_from_db()
        verified = source.verification
        self.assertEqual(float(source.bor), 999.0)
        self.assertEqual(float(source.calculated_bor), 70.0)
        self.assertEqual(float(verified.bor), 70.0)
        verified.bor = 71
        verified.status = VerifiedInpatientIndicator.Status.APPROVED
        verified.save()
        self.assertEqual(InpatientIndicatorSource.objects.get().bor, 999)


@override_settings(
    SIMADU_TOKEN_URL="https://simadu.example/o/token/",
    SIMADU_CLIENT_ID="datahub-simrs-reader",
    SIMADU_CLIENT_SECRET="outbound-secret",
    SIMADU_SIMRS_SCOPE="simrs.indicators.read",
    SIMADU_INTROSPECTION_URL="https://simadu.example/o/introspect/",
    SIMADU_INTROSPECTION_CLIENT_ID="datahub-resource-server",
    SIMADU_INTROSPECTION_CLIENT_SECRET="introspection-secret",
    SIMADU_INTROSPECTION_CACHE_SECONDS=30,
    SIMADU_OAUTH_TIMEOUT=10,
)
class OAuthOpaqueTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("verification.oauth.urlopen")
    def test_machine_token_is_requested_and_cached(self, urlopen_mock):
        urlopen_mock.return_value = BytesIO(
            json.dumps(
                {
                    "access_token": "opaque-simrs-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                }
            ).encode()
        )
        self.assertEqual(get_simrs_access_token(), "opaque-simrs-token")
        self.assertEqual(get_simrs_access_token(), "opaque-simrs-token")
        self.assertEqual(urlopen_mock.call_count, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.headers["Authorization"].startswith("Basic "))
        self.assertIn(b"grant_type=client_credentials", request.data)

    @patch("verification.oauth.urlopen")
    def test_introspection_validates_token_and_uses_cache(self, urlopen_mock):
        urlopen_mock.return_value = BytesIO(
            json.dumps({"active": True, "client_id": "mitra-test", "scope": "read:dash", "exp": 4102444800}).encode()
        )
        first = introspect_raw_access_token("opaque-third-party")
        second = introspect_raw_access_token("opaque-third-party")
        self.assertEqual(first["client_id"], "mitra-test")
        self.assertEqual(second["client_id"], "mitra-test")
        self.assertEqual(urlopen_mock.call_count, 1)


class MonthlyHealthMetadataTests(TestCase):
    def test_metadata_payload_is_normalized_and_copied_for_verification(self):
        source = store_monthly_health_indicators(
            period=date(2026, 7, 1),
            payload={
                "hospital": {"code": "RS-MANDALIKA", "name": "RS Mandalika"},
                "visits": [
                    {"installation": "outpatient", "payment_status": "bpjs", "count": 120},
                    {"installation": "inpatient", "payment_status": "general", "count": 20},
                    {"installation": "emergency", "payment_status": "other", "count": 15},
                ],
                "top_diseases": [{"installation": "outpatient", "icd10_code": "J06.9", "name": "ISPA", "patient_count": 30}],
                "tourist_visits": [{"category": "domestic", "origin": "Bali", "count": 7}],
                "disease_groups": [{"code": "cancer", "patient_count": 8}],
            },
        )
        self.assertEqual(source.verification.verified_data["visits"][0]["count"], 120)
        self.assertEqual(source.source_data["disease_groups"][0]["icd10_range"], "C00-C96,D00-D48")
        self.assertEqual(VerifiedHealthVisitRow.objects.filter(verification=source.verification).count(), 3)
        self.assertEqual(VerifiedTopDiseaseRow.objects.filter(verification=source.verification).count(), 1)
        self.assertEqual(VerifiedTouristVisitRow.objects.filter(verification=source.verification).count(), 1)
        self.assertEqual(VerifiedDiseaseGroupRow.objects.filter(verification=source.verification).count(), 1)

    def test_patient_satisfaction_is_discarded_from_source(self):
        source = store_monthly_health_indicators(
            period=date(2026, 8, 1),
            payload={
                "hospital": {"code": "RS-MANDALIKA", "name": "RS Mandalika"},
                "patient_satisfaction": {"score": 90, "respondents": 20},
            },
        )
        self.assertNotIn("patient_satisfaction", source.source_data)
        self.assertNotIn("patient_satisfaction", source.verification.verified_data)


class UserRoleTests(TestCase):
    def test_default_groups_have_separated_permissions(self):
        from django.contrib.auth.models import Group

        operator = Group.objects.get(name="Petugas Data")
        verifier = Group.objects.get(name="Verifikator")
        administrator = Group.objects.get(name="Administrator DataHub")
        reader = Group.objects.get(name="Pembaca")

        self.assertTrue(operator.permissions.filter(codename="add_inpatientindicatorsource").exists())
        self.assertFalse(operator.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertTrue(verifier.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertFalse(verifier.permissions.filter(codename="add_inpatientindicatorsource").exists())
        self.assertTrue(administrator.permissions.filter(codename="add_inpatientindicatorsource").exists())
        self.assertTrue(administrator.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertEqual(reader.permissions.count(), 0)


class FlexiblePeriodAndRowFormTests(TestCase):
    def test_supported_reporting_period_ranges(self):
        cases = [
            ({"period_type": "month", "year": 2026, "month": 2}, date(2026, 2, 1), date(2026, 2, 28)),
            ({"period_type": "quarter", "year": 2026, "quarter": 3}, date(2026, 7, 1), date(2026, 9, 30)),
            ({"period_type": "semester", "year": 2026, "semester": 2}, date(2026, 7, 1), date(2026, 12, 31)),
            ({"period_type": "year", "year": 2026}, date(2026, 1, 1), date(2026, 12, 31)),
        ]
        for data, expected_start, expected_end in cases:
            form = IndicatorPeriodForm(data)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["period_start"], expected_start)
            self.assertEqual(form.cleaned_data["period_end"], expected_end)

    def test_health_verification_form_rebuilds_json_from_rows(self):
        payload = {
            "hospital": {"code": "RS-MANDALIKA", "name": "RS Mandalika"},
            "visits": [{"installation": "outpatient", "payment_status": "bpjs", "count": 10}],
            "top_diseases": [{"installation": "outpatient", "icd10_code": "I10", "name": "Hipertensi", "patient_count": 5}],
            "tourist_visits": [{"category": "domestic", "origin": "Bali", "count": 2}],
            "disease_groups": [{"code": "heart", "patient_count": 3}],
        }
        form = MonthlyHealthVerificationForm(
            {"visit_0_count": 12, "disease_0_code": "I10", "disease_0_name": "Hipertensi", "disease_0_count": 6, "tourist_0_origin": "Bali", "tourist_0_count": 4, "group_0_count": 7, "notes": "Sesuai"},
            payload=payload,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["verified_data"]["visits"][0]["count"], 12)
        self.assertEqual(form.cleaned_data["verified_data"]["disease_groups"][0]["patient_count"], 7)


class DynamicSimrsEndpointTests(TestCase):
    def test_database_endpoint_has_priority_over_environment_fallback(self):
        endpoint = SimrsApiEndpoint.objects.get(code=SimrsApiEndpoint.Code.INPATIENT_INDICATORS)
        endpoint.url = "https://simrs.example/api/inpatient/"
        endpoint.timeout_seconds = 45
        endpoint.save()

        self.assertEqual(
            resolve_simrs_endpoint(SimrsApiEndpoint.Code.INPATIENT_INDICATORS, "https://fallback.example/"),
            ("https://simrs.example/api/inpatient/", 45),
        )

    def test_inactive_database_endpoint_does_not_fall_back_silently(self):
        endpoint = SimrsApiEndpoint.objects.get(code=SimrsApiEndpoint.Code.INPATIENT_INDICATORS)
        endpoint.is_active = False
        endpoint.save()

        with self.assertRaises(ImproperlyConfigured):
            resolve_simrs_endpoint(SimrsApiEndpoint.Code.INPATIENT_INDICATORS, "https://fallback.example/")

    def test_environment_is_used_when_database_configuration_is_absent(self):
        SimrsApiEndpoint.objects.filter(code=SimrsApiEndpoint.Code.HEALTH_AGGREGATE).delete()
        self.assertEqual(
            resolve_simrs_endpoint(SimrsApiEndpoint.Code.HEALTH_AGGREGATE, "https://fallback.example/health/"),
            ("https://fallback.example/health/", 30),
        )
