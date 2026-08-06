from rest_framework.throttling import SimpleRateThrottle

from .models import ExternalApiClient


class ExternalClientRateThrottle(SimpleRateThrottle):
    scope = "external-client"

    def get_rate(self):
        # Nilai awal diperlukan DRF; diganti dengan rate client pada get_cache_key.
        return "60/min"

    def get_cache_key(self, request, view):
        client_id = getattr(getattr(request, "user", None), "client_id", None)
        if not client_id:
            return None
        try:
            client = ExternalApiClient.objects.only(
                "requests_per_minute"
            ).get(client_id=client_id, is_active=True)
        except ExternalApiClient.DoesNotExist:
            return None

        self.rate = f"{max(client.requests_per_minute, 1)}/min"
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return self.cache_format % {"scope": self.scope, "ident": client_id}
