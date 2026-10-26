import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .maternal import METRICS, MaternalVerificationForm, fetch_maternal, save_maternal, store_maternal, summarize_maternal, validate_maternal
from .models import MaternalPerinatalRecord, MaternalPerinatalSnapshot, SimrsApiEndpoint


class MaternalProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("maternal-admin", is_superuser=True)
        self.client.force_login(self.user)
        self.start, self.end = date(2026, 10, 1), date(2026, 10, 31)
        self.payload = json.loads((Path(settings.BASE_DIR) / "docs/maternal-perinatal.example.json").read_text(encoding="utf-8"))

    def store(self, payload=None):
        return store_maternal(payload or self.payload, self.start, self.end, self.user)

    def post_data(self, record):
        data = {"revision": record.revision, "notes": "Sesuai register yang telah direkonsiliasi", "action": "approve"}
        data.update({f"metric_{key}": value if value is not None else "" for key, value in record.working_data["metrics"].items()})
        for key in ("maternal_diagnoses", "perinatal_diagnoses"):
            data.update({f"{key}_{i}": row["count"] for i, row in enumerate(record.working_data[key] or [])})
        return data

    def test_example_contract_and_reject_invalid_fields_and_numbers(self):
        self.assertEqual(validate_maternal(self.payload, self.start, self.end), self.payload)
        for mutate in (
            lambda p: p.update({"patient_name": "not allowed"}),
            lambda p: p["metrics"].update({"maternal_deaths": True}),
            lambda p: p["metrics"].update({"maternal_deaths": -1}),
            lambda p: p["metrics"].update({"deliveries_total": 999}),
            lambda p: p["period"].update({"end": "2026-10-26"}),
            lambda p: p.update({"maternal_diagnoses": [p["maternal_diagnoses"][0]] * 2}),
            lambda p: p["metrics"].update({"maternal_discharges": 1}),
            lambda p: p["metrics"].pop("live_births"),
        ):
            payload = deepcopy(self.payload)
            mutate(payload)
            with self.assertRaises(ValidationError):
                validate_maternal(payload, self.start, self.end)
        self.assertEqual(MaternalPerinatalSnapshot.objects.count(), 0)

    def test_refetch_preserves_snapshots_and_verified_work_until_explicit_reload(self):
        record = self.store()
        old_snapshot = record.source_id
        save_maternal(record.pk, 1, self.user, data=self.payload, notes="V1", approve=True)
        latest = deepcopy(self.payload)
        latest["metrics"]["maternal_deaths"] = 1
        self.store(latest)
        record.refresh_from_db()
        self.assertEqual(record.status, "approved")
        self.assertEqual(record.working_data["metrics"]["maternal_deaths"], 0)
        self.assertEqual(record.source_id, old_snapshot)
        record = save_maternal(record.pk, record.revision, self.user, reload=True)
        self.assertEqual(record.status, "draft")
        self.assertIsNone(record.verified_at)
        self.assertEqual(record.working_data["metrics"]["maternal_deaths"], 1)
        self.assertEqual(MaternalPerinatalSnapshot.objects.get(pk=old_snapshot).payload, self.payload)
        self.assertEqual(MaternalPerinatalSnapshot.objects.count(), 2)
        audit = record.audits.first()
        self.assertEqual(audit.action, "reloaded")
        self.assertEqual(audit.before_data["metrics"]["maternal_deaths"], 0)
        self.assertEqual(audit.after_data["metrics"]["maternal_deaths"], 1)
        self.assertEqual(audit.actor, self.user)

    def test_stale_revision_cannot_overwrite_or_reload(self):
        record = self.store()
        save_maternal(record.pk, 1, self.user, data=self.payload, notes="Pemeriksaan")
        for kwargs in ({"reload": True}, {"data": self.payload, "notes": "Usang", "approve": True}):
            with self.assertRaises(ValidationError):
                save_maternal(record.pk, 1, self.user, **kwargs)
        self.assertEqual(record.audits.count(), 2)

    def test_verification_form_correction_requires_note_preserves_snapshot_and_resets_approval(self):
        record = self.store()
        url = reverse("verification:maternal-verify", args=[record.pk])
        data = self.post_data(record)
        self.assertContains(self.client.get(url), "Lihat snapshot sumber")
        self.assertEqual(self.client.post(url, data).status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.status, "approved")
        data = self.post_data(record)
        data.update({"action": "save", "metric_maternal_deaths": 1})
        self.client.post(url, data)
        record.refresh_from_db()
        self.assertEqual(record.status, "draft")
        self.assertEqual(record.working_data["metrics"]["maternal_deaths"], 1)
        self.assertEqual(record.source.payload["metrics"]["maternal_deaths"], 0)
        data = self.post_data(record)
        data["notes"] = ""
        self.assertFalse(MaternalVerificationForm(data, record=record).is_valid())

    def test_profile_only_approved_months_filter_and_missing_values(self):
        record = self.store()
        url = reverse("verification:maternal-profile")
        query = {"period_type": "year", "year": 2026}
        response = self.client.get(url, query)
        self.assertContains(response, "Belum ada profil yang disetujui")
        save_maternal(record.pk, 1, self.user, data=self.payload, notes="Valid", approve=True)
        response = self.client.get(url, query)
        self.assertEqual(response.context["covered_months"], 1)
        self.assertEqual(response.context["expected_months"], 12)
        metrics = {r["key"]: r for r in response.context["summary"]["metrics"]}
        self.assertEqual(metrics["maternal_deaths"]["value"], 0)
        self.assertIsNone(metrics["stillbirths_unknown_ga"]["value"])
        self.assertContains(response, "Belum tersedia")
        self.assertEqual(self.client.get(url, {"period_type": "month", "year": 2026, "month": 9}).context["covered_months"], 0)
        self.assertEqual(self.client.get(url, {"period_type": "quarter", "year": 2026, "quarter": 4}).context["covered_months"], 1)
        self.assertEqual(self.client.get(url, {"period_type": "semester", "year": 2026, "semester": 2}).context["covered_months"], 1)
        self.assertEqual(self.client.get(url, {"year": "invalid"}).status_code, 200)

    def test_annual_ranking_aggregates_all_codes_and_flags_missing_month_values(self):
        first = self.store()
        other = deepcopy(self.payload)
        other["period"] = {"start": "2026-11-01", "end": "2026-11-30"}
        other["metrics"]["maternal_deaths"] = None
        other["maternal_diagnoses"] = [
            {"icd10_code": f"O{i:02}", "name": f"Diagnosis {i}", "count": i} for i in range(1, 12)
        ]
        second = store_maternal(other, date(2026, 11, 1), date(2026, 11, 30), self.user)
        summary = summarize_maternal([first, second])
        self.assertEqual(len(summary["rankings"][0]["rows"]), 10)
        self.assertEqual(summary["rankings"][0]["rows"][0]["icd10_code"], "O14.9")
        death = next(r for r in summary["metrics"] if r["key"] == "maternal_deaths")
        self.assertEqual(death["value"], 0)
        self.assertTrue(death["partial"])

    def test_permissions_login_and_approval_are_enforced(self):
        record = self.store()
        verify_url = reverse("verification:maternal-verify", args=[record.pk])
        self.client.logout()
        self.assertEqual(self.client.get(reverse("verification:maternal-profile")).status_code, 302)
        reader = get_user_model().objects.create_user("maternal-reader")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(verify_url).status_code, 403)
        self.assertEqual(self.client.post(reverse("verification:maternal-sync"), {}).status_code, 403)
        reader.user_permissions.add(Permission.objects.get(codename="change_verifiedmonthlyhealthindicator"))
        self.assertEqual(self.client.post(verify_url, self.post_data(record)).status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.status, "draft")

    @patch("verification.maternal._fetch_simrs_json")
    @patch("verification.maternal.get_simrs_access_token", return_value="test-token")
    def test_fetch_uses_configured_endpoint_auth_and_period(self, token, fetch):
        SimrsApiEndpoint.objects.create(code="maternal-perinatal", name="Maternal", url="https://simrs.example/maternal/", timeout_seconds=12)
        fetch.return_value = self.payload
        record = fetch_maternal(self.start, self.end, self.user)
        self.assertEqual(record.status, "draft")
        self.assertIn("tgl_awal=2026-10-01", fetch.call_args.args[0])
        self.assertEqual(fetch.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(fetch.call_args.kwargs["timeout"], 12)

    def test_non_month_or_different_hospital_rejected_without_snapshot(self):
        with self.assertRaises(ValidationError):
            store_maternal(self.payload, self.start, date(2026, 10, 26), self.user)
        self.store()
        payload = deepcopy(self.payload)
        payload["hospital"]["code"] = "another-hospital"
        with self.assertRaises(ValidationError):
            self.store(payload)
        self.assertEqual(MaternalPerinatalSnapshot.objects.count(), 1)
