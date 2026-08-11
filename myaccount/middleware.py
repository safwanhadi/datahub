from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SimaduOfficialAccessMiddleware:
    """Cabut sesi akun SSO ketika status pejabat tidak lagi valid."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, "account_profile", None)
            if profile and profile.simadu_subject and not profile.is_simadu_official:
                logout(request)
                messages.error(request, "Akses DataHub hanya tersedia untuk pejabat yang terdaftar di SIMADU.")
                return redirect(settings.LOGIN_URL)
            allowed_paths = {reverse("myaccount:detail"), reverse("logout")}
            if (
                profile and not profile.has_datahub_access
                and request.path not in allowed_paths
                and not request.path.startswith(f"/{settings.STATIC_URL.lstrip('/')}")
            ):
                messages.warning(request, "Akses DataHub Anda belum disetujui atau sedang dibatasi.")
                return redirect("myaccount:detail")
        return self.get_response(request)
