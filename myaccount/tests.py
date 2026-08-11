import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from urllib.parse import parse_qs, urlparse

from .models import AccountProfile
from .views import SSO_STATE_SESSION_KEY, SSO_VERIFIER_SESSION_KEY


class AccountManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("account-admin", password="secret")
        self.admin.groups.add(Group.objects.get(name="Administrator DataHub"))
        self.client.force_login(self.admin)

    def test_admin_can_create_user_and_assign_role(self):
        verifier = Group.objects.get(name="Verifikator")
        response = self.client.post(reverse("myaccount:user-create"), {
            "username": "new-verifier", "first_name": "New", "last_name": "Verifier",
            "email": "verifier@example.test", "is_active": "on",
            "roles": [str(verifier.pk)], "new_password": "safe-test-password",
        })
        self.assertRedirects(response, reverse("myaccount:user-list"))
        user = get_user_model().objects.get(username="new-verifier")
        self.assertTrue(user.groups.filter(name="Verifikator").exists())
        self.assertTrue(user.check_password("safe-test-password"))

    def test_admin_cannot_deactivate_own_account(self):
        response = self.client.post(reverse("myaccount:user-edit", args=[self.admin.pk]), {
            "username": self.admin.username, "first_name": "", "last_name": "",
            "email": "", "roles": [str(self.admin.groups.get().pk)], "new_password": "",
        })
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


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

    def test_pending_profile_cannot_read_dashboard(self):
        user = get_user_model().objects.create_user(username="pending-user", password="secret")
        AccountProfile.objects.create(
            user=user, simadu_subject="official-pending", is_simadu_official=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("verification:dashboard"))

        self.assertRedirects(response, reverse("myaccount:detail"))

    def test_approved_profile_can_read_dashboard(self):
        user = get_user_model().objects.create_user(username="approved-user", password="secret")
        AccountProfile.objects.create(
            user=user, simadu_subject="official-approved", is_simadu_official=True,
            access_status=AccountProfile.AccessStatus.APPROVED,
        )
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
            reverse("myaccount:detail"),
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
        self.assertEqual(profile.access_status, AccountProfile.AccessStatus.PENDING)
        self.assertFalse(profile.user.groups.exists())
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
    def test_callback_records_rejected_non_official(self, exchange_mock, userinfo_mock):
        exchange_mock.return_value = "opaque-token"
        userinfo_mock.return_value = {"nik": "5202000000000001", "email": "biasa@example.com", "pejabat": False}
        login_response = self.client.get(reverse("myaccount:simadu-login"))
        state = parse_qs(urlparse(login_response.url).query)["state"][0]

        response = self.client.get(reverse("myaccount:simadu-callback"), {"code": "authorization-code", "state": state})

        self.assertRedirects(response, reverse("login"))
        user = get_user_model().objects.get(email="biasa@example.com")
        self.assertEqual(user.account_profile.access_status, AccountProfile.AccessStatus.REJECTED)
        self.assertFalse(user.account_profile.is_simadu_official)

    @patch("myaccount.views.fetch_userinfo")
    @patch("myaccount.views.exchange_code")
    def test_existing_role_is_preserved_for_official(self, exchange_mock, userinfo_mock):
        from django.contrib.auth.models import Group

        user = get_user_model().objects.create_user("pejabat")
        AccountProfile.objects.create(
            user=user, simadu_subject="official-1",
            access_status=AccountProfile.AccessStatus.APPROVED,
        )
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
