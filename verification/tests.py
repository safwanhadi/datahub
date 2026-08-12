import json
from io import BytesIO
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    InpatientIndicatorSource,
    HealthIndicatorVerification,
    InpatientIndicatorAudit,
    InpatientRoomIndicatorSource,
    VerifiedInpatientRoomIndicator,
    VerifiedInpatientIndicator,
    VerifiedHealthVisitRow,
    VerifiedTopDiseaseRow,
    VerifiedTouristVisitRow,
    VerifiedDiseaseGroupRow,
    SimrsApiEndpoint,
)
from .services import fetch_monthly_health_indicators, resolve_simrs_endpoint, save_inpatient_working_data_correction, store_inpatient_indicator, store_monthly_health_indicators
from .forms import IndicatorPeriodForm, MonthlyHealthVerificationForm
from .oauth import (
    get_simrs_access_token,
    introspect_raw_access_token,
)


class VerificationFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("verifikator", password="secret123")
        self.user.groups.add(Group.objects.get(name="Verifikator"))
        self.client.force_login(self.user)

    def test_sidebar_marks_only_health_indicators_as_active(self):
        response = self.client.get(reverse("verification:health-indicators"))

        self.assertContains(
            response,
            f'href="{reverse("verification:health-indicators")}" class="active" aria-current="page"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("verification:indicators")}" class="active"',
        )

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

    def test_inpatient_indicators_are_calculated_per_room(self):
        source = store_inpatient_indicator(
            period=date(2027, 4, 1), user=self.user,
            payload={
                "periode": {"hari": 30},
                "data_dasar": {"jumlah_bed": 30, "hari_perawatan": 600, "pasien_keluar": 100, "pasien_mati": 2, "pasien_mati_48": 1},
                "indikator": {"alos": 6, "bor": 66.67, "bto": 3.33, "toi": 3, "gdr": 20, "ndr": 10},
                "ruangan": [
                    {"kd_bangsal": "ANAK", "bangsal": "Ruang Anak", "bed": 10, "hp": 240, "d": 40, "mati": 1, "mati_48": 0, "is_khusus": False},
                    {"kd_bangsal": "ICU", "bangsal": "ICU", "bed": 5, "hp": 120, "d": 20, "mati": 2, "mati_48": 1, "is_khusus": True},
                    {"kd_bangsal": "PICU", "bangsal": "PICU", "bed": 4, "hp": 60, "d": 10, "mati": 0, "mati_48": 0, "is_khusus": True},
                    {"kd_bangsal": "PERINA", "bangsal": "Ruang Perina", "bed": 6, "hp": 90, "d": 15, "mati": 0, "mati_48": 0, "is_khusus": False},
                ],
            },
        )

        self.assertEqual(InpatientRoomIndicatorSource.objects.filter(source=source).count(), 4)
        room = VerifiedInpatientRoomIndicator.objects.get(source_room__room_code="ANAK")
        self.assertEqual(room.alos, 6)
        self.assertEqual(room.bor, 80)
        self.assertEqual(room.gdr, 25)
        self.assertTrue(VerifiedInpatientRoomIndicator.objects.get(source_room__room_code="ICU").source_room.is_special)
        self.assertTrue(VerifiedInpatientRoomIndicator.objects.get(source_room__room_code="PERINA").source_room.is_special)
        self.assertTrue(VerifiedInpatientRoomIndicator.objects.get(source_room__room_code="PICU").source_room.is_special)

        page = self.client.get(reverse("verification:indicator-verify", args=[source.pk]))
        self.assertContains(page, "Indikator per ruang rawat inap")
        self.assertContains(page, "Ruang Anak")

    def test_refetch_resets_approval_and_replaces_working_data_and_rooms(self):
        period = date(2027, 6, 1)
        original = {
            "periode": {"hari": 30},
            "data_dasar": {"jumlah_bed": 20, "hari_perawatan": 300, "pasien_keluar": 60, "pasien_mati": 3, "pasien_mati_48": 1},
            "indikator": {"alos": 5, "bor": 50, "bto": 3, "toi": 5, "gdr": 50, "ndr": 16.67},
            "ruangan": [
                {"kd_bangsal": "LAMA", "bangsal": "Ruang Lama", "bed": 10, "hp": 150, "d": 30, "mati": 2, "mati_48": 1},
                {"kd_bangsal": "TETAP", "bangsal": "Ruang Tetap", "bed": 10, "hp": 150, "d": 30, "mati": 1, "mati_48": 0},
            ],
        }
        source = store_inpatient_indicator(period=period, payload=original, user=self.user)
        record = source.verification
        record.status = VerifiedInpatientIndicator.Status.APPROVED
        record.notes = "Data lama disetujui"
        record.verified_by = self.user
        record.verified_at = timezone.now()
        record.bor = 51
        record.save()

        corrected = {
            "periode": {"hari": 30},
            "data_dasar": {"jumlah_bed": 25, "hari_perawatan": 450, "pasien_keluar": 75, "pasien_mati": 2, "pasien_mati_48": 1},
            "indikator": {"alos": 6, "bor": 60, "bto": 3, "toi": 4, "gdr": 26.67, "ndr": 13.33},
            "ruangan": [
                {"kd_bangsal": "TETAP", "bangsal": "Ruang Tetap", "bed": 10, "hp": 210, "d": 35, "mati": 1, "mati_48": 1},
                {"kd_bangsal": "BARU", "bangsal": "Ruang Baru", "bed": 15, "hp": 240, "d": 40, "mati": 1, "mati_48": 0},
            ],
        }
        refreshed_source = store_inpatient_indicator(period=period, payload=corrected, user=self.user)

        self.assertEqual(refreshed_source.pk, source.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, VerifiedInpatientIndicator.Status.DRAFT)
        self.assertIsNone(record.verified_by)
        self.assertIsNone(record.verified_at)
        self.assertEqual(record.notes, "")
        self.assertEqual(record.working_beds, 25)
        self.assertEqual(record.working_care_days, 450)
        self.assertEqual(record.bor, 60)
        self.assertSetEqual(
            set(refreshed_source.room_sources.values_list("room_code", flat=True)),
            {"TETAP", "BARU"},
        )
        audit = InpatientIndicatorAudit.objects.get(record=record, action="refetched_from_simrs")
        self.assertEqual(audit.before_data["status"], VerifiedInpatientIndicator.Status.APPROVED)
        self.assertEqual(audit.after_data["status"], VerifiedInpatientIndicator.Status.DRAFT)

    def test_api_documentation_hub_exposes_shareable_and_internal_links(self):
        response = self.client.get(reverse("verification:api-documentation"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dokumentasi API")
        self.assertContains(response, "http://testserver/docs/external/")
        self.assertContains(response, "http://testserver/docs/internal/")
        self.assertContains(response, "http://testserver/api/external/v1/")
        self.assertContains(response, "http://testserver/api/internal/v1/indicators/inpatient/")

    def test_api_documentation_hub_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("verification:api-documentation"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_inpatient_working_data_correction_preserves_simrs_snapshot(self):
        source = store_inpatient_indicator(
            period=date(2027, 2, 1), user=self.user,
            payload={
                "periode": {"hari": 28},
                "data_dasar": {"jumlah_bed": 100, "hari_perawatan": 1400, "pasien_keluar": 280, "pasien_mati": 8, "pasien_mati_48": 4},
                "indikator": {"alos": 5, "bor": 50, "bto": 2.8, "toi": 5, "gdr": 28.57, "ndr": 14.29},
            },
        )
        source.verification.status = VerifiedInpatientIndicator.Status.APPROVED
        source.verification.save()

        changed = save_inpatient_working_data_correction(
            record=source.verification,
            cleaned_data={
                "beds": 100, "care_days": 1680, "discharged_patients": 280,
                "deaths": 8, "deaths_over_48h": 4, "days_in_period": 28,
                "reason": "Sesuai sensus harian ruang rawat",
            }, user=self.user,
        )

        source.refresh_from_db()
        source.verification.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(source.care_days, 1400)
        self.assertEqual(source.verification.working_care_days, 1680)
        self.assertEqual(source.verification.bor, 60)
        self.assertEqual(source.verification.status, VerifiedInpatientIndicator.Status.DRAFT)
        self.assertTrue(InpatientIndicatorAudit.objects.filter(record=source.verification, action="corrected_working_data").exists())

        page = self.client.get(reverse("verification:inpatient-working-data-correct", args=[source.pk]))
        self.assertContains(page, "Snapshot asli SIMRS")
        self.assertContains(page, "Sesuai sensus", count=0)


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
        self.assertEqual(source.verification.indicator_verifications.count(), 6)
        self.assertFalse(source.verification.indicator_verifications.exclude(status=HealthIndicatorVerification.Status.DRAFT).exists())

    def test_health_workflow_lists_each_indicator_separately(self):
        user = get_user_model().objects.create_user("health-verifier", password="secret")
        user.groups.add(Group.objects.get(name="Verifikator"))
        source = store_monthly_health_indicators(
            period=date(2026, 10, 1),
            payload={
                "hospital": {"code": "RS-M", "name": "RS Mandalika"},
                "visits": [{"installation": "outpatient", "payment_status": "bpjs", "count": 12}],
            },
        )
        self.client.force_login(user)

        listing = self.client.get(reverse("verification:health-indicators"))
        detail = self.client.get(reverse(
            "verification:health-indicator-verify",
            args=[source.pk, "outpatient-visits"],
        ))

        self.assertContains(listing, "Antrean verifikasi")
        self.assertContains(listing, "Kunjungan Rawat Jalan")
        self.assertContains(listing, "Kunjungan IGD")
        self.assertContains(listing, "Evaluasi KJSU")
        self.assertContains(detail, "Persetujuan ini hanya berlaku")
        self.assertContains(detail, "visit_0_count")

        kjsu_detail = self.client.get(reverse(
            "verification:health-indicator-verify",
            args=[source.pk, "kjsu-evaluation"],
        ))
        self.assertContains(kjsu_detail, "Kanker, Jantung, Stroke, dan Uronefrologi")

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
        self.assertTrue(operator.permissions.filter(codename="change_simrsapiendpoint").exists())
        self.assertFalse(operator.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertTrue(verifier.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertTrue(verifier.permissions.filter(codename="change_administrativeregion").exists())
        self.assertTrue(verifier.permissions.filter(codename="change_regionalias").exists())
        self.assertFalse(verifier.permissions.filter(codename="add_inpatientindicatorsource").exists())
        self.assertTrue(administrator.permissions.filter(codename="add_inpatientindicatorsource").exists())
        self.assertTrue(administrator.permissions.filter(codename="approve_verifiedinpatientindicator").exists())
        self.assertEqual(reader.permissions.count(), 0)

    def test_reader_can_view_indicator_lists_but_cannot_run_workflow_actions(self):
        reader = get_user_model().objects.create_user("read-only-user", password="secret")
        reader.groups.add(Group.objects.get(name="Pembaca"))
        self.client.force_login(reader)

        inpatient = self.client.get(reverse("verification:indicators"))
        health = self.client.get(reverse("verification:health-indicators"))

        self.assertEqual(inpatient.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertContains(inpatient, "Indikator rawat inap")
        self.assertContains(health, "Indikator kesehatan")
        self.assertNotContains(inpatient, "Ambil dari SIMRS")
        self.assertNotContains(inpatient, "Periksa &amp; verifikasi", html=True)
        self.assertNotContains(inpatient, "Ubah data dasar")
        self.assertNotContains(health, "Ambil dari SIMRS")
        self.assertNotContains(health, "Periksa &amp; verifikasi", html=True)
        self.assertEqual(self.client.post(reverse("verification:indicator-sync"), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("verification:health-indicator-sync"), {}).status_code, 403)


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
    @patch("verification.services.get_simrs_access_token", return_value="simrs-token")
    @patch("verification.services.urlopen")
    def test_inpatient_dns_error_identifies_endpoint_and_host(self, urlopen_mock, token_mock):
        import socket
        from urllib.error import URLError

        from .services import SimrsConnectionError, fetch_inpatient_indicator

        urlopen_mock.side_effect = URLError(socket.gaierror(-2, "Name or service not known"))

        with self.assertRaisesRegex(
            SimrsConnectionError,
            r"DNS server production.*host .+.*indikator rawat inap",
        ):
            fetch_inpatient_indicator(period=date(2027, 5, 1))

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
        SimrsApiEndpoint.objects.filter(code=SimrsApiEndpoint.Code.VISITS).delete()
        self.assertEqual(
            resolve_simrs_endpoint(SimrsApiEndpoint.Code.VISITS, "https://fallback.example/health/"),
            ("https://fallback.example/health/", 30),
        )

    @patch("verification.services.get_simrs_access_token", return_value="simrs-token")
    @patch("verification.services.urlopen")
    def test_inpatient_total_and_room_endpoints_are_fetched_together(self, urlopen_mock, token_mock):
        SimrsApiEndpoint.objects.update_or_create(
            code=SimrsApiEndpoint.Code.INPATIENT_ROOMS,
            defaults={"name": "Per Ruang", "url": "https://simrs.example/inpatient-rooms/", "is_active": True},
        )
        total = {
            "periode": {"hari": 31},
            "data_dasar": {"jumlah_bed": 20, "hari_perawatan": 310, "pasien_keluar": 62, "pasien_mati": 2, "pasien_mati_48": 1},
            "indikator": {"alos": 5, "bor": 50, "bto": 3.1, "toi": 5, "gdr": 32.26, "ndr": 16.13},
        }
        rooms = {"data": [
            {"kd_bangsal": "A", "bangsal": "Ruang A", "bed": 10, "hp": 186, "d": 31, "mati": 1, "mati_48": 1, "is_khusus": False},
        ]}
        urlopen_mock.side_effect = [BytesIO(json.dumps(total).encode()), BytesIO(json.dumps(rooms).encode())]

        from .services import fetch_inpatient_indicator
        source = fetch_inpatient_indicator(period=date(2027, 5, 1))

        self.assertEqual(urlopen_mock.call_count, 2)
        self.assertEqual(source.verification.room_indicators.get().source_room.room_name, "Ruang A")
        self.assertEqual(source.verification.room_indicators.get().bor, 60)

    @patch("verification.services.get_simrs_access_token", return_value="simrs-token")
    @patch("verification.services.urlopen")
    def test_health_endpoints_are_aggregated_by_datahub(self, urlopen_mock, token_mock):
        endpoints = (
            (SimrsApiEndpoint.Code.VISITS, "visits"),
            (SimrsApiEndpoint.Code.TOP_DISEASES, "top-diseases"),
            (SimrsApiEndpoint.Code.TOURIST_VISITS, "tourist-visits"),
            (SimrsApiEndpoint.Code.DISEASE_GROUPS, "disease-groups"),
        )
        for code, path in endpoints:
            SimrsApiEndpoint.objects.update_or_create(
                code=code,
                defaults={"name": path, "url": f"https://simrs.example/{path}/", "is_active": True},
            )
        hospital = {"code": "RS-M", "name": "RS Mandalika"}
        responses = [
            {"hospital": hospital, "results": [{"installation": "outpatient", "payment_status": "bpjs", "count": 20}]},
            {"hospital": hospital, "results": [{"installation": "outpatient", "icd10_code": "I10", "name": "Hipertensi", "patient_count": 8}]},
            {"hospital": hospital, "results": [{"category": "domestic", "origin": "Bali", "count": 4}]},
            {"hospital": hospital, "results": [{"code": "heart", "patient_count": 3}]},
        ]
        urlopen_mock.side_effect = [BytesIO(json.dumps(item).encode()) for item in responses]

        source = fetch_monthly_health_indicators(period=date(2026, 9, 1))

        self.assertEqual(source.source_data["visits"][0]["count"], 20)
        self.assertEqual(source.source_data["disease_groups"][0]["icd10_range"], "I00-I52")
        self.assertEqual(urlopen_mock.call_count, 4)
