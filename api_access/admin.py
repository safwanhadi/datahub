from django.contrib import admin

from .models import ApiAccessLog, ApiProduct, ExternalApiClient, ExternalApiGrant


class ExternalApiGrantInline(admin.TabularInline):
    model = ExternalApiGrant
    extra = 0


@admin.register(ExternalApiClient)
class ExternalApiClientAdmin(admin.ModelAdmin):
    list_display = ("name", "client_id", "is_active", "requests_per_minute")
    list_filter = ("is_active",)
    search_fields = ("name", "client_id")
    inlines = (ExternalApiGrantInline,)


@admin.register(ApiProduct)
class ApiProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "required_scope", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(ApiAccessLog)
class ApiAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "client_id", "product_code", "method", "status_code")
    list_filter = ("status_code", "product_code")
    search_fields = ("client_id", "path")
    readonly_fields = (
        "client_id", "product_code", "method", "path", "status_code",
        "remote_address", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
