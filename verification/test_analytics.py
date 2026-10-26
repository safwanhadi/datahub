from decimal import Decimal
from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .analytics import analyze_inpatient_record, get_applicable_standards, summarize_inpatient_records
from .models import InpatientIndicatorStandard


class InpatientAnalyticsTests(SimpleTestCase):
    def period_record(self, month, *, beds=100, care=2000, discharged=400):
        import calendar
        start = date(2024, month, 1)
        end = date(2024, month, calendar.monthrange(2024, month)[1])
        return SimpleNamespace(
            source=SimpleNamespace(period_start=start, period_end=end, period_type="month"),
            working_days_in_period=end.day, working_beds=beds, working_care_days=care,
            working_discharged_patients=discharged, working_deaths=4, working_deaths_over_48h=2,
            alos=Decimal("5"), bor=Decimal("70"), bto=Decimal("4"), toi=Decimal("2"),
            gdr=Decimal("10"), ndr=Decimal("5"),
        )

    def test_period_totals_use_capacity_weighting_and_exclude_duplicate_annual_data(self):
        january = self.period_record(1)
        february = self.period_record(2, beds=200, care=4000, discharged=800)
        summary = summarize_inpatient_records([february, january], date(2024, 1, 1), date(2024, 12, 31))
        self.assertEqual(summary.alos, Decimal("5.00"))
        self.assertEqual(summary.bor, Decimal("67.42"))
        self.assertEqual(summary.bto, Decimal("8.09"))
        self.assertEqual(summary.covered_days, 60)
        self.assertEqual(summary.expected_days, 366)
        self.assertEqual(summary.gdr, Decimal("6.67"))

    def test_exact_period_takes_precedence_over_months(self):
        month = self.period_record(1)
        annual = self.period_record(1)
        annual.source.period_end = date(2024, 12, 31)
        annual.source.period_type = "year"
        annual.working_days_in_period = 366
        annual.bto = Decimal("45")
        summary = summarize_inpatient_records([month, annual], date(2024, 1, 1), date(2024, 12, 31))
        self.assertEqual(summary.bto, Decimal("45"))
        self.assertEqual(summary.covered_days, 366)

    def test_empty_period_has_no_summary(self):
        self.assertIsNone(summarize_inpatient_records([], date(2024, 1, 1), date(2024, 12, 31)))

    def test_bto_standard_follows_each_filter_period(self):
        for days, label in [(31, "bulan"), (91, "triwulan"), (182, "semester"), (366, "tahun")]:
            with self.subTest(label=label):
                fraction = Decimal(days) / 366
                record = self.make_record(bto=45 * fraction)
                result = {r["code"]: r for r in analyze_inpatient_record(
                    record, period_fraction=fraction, period_label=label)}
                self.assertEqual(result["bto"]["level"], "ideal")
                self.assertEqual(result["bto"]["minimum"], 40 * fraction)
                self.assertIn("/" + label, result["bto"]["standard"])
                self.assertEqual(result["alos"]["minimum"], Decimal("6"))

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

    def test_dashboard_payment_breakdown_respects_period_and_indicator_approval(self):
        from .services import store_monthly_health_indicators

        for month in (1, 2, 4):
            source = store_monthly_health_indicators(
                period=date(2026, month, 1),
                payload={
                    "hospital": {"code": "RS-M", "name": "RS Mandalika"},
                    "visits": [
                        {"installation": "outpatient", "payment_status": status, "count": count}
                        for status, count in [("general", 2), ("bpjs", 3), ("private_insurance", 4), ("social_assistance", 5), ("other", 6)]
                    ] + [
                        {"installation": "inpatient", "payment_status": "bpjs", "count": 7},
                        {"installation": "emergency", "payment_status": "general", "count": 99},
                    ],
                },
            )
            source.verification.indicator_verifications.filter(
                indicator_code__in=["outpatient-visits", "inpatient-visits"]
            ).update(status="approved")

        for mode, multiplier in [("monthly", 1), ("quarterly", 2), ("semester", 3), ("yearly", 3)]:
            with self.subTest(mode=mode):
                response = self.client.get(reverse("verification:dashboard"), {"period": mode, "reference": "2026-02"})
                self.assertContains(response, "Rincian kunjungan berdasarkan penjamin")
                summary = response.context["health_summary"]
                rows = {row["label"]: row for row in summary["payment_breakdown"]}
                self.assertEqual(rows["Umum"]["total"], 2 * multiplier)
                self.assertEqual(rows["BPJS"]["total"], 10 * multiplier)
                self.assertEqual(rows["Asuransi"]["total"], 4 * multiplier)
                self.assertEqual(rows["Bantuan sosial"]["total"], 5 * multiplier)
                self.assertEqual(rows["Lainnya"]["total"], 6 * multiplier)
                self.assertEqual(sum(row["total"] for row in rows.values()), summary["total_visits"])
                self.assertEqual(summary["emergency"], 0)

        response = self.client.get(reverse("verification:dashboard"), {"reference": "2025-02"})
        self.assertContains(response, "Belum ada rincian kunjungan terverifikasi")

    def test_dashboard_filter_aggregates_months_and_does_not_reuse_latest_month(self):
        import calendar
        from .services import store_inpatient_indicator
        for month in range(1, 13):
            source = store_inpatient_indicator(
                period=date(2026, month, 1), user=self.admin,
                payload={
                    "periode": {"hari": calendar.monthrange(2026, month)[1]},
                    "data_dasar": {"jumlah_bed": 100, "hari_perawatan": 2000,
                                   "pasien_keluar": 400, "pasien_mati": 4, "pasien_mati_48": 2},
                    "indikator": {"alos": 5, "bor": 70, "bto": 4, "toi": 2, "gdr": 10, "ndr": 5},
                },
            )
            source.verification.status = "approved"
            source.verification.save()
        for mode, months in (("quarterly", 3), ("semester", 6), ("yearly", 12)):
            response = self.client.get(reverse("verification:dashboard"), {"period": mode, "reference": "2026-02"})
            self.assertEqual(response.status_code, 200)
            items = {r["code"]: r for r in response.context["indicator_analysis"]}
            self.assertEqual(items["bto"]["value"], Decimal(4 * months))
            self.assertEqual(
                [row.source.period_start.month for row in response.context["inpatient_trend"]],
                list(range(1, months + 1)),
            )
            self.assertContains(response, "Seluruh hasil terverifikasi")
        response = self.client.get(reverse("verification:dashboard"), {"period": "monthly", "reference": "2026-02"})
        self.assertEqual(response.context["latest_inpatient"].bto, Decimal("4.00"))
        self.assertEqual([row.source.period_start.month for row in response.context["inpatient_trend"]], [2])
        response = self.client.get(reverse("verification:dashboard"), {"period": "yearly", "reference": "2025-02"})
        self.assertEqual(response.context["indicator_analysis"], [])
        self.assertEqual(list(response.context["inpatient_trend"]), [])

    def test_dashboard_shows_ten_highest_verified_diseases_in_selected_period(self):
        from .services import store_monthly_health_indicators

        for month in (1, 2, 4):
            source = store_monthly_health_indicators(period=date(2026, month, 1), payload={
                "hospital": {"code": "RS-M", "name": "RS Mandalika"},
                "top_diseases": [
                    {"installation": "outpatient" if i <= 10 else "inpatient",
                     "icd10_code": f"A{i:02}", "name": f"Penyakit {i:02}", "patient_count": i}
                    for i in range(1, 12)
                ],
            })
            if month != 4:
                source.verification.indicator_verifications.filter(indicator_code="top-diseases").update(status="approved")
        for mode, multiplier in (("monthly", 1), ("quarterly", 2), ("yearly", 2)):
            response = self.client.get(reverse("verification:dashboard"), {"period": mode, "reference": "2026-02"})
            diseases = response.context["health_summary"]["top_diseases"]
            self.assertEqual([row["patient_count"] for row in diseases], [i * multiplier for i in range(11, 1, -1)])
            self.assertContains(response, "Sepuluh penyakit")
            self.assertContains(response, "Penyakit 02")
            self.assertNotContains(response, "Penyakit 01")

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
