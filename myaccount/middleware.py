from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class SimaduOfficialAccessMiddleware:
    """Cabut sesi akun SSO ketika status pejabat tidak lagi valid."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith("/accounts/"):
            profile = getattr(request.user, "account_profile", None)
            if profile and profile.simadu_subject and not profile.is_simadu_official:
                logout(request)
                messages.error(request, "Akses DataHub hanya tersedia untuk pejabat yang terdaftar di SIMADU.")
                return redirect(settings.LOGIN_URL)
        return self.get_response(request)
