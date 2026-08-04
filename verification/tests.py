import json
from io import BytesIO
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
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
)
from .services import store_inpatient_indicator
from .oauth import (
    InsufficientScope,
    get_simrs_access_token,
    introspect_access_token,
)


class VerificationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("verifikator", password="secret123")
        self.user.user_permissions.add(
            Permission.objects.get(codename="add_importbatch"),
            Permission.objects.get(codename="change_verifiedrecord"),
        )
        self.source = DataSource.objects.create(name="SIMRS Khanza", code="simrs-khanza")
        self.client.force_login(self.user)

    @patch(
        "verification.views.introspect_access_token",
        return_value={
            "active": True,
            "client_id": "mitra-test",
            "scope": "datahub.indicators.read",
        },
    )
    def test_import_verify_and_access_public_api(self, introspect_mock):
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

        self.client.logout()
        response = self.client.get(
            reverse("verification:public-api", args=["kunjungan"]),
            HTTP_AUTHORIZATION="Bearer opaque-token-mitra",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["data"]["nama"], "Pasien Valid")
        introspect_mock.assert_called_once_with(
            "opaque-token-mitra", required_scope="datahub.indicators.read"
        )

    def test_api_rejects_missing_token(self):
        response = self.client.get(
            reverse("verification:public-api", args=["kunjungan"])
        )
        self.assertEqual(response.status_code, 401)

    @patch(
        "verification.views.introspect_access_token",
        return_value={
            "active": True,
            "client_id": "mitra-test",
            "scope": "datahub.indicators.read",
        },
    )
    def test_six_indicator_apis_only_publish_verified_copy(self, introspect_mock):
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

        self.client.logout()
        for indicator in ("alos", "bor", "bto", "toi", "gdr", "ndr"):
            response = self.client.get(
                reverse("verification:indicator-api", args=[indicator]),
                HTTP_AUTHORIZATION="Bearer opaque-token-mitra",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)
        response = self.client.get(
            reverse("verification:indicator-api", args=["bor"]),
            HTTP_AUTHORIZATION="Bearer opaque-token-mitra",
        )
        self.assertEqual(response.json()["results"][0]["nilai"], 71.0)

    @patch(
        "verification.views.introspect_access_token",
        side_effect=InsufficientScope("Scope datahub.indicators.read diperlukan."),
    )
    def test_api_rejects_token_without_scope(self, introspect_mock):
        response = self.client.get(
            reverse("verification:indicator-api", args=["bor"]),
            HTTP_AUTHORIZATION="Bearer opaque-token-salah-scope",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("insufficient_scope", response["WWW-Authenticate"])


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
    SIMADU_ALLOWED_API_CLIENTS={"mitra-test"},
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
    def test_introspection_validates_scope_client_and_uses_cache(self, urlopen_mock):
        urlopen_mock.return_value = BytesIO(
            json.dumps(
                {
                    "active": True,
                    "client_id": "mitra-test",
                    "scope": "datahub.indicators.read",
                    "exp": 4102444800,
                }
            ).encode()
        )
        first = introspect_access_token(
            "opaque-third-party", required_scope="datahub.indicators.read"
        )
        second = introspect_access_token(
            "opaque-third-party", required_scope="datahub.indicators.read"
        )
        self.assertEqual(first["client_id"], "mitra-test")
        self.assertEqual(second["client_id"], "mitra-test")
        self.assertEqual(urlopen_mock.call_count, 1)
