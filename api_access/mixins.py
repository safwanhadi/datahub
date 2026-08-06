from .models import ApiAccessLog
from django.core.validators import validate_ipv46_address
from django.core.exceptions import ValidationError


class ExternalApiAuditMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        principal = getattr(request, "user", None)
        client_id = getattr(principal, "client_id", "")
        product_code = ""
        try:
            product_code = self.get_api_product_code()
        except (AttributeError, KeyError):
            pass
        if client_id and product_code:
            remote = request.META.get("REMOTE_ADDR") or None
            try:
                if remote:
                    validate_ipv46_address(remote)
            except ValidationError:
                remote = None
            ApiAccessLog.objects.create(
                client_id=client_id,
                product_code=product_code,
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                remote_address=remote or None,
            )
        return response
