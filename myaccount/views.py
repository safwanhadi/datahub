import base64
import hashlib
import secrets
from hmac import compare_digest

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import AccountProfile
from .sso import (
    SimaduSSOError,
    authorization_url,
    exchange_code,
    fetch_userinfo,
)


SSO_STATE_SESSION_KEY = "simadu_sso_state"
SSO_VERIFIER_SESSION_KEY = "simadu_sso_code_verifier"
SSO_NEXT_SESSION_KEY = "simadu_sso_next"


def _safe_next_url(request):
    candidate = request.GET.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("verification:dashboard")


def simadu_launch(request):
    """Entry point stabil untuk ikon aplikasi pada portal SIMADU."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode("ascii")

    request.session[SSO_STATE_SESSION_KEY] = state
    request.session[SSO_VERIFIER_SESSION_KEY] = verifier
    request.session[SSO_NEXT_SESSION_KEY] = _safe_next_url(request)

    try:
        return redirect(authorization_url(state=state, code_challenge=challenge))
    except ImproperlyConfigured:
        messages.error(request, "Konfigurasi SSO SIMADU belum lengkap.")
        return redirect(settings.LOGIN_URL)


# Alias lama dipertahankan agar bookmark/integrasi yang ada tidak rusak.
simadu_login = simadu_launch


def _claim(claims, *names):
    for name in names:
        value = claims.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _subject_from_claims(claims):
    subject = _claim(claims, "sub", "id", "user_id", "pk")
    if subject:
        return subject

    # SIMADU menggunakan NIK sebagai identifier stabil. Jangan simpan NIK mentah.
    nik = _claim(claims, "nik")
    if nik:
        digest = hashlib.sha256(nik.encode("utf-8")).hexdigest()
        return f"nik:{digest}"
    return ""


def _is_simadu_official(claims):
    value = claims.get("pejabat", claims.get("is_pejabat", False))
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value).strip().lower() in {"true", "1", "ya", "yes"}


def _unique_username(base):
    User = get_user_model()
    username_field = User._meta.get_field(User.USERNAME_FIELD)
    max_length = username_field.max_length or 150
    base = base[:max_length] or "simadu-user"
    candidate = base
    suffix = 1
    while User._default_manager.filter(**{User.USERNAME_FIELD: candidate}).exists():
        marker = f"-{suffix}"
        candidate = f"{base[:max_length - len(marker)]}{marker}"
        suffix += 1
    return candidate


@transaction.atomic
def _resolve_user(claims):
    subject = _subject_from_claims(claims)
    if not subject:
        raise SimaduSSOError(
            "Profil SIMADU tidak memiliki ID pengguna permanen atau NIK."
        )

    linked = AccountProfile.objects.select_related("user").filter(
        simadu_subject=subject
    ).first()
    if linked:
        user = linked.user
        profile = linked
    else:
        User = get_user_model()
        username = _claim(claims, "preferred_username", "username")
        email = _claim(claims, "email")
        if not username and email:
            username = email.partition("@")[0]
        username = _unique_username(username)
        user = User._default_manager.create(**{User.USERNAME_FIELD: username})
        user.set_unusable_password()
        profile = AccountProfile.objects.create(
            user=user,
            simadu_subject=subject,
            sso_linked_at=timezone.now(),
        )

    changed_fields = []
    field_claims = {
        "email": _claim(claims, "email"),
        "first_name": _claim(claims, "first_name", "given_name"),
        "last_name": _claim(claims, "last_name", "family_name"),
    }
    full_name = _claim(claims, "name", "full_name")
    if full_name and not field_claims["first_name"]:
        first_name, _, last_name = full_name.partition(" ")
        field_claims["first_name"] = first_name
        field_claims["last_name"] = last_name

    for field, value in field_claims.items():
        if hasattr(user, field) and value and getattr(user, field) != value:
            model_field = user._meta.get_field(field)
            setattr(user, field, value[: model_field.max_length] if model_field.max_length else value)
            changed_fields.append(field)
    if changed_fields:
        user.save(update_fields=changed_fields)
    profile.is_simadu_official = True
    profile.official_status_checked_at = timezone.now()
    profile.save(update_fields=("is_simadu_official", "official_status_checked_at", "updated_at"))
    # Pejabat baru/default hanya membaca. Role yang telah ditetapkan admin
    # tidak dihapus atau ditimpa saat login ulang.
    if not user.groups.exists():
        reader_group, _ = Group.objects.get_or_create(name="Pembaca")
        user.groups.add(reader_group)
    return user


def simadu_callback(request):
    expected_state = request.session.pop(SSO_STATE_SESSION_KEY, "")
    verifier = request.session.pop(SSO_VERIFIER_SESSION_KEY, "")
    next_url = request.session.pop(
        SSO_NEXT_SESSION_KEY, reverse("verification:dashboard")
    )
    received_state = request.GET.get("state", "")

    if request.GET.get("error"):
        messages.error(request, "Login SIMADU dibatalkan atau ditolak.")
        return redirect(settings.LOGIN_URL)
    if not expected_state or not compare_digest(expected_state, received_state):
        messages.error(request, "State login SIMADU tidak valid atau sudah kedaluwarsa.")
        return redirect(settings.LOGIN_URL)

    code = request.GET.get("code", "")
    if not code or not verifier:
        messages.error(request, "Authorization code SIMADU tidak ditemukan.")
        return redirect(settings.LOGIN_URL)

    try:
        token = exchange_code(code, verifier)
        claims = fetch_userinfo(token)
        if not _is_simadu_official(claims):
            raise SimaduSSOError("Akses DataHub hanya tersedia untuk pejabat yang terdaftar di SIMADU.")
        user = _resolve_user(claims)
    except (SimaduSSOError, ImproperlyConfigured) as exc:
        messages.error(request, str(exc))
        return redirect(settings.LOGIN_URL)

    if not user.is_active:
        messages.error(request, "Akun DataHub ini tidak aktif.")
        return redirect(settings.LOGIN_URL)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(next_url)


@login_required
def account_detail(request):
    return render(request, "myaccount/detail.html")
