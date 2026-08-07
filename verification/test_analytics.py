from decimal import Decimal
from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .analytics import analyze_inpatient_record, get_applicable_standards
from .models import InpatientIndicatorStandard


class InpatientAnalyticsTests(SimpleTestCase):
    def make_record(self, **overrides):
        values = {
            "alos": Decimal("7"), "bor": Decimal("75"),
            "bto": Decimal("4"), "toi": Decimal("2"),
            "gdr": Decimal("40"), "ndr": Decimal("20"),
        }
        values.update(overrides)
        return SimpleNamespace(source=SimpleNamespace(days_in_period=30), **values)

    def test_values_are_classified_below_within_and_above_standard(self):
        result = {item["code"]: item for item in analyze_inpatient_record(
            self.make_record(alos=Decimal("5"), bor=Decimal("90"), ndr=Decimal("25"))
        )}

        self.assertEqual(result["alos"]["level"], "low")
        self.assertEqual(result["bor"]["level"], "high")
        self.assertEqual(result["toi"]["level"], "ideal")
        self.assertEqual(result["ndr"]["level"], "high")

    def test_monthly_bto_is_annualized_before_comparison(self):
        result = {item["code"]: item for item in analyze_inpatient_record(self.make_record())}

        self.assertEqual(result["bto"]["level"], "ideal")
        self.assertIn("Proyeksi tahunan", result["bto"]["comparison_note"])


class DynamicIndicatorStandardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("standard-admin", password="secret")
        self.admin.groups.add(Group.objects.get(name="Administrator DataHub"))
        self.client.force_login(self.admin)

    def test_internal_policy_overrides_national_policy_for_same_period(self):
        internal = InpatientIndicatorStandard.objects.create(
            indicator="bor", policy_level="internal", minimum_value=Decimal("70"),
            maximum_value=Decimal("80"), unit="%", effective_from=date(2026, 1, 1),
            reference_name="Kebijakan Direktur", updated_by=self.admin,
        )

        selected = get_applicable_standards(date(2026, 8, 1))

        self.assertEqual(selected["bor"], internal)

    def test_admin_can_create_standard_from_management_ui(self):
        response = self.client.post(reverse("verification:standard-create"), {
            "indicator": "alos", "policy_level": "internal",
            "minimum_value": "5", "maximum_value": "8", "unit": "hari",
            "period_basis": "reporting", "effective_from": "2027-01-01",
            "effective_until": "", "reference_name": "Standar mutu internal 2027",
            "reference_url": "", "notes": "", "is_active": "on",
        })

        self.assertRedirects(response, reverse("verification:standard-list"))
        self.assertTrue(InpatientIndicatorStandard.objects.filter(
            indicator="alos", policy_level="internal", effective_from=date(2027, 1, 1)
        ).exists())
