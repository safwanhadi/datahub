"""OAuth2 Authorization Code client untuk SSO SIMADU."""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SimaduSSOError(Exception):
    """Kesalahan aman yang boleh ditampilkan sebagai kegagalan login."""


def required_setting(name):
    value = getattr(settings, name, "")
    if not value:
        raise ImproperlyConfigured(f"{name} belum dikonfigurasi.")
    return value


def authorization_url(*, state, code_challenge):
    query = urlencode(
        {
            "response_type": "code",
            "client_id": required_setting("SIMADU_SSO_CLIENT_ID"),
            "redirect_uri": required_setting("SIMADU_SSO_REDIRECT_URI"),
            "scope": settings.SIMADU_SSO_SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f'{required_setting("SIMADU_SSO_AUTHORIZE_URL")}?{query}'


def _basic_authorization(client_id, client_secret):
    credentials = f"{quote_plus(client_id)}:{quote_plus(client_secret)}".encode()
    return "Basic " + base64.b64encode(credentials).decode("ascii")


def _read_json(request, *, operation):
    try:
        with urlopen(request, timeout=settings.SIMADU_SSO_TIMEOUT) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise SimaduSSOError(
            f"SIMADU menolak {operation} (HTTP {exc.code})."
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SimaduSSOError("Layanan SSO SIMADU tidak dapat dihubungi.") from exc

    if not isinstance(payload, dict):
        raise SimaduSSOError("Respons SSO SIMADU tidak valid.")
    return payload


def exchange_code(code, code_verifier):
    """Tukar authorization code dengan opaque access token."""
    request = Request(
        required_setting("SIMADU_SSO_TOKEN_URL"),
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": required_setting("SIMADU_SSO_REDIRECT_URI"),
                "code_verifier": code_verifier,
            }
        ).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": _basic_authorization(
                required_setting("SIMADU_SSO_CLIENT_ID"),
                required_setting("SIMADU_SSO_CLIENT_SECRET"),
            ),
        },
        method="POST",
    )
    payload = _read_json(request, operation="pertukaran authorization code")
    access_token = payload.get("access_token")
    if not access_token or str(payload.get("token_type", "")).lower() != "bearer":
        raise SimaduSSOError("SIMADU tidak mengembalikan Bearer Token yang valid.")
    return access_token


def fetch_userinfo(access_token):
    """Ambil profil pemilik opaque token dari endpoint SIMADU."""
    request = Request(
        required_setting("SIMADU_SSO_USERINFO_URL"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    payload = _read_json(request, operation="permintaan profil pengguna")
    # Beberapa API membungkus profil di dalam properti ``user`` atau ``data``.
    for wrapper in ("user", "data"):
        if isinstance(payload.get(wrapper), dict):
            return payload[wrapper]
    return payload
