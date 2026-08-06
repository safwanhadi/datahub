from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from .models import ApiProduct, ExternalApiClient, ExternalApiGrant


class HasExternalApiGrant(BasePermission):
    message = "Client tidak memiliki izin untuk produk API ini."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        product_code = view.get_api_product_code()
        try:
            product = ApiProduct.objects.get(code=product_code, is_active=True)
        except ApiProduct.DoesNotExist as exc:
            raise NotFound("Produk API belum tersedia.") from exc

        try:
            client = ExternalApiClient.objects.get(
                client_id=request.user.client_id,
                is_active=True,
            )
        except ExternalApiClient.DoesNotExist as exc:
            raise PermissionDenied("OAuth client belum terdaftar di DataHub.") from exc

        grant = ExternalApiGrant.objects.filter(
            client=client,
            product=product,
            is_active=True,
        ).first()
        if not grant or (grant.expires_at and grant.expires_at <= timezone.now()):
            raise PermissionDenied(self.message)

        scopes = set(str(request.auth.get("scope", "")).split())
        if product.required_scope not in scopes:
            raise PermissionDenied(f"Scope {product.required_scope} diperlukan.")

        request.api_client = client
        request.api_product = product
        return True
