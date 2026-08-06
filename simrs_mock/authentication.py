from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed


class MockBearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            raise AuthenticationFailed("Bearer Token diperlukan.")
        try:
            token = parts[1].decode("utf-8")
        except UnicodeError as exc:
            raise AuthenticationFailed("Bearer Token tidak valid.") from exc
        if token != settings.SIMRS_MOCK_TOKEN:
            raise AuthenticationFailed("Bearer Token mock tidak valid.")
        return MockMachinePrincipal(), token

    def authenticate_header(self, request):
        return 'Bearer realm="mock-simrs"'


class MockMachinePrincipal:
    is_authenticated = True
    is_anonymous = False

    def __str__(self):
        return "datahub-simrs-reader"
