from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, SIMRS_MOCK_TOKEN="test-mock-token", ROOT_URLCONF="dash.schema_mock_simrs_urls")
class MockSimrsApiTests(TestCase):
    def setUp(self):
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-mock-token"}
        self.params = {"tgl_awal": "2026-07-01", "tgl_akhir": "2026-07-31"}

    def test_visits_are_combined_in_one_endpoint(self):
        response = self.client.get(reverse("simrs_mock:visits"), self.params, **self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["period"]["label"], "2026-07")
        self.assertEqual(len(payload["results"]), 15)
        self.assertEqual({row["installation"] for row in payload["results"]}, {"outpatient", "inpatient", "emergency"})

    def test_disease_groups_are_combined_in_one_endpoint(self):
        response = self.client.get(reverse("simrs_mock:disease-groups"), self.params, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["code"] for row in response.json()["results"]}, {"cancer", "heart", "stroke", "uronephrology"})

    def test_quarter_semester_and_year_periods_are_identified(self):
        cases = [
            ({"tgl_awal": "2026-01-01", "tgl_akhir": "2026-03-31"}, "quarter", "2026-Q1"),
            ({"tgl_awal": "2026-01-01", "tgl_akhir": "2026-06-30"}, "semester", "2026-S1"),
            ({"tgl_awal": "2026-01-01", "tgl_akhir": "2026-12-31"}, "year", "2026"),
        ]
        for params, kind, label in cases:
            response = self.client.get(reverse("simrs_mock:visits"), params, **self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["period"]["type"], kind)
            self.assertEqual(response.json()["period"]["label"], label)

    def test_each_indicator_endpoint_requires_bearer(self):
        response = self.client.get(reverse("simrs_mock:visits"), self.params)
        self.assertEqual(response.status_code, 401)

    def test_invalid_period_is_rejected(self):
        response = self.client.get(reverse("simrs_mock:top-diseases"), {"tgl_awal": "2026-08-01", "tgl_akhir": "2026-07-01"}, **self.headers)
        self.assertEqual(response.status_code, 400)
