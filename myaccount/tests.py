import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import parse_qs, urlparse

from .models import AccountProfile
from .views import SSO_STATE_SESSION_KEY, SSO_VERIFIER_SESSION_KEY


@override_settings(SECURE_SSL_REDIRECT=False)
class AccountProfileTests(TestCase):
    def test_profile_extends_default_django_user(self):
        user = get_user_model().objects.create_user(
            username="operator",
            password="test-password",
        )
        profile = AccountProfile.objects.create(
            user=user,
            simadu_subject="simadu-user-1",
        )

        self.assertEqual(user.account_profile, profile)

    def test_account_page_requires_login(self):
        response = self.client.get(reverse("myaccount:detail"))

        self.assertEqual(response.status_code, 302)

    def test_existing_non_official_sso_session_is_revoked(self):
        user = get_user_model().objects.create_user(username="ordinary-sso", password="secret")
        AccountProfile.objects.create(user=user, simadu_subject="ordinary-1", is_simadu_official=False)
        self.client.force_login(user)

        response = self.client.get(reverse("verification:dashboard"))

        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_local_user_is_not_affected_by_simadu_gate(self):
        user = get_user_model().objects.create_user(username="local-user", password="secret")
        self.client.force_login(user)

        response = self.client.get(reverse("verification:dashboard"))

        self.assertEqual(response.status_code, 200)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SIMADU_SSO_AUTHORIZE_URL="https://simadu.example/o/authorize/",
    SIMADU_SSO_TOKEN_URL="https://simadu.example/o/token/",
    SIMADU_SSO_USERINFO_URL="https://simadu.example/api/sso/user/",
    SIMADU_SSO_CLIENT_ID="datahub-sso",
    SIMADU_SSO_CLIENT_SECRET="test-secret",
    SIMADU_SSO_REDIRECT_URI="http://127.0.0.1:8000/accounts/callback/",
    SIMADU_SSO_SCOPE="profile email groups",
)
class SimaduSSOTests(TestCase):
    def test_portal_launch_starts_authorization_with_state_and_pkce(self):
        response = self.client.get(reverse("myaccount:simadu-launch"))

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "simadu.example")
        self.assertEqual(query["client_id"], ["datahub-sso"])
        self.assertTrue(query["state"][0])
        self.assertTrue(query["code_challenge"][0])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_login_redirect_contains_state_and_pkce(self):
        response = self.client.get(reverse("myaccount:simadu-login"))

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], ["datahub-sso"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(
            query["redirect_uri"],
            ["http://127.0.0.1:8000/accounts/callback/"],
        )
        self.assertEqual(query["state"], [self.client.session[SSO_STATE_SESSION_KEY]])
        self.assertTrue(self.client.session[SSO_VERIFIER_SESSION_KEY])

    @patch("myaccount.views.fetch_userinfo")
    @patch("myaccount.views.exchange_code")
    def test_callback_creates_and_logs_in_linked_user(self, exchange_mock, userinfo_mock):
        exchange_mock.return_value = "opaque-token"
        userinfo_mock.return_value = {
            "nik": "5202052401840001",
            "full_name": "M. Sapoan Hadi",
            "email": "pegawai@example.com",
            "pejabat": True,
        }
        login_response = self.client.get(reverse("myaccount:simadu-login"))
        state = parse_qs(urlparse(login_response.url).query)["state"][0]

        response = self.client.get(
            reverse("myaccount:simadu-callback"),
            {"code": "authorization-code", "state": state},
        )

        self.assertRedirects(
            response,
            reverse("verification:dashboard"),
            fetch_redirect_response=False,
        )
        expected_subject = "nik:" + hashlib.sha256(
            b"5202052401840001"
        ).hexdigest()
        profile = AccountProfile.objects.select_related("user").get(
            simadu_subject=expected_subject
        )
        self.assertEqual(profile.user.username, "pegawai")
        self.assertEqual(profile.user.email, "pegawai@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), profile.user.pk)
        self.assertTrue(profile.is_simadu_official)
        self.assertTrue(profile.user.groups.filter(name="Pembaca").exists())
        exchange_mock.assert_called_once()
        userinfo_mock.assert_called_once_with("opaque-token")

    @patch("myaccount.views.exchange_code")
    def test_callback_rejects_invalid_state(self, exchange_mock):
        self.client.get(reverse("myaccount:simadu-login"))

        response = self.client.get(
            reverse("myaccount:simadu-callback"),
            {"code": "authorization-code", "state": "invalid"},
        )

        self.assertRedirects(response, reverse("login"))
        exchange_mock.assert_not_called()

    @patch("myaccount.views.fetch_userinfo")
    @patch("myaccount.views.exchange_code")
    def test_callback_rejects_non_official_without_creating_user(self, exchange_mock, userinfo_mock):
        exchange_mock.return_value = "opaque-token"
        userinfo_mock.return_value = {"nik": "5202000000000001", "email": "biasa@example.com", "pejabat": False}
        login_response = self.client.get(reverse("myaccount:simadu-login"))
        state = parse_qs(urlparse(login_response.url).query)["state"][0]

        response = self.client.get(reverse("myaccount:simadu-callback"), {"code": "authorization-code", "state": state})

        self.assertRedirects(response, reverse("login"))
        self.assertFalse(get_user_model().objects.filter(email="biasa@example.com").exists())

    @patch("myaccount.views.fetch_userinfo")
    @patch("myaccount.views.exchange_code")
    def test_existing_role_is_preserved_for_official(self, exchange_mock, userinfo_mock):
        from django.contrib.auth.models import Group

        user = get_user_model().objects.create_user("pejabat")
        AccountProfile.objects.create(user=user, simadu_subject="official-1")
        verifier = Group.objects.get(name="Verifikator")
        user.groups.add(verifier)
        exchange_mock.return_value = "opaque-token"
        userinfo_mock.return_value = {"sub": "official-1", "username": "pejabat", "pejabat": True}
        login_response = self.client.get(reverse("myaccount:simadu-login"))
        state = parse_qs(urlparse(login_response.url).query)["state"][0]

        response = self.client.get(reverse("myaccount:simadu-callback"), {"code": "authorization-code", "state": state})

        self.assertRedirects(response, reverse("verification:dashboard"), fetch_redirect_response=False)
        self.assertTrue(user.groups.filter(name="Verifikator").exists())
        self.assertFalse(user.groups.filter(name="Pembaca").exists())
