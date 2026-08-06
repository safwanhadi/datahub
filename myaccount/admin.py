from django.contrib import admin

from .models import AccountProfile


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "simadu_subject", "sso_linked_at", "updated_at")
    search_fields = (
        "user__username",
        "user__email",
        "simadu_subject",
    )
    readonly_fields = ("created_at", "updated_at")
