from django.contrib import admin

from .models import AccountProfile


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "access_status", "simadu_subject", "last_sso_attempt_at", "updated_at")
    list_filter = ("access_status", "is_simadu_official")
    search_fields = (
        "user__username",
        "user__email",
        "simadu_subject",
    )
    readonly_fields = ("requested_at", "created_at", "updated_at")
