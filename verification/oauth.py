import base64
import hashlib
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured


class OAuthError(Exception):
    """Base exception untuk komunikasi OAuth SIMADU."""


class OAuthServerUnavailable(OAuthError):
    pass


class InvalidAccessToken(OAuthError):
    pass


class InsufficientScope(OAuthError):
    pass


def _required_setting(name):
    value = getattr(settings, name, "")
    if not value:
        raise ImproperlyConfigured(f"{name} belum dikonfigurasi.")
    return value


def _basic_authorization(client_id, client_secret):
    # RFC 6749 §2.3.1: encode kedua nilai sebelum membentuk Basic credentials.
    raw = f"{quote_plus(client_id)}:{quote_plus(client_secret)}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _post_form(url, form, *, client_id, client_secret, timeout):
    request = Request(
        url,
        data=urlencode(form).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": _basic_authorization(client_id, client_secret),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        # Jangan sertakan response body karena dapat mengandung detail sensitif.
        raise OAuthServerUnavailable(
            f"SIMADU menolak permintaan OAuth (HTTP {exc.code})."
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OAuthServerUnavailable("Layanan OAuth SIMADU tidak dapat dihubungi.") from exc


def get_simrs_access_token():
    """Ambil opaque access token untuk DataHub → PHP/SIMRS."""
    cache_key = "oauth:simadu:simrs-machine-token"
    cached = cache.get(cache_key)
    if cached:
        return cached

    payload = _post_form(
        _required_setting("SIMADU_TOKEN_URL"),
        {
            "grant_type": "client_credentials",
            "scope": settings.SIMADU_SIMRS_SCOPE,
        },
        client_id=_required_setting("SIMADU_CLIENT_ID"),
        client_secret=_required_setting("SIMADU_CLIENT_SECRET"),
        timeout=settings.SIMADU_OAUTH_TIMEOUT,
    )
    access_token = payload.get("access_token")
    if not access_token or payload.get("token_type", "").lower() != "bearer":
        raise OAuthServerUnavailable("Respons token SIMADU tidak valid.")

    expires_in = max(int(payload.get("expires_in", 300)), 1)
    # Ambil token baru sebelum token lama benar-benar kedaluwarsa.
    cache.set(cache_key, access_token, timeout=max(expires_in - 30, 1))
    return access_token


def introspect_access_token(raw_token, *, required_scope):
    """Validasi token pihak ketiga melalui introspection SIMADU (fail-closed)."""
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    cache_key = f"oauth:introspection:{token_digest}"
    payload = cache.get(cache_key)
    if payload is None:
        payload = _post_form(
            _required_setting("SIMADU_INTROSPECTION_URL"),
            {"token": raw_token, "token_type_hint": "access_token"},
            client_id=_required_setting("SIMADU_INTROSPECTION_CLIENT_ID"),
            client_secret=_required_setting("SIMADU_INTROSPECTION_CLIENT_SECRET"),
            timeout=settings.SIMADU_OAUTH_TIMEOUT,
        )
        if payload.get("active") is not True:
            raise InvalidAccessToken("Token tidak aktif atau kedaluwarsa.")

        now = int(time.time())
        exp = int(payload.get("exp", now + settings.SIMADU_INTROSPECTION_CACHE_SECONDS))
        ttl = min(settings.SIMADU_INTROSPECTION_CACHE_SECONDS, max(exp - now, 0))
        if ttl <= 0:
            raise InvalidAccessToken("Token tidak aktif atau kedaluwarsa.")
        cache.set(cache_key, payload, timeout=ttl)

    if payload.get("active") is not True:
        raise InvalidAccessToken("Token tidak aktif atau kedaluwarsa.")

    scopes = set(payload.get("scope", "").split())
    if required_scope not in scopes:
        raise InsufficientScope(f"Scope {required_scope} diperlukan.")

    allowed_clients = settings.SIMADU_ALLOWED_API_CLIENTS
    client_id = payload.get("client_id")
    if allowed_clients and client_id not in allowed_clients:
        raise InvalidAccessToken("OAuth client tidak diizinkan mengakses DataHub.")
    return payload
