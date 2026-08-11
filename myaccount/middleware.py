from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class SimaduOfficialAccessMiddleware:
    """Batasi data berdasarkan persetujuan DataHub, bukan atribut SIMADU."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, "account_profile", None)
            allowed_paths = {reverse("myaccount:detail"), reverse("logout")}
            if (
                profile and not profile.has_datahub_access
                and request.path not in allowed_paths
                and not request.path.startswith(f"/{settings.STATIC_URL.lstrip('/')}")
            ):
                messages.warning(request, "Akses DataHub Anda belum disetujui atau sedang dibatasi.")
                return redirect("myaccount:detail")
        return self.get_response(request)
