from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from verification.oauth import (
    InvalidAccessToken,
    OAuthServerUnavailable,
    introspect_raw_access_token,
)


@dataclass(frozen=True)
class OAuthClientPrincipal:
    client_id: str
    claims: dict

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return self.client_id


class SimaduOpaqueTokenAuthentication(BaseAuthentication):
    """Autentikasi client eksternal menggunakan opaque Bearer Token SIMADU."""

    keyword = b"bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if parts[0].lower() != self.keyword or len(parts) != 2:
            raise AuthenticationFailed("Format Bearer Token tidak valid.")
        try:
            token = parts[1].decode("utf-8")
        except UnicodeError as exc:
            raise AuthenticationFailed("Bearer Token tidak valid.") from exc

        try:
            claims = introspect_raw_access_token(token)
        except InvalidAccessToken as exc:
            raise AuthenticationFailed(str(exc)) from exc
        except (OAuthServerUnavailable, ImproperlyConfigured) as exc:
            raise AuthenticationFailed("Validasi token SIMADU tidak tersedia.") from exc

        client_id = str(claims.get("client_id", "")).strip()
        if not client_id:
            raise AuthenticationFailed("Token tidak memiliki client_id.")
        return OAuthClientPrincipal(client_id, claims), claims

    def authenticate_header(self, request):
        return 'Bearer realm="datahub-external"'
